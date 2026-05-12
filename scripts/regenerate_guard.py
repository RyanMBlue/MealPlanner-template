#!/usr/bin/env python3
"""Scrub a prior plan attempt for the upcoming week before regenerating.

Runs at the start of the weekly-plan workflow, before Claude. Lets the user
re-fire the workflow without polluting `meal-history.md` with the leftover
unrated entries from the prior attempt.

If `current-week.md` covers the target week (Mon–Sun starting from the next
Monday in the configured timezone), this script:

  - Deletes `current-week.md` entirely (so Claude sees no prior plan).
  - Removes target-week entries from `meal-history.md` that have an empty
    `**Rating:**` field. Rated entries are never touched.

If `current-week.md` doesn't exist or covers an older week (the normal
case on a scheduled Saturday run with a fresh week ahead), this is a no-op.

Always exits 0.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

CONFIG = Path("config.yml")
PLAN = Path("current-week.md")
HISTORY = Path("meal-history.md")
BRING_STATE = Path("bring_state.json")


def load_timezone() -> str:
    if not CONFIG.exists():
        return "America/New_York"
    cfg = yaml.safe_load(CONFIG.read_text()) or {}
    return cfg.get("timezone") or "America/New_York"


def target_week(tz_name: str) -> tuple[date, date]:
    """Return (monday, sunday) of the upcoming target week."""
    today = datetime.now(ZoneInfo(tz_name)).date()
    # weekday(): Monday=0..Sunday=6. Days until next Monday (1..7; never 0).
    days_to_monday = (7 - today.weekday()) % 7 or 7
    monday = today + timedelta(days=days_to_monday)
    sunday = monday + timedelta(days=6)
    return monday, sunday


def scrub_current_week(monday: date, sunday: date) -> bool:
    """Delete current-week.md if it has any heading dated in the target week."""
    if not PLAN.exists():
        return False
    text = PLAN.read_text()
    heading_re = re.compile(r"^##\s+\w+\s+(\d{4}-\d{2}-\d{2})\s+[—–-]", re.MULTILINE)
    for match in heading_re.finditer(text):
        try:
            d = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        if monday <= d <= sunday:
            PLAN.unlink()
            print(f"Deleted {PLAN} (covered target week {monday}..{sunday}).")
            return True
    print(f"{PLAN} exists but does not cover target week — leaving alone.")
    return False


def scrub_history(monday: date, sunday: date) -> int:
    """Remove unrated meal-history entries dated in the target week.

    Returns the number of entries removed.
    """
    if not HISTORY.exists():
        return 0

    text = HISTORY.read_text()

    # Split into entries: each entry starts with `### YYYY-MM-DD` at line start.
    # Anything before the first such heading is the "preamble" (header + format
    # section + "Real entries start below" line) and must be preserved verbatim.
    entry_split = re.compile(r"(?=^###\s+\d{4}-\d{2}-\d{2}\b)", re.MULTILINE)
    parts = entry_split.split(text)
    if not parts:
        return 0

    preamble = parts[0]
    entries = parts[1:]
    if not entries:
        return 0

    entry_head = re.compile(r"^###\s+(\d{4}-\d{2}-\d{2})\b")
    # Use [ \t] (not \s) so the trailing whitespace match doesn't eat the
    # newline and slurp the next line's content into the capture.
    rating_re = re.compile(
        r"^[ \t]*[-*][ \t]+\*\*Rating:\*\*[ \t]*(.*)$", re.MULTILINE
    )

    kept: list[str] = []
    removed: list[str] = []
    for entry in entries:
        head = entry_head.match(entry)
        if not head:
            kept.append(entry)
            continue
        try:
            d = date.fromisoformat(head.group(1))
        except ValueError:
            kept.append(entry)
            continue
        if not (monday <= d <= sunday):
            kept.append(entry)
            continue
        rating_match = rating_re.search(entry)
        rating_value = rating_match.group(1).strip() if rating_match else ""
        if rating_value:
            # Defensive: never drop a rated entry, even if dated in target week.
            kept.append(entry)
            continue
        removed.append(head.group(1))

    if not removed:
        print("No unrated target-week entries found in meal-history.md.")
        return 0

    new_text = preamble + "".join(kept)
    HISTORY.write_text(new_text)
    print(f"Removed {len(removed)} unrated target-week entries from {HISTORY}:")
    for d in removed:
        print(f"  - {d}")
    return len(removed)


def scrub_bring(monday: date, sunday: date, tz_name: str) -> int:
    """Remove prior-run MealPlanner items from the Bring! list on re-fire.

    Reads `bring_state.json` (if present). If it targets the current target
    week, for each item we added last time:
      - Look it up in the Bring! list's ACTIVE items.
      - If present and unchecked, remove it.
      - If absent (manually removed, or checked off and moved to 'recent'),
        leave Bring! alone.

    Deletes `bring_state.json` when done.

    Any failure is logged and the function returns 0 — cleanup never blocks
    the rest of the guard.
    """
    if not BRING_STATE.exists():
        return 0

    try:
        state = json.loads(BRING_STATE.read_text())
    except (ValueError, OSError) as exc:
        print(f"WARN: could not read {BRING_STATE}: {exc}")
        return 0

    try:
        state_monday = date.fromisoformat(state.get("week_of", ""))
    except ValueError:
        state_monday = None
    if state_monday != monday:
        print(f"{BRING_STATE} covers a different week "
              f"({state.get('week_of')}) — leaving alone.")
        return 0

    added_items = state.get("added_items") or []
    if not added_items:
        # No items to clean up; still delete the state file so the new run
        # starts clean.
        BRING_STATE.unlink()
        return 0

    # Read config for Bring! block.
    cfg: dict = {}
    if CONFIG.exists():
        cfg = yaml.safe_load(CONFIG.read_text()) or {}
    bring_cfg = cfg.get("bring") or {}
    list_name = bring_cfg.get("list_name")
    email = os.environ.get("BRING_EMAIL")
    password = os.environ.get("BRING_PASSWORD")

    if not list_name or not email or not password:
        print("Bring! not configured — cannot clean up prior items. "
              f"Deleting {BRING_STATE} anyway.")
        BRING_STATE.unlink()
        return 0

    # Import here so the guard doesn't require bring-api unless needed.
    try:
        from bring_client import BringClient  # noqa: PLC0415
    except ImportError as exc:
        print(f"WARN: bring_client import failed ({exc}). "
              f"Deleting {BRING_STATE}.")
        BRING_STATE.unlink()
        return 0

    # Import normalizer here so dedup logic mirrors push_to_bring.py
    # (Bring!'s catalog often title-cases item names, so raw equality misses items).
    from item_normalizer import normalize  # noqa: PLC0415

    removed = 0
    try:
        client = BringClient(email, password)
        try:
            client.login()
            list_uuid = client.find_list_by_name(list_name)
            if not list_uuid:
                print(f"WARN: no Bring! list {list_name!r} — skipping cleanup.")
            else:
                items = client.get_items(list_uuid)
                active_by_norm: dict[str, str] = {}
                for i in items.get("active", []):
                    raw = i.get("itemId") or i.get("name") or ""
                    if raw:
                        active_by_norm.setdefault(normalize(raw), raw)
                for name in added_items:
                    target = active_by_norm.get(normalize(name))
                    if target:
                        try:
                            client.remove_item(list_uuid, target)
                            print(f"  REMOVED  {target!r} (prior run's unchecked item)")
                            removed += 1
                        except Exception as exc:
                            print(f"  WARN: could not remove {target!r}: {exc}")
                    else:
                        print(f"  KEEP     {name!r} (not on active list — "
                              "likely purchased or manually removed)")
        finally:
            client.close()
    except Exception as exc:
        print(f"WARN: Bring! cleanup failed ({exc.__class__.__name__}): {exc}")

    BRING_STATE.unlink(missing_ok=True)
    return removed


def main() -> None:
    tz_name = load_timezone()
    monday, sunday = target_week(tz_name)
    print(f"Target week: {monday}..{sunday} ({tz_name})")

    deleted_plan = scrub_current_week(monday, sunday)
    removed_count = scrub_history(monday, sunday)
    bring_removed = scrub_bring(monday, sunday, tz_name)

    if deleted_plan or removed_count or bring_removed:
        print("Guard scrubbed prior re-fire artifacts. Claude can regenerate cleanly.")
    else:
        print("No prior plan for the target week — nothing to scrub.")


if __name__ == "__main__":
    main()
