"""Cost tracking and budget enforcement (section 10).

Every model call goes through ``BudgetGuard.check`` before it is sent and
``BudgetGuard.record`` after it returns. The guard is deliberately
pessimistic: it prices the call as if the full ``max_tokens`` were used, so
the monthly cap cannot be overshot by a single large response.

The Anthropic Console hard cap ($10) remains the final backstop; this module
keeps spend well under it.
"""

from __future__ import annotations

import enum
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from hackagent.shared.store import Store


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: Decimal
    output: Decimal
    cache_read: Decimal

    @property
    def cache_write(self) -> Decimal:
        # 5-minute cache writes are billed at 1.25x the input price.
        return self.input * Decimal("1.25")


PRICES: dict[str, Price] = {
    "claude-haiku-5-5": Price(Decimal("0.10"), Decimal("0.50"), Decimal("0.01")),
    "claude-sonnet-5-5": Price(Decimal("2.00"), Decimal("10.00"), Decimal("0.20")),
    "claude-opus-5-5": Price(Decimal("4.00"), Decimal("20.00"), Decimal("0.20")),
}
# Unknown models are priced at the most expensive known rate so a typo in a
# model override can never make spend look cheaper than it is.
_FALLBACK = max(PRICES.values(), key=lambda p: p.output)
_MILLION = Decimal(1_000_000)
_BATCH_DISCOUNT = Decimal("0.5")


def price_for(model: str) -> Price:
    return PRICES.get(model, _FALLBACK)


def usage_cost(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    batch: bool = False,
) -> Decimal:
    p = price_for(model)
    cost = (
        Decimal(input_tokens) * p.input
        + Decimal(output_tokens) * p.output
        + Decimal(cache_creation_tokens) * p.cache_write
        + Decimal(cache_read_tokens) * p.cache_read
    ) / _MILLION
    if batch:
        cost *= _BATCH_DISCOUNT
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def estimate_tokens(text: str) -> int:
    """Conservative token estimate (about 3 characters per token)."""
    return len(text) // 3 + 1


def worst_case_cost(model: str, prompt_chars: int, max_tokens: int, batch: bool = False) -> Decimal:
    return usage_cost(
        model,
        input_tokens=prompt_chars // 3 + 1,
        output_tokens=max_tokens,
        batch=batch,
    )


class Priority(enum.Enum):
    # Discovery, rules parsing, scoring: paused once spend reaches the pause line.
    ROUTINE = "routine"
    # Work on events the owner already approved (plan, build, review).
    ESSENTIAL = "essential"


class BudgetExceeded(RuntimeError):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind  # "monthly_cap" | "paused" | "event_budget"


@dataclass
class Limits:
    monthly_cap: Decimal = Decimal("10")
    soft_warn: Decimal = Decimal("5")
    pause: Decimal = Decimal("8")
    event_budget: Decimal = Decimal("1.50")

    @classmethod
    def from_settings(cls, s: dict[str, Any]) -> Limits:
        return cls(
            monthly_cap=Decimal(str(s.get("monthly_cap_usd", 10))),
            soft_warn=Decimal(str(s.get("soft_warn_usd", 5))),
            pause=Decimal(str(s.get("pause_usd", 8))),
            event_budget=Decimal(str(s.get("event_budget_usd", 1.5))),
        )


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class BudgetGuard:
    """Reads spend once per run, then tracks it incrementally in memory."""

    def __init__(self, store: Store, limits: Limits, run_id: str | None = None):
        self.store = store
        self.limits = limits
        self.run_id = run_id
        self._lock = threading.Lock()
        self._month: Decimal | None = None
        self._events: dict[str, Decimal] = {}
        # Per-event budget extensions granted by the owner (loaded lazily).
        self._extra: dict[str, Decimal] = {}

    # -- reads ---------------------------------------------------------------

    def month_spend(self) -> Decimal:
        with self._lock:
            if self._month is None:
                rows = self.store.select(
                    "spend_log",
                    [("created_at", "gte", month_start().isoformat())],
                    columns="cost_usd",
                )
                self._month = sum((Decimal(str(r["cost_usd"])) for r in rows), Decimal(0))
            return self._month

    def event_spend(self, event_id: str) -> Decimal:
        with self._lock:
            if event_id not in self._events:
                rows = self.store.select("spend_log", {"event_id": event_id}, columns="cost_usd")
                self._events[event_id] = sum(
                    (Decimal(str(r["cost_usd"])) for r in rows), Decimal(0)
                )
            return self._events[event_id]

    def event_limit(self, event_id: str) -> Decimal:
        if event_id not in self._extra:
            self._extra[event_id] = self._approved_extensions(event_id)
        return self.limits.event_budget + self._extra[event_id]

    def refresh_extensions(self, event_id: str) -> None:
        self._extra.pop(event_id, None)

    def _approved_extensions(self, event_id: str) -> Decimal:
        """Extensions the owner granted by answering budget_extension requests.

        A reply of "yes" adds one more event budget; a number adds that many
        dollars (capped at $5 per reply). Anything else grants nothing.
        """
        total = Decimal(0)
        rows = self.store.select(
            "input_requests",
            {"event_id": event_id, "kind": "budget_extension", "status": "answered"},
            columns="response",
        )
        for r in rows:
            reply = (r.get("response") or "").strip().lower()
            m = re.fullmatch(r"\$?\s*(\d+(?:\.\d+)?)", reply)
            if m:
                total += min(Decimal(m.group(1)), Decimal(5))
            elif reply in {"yes", "y", "continue", "approve", "approved"}:
                total += self.limits.event_budget
        return total

    # -- enforcement ---------------------------------------------------------

    def check(self, estimate: Decimal, *, priority: Priority, event_id: str | None) -> None:
        spent = self.month_spend()
        if spent + estimate > self.limits.monthly_cap:
            raise BudgetExceeded(
                "monthly_cap",
                f"Monthly cap ${self.limits.monthly_cap} would be exceeded "
                f"(spent ${spent:.4f}, call up to ${estimate:.4f}).",
            )
        if priority is Priority.ROUTINE and spent >= self.limits.pause:
            raise BudgetExceeded(
                "paused",
                f"Spend ${spent:.2f} reached the ${self.limits.pause} pause line; "
                "non-essential work waits for next month.",
            )
        if event_id is not None and priority is Priority.ESSENTIAL:
            ev = self.event_spend(event_id)
            limit = self.event_limit(event_id)
            if ev + estimate > limit:
                raise BudgetExceeded(
                    "event_budget",
                    f"Event budget ${limit} would be exceeded (spent ${ev:.4f}, "
                    f"call up to ${estimate:.4f}).",
                )

    def record(self, row: dict[str, Any]) -> None:
        cost = Decimal(str(row["cost_usd"]))
        self.store.insert("spend_log", {**row, "run_id": self.run_id, "cost_usd": str(cost)})
        with self._lock:
            if self._month is not None:
                self._month += cost
            ev = row.get("event_id")
            if ev and ev in self._events:
                self._events[ev] += cost

    def crossed_lines(self) -> list[tuple[str, Decimal]]:
        """Warning lines crossed so far this month (for alerts)."""
        spent = self.month_spend()
        out = []
        if spent >= self.limits.soft_warn:
            out.append(("soft_warn", self.limits.soft_warn))
        if spent >= self.limits.pause:
            out.append(("pause", self.limits.pause))
        return out
