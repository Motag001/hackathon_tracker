"""Devpost adapter: uses the public JSON listing behind devpost.com/hackathons."""

from __future__ import annotations

from typing import Any

from hackagent.shared.security import SafeFetcher
from hackagent.sources.base import (
    RawEvent,
    SourceAdapter,
    SourceError,
    parse_date_range,
    parse_money,
    strip_tags,
)


class DevpostAdapter(SourceAdapter):
    id = "devpost"
    allowed_hosts = ("devpost.com",)
    LIST_URL = "https://devpost.com/api/hackathons"

    def fetch(self, fetcher: SafeFetcher, max_pages: int = 5) -> list[RawEvent]:
        events: list[RawEvent] = []
        for page in range(1, max_pages + 1):
            data = fetcher.get_json(
                self.LIST_URL,
                params=[
                    ("page", str(page)),
                    ("status[]", "upcoming"),
                    ("status[]", "open"),
                    ("challenge_type[]", "online"),
                    ("order_by", "deadline"),
                ],
            )
            if not isinstance(data, dict) or "hackathons" not in data:
                raise SourceError("Devpost listing format changed (no 'hackathons' key)")
            batch = data["hackathons"] or []
            events.extend(e for e in (self.parse(h) for h in batch) if e is not None)
            per_page = (data.get("meta") or {}).get("per_page") or len(batch)
            if not batch or len(batch) < per_page:
                break
        return events

    @staticmethod
    def parse(h: dict[str, Any]) -> RawEvent | None:
        url = str(h.get("url") or "")
        if not h.get("id") or not h.get("title") or not url.startswith("https://"):
            return None
        location = ((h.get("displayed_location") or {}).get("location") or "").strip().lower()
        start, end = parse_date_range(h.get("submission_period_dates"))
        prize_text = h.get("prize_amount")
        return RawEvent(
            source_id="devpost",
            external_id=str(h["id"]),
            title=str(h["title"]).strip(),
            url=url if url.endswith("/") else url + "/",
            organizer=h.get("organization_name"),
            starts_at=start,
            submission_deadline=end,
            prize_text=strip_tags(prize_text),
            cash_value_usd=parse_money(prize_text),
            is_online=location == "online" if location else None,
            invite_only=bool(h.get("invite_only")),
            themes=[
                t["name"] for t in h.get("themes") or [] if isinstance(t, dict) and t.get("name")
            ],
            registrants=h.get("registrations_count"),
            raw={
                k: h.get(k)
                for k in (
                    "open_state",
                    "time_left_to_submission",
                    "featured",
                    "submission_period_dates",
                    "managed_by_devpost_badge",
                )
            },
        )

    def rules_urls(self, event: dict[str, Any]) -> list[str]:
        base = event["url"].rstrip("/")
        return [f"{base}/", f"{base}/rules"]
