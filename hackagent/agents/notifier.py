"""In-site notifications that need no model: deadline warnings, weekly and
monthly summaries (including rejection patterns, section 6)."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from decimal import Decimal
from typing import Any

from hackagent.shared.context import Context, agent_run, raise_alert
from hackagent.sources.base import parse_iso

ACTIVE = [
    "approved",
    "planning",
    "plan_ready",
    "plan_approved",
    "building",
    "awaiting_input",
    "paused_budget",
    "in_review",
    "submission_ready",
]


def deadline_alerts(ctx: Context) -> int:
    now = ctx.now()
    soon = now + timedelta(hours=48)
    n = 0
    for ev in ctx.store.select("events", [("status", "in", ACTIVE)]):
        deadline = parse_iso(ev.get("submission_deadline"))
        if deadline and now <= deadline <= soon:
            hours = (deadline - now).total_seconds() / 3600
            raise_alert(
                ctx.store,
                "deadline_48h",
                f"Deadline in {hours:.0f}h: {ev['title'][:120]}",
                f"deadline:{ev['id']}",
                event_id=ev["id"],
                body=f"Submission closes {deadline:%Y-%m-%d %H:%M} UTC. "
                f"Current stage: {ev['status']}.",
            )
            n += 1
    return n


def _since(ctx: Context, table: str, days: int, columns: str = "*") -> list[dict[str, Any]]:
    start = (ctx.now() - timedelta(days=days)).isoformat()
    col = "first_seen_at" if table == "events" else "created_at"
    return ctx.store.select(table, [(col, "gte", start)], columns=columns)


def rejection_patterns(ctx: Context, days: int = 30) -> list[str]:
    """Most common reasons events were filtered or rejected."""
    counts: Counter[str] = Counter()
    for s in _since(ctx, "scores", days, "hard_filters,passed_hard_filters"):
        if not s.get("passed_hard_filters"):
            counts.update(
                f"hard filter: {f['name']}"
                for f in s.get("hard_filters") or []
                if not f.get("passed")
            )
    for ev in _since(ctx, "events", days, "status,raw"):
        reason = (ev.get("raw") or {}).get("filter_reason")
        if ev.get("status") == "filtered_out" and reason:
            counts[f"pre-filter: {reason.split(' $')[0]}"] += 1
    for d in _since(ctx, "decisions", days, "gate,decision,reason"):
        if d["gate"] == "event" and d["decision"] == "reject":
            counts[f"you rejected: {(d.get('reason') or '')[:60]}"] += 1
    return [f"{reason} ({n})" for reason, n in counts.most_common(8)]


def summary(ctx: Context, days: int) -> str:
    events = _since(ctx, "events", days, "status")
    decisions = _since(ctx, "decisions", days, "gate,decision")
    spend = sum(
        (Decimal(str(r["cost_usd"])) for r in _since(ctx, "spend_log", days, "cost_usd")),
        Decimal(0),
    )
    statuses = Counter(e["status"] for e in events)
    approved = sum(1 for d in decisions if d["gate"] == "event" and d["decision"] == "approve")
    submitted = sum(
        1 for d in decisions if d["gate"] == "submission" and d["decision"] == "approve"
    )
    lines = [
        f"Events considered: {len(events)} (surfaced {statuses.get('awaiting_approval', 0)}, "
        f"filtered {statuses.get('filtered_out', 0)}, below threshold "
        f"{statuses.get('below_threshold', 0)})",
        f"Approved: {approved}. Submitted: {submitted}.",
        f"Anthropic spend: ${spend:.2f} (month to date ${ctx.guard.month_spend():.2f}).",
        "Top rejection reasons:",
        *(f"- {r}" for r in rejection_patterns(ctx, days)),
    ]
    return "\n".join(lines)


def run(ctx: Context) -> dict[str, Any]:
    with agent_run(ctx, "notifier") as stats:
        now = ctx.now()
        stats["deadline_alerts"] = deadline_alerts(ctx)
        if now.weekday() == 0:  # Mondays
            week = now.strftime("%G-W%V")
            raise_alert(
                ctx.store,
                "weekly_summary",
                f"Weekly summary {week}",
                f"weekly:{week}",
                body=summary(ctx, 7),
            )
            stats["weekly"] = True
        if now.day == 1:
            month = (now - timedelta(days=1)).strftime("%Y-%m")
            raise_alert(
                ctx.store,
                "monthly_summary",
                f"Monthly summary {month}",
                f"monthly:{month}",
                body=summary(ctx, 30),
            )
            stats["monthly"] = True
    return stats
