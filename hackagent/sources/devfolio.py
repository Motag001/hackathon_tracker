"""Devfolio adapter: uses the search API behind devfolio.co/hackathons.

The response shape is not documented, so parsing is defensive: unknown or
missing fields become ``None`` and the Rules Analyst fills gaps from the
event page.
"""

from __future__ import annotations

import re
from typing import Any

from hackagent.shared.security import SafeFetcher
from hackagent.sources.base import RawEvent, SourceAdapter, SourceError, parse_iso, parse_money

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


class DevfolioAdapter(SourceAdapter):
    id = "devfolio"
    allowed_hosts = ("devfolio.co",)
    SEARCH_URL = "https://api.devfolio.co/api/search/hackathons"
    PAGE_SIZE = 24

    def fetch(self, fetcher: SafeFetcher, max_pages: int = 5) -> list[RawEvent]:
        events: list[RawEvent] = []
        for page in range(max_pages):
            data = fetcher.post_json(
                self.SEARCH_URL,
                {"type": "application_open", "from": page * self.PAGE_SIZE, "size": self.PAGE_SIZE},
            )
            try:
                hits = data["hits"]["hits"]
            except (KeyError, TypeError):
                raise SourceError("Devfolio search format changed (no hits.hits)") from None
            events.extend(e for e in (self.parse(h.get("_source") or {}) for h in hits) if e)
            if len(hits) < self.PAGE_SIZE:
                break
        return events

    @staticmethod
    def parse(src: dict[str, Any]) -> RawEvent | None:
        slug = str(src.get("slug") or "").lower()
        name = src.get("name")
        if not name or not _SLUG.match(slug):
            return None
        prizes = src.get("prizes") or []
        prize_text = None
        if isinstance(prizes, list) and prizes:
            prize_text = "; ".join(
                f"{p.get('name', '')} {p.get('amount', '')} {p.get('currency', '')}".strip()
                for p in prizes
                if isinstance(p, dict)
            )[:200]
        prize_text = prize_text or src.get("prize_pool") or None
        cash = parse_money(_currency_first(prize_text)) if prize_text else None
        themes = [
            (t.get("name") if isinstance(t, dict) else str(t)) for t in src.get("themes") or []
        ]
        settings = src.get("settings") or {}
        return RawEvent(
            source_id="devfolio",
            external_id=str(src.get("uuid") or slug),
            title=str(name).strip(),
            url=f"https://{slug}.devfolio.co/",
            organizer=(src.get("organization") or {}).get("name")
            if isinstance(src.get("organization"), dict)
            else None,
            starts_at=parse_iso(src.get("starts_at")),
            submission_deadline=parse_iso(src.get("ends_at")),
            registration_deadline=parse_iso(settings.get("reg_ends_at")),
            prize_text=prize_text,
            cash_value_usd=cash,
            is_online=src.get("is_online"),
            themes=[t for t in themes if t],
            registrants=src.get("participants_count"),
            raw={"tagline": src.get("tagline"), "location": src.get("location")},
        )

    def rules_urls(self, event: dict[str, Any]) -> list[str]:
        base = event["url"].rstrip("/")
        return [f"{base}/", f"{base}/rules"]


def _currency_first(text: str) -> str:
    """'1000 USD' -> 'USD 1000' so parse_money recognises trailing currency codes."""
    return re.sub(r"(\d[\d,.]*)\s*(USD|INR|EUR|GBP|NGN)\b", r"\2 \1", text)
