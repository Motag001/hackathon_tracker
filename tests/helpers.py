from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel

from hackagent.shared.config import Config
from hackagent.shared.context import Context, load_settings
from hackagent.shared.cost import BudgetGuard, Limits
from hackagent.shared.llm import Call
from hackagent.shared.store import MemoryStore

FIXED_NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


class FakeLLM:
    """Answers each call with ``responder(call)``; records every call."""

    def __init__(self, responder: Callable[[Call], BaseModel | dict]):
        self.responder = responder
        self.calls: list[Call] = []

    def _answer(self, call: Call) -> BaseModel:
        self.calls.append(call)
        out = self.responder(call)
        return out if isinstance(out, BaseModel) else call.schema.model_validate(out)

    def structured(self, call: Call) -> BaseModel:
        return self._answer(call)

    def structured_batch(self, calls: list[Call]) -> dict[str, BaseModel | Exception]:
        return {c.custom_id: self._answer(c) for c in calls}


def make_ctx(responder=None, store: MemoryStore | None = None, **settings: Any) -> Context:
    store = store or MemoryStore()
    store.insert("settings", {"id": 1, **settings})
    config = Config(_env_file=None, HACKAGENT_DRY_RUN=True)
    s = load_settings(store)
    guard = BudgetGuard(store, Limits.from_settings(s), run_id="test-run")
    llm = FakeLLM(responder or (lambda c: (_ for _ in ()).throw(AssertionError("no LLM"))))
    return Context(config, store, llm, guard, s, "test-run", clock=lambda: FIXED_NOW)


def fake_message(payload: dict, *, stop_reason="end_turn", model="claude-haiku-5-5", **usage):
    u = {
        "input_tokens": 1000,
        "output_tokens": 200,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        **usage,
    }
    return SimpleNamespace(
        id="msg_1",
        model=model,
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=SimpleNamespace(**u),
    )
