"""Command-line entry point used by the GitHub Actions workflows.

hackagent intake          # discover -> rules -> score
hackagent discover | rules | score
hackagent plan            # draft plans for approved events, activate approved plans
hackagent notify          # deadline alerts, weekly / monthly summaries
hackagent sync-skills     # push skills/registry.json to the skills table
hackagent keepalive
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from typing import Any

from hackagent.shared.config import get_config
from hackagent.shared.context import Context, build_context
from hackagent.shared.security import redact

log = logging.getLogger("hackagent")


def _intake(ctx: Context) -> dict[str, Any]:
    from hackagent.agents import discovery, rules_analyst, scout

    return {
        "discovery": discovery.run(ctx),
        "rules": rules_analyst.run(ctx),
        "scout": scout.run(ctx),
    }


def _discover(ctx: Context) -> dict[str, Any]:
    from hackagent.agents import discovery

    return discovery.run(ctx)


def _rules(ctx: Context) -> dict[str, Any]:
    from hackagent.agents import rules_analyst

    return rules_analyst.run(ctx)


def _score(ctx: Context) -> dict[str, Any]:
    from hackagent.agents import scout

    return scout.run(ctx)


def _plan(ctx: Context) -> dict[str, Any]:
    from hackagent.agents import planner

    return planner.run(ctx)


def _notify(ctx: Context) -> dict[str, Any]:
    from hackagent.agents import notifier

    return notifier.run(ctx)


def _sync_skills(ctx: Context) -> dict[str, Any]:
    from hackagent.skills import registry

    return {"skills": registry.sync(ctx.store)}


def _keepalive(ctx: Context) -> dict[str, Any]:
    # A trivial read keeps the free-tier Supabase project from pausing.
    rows = ctx.store.select("settings", {"id": 1}, columns="id", limit=1)
    return {"ok": bool(rows)}


COMMANDS: dict[str, Callable[[Context], dict[str, Any]]] = {
    "intake": _intake,
    "discover": _discover,
    "rules": _rules,
    "score": _score,
    "plan": _plan,
    "notify": _notify,
    "sync-skills": _sync_skills,
    "keepalive": _keepalive,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hackagent")
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Never let HTTP client debug logs print auth headers.
    for noisy in ("httpx", "httpx2", "httpcore", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    try:
        ctx = build_context(get_config())
        result = COMMANDS[args.command](ctx)
    except Exception as e:
        log.error("%s failed: %s", args.command, redact(f"{type(e).__name__}: {e}"))
        return 1
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
