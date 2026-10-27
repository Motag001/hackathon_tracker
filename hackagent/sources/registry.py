from __future__ import annotations

from hackagent.sources.base import SourceAdapter
from hackagent.sources.devfolio import DevfolioAdapter
from hackagent.sources.devpost import DevpostAdapter
from hackagent.sources.mlh import MLHAdapter

ADAPTERS: dict[str, SourceAdapter] = {
    a.id: a for a in (DevpostAdapter(), MLHAdapter(), DevfolioAdapter())
}

# Hosts the Rules Analyst may read from in addition to an event's own site.
SOURCE_HOSTS: tuple[str, ...] = tuple(h for a in ADAPTERS.values() for h in a.allowed_hosts)
