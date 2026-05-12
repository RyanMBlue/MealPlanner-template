#!/usr/bin/env python3
"""Send the Friday-morning "what do you want next week?" email.

Subject carries the magic tag fetch_requests.py keys off of. Body is a
templated 3-section reply form the user fills in on their phone.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

from fetch_requests import subject_tag, target_monday


def load_config() -> dict:
    config_path = Path("config.yml")
    if not config_path.exists():
        sys.exit("ERROR: config.yml not found")
    return yaml.safe_load(config_path.read_text())


def build_message(monday: date) -> tuple[str, str]:
    sunday = monday + timedelta(days=6)
    fmt = "%a %b %d"  # "Mon May 18"
    range_str = f"{monday.strftime(fmt)} — {sunday.strftime(fmt)}"
    subject = subject_tag(monday)
    body = (
        f"What do you want for the week of {range_str}?\n"
        "\n"
        "Reply to this email. Type under each heading below.\n"
        "Leave a section blank if there's nothing for it.\n"
        "Send any time before Saturday 8am ET.\n"
        "\n"
        "## Must have / Must avoid\n"
        "(hard constraints — e.g. \"no fish\", \"tacos one night\")\n"
        "\n"
        "\n"
        "## Soft preferences\n"
        "(suggestions — e.g. \"lean Italian\", \"lighter meals\")\n"
        "\n"
        "\n"
        "## Use up\n"
        "(ingredients in the fridge/pantry to lean on)\n"
    )
    return subject, body


def build_payload(config: dict, subject: str, body: str) -> dict:
    """Build the Resend POST payload for the Friday prompt.

    Sets `reply_to` to the configured `requests.gmail_user` so replies
    land in the Gmail inbox that `fetch_requests.py` will poll on Saturday
    — the `email_from` domain is Resend-verified and send-only.
    """
    sender = config.get("email_from", "Meal Plan <onboarding@resend.dev>")
    recipients = config.get("email_recipients", [])
    payload: dict = {"from": sender, "to": recipients, "subject": subject, "text": body}
    gmail_user = (config.get("requests") or {}).get("gmail_user")
    if gmail_user:
        payload["reply_to"] = [gmail_user]
    return payload


def send_email(config: dict, subject: str, body: str) -> None:
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        sys.exit("ERROR: RESEND_API_KEY not set")

    recipients = config.get("email_recipients", [])
    if not recipients:
        sys.exit("ERROR: no email_recipients configured")

    payload = build_payload(config, subject, body)
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if resp.ok:
        print(f"OK: request prompt sent to {', '.join(recipients)}")
    else:
        sys.exit(f"ERROR: Resend returned {resp.status_code}: {resp.text}")


def main() -> None:
    config = load_config()
    if not config.get("requests"):
        print("send_request_prompt: no `requests:` block in config.yml, skipping")
        return

    tz_name = config.get("timezone", "America/New_York")
    now = datetime.now(ZoneInfo(tz_name))
    monday = target_monday(now)
    subject, body = build_message(monday)
    send_email(config, subject, body)


if __name__ == "__main__":
    main()
