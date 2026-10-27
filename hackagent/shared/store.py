"""Data access.

Agents communicate only through the database (section 4). ``Store`` is the
small interface every agent uses; ``SupabaseStore`` talks to PostgREST and
Supabase Storage over HTTPS, ``MemoryStore`` backs the tests and dry runs.

Table and column names are validated against a strict pattern before they
are placed in a URL, and values are always sent as query parameters or JSON
bodies, never interpolated into paths.
"""

from __future__ import annotations

import copy
import re
import threading
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx2 as httpx

from hackagent.shared.config import Config

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_STORAGE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,511}$")
_OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "in", "is", "cs"}

Row = dict[str, Any]
Filter = tuple[str, str, Any]
Filters = Mapping[str, Any] | Iterable[Filter] | None


class StoreError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


def normalize_filters(filters: Filters) -> list[Filter]:
    if filters is None:
        return []
    if isinstance(filters, Mapping):
        return [(k, "eq", v) for k, v in filters.items()]
    out = []
    for col, op, val in filters:
        if op not in _OPS:
            raise ValueError(f"Unsupported filter operator: {op}")
        out.append((_ident(col), op, val))
    return out


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Store(Protocol):
    def select(
        self,
        table: str,
        filters: Filters = None,
        *,
        columns: str = "*",
        order: str | None = None,
        desc: bool = False,
        limit: int | None = None,
    ) -> list[Row]: ...

    def insert(self, table: str, rows: Row | list[Row]) -> list[Row]: ...

    def upsert(
        self,
        table: str,
        rows: Row | list[Row],
        *,
        on_conflict: str,
        ignore_duplicates: bool = False,
    ) -> list[Row]: ...

    def update(self, table: str, filters: Filters, patch: Row) -> list[Row]: ...

    def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> str: ...


# ---------------------------------------------------------------------------
# Supabase (PostgREST + Storage)
# ---------------------------------------------------------------------------


def _quote(value: Any) -> str:
    s = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _encode_value(op: str, value: Any) -> str:
    if op == "in":
        return "in.(" + ",".join(_quote(v) for v in value) + ")"
    if op == "cs":
        return "cs.{" + ",".join(_quote(v) for v in value) + "}"
    if op == "is":
        if value not in (None, True, False):
            raise ValueError("'is' filter accepts only None, True or False")
        return "is." + {None: "null", True: "true", False: "false"}[value]
    if isinstance(value, bool):
        value = "true" if value else "false"
    return f"{op}.{value}"


class SupabaseStore:
    """PostgREST client using the service role key (agents only)."""

    def __init__(self, config: Config, client: httpx.Client | None = None):
        if not config.supabase_url or not config.supabase_service_role_key:
            raise StoreError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        key = config.supabase_service_role_key.get_secret_value()
        self._base = config.supabase_url
        self._client = client or httpx.Client(timeout=config.http_timeout_s)
        self._headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "User-Agent": config.user_agent,
        }

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        headers = {**self._headers, **kw.pop("headers", {})}
        try:
            resp = self._client.request(method, f"{self._base}{path}", headers=headers, **kw)
        except httpx.HTTPError as e:
            raise StoreError(f"{method} {path} failed: {type(e).__name__}") from None
        if resp.status_code >= 400:
            # Body carries PostgREST's error message; it never contains our key.
            detail = resp.text[:500]
            raise StoreError(f"{method} {path} -> {resp.status_code}: {detail}", resp.status_code)
        return resp

    def select(self, table, filters=None, *, columns="*", order=None, desc=False, limit=None):
        params: list[tuple[str, str]] = [("select", columns)]
        for col, op, val in normalize_filters(filters):
            params.append((col, _encode_value(op, val)))
        if order:
            params.append(("order", f"{_ident(order)}.{'desc' if desc else 'asc'}"))
        if limit is not None:
            params.append(("limit", str(int(limit))))
        return self._request("GET", f"/rest/v1/{_ident(table)}", params=params).json()

    def insert(self, table, rows):
        resp = self._request(
            "POST",
            f"/rest/v1/{_ident(table)}",
            json=rows,
            headers={"Prefer": "return=representation"},
        )
        return resp.json()

    def upsert(self, table, rows, *, on_conflict, ignore_duplicates=False):
        cols = ",".join(_ident(c.strip()) for c in on_conflict.split(","))
        resolution = "ignore-duplicates" if ignore_duplicates else "merge-duplicates"
        resp = self._request(
            "POST",
            f"/rest/v1/{_ident(table)}",
            params={"on_conflict": cols},
            json=rows,
            headers={"Prefer": f"return=representation,resolution={resolution}"},
        )
        return resp.json()

    def update(self, table, filters, patch):
        flt = normalize_filters(filters)
        if not flt:
            raise ValueError("Refusing an update without filters")
        params = [(col, _encode_value(op, val)) for col, op, val in flt]
        resp = self._request(
            "PATCH",
            f"/rest/v1/{_ident(table)}",
            params=params,
            json=patch,
            headers={"Prefer": "return=representation"},
        )
        return resp.json()

    def upload(self, bucket, path, data, content_type):
        if not _STORAGE_PATH.match(path) or ".." in path:
            raise ValueError(f"Unsafe storage path: {path!r}")
        self._request(
            "POST",
            f"/storage/v1/object/{_ident(bucket)}/{path}",
            content=data,
            headers={"Content-Type": content_type, "x-upsert": "true"},
        )
        return f"{bucket}/{path}"


# ---------------------------------------------------------------------------
# In-memory store (tests, dry runs)
# ---------------------------------------------------------------------------


def _match(row: Row, flt: list[Filter]) -> bool:
    for col, op, val in flt:
        cur = row.get(col)
        if op == "eq" and cur != val:
            return False
        if op == "neq" and cur == val:
            return False
        if op == "in" and cur not in list(val):
            return False
        if op == "is" and cur is not val:
            return False
        if op == "cs" and not set(val) <= set(cur or []):
            return False
        if op in {"gt", "gte", "lt", "lte"}:
            if cur is None:
                return False
            if op == "gt" and not cur > val:
                return False
            if op == "gte" and not cur >= val:
                return False
            if op == "lt" and not cur < val:
                return False
            if op == "lte" and not cur <= val:
                return False
    return True


class MemoryStore:
    """Thread-safe in-memory implementation of ``Store``."""

    # Columns with database defaults the agents rely on.
    _DEFAULTS: dict[str, dict[str, Any]] = {
        "events": {"status": "discovered", "themes": [], "raw": {}},
        "plans": {"status": "draft", "version": 1},
        "milestones": {"status": "pending", "skills": [], "input_keys": []},
        "input_requests": {"status": "pending"},
        "submissions": {"status": "draft", "version": 1, "review_notes": []},
        "learnings": {"status": "draft"},
        "playbook": {"status": "proposed"},
        "skills": {"enabled": True, "usage_count": 0, "success_count": 0},
        "sources": {"enabled": False, "consecutive_failures": 0},
    }
    _KEYS: dict[str, str] = {"sources": "id", "skills": "id", "settings": "id"}

    def __init__(self) -> None:
        self.tables: dict[str, list[Row]] = {}
        self.files: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def _prepare(self, table: str, row: Row) -> Row:
        out = copy.deepcopy(self._DEFAULTS.get(table, {}))
        out.update(copy.deepcopy(row))
        key = self._KEYS.get(table, "id")
        if key == "id" and "id" not in out:
            out["id"] = str(uuid.uuid4())
        out.setdefault("created_at", now_iso())
        return out

    def select(self, table, filters=None, *, columns="*", order=None, desc=False, limit=None):
        flt = normalize_filters(filters)
        with self._lock:
            rows = [copy.deepcopy(r) for r in self.tables.get(table, []) if _match(r, flt)]
        if order:
            rows.sort(key=lambda r: (r.get(order) is None, r.get(order)), reverse=desc)
        return rows[:limit] if limit is not None else rows

    def insert(self, table, rows):
        items = rows if isinstance(rows, list) else [rows]
        with self._lock:
            prepared = [self._prepare(table, r) for r in items]
            self.tables.setdefault(table, []).extend(prepared)
        return copy.deepcopy(prepared)

    def upsert(self, table, rows, *, on_conflict, ignore_duplicates=False):
        items = rows if isinstance(rows, list) else [rows]
        keys = [c.strip() for c in on_conflict.split(",")]
        out = []
        with self._lock:
            existing = self.tables.setdefault(table, [])
            for r in items:
                hit = next((e for e in existing if all(e.get(k) == r.get(k) for k in keys)), None)
                if hit is None:
                    new = self._prepare(table, r)
                    existing.append(new)
                    out.append(copy.deepcopy(new))
                elif not ignore_duplicates:
                    hit.update(copy.deepcopy(r))
                    out.append(copy.deepcopy(hit))
        return out

    def update(self, table, filters, patch):
        flt = normalize_filters(filters)
        if not flt:
            raise ValueError("Refusing an update without filters")
        out = []
        with self._lock:
            for r in self.tables.get(table, []):
                if _match(r, flt):
                    r.update(copy.deepcopy(patch))
                    out.append(copy.deepcopy(r))
        return out

    def upload(self, bucket, path, data, content_type):
        if not _STORAGE_PATH.match(path) or ".." in path:
            raise ValueError(f"Unsafe storage path: {path!r}")
        self.files[f"{bucket}/{path}"] = data
        return f"{bucket}/{path}"


def get_store(config: Config) -> Store:
    if config.dry_run:
        return MemoryStore()
    return SupabaseStore(config)
