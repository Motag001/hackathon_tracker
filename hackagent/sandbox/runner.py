"""Run model-generated tests. Designed for a CI job that holds no secrets.

    python -m hackagent.sandbox.runner <staged-dir> <report.json>

Each staged milestone directory (``<event_id>/<milestone_id>/``) runs in its
own subprocess with a minimal environment, isolated mode, a time limit and
output truncation. This module imports nothing from the rest of the package
so it can run with only the standard library and pytest installed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT_S = 120
TAIL_CHARS = 4000
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _counts(output: str) -> dict[str, int]:
    out = {"passed": 0, "failed": 0, "errors": 0}
    for n, word in re.findall(r"(\d+) (passed|failed|errors?)", output):
        out["errors" if word.startswith("error") else word] += int(n)
    return out


def run_dir(path: Path) -> dict:
    with tempfile.TemporaryDirectory() as home:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": home,
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
        }
        cmd = [
            sys.executable,
            "-I",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--rootdir",
            ".",
            "-o",
            "pythonpath=.",
            "--maxfail=25",
        ]
        try:
            proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
                cmd,
                cwd=path,
                env=env,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_S,
                check=False,
            )
            output, code, timed_out = proc.stdout + proc.stderr, proc.returncode, False
        except subprocess.TimeoutExpired as e:
            output = (e.stdout or "") if isinstance(e.stdout, str) else ""
            code, timed_out = -1, True
    return {
        "exit_code": code,
        "timed_out": timed_out,
        "output_tail": output[-TAIL_CHARS:],
        **_counts(output),
    }


def main(argv: list[str]) -> int:
    root, report = Path(argv[0]), Path(argv[1])
    results = []
    if root.exists():
        for event_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            for ms_dir in sorted(p for p in event_dir.iterdir() if p.is_dir()):
                if not (_UUID.match(event_dir.name) and _UUID.match(ms_dir.name)):
                    continue
                results.append(
                    {"event_id": event_dir.name, "milestone_id": ms_dir.name, **run_dir(ms_dir)}
                )
    report.write_text(json.dumps({"version": 1, "results": results}))
    print(f"Ran tests for {len(results)} milestone(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
