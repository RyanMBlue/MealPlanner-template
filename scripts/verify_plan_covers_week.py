#!/usr/bin/env python3
"""Fail the workflow if `current-week.md` doesn't cover the upcoming week.

Runs after Claude generates the plan and before any downstream step that
would commit, push, or email it. Without this guard, a Claude failure
mode (max-turn exhaustion, timeout, partial write) leaves the previous
week's plan in place and the rest of the pipeline silently re-publishes
it — see issue #26.

Exit code:
  0  current-week.md has a `## Monday <upcoming-Monday>` heading.
  1  it doesn't (or the file is missing) — print a clear error.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date
from pathlib import Path

from week_target import ENV_VAR, load_timezone, resolve_target_monday

PLAN = Path("current-week.md")


def plan_covers_week(md: str, monday: date) -> bool:
    """True iff `md` has a `## Monday <monday> [—–-]` heading."""
    pattern = re.compile(
        rf"^##\s+Monday\s+{re.escape(monday.isoformat())}\s+[—–-]",
        re.MULTILINE,
    )
    return pattern.search(md) is not None


def main() -> int:
    try:
        monday = resolve_target_monday(load_timezone(), os.environ.get(ENV_VAR))
    except ValueError as exc:
        print(f"FAIL: invalid {ENV_VAR}: {exc}", file=sys.stderr)
        return 1

    if not PLAN.exists():
        print(
            f"FAIL: {PLAN} is missing — Claude did not produce a plan for "
            f"the week of {monday}.",
            file=sys.stderr,
        )
        return 1

    md = PLAN.read_text()
    if not plan_covers_week(md, monday):
        print(
            f"FAIL: {PLAN} does not contain a Monday heading for {monday} — "
            f"Claude likely failed to write a fresh plan for the upcoming "
            f"week (see issue #26).",
            file=sys.stderr,
        )
        return 1

    print(f"OK: {PLAN} covers the week of {monday}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
