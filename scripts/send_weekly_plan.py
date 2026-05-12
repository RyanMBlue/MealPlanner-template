#!/usr/bin/env python3
"""Send the weekly meal plan by email via Resend.

Run after Claude has generated and committed current-week.md.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

from verify_plan_covers_week import plan_covers_week


def load_config() -> dict:
    config_path = Path("config.yml")
    if not config_path.exists():
        sys.exit("ERROR: config.yml not found in repo root")
    return yaml.safe_load(config_path.read_text())


def load_plan() -> str:
    plan_path = Path("current-week.md")
    if not plan_path.exists():
        sys.exit("ERROR: current-week.md not found — did the Claude step fail?")
    text = plan_path.read_text().strip()
    if not text:
        sys.exit("ERROR: current-week.md is empty")
    return text


def expected_plan_monday(tz_name: str, today: date | None = None) -> date:
    """Return the Monday whose week current-week.md should currently cover.

    On Saturday/Sunday the weekly workflow has just generated the upcoming
    week's plan, so we expect that Monday. On Monday–Friday the plan is
    the active week's, so we expect the most recent Monday. The `today`
    argument is for tests; production passes None to read the wall clock.
    """
    if today is None:
        today = datetime.now(ZoneInfo(tz_name)).date()
    weekday = today.weekday()  # Mon=0..Sun=6
    if weekday >= 5:  # Sat or Sun
        return today + timedelta(days=(7 - weekday))
    return today - timedelta(days=weekday)


def verify_plan_is_fresh(config: dict, plan_md: str) -> None:
    """Refuse to send if the plan doesn't cover the expected week.

    Defense against the 2026-04-25 failure mode where Claude exhausted
    its turn budget without writing a fresh plan and the email step
    happily re-sent the prior week's. See issue #27.
    """
    tz_name = config.get("timezone") or "America/New_York"
    monday = expected_plan_monday(tz_name)
    if not plan_covers_week(plan_md, monday):
        sys.exit(
            f"ERROR: current-week.md does not contain a Monday heading for "
            f"{monday}. Refusing to email what looks like a stale plan "
            f"(issue #27)."
        )


def markdown_to_html(md: str) -> str:
    """Minimal markdown → HTML for email rendering.

    We don't need full markdown; current-week.md uses a predictable subset:
    - # / ## / ### headings
    - bullet lists
    - **bold** inline
    - bare URLs
    """
    import html
    import re

    lines = md.split("\n")
    out: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.rstrip()
        if not line:
            close_list()
            out.append("")
            continue

        # Headings
        heading_match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading_match:
            close_list()
            level = len(heading_match.group(1))
            content = html.escape(heading_match.group(2))
            # Bold inline
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
            out.append(f"<h{level}>{content}</h{level}>")
            continue

        # Bullet lists
        bullet_match = re.match(r"^\s*[-*]\s+(.*)$", line)
        if bullet_match:
            if not in_list:
                out.append("<ul>")
                in_list = True
            content = html.escape(bullet_match.group(1))
            content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
            # Linkify bare URLs
            content = re.sub(
                r"(https?://[^\s<]+)",
                r'<a href="\1">\1</a>',
                content,
            )
            out.append(f"<li>{content}</li>")
            continue

        # Plain paragraph
        close_list()
        content = html.escape(line)
        content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
        content = re.sub(
            r"(https?://[^\s<]+)",
            r'<a href="\1">\1</a>',
            content,
        )
        out.append(f"<p>{content}</p>")

    close_list()

    body = "\n".join(out)
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         max-width: 700px; margin: 2em auto; padding: 0 1em; color: #222; }}
  h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.3em; }}
  h2 {{ margin-top: 1.5em; color: #1a4d8f; }}
  h3 {{ color: #555; }}
  ul {{ padding-left: 1.5em; }}
  li {{ margin: 0.2em 0; }}
  a {{ color: #1a73e8; }}
</style>
</head>
<body>
{body}
</body>
</html>"""


def send_email(config: dict, plan_md: str) -> None:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        sys.exit("ERROR: RESEND_API_KEY env var not set")

    recipients = config.get("email_recipients", [])
    if not recipients:
        sys.exit("ERROR: no email_recipients configured in config.yml")

    sender = config.get("email_from", "Meal Plan <onboarding@resend.dev>")

    # Extract the target week range from the first line of the plan for the subject
    first_line = plan_md.split("\n", 1)[0]
    # Expected: "# Current Week: 2026-04-20 to 2026-04-26"
    subject = first_line.lstrip("#").strip().replace("Current Week:", "Meal Plan:")
    if not subject.startswith("Meal Plan"):
        subject = "Meal Plan for this week"

    html_body = markdown_to_html(plan_md)

    payload = {
        "from": sender,
        "to": recipients,
        "subject": subject,
        "html": html_body,
        "text": plan_md,  # plain-text fallback
    }

    response = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    if not response.ok:
        sys.exit(f"ERROR: Resend returned {response.status_code}: {response.text}")

    print(f"OK: weekly plan sent to {', '.join(recipients)}")
    print(f"    subject: {subject}")
    print(f"    response id: {response.json().get('id', 'unknown')}")


def main() -> None:
    config = load_config()
    plan = load_plan()
    verify_plan_is_fresh(config, plan)
    send_email(config, plan)


if __name__ == "__main__":
    main()
