"""Record sandbox test results (runs in a job with database access).

The report was produced next to untrusted code, so it is treated as
untrusted input: strict schema, UUID-only ids, bounded sizes, and each
milestone must already belong to the event it claims.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hackagent.shared.context import Context, agent_run, raise_alert
from hackagent.skills.registry import record_use

_UUID = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(pattern=_UUID)
    milestone_id: str = Field(pattern=_UUID)
    exit_code: int
    timed_out: bool
    output_tail: str = Field(max_length=5000)
    passed: int = Field(ge=0, le=100_000)
    failed: int = Field(ge=0, le=100_000)
    errors: int = Field(ge=0, le=100_000)


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int
    results: list[Result] = Field(max_length=200)


def record(ctx: Context, report_path: Path) -> dict[str, Any]:
    with agent_run(ctx, "sandbox_recorder") as stats:
        raw = report_path.read_bytes()
        if len(raw) > 2_000_000:
            raise ValueError("Report too large")
        try:
            report = Report.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as e:
            raise ValueError(f"Invalid sandbox report: {e}") from None
        stats.update({"recorded": 0, "rejected": 0, "failing": 0})
        for r in report.results:
            ms = ctx.store.select(
                "milestones",
                {"id": r.milestone_id, "event_id": r.event_id},
                columns="id,seq,title,notes",
                limit=1,
            )
            if not ms:
                stats["rejected"] += 1
                continue
            ok = r.exit_code == 0 and not r.timed_out and r.failed == 0 and r.errors == 0
            ctx.store.update(
                "milestones",
                {"id": r.milestone_id},
                {
                    "test_report": {
                        "ok": ok,
                        "passed": r.passed,
                        "failed": r.failed,
                        "errors": r.errors,
                        "timed_out": r.timed_out,
                        "exit_code": r.exit_code,
                        "output_tail": r.output_tail,
                    }
                },
            )
            record_use(ctx.store, "code_tests", success=ok)
            stats["recorded"] += 1
            if not ok:
                stats["failing"] += 1
                raise_alert(
                    ctx.store,
                    "info",
                    f"Tests failing for milestone #{ms[0]['seq']}",
                    f"tests:{r.milestone_id}:{r.passed}:{r.failed}:{r.errors}",
                    event_id=r.event_id,
                    body=f"'{ms[0]['title']}': {r.passed} passed, {r.failed} failed, "
                    f"{r.errors} errors{' (timed out)' if r.timed_out else ''}.",
                )
    return stats
