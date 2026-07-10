#!/usr/bin/env python3
"""Resolve the target Monday for a weekly-plan run — the single source of truth.

The workflow, the plan prompt, the freshness verifier, the email sender, and the
commit message must all agree on *which* week is being planned. Before this
helper existed they each derived it independently and disagreed off-Saturday
(the verifier always wanted the strictly-next Monday; the sender wanted the
current week's Monday Mon–Fri; the prompt hardcoded "today is Saturday"), so a
manual `workflow_dispatch` on a weekday could generate, verify, and email
mismatched weeks. See issue #3.

Resolution order:
  1. An explicit target (``--monday`` or ``$TARGET_MONDAY``), which must be a
     valid ``YYYY-MM-DD`` date that falls on a Monday, else we fail fast.
  2. Otherwise the upcoming Monday (strictly after today) in the configured
     timezone — the scheduled Saturday behavior, unchanged.

CLI: prints the resolved Monday (``YYYY-MM-DD``) to stdout and exits 0; exits 1
with a message on invalid input. With ``--emit-file PATH`` it also writes a small
markdown file the plan prompt reads (the Claude step has no Bash tool, so it
can't read the env var directly).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

CONFIG = Path("config.yml")
ENV_VAR = "TARGET_MONDAY"
DEFAULT_TZ = "America/New_York"


def load_timezone() -> str:
    if not CONFIG.exists():
        return DEFAULT_TZ
    cfg = yaml.safe_load(CONFIG.read_text()) or {}
    return cfg.get("timezone") or DEFAULT_TZ


def upcoming_monday(tz_name: str, today: date | None = None) -> date:
    """The next Monday strictly after today in the given timezone."""
    if today is None:
        today = datetime.now(ZoneInfo(tz_name)).date()
    days = (7 - today.weekday()) % 7 or 7
    return today + timedelta(days=days)


def parse_monday(value: str) -> date:
    """Parse an ISO date that must land on a Monday. Raise ValueError otherwise."""
    text = value.strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"target Monday {value!r} is not a valid YYYY-MM-DD date"
        ) from exc
    if parsed.weekday() != 0:
        raise ValueError(
            f"target Monday {value!r} falls on a {parsed.strftime('%A')}, not a Monday"
        )
    return parsed


def resolve_target_monday(
    tz_name: str,
    explicit: str | None = None,
    today: date | None = None,
) -> date:
    """Return the validated explicit Monday if given, else the upcoming Monday."""
    if explicit is not None and explicit.strip():
        return parse_monday(explicit)
    return upcoming_monday(tz_name, today)


def render_target_file(monday: date) -> str:
    sunday = monday + timedelta(days=6)
    return (
        "# Target week\n\n"
        f"- **Monday:** {monday.isoformat()}\n"
        f"- **Sunday:** {sunday.isoformat()}\n\n"
        f"The plan covers Monday {monday.isoformat()} through "
        f"Sunday {sunday.isoformat()}. This file is authoritative — do not infer "
        "the week from today's date.\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--monday",
        default=os.environ.get(ENV_VAR),
        help="Explicit target Monday (YYYY-MM-DD). "
        f"Defaults to ${ENV_VAR}, else the upcoming Monday.",
    )
    parser.add_argument(
        "--emit-file",
        metavar="PATH",
        help="Also write a small markdown file (for the plan prompt to Read).",
    )
    args = parser.parse_args()

    tz_name = load_timezone()
    try:
        monday = resolve_target_monday(tz_name, args.monday)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.emit_file:
        Path(args.emit_file).write_text(render_target_file(monday))

    print(monday.isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
