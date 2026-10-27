"""Analyst: drafts "What I learned" records and playbook proposals (section 9).

Cheap model, compact inputs. Drafts only: the owner edits and approves the
learning record and decides which proposed lessons join the playbook (both
enforced in the database).
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

from hackagent.shared.context import Context, agent_run
from hackagent.shared.cost import Priority
from hackagent.shared.history import active_playbook
from hackagent.shared.llm import Call, LLMError, Tier
from hackagent.shared.security import untrusted

log = logging.getLogger(__name__)


class LearningDraft(BaseModel):
    went_well: str
    would_change: str
    carry_forward: str
    playbook_candidates: list[str]


SYSTEM = """You are the Analyst for a solo hackathon participant. Draft a short, candid
"What I learned" record from the facts given: what went well, what to change, and what to carry
forward. Use only the facts provided; do not invent feedback or outcomes. Write in the first
person as a draft for the participant to edit. playbook_candidates: at most 3 general, reusable
lessons (one sentence each, under 200 characters) that would help plan future events, and only
if the facts support them. Avoid lessons already in the playbook."""


def facts(ctx: Context, event: dict[str, Any]) -> str:
    eid = event["id"]
    plan = ctx.store.select(
        "plans", {"event_id": eid, "status": "approved"}, order="version", desc=True, limit=1
    )
    ms = ctx.store.select("milestones", {"plan_id": plan[0]["id"]}) if plan else []
    result = ctx.store.select("results", {"event_id": eid}, limit=1)
    spend = sum(
        (
            Decimal(str(r["cost_usd"]))
            for r in ctx.store.select("spend_log", {"event_id": eid}, columns="cost_usd")
        ),
        Decimal(0),
    )
    score = ctx.store.select("scores", {"event_id": eid}, order="created_at", desc=True, limit=1)
    datasets = ctx.store.select("datasets", {"event_id": eid}, columns="name,license")
    lines = [f"Event: {event['title']} ({event['source_id']}); themes {event.get('themes')}"]
    if score:
        lines.append(f"Scout score {score[0]['total']}, estimated {score[0].get('est_hours')}h")
    planned = sum(float(m.get("est_hours") or 0) for m in ms)
    actual = sum(float(m.get("actual_hours") or 0) for m in ms)
    lines.append(f"Hours planned {planned:.1f}, actual {actual:.1f}")
    for m in sorted(ms, key=lambda m: m["seq"]):
        tests = (m.get("test_report") or {}).get("ok")
        lines.append(
            f"- #{m['seq']} {m['title']}: plan {m.get('est_hours')}h, actual "
            f"{m.get('actual_hours')}h, {m['status']}, skills {m.get('skills')}, "
            f"tests {'n/a' if tests is None else tests}"
        )
    lines.append(f"Datasets: {[(d['name'], d.get('license')) for d in datasets]}")
    lines.append(f"Anthropic spend on this event: ${spend:.2f}")
    if result:
        r = result[0]
        lines.append(
            f"Result: placement {r.get('placement') or r.get('placement_text') or 'none'}, "
            f"prize ${r.get('prize_won_usd') or 0}"
        )
        fb = "\n".join(x for x in (r.get("judge_feedback"), r.get("platform_notes")) if x)
        if fb:
            lines.append("Judge and platform feedback:\n" + untrusted(fb[:6000], "feedback"))
    else:
        lines.append("No result recorded (event closed without a result).")
    return "\n".join(lines)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def draft_learning(ctx: Context, event: dict[str, Any]) -> dict[str, Any]:
    playbook = active_playbook(ctx.store, limit=30)
    call = Call(
        agent="analyst",
        tier=Tier.CHEAP,
        system=SYSTEM,
        stable_context="## Current playbook\n" + "\n".join(f"- {x}" for x in playbook),
        prompt=facts(ctx, event),
        schema=LearningDraft,
        max_tokens=4000,
        effort="low",
        event_id=event["id"],
        priority=Priority.ESSENTIAL,
        purpose=f"learnings: {event['title'][:80]}",
    )
    d = ctx.llm.structured(call)
    assert isinstance(d, LearningDraft)
    row = ctx.store.insert(
        "learnings",
        {
            "event_id": event["id"],
            "went_well": d.went_well,
            "would_change": d.would_change,
            "carry_forward": d.carry_forward,
            "status": "draft",
            "drafted_by": ctx.config.model_cheap,
        },
    )[0]
    known = {_norm(x) for x in playbook} | {
        _norm(r["lesson"])
        for r in ctx.store.select("playbook", {"status": "proposed"}, columns="lesson")
    }
    for lesson in d.playbook_candidates[:3]:
        lesson = lesson.strip()[:500]
        if lesson and _norm(lesson) not in known:
            ctx.store.insert(
                "playbook",
                {"lesson": lesson, "source_event_ids": [event["id"]], "status": "proposed"},
            )
            known.add(_norm(lesson))
    return row


def run(ctx: Context, limit: int = 5) -> dict[str, Any]:
    with agent_run(ctx, "analyst") as stats:
        stats.update({"drafted": 0, "failed": 0})
        events = ctx.store.select(
            "events",
            [("status", "in", ["results_in", "closed"])],
            order="updated_at",
            desc=True,
            limit=50,
        )
        done = (
            {
                r["event_id"]
                for r in ctx.store.select(
                    "learnings", [("event_id", "in", [e["id"] for e in events])], columns="event_id"
                )
            }
            if events
            else set()
        )
        for ev in [e for e in events if e["id"] not in done][:limit]:
            # A closed event that never got a plan has nothing to learn from.
            if ev["status"] == "closed" and not ctx.store.select(
                "plans", {"event_id": ev["id"]}, columns="id", limit=1
            ):
                continue
            try:
                draft_learning(ctx, ev)
                stats["drafted"] += 1
            except LLMError as e:
                stats["failed"] += 1
                log.warning("Learning draft failed for %s: %s", ev["id"], e)
    return stats
