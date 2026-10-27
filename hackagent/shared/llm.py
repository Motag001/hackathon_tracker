"""The single gateway for Anthropic API calls.

Everything an agent asks of a model goes through ``LLM.structured`` (or the
batch variant), which:

1. routes the request to the model tier the task allows (top tier only when
   the caller passes an explicit owner approval);
2. prices the worst case and asks ``BudgetGuard`` for permission first;
3. lays the prompt out for caching: frozen instructions and stable context
   (profile, playbook, skill registry) first, volatile content last;
4. constrains the reply to a JSON schema and validates it with pydantic;
5. records the real token usage and cost in ``spend_log``.
"""

from __future__ import annotations

import enum
import json
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from hackagent.shared.config import Config
from hackagent.shared.cost import BudgetGuard, Priority, usage_cost, worst_case_cost
from hackagent.shared.security import UNTRUSTED_NOTICE

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class Tier(enum.Enum):
    CHEAP = "cheap"
    MID = "mid"
    TOP = "top"


class LLMError(RuntimeError):
    pass


class LLMRefusal(LLMError):
    pass


class LLMUnavailable(LLMError):
    pass


# JSON-schema keywords that structured outputs do not accept. They are still
# enforced locally by pydantic after the response arrives.
_UNSUPPORTED = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "format",
    "title",
    "default",
    "examples",
}


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON schema for ``model`` with closed objects and all fields required."""

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: walk(v) for k, v in node.items() if k not in _UNSUPPORTED}
            if out.get("type") == "object" and "properties" in out:
                out["additionalProperties"] = False
                out["required"] = list(out["properties"].keys())
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(model.model_json_schema())


@dataclass
class Call:
    """One structured request. ``custom_id`` is used by batches."""

    agent: str
    tier: Tier
    system: str
    prompt: str
    schema: type[BaseModel]
    stable_context: str = ""
    max_tokens: int = 8000
    effort: str = "low"
    event_id: str | None = None
    priority: Priority = Priority.ROUTINE
    purpose: str = ""
    top_tier_approved: bool = False
    custom_id: str = ""


class LLMClient(Protocol):
    def structured(self, call: Call) -> BaseModel: ...

    def structured_batch(self, calls: list[Call]) -> dict[str, BaseModel | Exception]: ...


class LLM:
    FALLBACK_BETA = "server-side-fallback-2026-07-01"

    def __init__(
        self,
        config: Config,
        guard: BudgetGuard,
        client: anthropic.Anthropic | None = None,
        *,
        batch_poll_s: float = 30.0,
        batch_wait_s: float = 3000.0,
    ):
        self.config = config
        self.guard = guard
        self.batch_poll_s = batch_poll_s
        self.batch_wait_s = batch_wait_s
        self._client: anthropic.Anthropic | None
        if client is not None:
            self._client = client
        elif config.dry_run or config.anthropic_api_key is None:
            self._client = None
        else:
            self._client = anthropic.Anthropic(
                api_key=config.anthropic_api_key.get_secret_value(), max_retries=3, timeout=300.0
            )

    # -- request building ----------------------------------------------------

    def model_for(self, call: Call) -> str:
        if call.tier is Tier.TOP:
            if not call.top_tier_approved:
                raise LLMError("Top-tier model requested without owner approval")
            return self.config.model_top
        return self.config.model_mid if call.tier is Tier.MID else self.config.model_cheap

    def _params(self, call: Call, model: str) -> dict[str, Any]:
        system: list[dict[str, Any]] = [
            {"type": "text", "text": f"{call.system}\n\n{UNTRUSTED_NOTICE}"}
        ]
        if call.stable_context:
            system.append({"type": "text", "text": call.stable_context})
        # Cache breakpoint after the last stable block; the user turn is volatile.
        system[-1]["cache_control"] = {"type": "ephemeral"}
        return {
            "model": model,
            "max_tokens": call.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": call.prompt}],
            "output_config": {
                "effort": call.effort,
                "format": {"type": "json_schema", "schema": strict_schema(call.schema)},
            },
        }

    def _estimate(self, call: Call, model: str, batch: bool = False) -> Decimal:
        chars = len(call.system) + len(call.stable_context) + len(call.prompt) + 2000
        return worst_case_cost(model, chars, call.max_tokens, batch=batch)

    def _parse(self, call: Call, message: Any) -> BaseModel:
        if message.stop_reason == "refusal":
            raise LLMRefusal(f"{call.agent}: model declined the request")
        if message.stop_reason == "max_tokens":
            raise LLMError(f"{call.agent}: response truncated at max_tokens={call.max_tokens}")
        text = next((b.text for b in message.content if b.type == "text"), "")
        try:
            return call.schema.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as e:
            raise LLMError(f"{call.agent}: invalid structured output: {e}") from None

    def _record(self, call: Call, message: Any, batch: bool) -> None:
        u = message.usage
        model = getattr(message, "model", None) or self.model_for(call)
        cost = usage_cost(
            model,
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_creation_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            batch=batch,
        )
        self.guard.record(
            {
                "agent": call.agent,
                "event_id": call.event_id,
                "model": model,
                "input_tokens": u.input_tokens or 0,
                "output_tokens": u.output_tokens or 0,
                "cache_creation_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
                "cache_read_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
                "cost_usd": cost,
                "batch": batch,
                "purpose": call.purpose[:200],
                "request_id": getattr(message, "_request_id", None) or getattr(message, "id", None),
            }
        )

    def _require_client(self) -> anthropic.Anthropic:
        if self._client is None:
            raise LLMUnavailable("No Anthropic client (dry run or ANTHROPIC_API_KEY unset)")
        return self._client

    # -- public API ----------------------------------------------------------

    def structured(self, call: Call) -> BaseModel:
        client = self._require_client()
        model = self.model_for(call)
        estimate = self._estimate(call, model)
        self.guard.check(estimate, priority=call.priority, event_id=call.event_id)
        params = self._params(call, model)
        try:
            if call.tier is Tier.CHEAP:
                message = client.messages.create(**params)
            else:
                # Mid/top tier: let the API re-run a declined request on a
                # suitable model instead of failing the whole step.
                message = client.beta.messages.create(
                    **params, betas=[self.FALLBACK_BETA], fallbacks="default"
                )
        except anthropic.BadRequestError as e:
            raise LLMError(f"{call.agent}: bad request: {e.message}") from None
        except anthropic.RateLimitError:
            raise LLMError(f"{call.agent}: rate limited after retries") from None
        except anthropic.APIStatusError as e:
            raise LLMError(f"{call.agent}: API error {e.status_code}") from None
        except anthropic.APIConnectionError:
            raise LLMError(f"{call.agent}: connection error") from None
        # Usage is billed even when parsing fails, so record first.
        self._record(call, message, batch=False)
        return self._parse(call, message)

    def structured_batch(self, calls: list[Call]) -> dict[str, BaseModel | Exception]:
        """Run non-urgent calls through the Batches API at half price."""
        if not calls:
            return {}
        client = self._require_client()
        ids = [c.custom_id for c in calls]
        if len(set(ids)) != len(ids) or not all(ids):
            raise ValueError("Batch calls need unique, non-empty custom_id values")
        estimate = Decimal(0)
        requests: list[Any] = []
        for c in calls:
            model = self.model_for(c)
            estimate += self._estimate(c, model, batch=True)
            requests.append({"custom_id": c.custom_id, "params": self._params(c, model)})
        self.guard.check(estimate, priority=calls[0].priority, event_id=None)

        batch = client.messages.batches.create(requests=requests)
        deadline = time.monotonic() + self.batch_wait_s
        while batch.processing_status != "ended":
            if time.monotonic() > deadline:
                client.messages.batches.cancel(batch.id)
                raise LLMError(f"Batch {batch.id} did not finish in time; cancelled")
            time.sleep(self.batch_poll_s)
            batch = client.messages.batches.retrieve(batch.id)

        by_id = {c.custom_id: c for c in calls}
        out: dict[str, BaseModel | Exception] = {}
        for result in client.messages.batches.results(batch.id):
            call = by_id.get(result.custom_id)
            if call is None:
                continue
            if result.result.type != "succeeded":
                out[call.custom_id] = LLMError(f"batch item {result.result.type}")
                continue
            message = result.result.message
            self._record(call, message, batch=True)
            try:
                out[call.custom_id] = self._parse(call, message)
            except LLMError as e:
                out[call.custom_id] = e
        for cid in ids:
            out.setdefault(cid, LLMError("missing from batch results"))
        return out
