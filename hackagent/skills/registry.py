"""Skill registry (section 7): definitions live in registry.json and are
synced to the ``skills`` table, where usage and success counts accumulate."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from hackagent.shared.store import Store

_PATH = Path(__file__).with_name("registry.json")


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    purpose: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    cost_notes: str

    @property
    def extensions(self) -> tuple[str, ...]:
        return tuple(o if o.startswith(".") else Path(o).suffix for o in self.outputs if "." in o)


@lru_cache(maxsize=1)
def load_skills() -> dict[str, Skill]:
    data = json.loads(_PATH.read_text())
    return {
        d["id"]: Skill(
            d["id"],
            d["name"],
            d["purpose"],
            tuple(d["inputs"]),
            tuple(d["outputs"]),
            d.get("cost_notes", ""),
        )
        for d in data
    }


def enabled_skills(store: Store) -> dict[str, Skill]:
    """Registry skills not disabled by the owner on the dashboard."""
    disabled = {r["id"] for r in store.select("skills", {"enabled": False}, columns="id")}
    return {k: v for k, v in load_skills().items() if k not in disabled}


def registry_prompt(skills: dict[str, Skill]) -> str:
    lines = ["## Skill registry (use these ids only)"]
    for s in sorted(skills.values(), key=lambda s: s.id):
        lines.append(f"- {s.id}: {s.purpose} Outputs: {', '.join(s.outputs)}.")
    return "\n".join(lines)


def sync(store: Store) -> int:
    rows: list[dict[str, Any]] = [
        {
            "id": s.id,
            "name": s.name,
            "purpose": s.purpose,
            "inputs": list(s.inputs),
            "outputs": list(s.outputs),
            "cost_notes": s.cost_notes,
        }
        for s in load_skills().values()
    ]
    store.upsert("skills", rows, on_conflict="id")
    return len(rows)


def record_use(store: Store, skill_id: str, success: bool) -> None:
    rows = store.select("skills", {"id": skill_id}, columns="usage_count,success_count", limit=1)
    if not rows:
        return
    r = rows[0]
    store.update(
        "skills",
        {"id": skill_id},
        {
            "usage_count": int(r.get("usage_count") or 0) + 1,
            "success_count": int(r.get("success_count") or 0) + (1 if success else 0),
        },
    )
