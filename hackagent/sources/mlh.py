"""MLH adapter: parses the season events page (schema.org Event microdata).

MLH lists few prizes on its index, so prize values stay unknown here and
the Rules Analyst reads them from the event's own site.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from hackagent.shared.security import SafeFetcher
from hackagent.sources.base import RawEvent, SourceAdapter, SourceError, parse_iso

_VOID = {"meta", "link", "img", "br", "hr", "input", "source", "wbr"}


class _MicrodataParser(HTMLParser):
    """Collects itemscope blocks of type schema.org/Event."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[dict[str, Any]] = []
        self._stack: list[tuple[str, dict[str, Any] | None]] = []
        self._current: dict[str, Any] | None = None
        self._capture: str | None = None
        self._href: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self._href = a["href"]
        started = None
        if "itemscope" in a and "schema.org/Event" in (a.get("itemtype") or ""):
            started = {"href": self._href, "text": []}
            self._current = started
        self._stack.append((tag, started))
        if self._current is None:
            return
        prop = a.get("itemprop")
        if prop and a.get("content") is not None:
            self._current[prop] = a["content"]
        elif prop == "url" and a.get("href"):
            self._current["url"] = a["href"]
        elif prop:
            self._capture = prop
        if tag in _VOID:
            self._stack.pop()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        # Ignore stray or void end tags instead of unwinding the whole stack.
        if tag in _VOID or all(t != tag for t, _ in self._stack):
            return
        while self._stack:
            t, started = self._stack.pop()
            if started is not None:
                self.events.append(started)
                self._current = None
            if t == tag:
                break
        self._capture = None
        if tag == "a":
            self._href = None

    def handle_data(self, data):
        if self._current is None:
            return
        text = data.strip()
        if not text:
            return
        self._current["text"].append(text)
        if self._capture and self._capture not in self._current:
            self._current[self._capture] = text


def _clean_url(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return None
    # Drop tracking query strings; keep the path.
    return urlunsplit(("https", parts.netloc, parts.path or "/", "", ""))


class MLHAdapter(SourceAdapter):
    id = "mlh"
    allowed_hosts = ("mlh.io",)

    def season_url(self, now: datetime | None = None) -> str:
        now = now or datetime.now(UTC)
        # MLH seasons run Aug-Jul and are named after the year they end in.
        season = now.year + 1 if now.month >= 8 else now.year
        return f"https://mlh.io/seasons/{season}/events"

    def fetch(self, fetcher: SafeFetcher, max_pages: int = 1) -> list[RawEvent]:
        html = fetcher.get_text(self.season_url())
        events = self.parse_html(html)
        if not events:
            raise SourceError("MLH page parsed to zero events; the layout may have changed")
        return events

    @staticmethod
    def parse_html(html: str) -> list[RawEvent]:
        p = _MicrodataParser()
        p.feed(html)
        p.close()
        out = []
        for item in p.events:
            name = item.get("name")
            url = _clean_url(item.get("url") or item.get("href") or "")
            if not name or not url:
                continue
            text = " ".join(item.get("text", [])).lower()
            if "digital" in text or "online" in text:
                online: bool | None = True
            elif "in-person" in text or "hybrid" in text:
                online = False
            else:
                online = None
            start = parse_iso(item.get("startDate"))
            end = parse_iso(item.get("endDate"))
            if end:
                end = end.replace(hour=23, minute=59)
            ext = hashlib.sha256(f"{url}|{item.get('startDate')}".encode()).hexdigest()[:24]
            out.append(
                RawEvent(
                    source_id="mlh",
                    external_id=ext,
                    title=str(name).strip(),
                    url=url,
                    starts_at=start,
                    submission_deadline=end,
                    is_online=online,
                    raw={"location_text": item.get("addressLocality") or item.get("location")},
                )
            )
        return out
