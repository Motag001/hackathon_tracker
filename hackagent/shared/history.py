"""Compact summaries of past performance for agents (section 9).

Summaries are kept short and deterministic: they are computed here without
a model and inserted into prompts as a few lines, so reading history costs
very few tokens and does not break prompt caching from run to run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hackagent.shared.store import Store


@dataclass
class Calibration:
    ratio: float  # actual / planned hours
    samples: int

    def adjust(self, hours: float) -> float:
        return round(hours * self.ratio, 1)


def estimate_calibration(store: Store, min_samples: int = 3) -> Calibration:
    done = [
        r
        for r in store.select("milestones", {"status": "done"}, columns="est_hours,actual_hours")
        if r.get("actual_hours") is not None and float(r.get("est_hours") or 0) > 0
    ]
    if len(done) < min_samples:
        return Calibration(1.0, len(done))
    planned = sum(float(r["est_hours"]) for r in done)
    actual = sum(float(r["actual_hours"]) for r in done)
    return Calibration(min(max(actual / planned, 0.5), 3.0), len(done))


def _outcome(result: dict[str, Any]) -> float:
    """1.0 for a prize, 0.7 for top 3, 0.3 for a submission without placement."""
    if float(result.get("prize_won_usd") or 0) > 0:
        return 1.0
    placement = result.get("placement")
    if placement is not None and int(placement) <= 3:
        return 0.7
    return 0.3


class PastPerformance:
    """Loads results once, then scores any number of events without queries."""

    def __init__(self, store: Store):
        self.results = store.select("results", columns="event_id,placement,prize_won_usd")
        ids = [r["event_id"] for r in self.results]
        self.themes: dict[str, set[str]] = {}
        if ids:
            for e in store.select("events", [("id", "in", ids)], columns="id,themes"):
                self.themes[e["id"]] = {t.lower() for t in e.get("themes") or []}

    def score(self, themes: list[str]) -> tuple[float, str]:
        """Score 0-1 from results on events sharing a theme, plus a reason."""
        if not self.results:
            return 0.5, "No results recorded yet (neutral)."
        wanted = {t.lower() for t in themes}
        similar = [r for r in self.results if wanted & self.themes.get(r["event_id"], set())]
        pool = similar or self.results
        score = sum(_outcome(r) for r in pool) / len(pool)
        scope = f"{len(similar)} similar-theme" if similar else f"{len(pool)} (no theme match)"
        return round(score, 3), f"Average outcome {score:.2f} across {scope} past events."


def rejection_notes(store: Store, limit: int = 10) -> list[str]:
    rows = store.select(
        "decisions",
        {"gate": "event", "decision": "reject"},
        columns="event_id,reason",
        order="created_at",
        desc=True,
        limit=limit,
    )
    if not rows:
        return []
    titles = {
        e["id"]: e["title"]
        for e in store.select(
            "events", [("id", "in", [r["event_id"] for r in rows])], columns="id,title"
        )
    }
    return [f"{titles.get(r['event_id'], '?')[:60]}: {(r.get('reason') or '')[:160]}" for r in rows]


def active_playbook(store: Store, limit: int = 15) -> list[str]:
    rows = store.select(
        "playbook", {"status": "active"}, columns="lesson", order="created_at", limit=limit
    )
    return [r["lesson"] for r in rows]
