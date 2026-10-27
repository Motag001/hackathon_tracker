"""Source adapter contract and shared parsing helpers."""

from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from hackagent.shared.security import SafeFetcher


@dataclass
class RawEvent:
    source_id: str
    external_id: str
    title: str
    url: str
    organizer: str | None = None
    starts_at: datetime | None = None
    submission_deadline: datetime | None = None
    registration_deadline: datetime | None = None
    prize_text: str | None = None
    cash_value_usd: Decimal | None = None
    is_online: bool | None = None
    invite_only: bool = False
    themes: list[str] = field(default_factory=list)
    registrants: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("invite_only")
        for k in ("starts_at", "submission_deadline", "registration_deadline"):
            d[k] = d[k].isoformat() if d[k] else None
        d["cash_value_usd"] = str(self.cash_value_usd) if self.cash_value_usd is not None else None
        d["prize_value_known"] = self.cash_value_usd is not None
        d["dedupe_key"] = dedupe_key(self.title, self.submission_deadline)
        d["raw"] = {**self.raw, "invite_only": self.invite_only}
        d["title"] = self.title[:300]
        return d


class SourceError(RuntimeError):
    pass


class SourceAdapter(ABC):
    id: str
    allowed_hosts: tuple[str, ...]

    @abstractmethod
    def fetch(self, fetcher: SafeFetcher, max_pages: int = 5) -> list[RawEvent]: ...

    def rules_urls(self, event: dict[str, Any]) -> list[str]:
        """Pages the Rules Analyst should read for this event."""
        return [event["url"]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Approximate USD conversion for prize values. Marked approximate in the UI;
# the owner reviews prize values at GATE 1.
FX_TO_USD = {
    "$": Decimal("1"),
    "USD": Decimal("1"),
    "€": Decimal("1.08"),
    "EUR": Decimal("1.08"),
    "£": Decimal("1.27"),
    "GBP": Decimal("1.27"),
    "₹": Decimal("0.012"),
    "INR": Decimal("0.012"),
    "₦": Decimal("0.00065"),
    "NGN": Decimal("0.00065"),
}
_MONEY = re.compile(
    r"(?P<cur>\$|€|£|₹|₦|USD|EUR|GBP|INR|NGN)\s?(?P<num>\d[\d,]*(?:\.\d+)?)\s?(?P<mult>[kKmM]\b)?"
)


def strip_tags(value: Any, limit: int = 200) -> str | None:
    if not value:
        return None
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(value))).strip()[:limit] or None


def parse_money(text: str | None) -> Decimal | None:
    """Largest currency amount found in ``text``, in USD."""
    text = strip_tags(text, limit=2000)
    if not text:
        return None
    best: Decimal | None = None
    for m in _MONEY.finditer(text):
        try:
            value = Decimal(m.group("num").replace(",", ""))
        except InvalidOperation:
            continue
        mult = (m.group("mult") or "").lower()
        value *= {"k": 1000, "m": 1_000_000}.get(mult, 1)
        usd = (value * FX_TO_USD[m.group("cur")]).quantize(Decimal("0.01"))
        best = usd if best is None or usd > best else best
    return best


_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}


def parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def parse_date_range(
    text: str | None, today: datetime | None = None
) -> tuple[datetime | None, datetime | None]:
    """Parse Devpost-style ranges: 'Sep 23 - Nov 04, 2026' or 'Dec 01, 2026 - Jan 15, 2027'."""
    if not text:
        return None, None
    parts = re.findall(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,\s*(\d{4}))?", text)
    if not parts:
        return None, None
    fallback_year = (today or datetime.now(UTC)).year
    dates: list[datetime] = []
    for i, (mon, day, year) in enumerate(parts[:2]):
        m = _MONTHS.get(mon.lower())
        if not m:
            return None, None
        # A date without a year takes the next explicit year in the range.
        later = [int(y) for _, _, y in parts[i:] if y]
        y = int(year) if year else (later[0] if later else fallback_year)
        try:
            dates.append(datetime(y, m, int(day), 23, 59, tzinfo=UTC))
        except ValueError:
            return None, None
    start, end = dates[0].replace(hour=0, minute=0), dates[-1]
    if start > end:
        # 'Dec 01 - Jan 15, 2027': the start belongs to the previous year.
        start = start.replace(year=start.year - 1)
    return start, end


_STOP = {"hackathon", "hack", "the", "a", "an", "online", "virtual", "global", "edition"}


def dedupe_key(title: str, deadline: datetime | None) -> str:
    t = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\b20\d\d\b", " ", t)
    words = [w for w in re.findall(r"[a-z0-9]+", t) if w not in _STOP]
    month = deadline.strftime("%Y-%m") if deadline else "nodate"
    return "-".join(words)[:120] + "|" + month
