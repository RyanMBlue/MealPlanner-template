#!/usr/bin/env python3
"""Send today's dinner reminder by email via Resend.

Runs every morning. No Claude involved — just parses current-week.md.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

WEEKDAY_NAMES = {
    0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
    4: "Friday", 5: "Saturday", 6: "Sunday",
}


def load_config() -> dict:
    config_path = Path("config.yml")
    if not config_path.exists():
        sys.exit("ERROR: config.yml not found")
    return yaml.safe_load(config_path.read_text())


def load_plan() -> str | None:
    plan_path = Path("current-week.md")
    if not plan_path.exists():
        return None
    text = plan_path.read_text().strip()
    return text or None


def find_todays_section(plan: str, weekday: str, date_str: str) -> dict | None:
    """Parse current-week.md and return today's meal details, or None if not found.

    Looks for heading: `## <Weekday> YYYY-MM-DD — <Dish>`
    """
    # Split the plan into sections by `## ` headings
    # Match `## Monday 2026-04-20 — Chicken Piccata` (em-dash)
    section_pattern = re.compile(
        r"^##\s+(\w+)\s+(\d{4}-\d{2}-\d{2})\s+[—–-]\s+(.+?)\s*$",
        re.MULTILINE,
    )

    for match in section_pattern.finditer(plan):
        day_name, day_date, dish = match.group(1), match.group(2), match.group(3)
        if day_name == weekday and day_date == date_str:
            # Grab the content from here to the next `## ` or end of file
            start = match.end()
            next_heading = re.search(r"^##\s+", plan[start:], re.MULTILINE)
            end = start + next_heading.start() if next_heading else len(plan)
            section_body = plan[start:end]

            return {
                "dish": dish.strip(),
                "day": day_name,
                "date": day_date,
                "description": extract_field(section_body, "Description"),
                "active_time": extract_field(section_body, "Active time"),
                "protein": extract_field(section_body, "Protein"),
                "recipe": extract_field(section_body, "Recipe"),
                "notes": extract_field(section_body, "Notes"),
            }
    return None


def find_in_history(history: str, date_str: str) -> dict | None:
    """Parse meal-history.md and return today's meal details, or None if not found.

    Used as a fallback when current-week.md has been rotated forward by the
    Saturday workflow and no longer covers today (issue #35).

    Looks for heading: `### YYYY-MM-DD` followed by `- **Meal:** <dish>` and
    optional enriched fields (Description, Active time, Protein, Recipe).
    Returns the same dict shape as `find_todays_section` with empty strings
    where fields are missing — `build_message` already tolerates that.
    """
    heading_pattern = re.compile(
        rf"^###\s+{re.escape(date_str)}\s*$",
        re.MULTILINE,
    )
    match = heading_pattern.search(history)
    if not match:
        return None

    start = match.end()
    next_heading = re.search(r"^###\s+", history[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(history)
    section_body = history[start:end]

    dish = extract_field(section_body, "Meal")
    if not dish:
        return None

    return {
        "dish": dish,
        "day": "",
        "date": date_str,
        "description": extract_field(section_body, "Description"),
        "active_time": extract_field(section_body, "Active time"),
        "protein": extract_field(section_body, "Protein"),
        "recipe": extract_field(section_body, "Recipe"),
        "notes": extract_field(section_body, "Notes"),
    }


def load_history() -> str | None:
    history_path = Path("meal-history.md")
    if not history_path.exists():
        return None
    text = history_path.read_text().strip()
    return text or None


def extract_field(section_body: str, field_name: str) -> str:
    """Extract the value of `- **FieldName:** value` from a section body."""
    pattern = re.compile(
        rf"^\s*[-*]\s+\*\*{re.escape(field_name)}:\*\*\s*(.+?)$",
        re.MULTILINE,
    )
    match = pattern.search(section_body)
    return match.group(1).strip() if match else ""


def build_message(meal: dict) -> tuple[str, str]:
    """Return (subject, email_body)."""
    dish = meal["dish"]
    active_raw = meal.get("active_time", "")
    recipe = meal.get("recipe", "")

    # active_time field looks like: "25 min  |  **Total time:** 25 min"
    active = active_raw.split("|")[0].strip() if active_raw else ""
    is_long_passive = any(
        phrase in active_raw.lower()
        for phrase in ("long passive", "slow cook", "hour", "hr ")
    )

    subject = f"Dinner tonight: {dish}"

    tail_lines: list[str] = []
    if active:
        tail_lines.append(f"Active: {active}")
    if recipe and recipe.startswith("http"):
        tail_lines.append(f"Recipe: {recipe}")
    elif meal.get("description"):
        tail_lines.append(meal["description"])

    email_lines: list[str] = []
    if is_long_passive:
        email_lines.append("Heads up — long passive time today.")
    email_lines.append(f"Tonight: {dish}")
    email_lines.extend(tail_lines)
    email_body = "\n".join(email_lines)

    return subject, email_body


def send_plan_missing_alert(config: dict, reason: str) -> None:
    """When the plan can't be found/parsed, email (not SMS) an alert."""
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print(f"ERROR: plan missing ({reason}) and no RESEND_API_KEY to alert", file=sys.stderr)
        return

    recipients = config.get("email_recipients", [])
    if not recipients:
        return

    sender = config.get("email_from", "Meal Plan <onboarding@resend.dev>")

    payload = {
        "from": sender,
        "to": recipients,
        "subject": "⚠️ Meal plan reminder unavailable",
        "text": (
            f"The daily meal reminder couldn't find today's meal.\n\n"
            f"Reason: {reason}\n\n"
            f"Check the Actions tab in the meal-planning GitHub repo. "
            f"The Saturday weekly-plan workflow may not have run."
        ),
    }

    requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    print(f"Alert email sent: {reason}")


def send_reminder(config: dict, subject: str, email_body: str) -> None:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        sys.exit("ERROR: RESEND_API_KEY not set")

    sender = config.get("email_from", "Meal Plan <onboarding@resend.dev>")
    email_recipients = config.get("email_recipients", [])
    if not email_recipients:
        sys.exit("ERROR: no email_recipients configured in config.yml")

    payload = {
        "from": sender,
        "to": email_recipients,
        "subject": subject,
        "text": email_body,
    }
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if resp.ok:
        print(f"OK: email reminder sent to {', '.join(email_recipients)}")
    else:
        print(f"WARN: email send failed: {resp.status_code} {resp.text}", file=sys.stderr)


def main() -> None:
    config = load_config()
    tz_name = config.get("timezone", "America/New_York")
    now = datetime.now(ZoneInfo(tz_name))
    weekday = WEEKDAY_NAMES[now.weekday()]
    date_str = now.strftime("%Y-%m-%d")

    print(f"Running daily reminder for {weekday} {date_str} (tz: {tz_name})")

    plan = load_plan()
    if plan is None:
        send_plan_missing_alert(config, "current-week.md not found")
        return

    meal = find_todays_section(plan, weekday, date_str)
    if meal is None:
        history = load_history()
        if history is not None:
            meal = find_in_history(history, date_str)
            if meal is not None:
                meal["day"] = weekday
                print(f"current-week.md missing {date_str}; using meal-history.md fallback")

    if meal is None:
        send_plan_missing_alert(
            config,
            f"no entry for {weekday} {date_str} — plan may be stale or not yet generated",
        )
        return

    subject, email_body = build_message(meal)
    print(f"Today's meal: {meal['dish']}")
    print(f"Email body:\n{email_body}\n")

    send_reminder(config, subject, email_body)


if __name__ == "__main__":
    main()
