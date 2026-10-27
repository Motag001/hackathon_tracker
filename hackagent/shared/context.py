"""Per-run context shared by agents: config, store, model gateway, budget."""

from __future__ import annotations

import logging
import traceback
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from hackagent.shared.config import Config
from hackagent.shared.cost import BudgetExceeded, BudgetGuard, Limits
from hackagent.shared.llm import LLM, LLMClient
from hackagent.shared.security import redact
from hackagent.shared.store import Store, get_store, now_iso

log = logging.getLogger(__name__)

DEFAULT_SETTINGS: dict[str, Any] = {
    "surface_threshold": 65,
    "event_budget_usd": 1.5,
    "monthly_cap_usd": 10,
    "soft_warn_usd": 5,
    "pause_usd": 8,
    "min_prize_usd": 50,
    "max_effort_hours": 72,
    "profile": {},
}


@dataclass
class Context:
    config: Config
    store: Store
    llm: LLMClient
    guard: BudgetGuard
    settings: dict[str, Any]
    run_id: str
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def now(self) -> datetime:
        return self.clock()

    @property
    def profile(self) -> dict[str, Any]:
        return self.settings.get("profile") or {}


def load_settings(store: Store) -> dict[str, Any]:
    rows = store.select("settings", {"id": 1}, limit=1)
    merged = dict(DEFAULT_SETTINGS)
    if rows:
        merged.update({k: v for k, v in rows[0].items() if v is not None})
    for k in ("surface_threshold", "event_budget_usd", "min_prize_usd", "max_effort_hours"):
        merged[k] = float(merged[k])
    return merged


def build_context(config: Config, store: Store | None = None) -> Context:
    store = store or get_store(config)
    settings = load_settings(store)
    run_id = str(uuid.uuid4())
    guard = BudgetGuard(store, Limits.from_settings(settings), run_id=run_id)
    return Context(config, store, LLM(config, guard), guard, settings, run_id)


def raise_alert(
    store: Store,
    kind: str,
    title: str,
    dedupe_key: str,
    *,
    body: str = "",
    event_id: str | None = None,
) -> None:
    """Create an in-site alert once per ``dedupe_key``."""
    store.upsert(
        "alerts",
        {
            "kind": kind,
            "title": title[:200],
            "body": body[:4000],
            "event_id": event_id,
            "dedupe_key": dedupe_key[:200],
        },
        on_conflict="dedupe_key",
        ignore_duplicates=True,
    )


def budget_alerts(ctx: Context) -> None:
    month = ctx.now().strftime("%Y-%m")
    for line, amount in ctx.guard.crossed_lines():
        msg = (
            "Informational: month-to-date Anthropic spend passed the soft warning line."
            if line == "soft_warn"
            else "Non-essential work (discovery, rules, scoring) is paused until next month."
        )
        raise_alert(
            ctx.store, "budget", f"Spend passed ${amount}", f"budget:{month}:{line}", body=msg
        )


@contextmanager
def agent_run(ctx: Context, agent: str) -> Iterator[dict[str, Any]]:
    """Record an ``agent_runs`` row; the yielded dict becomes its stats."""
    row = ctx.store.insert("agent_runs", {"agent": agent, "status": "running"})[0]
    stats: dict[str, Any] = {}
    status, error = "ok", None
    try:
        yield stats
    except BudgetExceeded as e:
        status, error = "skipped", str(e)
        log.warning("%s stopped by budget: %s", agent, e)
    except Exception as e:
        status = "error"
        error = redact(f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}")[:4000]
        raise
    finally:
        ctx.store.update(
            "agent_runs",
            {"id": row["id"]},
            {"status": status, "error": error, "stats": stats, "finished_at": now_iso()},
        )
        budget_alerts(ctx)


def pause_for_budget(ctx: Context, event: dict[str, Any], err: BudgetExceeded) -> None:
    """Stop condition (section 10): pause the event and ask the owner."""
    if err.kind != "event_budget":
        raise err  # monthly cap / pause line: stop the whole run
    n = len(
        ctx.store.select(
            "input_requests", {"event_id": event["id"], "kind": "budget_extension"}, columns="id"
        )
    )
    ctx.store.insert(
        "input_requests",
        {
            "event_id": event["id"],
            "key": f"budget_extension_{n + 1}",
            "kind": "budget_extension",
            "description": f"{err} Reply 'yes' to add another "
            f"${ctx.guard.limits.event_budget} for this event, a dollar amount (max $5), or 'no'.",
        },
    )
    ctx.store.update(
        "events", {"id": event["id"]}, {"status": "paused_budget", "paused_from": event["status"]}
    )
    raise_alert(
        ctx.store,
        "input_needed",
        f"Budget reached: {event['title'][:120]}",
        f"budget:{event['id']}:{n + 1}",
        event_id=event["id"],
        body=str(err),
    )


def resume_budget_paused(ctx: Context) -> int:
    """Resume paused events once the owner has answered the extension request."""
    resumed = 0
    for ev in ctx.store.select("events", {"status": "paused_budget"}):
        pending = ctx.store.select(
            "input_requests",
            {"event_id": ev["id"], "kind": "budget_extension", "status": "pending"},
            columns="id",
            limit=1,
        )
        if pending:
            continue
        ctx.guard.refresh_extensions(ev["id"])  # re-read the owner's answers
        if ctx.guard.event_limit(ev["id"]) > ctx.guard.event_spend(ev["id"]):
            ctx.store.update(
                "events",
                {"id": ev["id"]},
                {"status": ev.get("paused_from") or "building", "paused_from": None},
            )
            resumed += 1
    return resumed
