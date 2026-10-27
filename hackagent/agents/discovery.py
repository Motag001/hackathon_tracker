"""Discovery agent: pulls listings, normalises, deduplicates, pre-filters.

Scripted, no LLM. Only sources the owner has enabled (after reviewing their
terms) are read. Cheap deterministic pre-filters run here so that obviously
ineligible events never cost a rules-analysis call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from hackagent.shared.context import Context, agent_run, raise_alert
from hackagent.shared.security import FetchError, SafeFetcher, redact
from hackagent.shared.store import now_iso
from hackagent.sources.base import RawEvent, SourceAdapter, SourceError
from hackagent.sources.registry import ADAPTERS

log = logging.getLogger(__name__)

# Listing fields, refreshed on every sighting. Status is never overwritten by
# discovery, and analysis results live in event_rules, so a refresh cannot
# clobber what the Rules Analyst found. ``raw`` is written once, on insert,
# so the pre-filter reason stored there survives later sightings.
_REFRESH = (
    "title",
    "url",
    "organizer",
    "starts_at",
    "submission_deadline",
    "registration_deadline",
    "prize_text",
    "cash_value_usd",
    "prize_value_known",
    "is_online",
    "themes",
    "registrants",
    "dedupe_key",
)


def prefilter(ev: RawEvent, now: datetime, min_prize: Decimal) -> str | None:
    """Return a rejection reason, or None if the event should be analysed."""
    if ev.is_online is False:
        return "Not an online event"
    if ev.invite_only:
        return "Invite-only"
    if ev.submission_deadline and ev.submission_deadline < now + timedelta(hours=48):
        return "Submission deadline is less than 48 hours away"
    if ev.registration_deadline and ev.registration_deadline < now:
        return "Registration has closed"
    if ev.cash_value_usd is not None and ev.cash_value_usd < min_prize:
        return f"Prize value ${ev.cash_value_usd} is below the ${min_prize} minimum"
    return None


def _fetcher(ctx: Context, adapter: SourceAdapter) -> SafeFetcher:
    return SafeFetcher(
        adapter.allowed_hosts,
        user_agent=ctx.config.user_agent,
        timeout_s=ctx.config.http_timeout_s,
        min_interval_s=2.0,
    )


def store_events(ctx: Context, source_id: str, events: list[RawEvent]) -> dict[str, int]:
    """Insert new events and refresh known ones. Two round trips per source."""
    stats = {"new": 0, "updated": 0, "filtered": 0, "duplicates": 0}
    if not events:
        return stats
    # Collapse duplicates inside one listing.
    unique = list({e.external_id: e for e in events}.values())
    ids = [e.external_id for e in unique]
    known = {
        r["external_id"]
        for r in ctx.store.select(
            "events",
            [("source_id", "eq", source_id), ("external_id", "in", ids)],
            columns="external_id",
        )
    }
    keys = list({e.to_row()["dedupe_key"] for e in unique})
    cross = {
        r["dedupe_key"]: r["id"]
        for r in ctx.store.select(
            "events",
            [("dedupe_key", "in", keys), ("source_id", "neq", source_id)],
            columns="id,dedupe_key",
        )
    }
    now = ctx.now()
    min_prize = Decimal(str(ctx.settings["min_prize_usd"]))
    stamp = now_iso()
    new_rows, refresh_rows = [], []
    for ev in unique:
        row = ev.to_row()
        if ev.external_id in known:
            refresh_rows.append(
                {
                    "source_id": source_id,
                    "external_id": ev.external_id,
                    **{k: row[k] for k in _REFRESH},
                    "last_seen_at": stamp,
                }
            )
            continue
        if row["dedupe_key"] in cross:
            row["status"] = "duplicate"
            row["duplicate_of"] = cross[row["dedupe_key"]]
            stats["duplicates"] += 1
        elif reason := prefilter(ev, now, min_prize):
            row["status"] = "filtered_out"
            row["raw"] = {**row["raw"], "filter_reason": reason}
            stats["filtered"] += 1
        new_rows.append(row)
    if new_rows:
        ctx.store.insert("events", new_rows)
        stats["new"] = len(new_rows)
    if refresh_rows:
        ctx.store.upsert("events", refresh_rows, on_conflict="source_id,external_id")
        stats["updated"] = len(refresh_rows)
    return stats


def _record_source(ctx: Context, source: dict[str, Any], error: str | None) -> None:
    failures = 0 if error is None else int(source.get("consecutive_failures") or 0) + 1
    ctx.store.update(
        "sources",
        {"id": source["id"]},
        {
            "last_run_at": now_iso(),
            "last_status": "error" if error else "ok",
            "last_error": error,
            "consecutive_failures": failures,
        },
    )
    if error:
        raise_alert(
            ctx.store,
            "source_failure",
            f"{source['name']} adapter failed",
            f"source:{source['id']}:{ctx.now():%Y-%m-%d}",
            body=f"{error}\nConsecutive failures: {failures}. "
            "The site may have changed layout or restricted access.",
        )


def run(ctx: Context, max_pages: int = 5) -> dict[str, Any]:
    with agent_run(ctx, "discovery") as stats:
        sources = ctx.store.select("sources", {"enabled": True})
        if not sources:
            log.warning("No sources enabled. Review each site's terms, then enable it.")
        for source in sources:
            adapter = ADAPTERS.get(source["id"])
            if adapter is None:
                continue
            try:
                events = adapter.fetch(_fetcher(ctx, adapter), max_pages=max_pages)
                stats[source["id"]] = store_events(ctx, source["id"], events)
                _record_source(ctx, source, None)
            except (FetchError, SourceError, ValueError, KeyError, TypeError) as e:
                err = redact(f"{type(e).__name__}: {e}")[:500]
                log.error("Source %s failed: %s", source["id"], err)
                stats[source["id"]] = {"error": err}
                _record_source(ctx, source, err)
    return stats
