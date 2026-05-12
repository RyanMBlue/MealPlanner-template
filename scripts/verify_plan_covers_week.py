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

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

CONFIG = Path("config.yml")
PLAN = Path("current-week.md")


def load_timezone() -> str:
    if not CONFIG.exists():
        return "America/New_York"
    cfg = yaml.safe_load(CONFIG.read_text()) or {}
    return cfg.get("timezone") or "America/New_York"


def upcoming_monday(tz_name: str) -> date:
    """Return the next Monday strictly after today in the given timezone."""
    today = datetime.now(ZoneInfo(tz_name)).date()
    days = (7 - today.weekday()) % 7 or 7
    return today + timedelta(days=days)


def plan_covers_week(md: str, monday: date) -> bool:
    """True iff `md` has a `## Monday <monday> [—–-]` heading."""
    pattern = re.compile(
        rf"^##\s+Monday\s+{re.escape(monday.isoformat())}\s+[—–-]",
        re.MULTILINE,
    )
    return pattern.search(md) is not None


def main() -> int:
    tz_name = load_timezone()
    monday = upcoming_monday(tz_name)

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
