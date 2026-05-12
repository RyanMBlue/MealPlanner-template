#!/usr/bin/env python3
"""Push the weekly shopping list to Bring!.

Runs after validate_recipe_urls.py, before the workflow commits.
Parses `current-week.md`, dedupes against the configured Bring! list
(both active and recently-purchased items), and adds missing items.
Writes `bring_state.json` recording what was added so the regen guard
can clean up on a re-fire.

Opt-in: if config.yml has no `bring:` block or `bring.list_name` is empty,
this script is a no-op. Any failure (auth, network, missing list, per-item
errors) is logged and the script exits 0 — the rest of the Saturday
pipeline always runs.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from item_normalizer import normalize
from shopping_list_parser import parse as parse_shopping_list


CONFIG = Path("config.yml")
PLAN = Path("current-week.md")
STATE = Path("bring_state.json")


def _load_config() -> dict:
    if not CONFIG.exists():
        print("No config.yml — skipping Bring! push.", file=sys.stderr)
        return {}
    return yaml.safe_load(CONFIG.read_text()) or {}


def _target_week_monday(tz_name: str) -> date:
    """The upcoming Monday (or today if today is Monday ... which it won't be
    on Saturday, but defining it anyway for consistency with regen guard).
    """
    today = datetime.now(ZoneInfo(tz_name)).date()
    days_to_monday = (7 - today.weekday()) % 7 or 7
    return today + timedelta(days=days_to_monday)


def _write_state(week_of: date, added: list[str]) -> None:
    STATE.write_text(
        json.dumps({"week_of": week_of.isoformat(), "added_items": added}, indent=2)
        + "\n"
    )


def _build_dedup_set(items_dict: dict[str, list[dict]]) -> set[str]:
    """Normalize the names of items already on the list (both active
    and recent), for O(1) dedup lookup.
    """
    out: set[str] = set()
    for bucket in ("active", "recent"):
        for item in items_dict.get(bucket, []):
            name = item.get("itemId") or item.get("name") or ""
            if name:
                out.add(normalize(name))
    return out


def main() -> int:
    config = _load_config()
    bring_cfg = config.get("bring") or {}
    list_name = bring_cfg.get("list_name")
    if not list_name:
        print("No bring.list_name in config.yml — Bring! push disabled.")
        return 0

    email = os.environ.get("BRING_EMAIL")
    password = os.environ.get("BRING_PASSWORD")
    if not email or not password:
        print(
            "WARN: BRING_EMAIL / BRING_PASSWORD not set but bring: is configured. "
            "Skipping Bring! push.",
            file=sys.stderr,
        )
        return 0

    if not PLAN.exists():
        print(f"WARN: {PLAN} not found — nothing to push.", file=sys.stderr)
        return 0

    tz_name = config.get("timezone") or "America/New_York"
    week_of = _target_week_monday(tz_name)

    parsed = parse_shopping_list(PLAN.read_text())
    if not parsed:
        print(
            f"No shopping-list items parsed from {PLAN} — nothing to push.",
            file=sys.stderr,
        )
        return 0

    print(f"Parsed {len(parsed)} shopping-list item(s).")

    # Deferred import: keep the opt-out path (no bring: block) a clean no-op
    # even when bring-api isn't installed locally.
    try:
        from bring_client import BringClient  # noqa: PLC0415
    except ImportError as exc:
        print(f"WARN: bring_client import failed ({exc}). Skipping push.",
              file=sys.stderr)
        return 0

    try:
        client = BringClient(email, password)
        client.login()
    except Exception as exc:
        print(f"WARN: Bring! login failed ({exc.__class__.__name__}): {exc}. "
              "Skipping push.", file=sys.stderr)
        return 0

    try:
        list_uuid = client.find_list_by_name(list_name)
        if not list_uuid:
            print(
                f"WARN: no Bring! list named {list_name!r} — skipping push.",
                file=sys.stderr,
            )
            return 0

        try:
            existing_items = client.get_items(list_uuid)
        except Exception as exc:
            print(
                f"WARN: could not fetch existing items "
                f"({exc.__class__.__name__}): {exc}. Skipping push.",
                file=sys.stderr,
            )
            return 0

        existing_norm = _build_dedup_set(existing_items)

        added: list[str] = []
        skipped: list[str] = []
        errored: list[str] = []

        for name, spec in parsed:
            if not name:
                continue
            if normalize(name) in existing_norm:
                skipped.append(name)
                print(f"  SKIP  (already on list) {name!r}")
                continue
            # Inline the quantity into the item name so it shows up next to
            # the item in the Bring! list view (the 'specification' field
            # renders as a subtitle that's easy to miss while shopping).
            display_name = f"{name} ({spec})" if spec else name
            try:
                client.add_item(list_uuid, display_name, "")
            except Exception as exc:
                errored.append(name)
                print(
                    f"  ERROR adding {display_name!r} ({exc.__class__.__name__}): {exc}",
                    file=sys.stderr,
                )
                continue
            added.append(display_name)
            # Track so the dedup set stays current across duplicates in our own input.
            existing_norm.add(normalize(name))
            print(f"  ADD   {display_name!r}")

        _write_state(week_of, added)

        print(
            f"\nSummary: {len(added)} added, {len(skipped)} skipped "
            f"(already on list), {len(errored)} errors."
        )
    finally:
        try:
            client.close()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
