#!/usr/bin/env python3
"""Fetch next-week meal requests from Gmail via IMAP.

Runs Saturday morning before the Claude invocation. Reads replies matching
the magic subject tag (regardless of read state), splits them into three
weighted sections, writes requests-inbox.md. Fails soft — any error logs
and exits 0.
"""
from __future__ import annotations

import email as email_pkg
import imaplib
import os
import re
import sys
import traceback
from datetime import date, datetime, timedelta
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from week_target import ENV_VAR, resolve_target_monday


CONFIG_PATH = Path("config.yml")
OUTPUT_PATH = Path("requests-inbox.md")


def target_monday(now: datetime) -> date:
    """Return the Monday that anchors the next plan week.

    For any day of week, returns the strictly-next Monday: Mon → +7 days,
    Tue → +6, ..., Sun → +1. The Friday-reminder/Saturday-fetch cycle relies
    on this — a Friday request can never target the current week.
    """
    today = now.date()
    return today + timedelta(days=(7 - today.weekday()))


def run_target_monday(tz_name: str, now: datetime) -> date:
    """The Monday this ingestion run targets.

    Honors ``$TARGET_MONDAY`` when the weekly workflow set it (issue #3), so
    request ingestion stays on the same week as the prompt, verifier, and
    sender — a manual backfill won't pull the *upcoming* week's replies into an
    older target week. Falls back to the upcoming Monday, which equals
    ``target_monday(now)`` on a normal run.
    """
    return resolve_target_monday(tz_name, os.environ.get(ENV_VAR), today=now.date())


def subject_tag(monday: date) -> str:
    return f"[meal-plan request: {monday.isoformat()}]"


_QUOTE_MARKERS = (
    re.compile(r"^On .+ wrote:\s*$"),
    re.compile(r"^-----\s*Original Message\s*-----\s*$"),
)

# One or more leading `>` quote prefixes (Gmail/Outlook indent quoted lines).
_QUOTE_PREFIX_RE = re.compile(r"^\s*(?:>\s?)+")

# A line that is solely a parenthetical — the prompt's placeholder hints, e.g.
# "(hard constraints — ...)". Template scaffolding, never a real answer, so it's
# dropped when it appears under a heading. Matching on shape (not exact text)
# survives the encoding/truncation drift seen in real replies' text/plain parts.
_HINT_RE = re.compile(r"^\(.*\)$")

SECTION_KEYS = ("must", "soft", "use_up")

_HEADING_TO_KEY = {
    "must have / must avoid": "must",
    "soft preferences": "soft",
    "use up": "use_up",
}

_SECTION_TITLES = {
    "must": "Must have / Must avoid",
    "soft": "Soft preferences",
    "use_up": "Use up",
}

_HEADING_RE = re.compile(r"^\s*#{2,3}\s+(.+?)\s*$")


def normalize_reply_body(body: str) -> str:
    """Flatten a reply so section parsing sees the sender's answers.

    The prompt tells recipients to "type under each heading below" — but the
    headings live in the quoted original, so many clients place the answer
    lines *inside* the quoted block. Discarding the quote wholesale (the old
    behavior) therefore threw the answers away. Instead we:

    - drop quote-attribution lines (`On … wrote:`, `-----Original Message-----`)
    - strip leading `>` quote prefixes from every remaining line

    so a quoted `> ## Use up` / `> Ground beef` pair parses just like an
    un-quoted answer. Content before the first known heading and the
    parenthetical placeholder hints are dropped downstream by `parse_sections`.
    """
    out: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if any(marker.match(stripped) for marker in _QUOTE_MARKERS):
            continue
        out.append(_QUOTE_PREFIX_RE.sub("", line))
    return "\n".join(out)


def parse_sections(body: str) -> dict[str, str]:
    """Split a reply body into the three known sections.

    Headings are matched case-insensitively against `## Must have / Must
    avoid`, `## Soft preferences`, and `## Use up` (also H3). Content
    before the first known heading or under an unknown heading is dropped,
    as are the prompt's parenthetical placeholder-hint lines. Returns a
    dict with keys `must`, `soft`, `use_up`; missing sections map to "".
    """
    sections: dict[str, list[str]] = {k: [] for k in SECTION_KEYS}
    current: str | None = None
    for raw in body.splitlines():
        heading = _HEADING_RE.match(raw)
        if heading:
            key = _HEADING_TO_KEY.get(heading.group(1).strip().lower())
            current = key  # may be None for unknown headings
            continue
        if current is not None:
            if _HINT_RE.match(raw.strip()):
                continue  # template placeholder hint, not a real answer
            sections[current].append(raw)
    return {k: "\n".join(lines).strip("\n") for k, lines in sections.items()}


def extract_sender(msg: Message) -> str | None:
    """Return the lowercase email address from a message's From header, or None."""
    from_header = msg.get("From")
    if not from_header:
        return None
    _, address = parseaddr(from_header)
    return address.lower() or None


def is_allowed(sender: str | None, allowlist: list[str]) -> bool:
    if not sender:
        return False
    normalized = {a.lower() for a in allowlist}
    return sender.lower() in normalized


def extract_text_body(msg: Message) -> str:
    """Return the message's text content, preferring text/plain."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return _decode_part(part)
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return _decode_part(part)
        return ""
    return _decode_part(msg)


def _decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def process_message(msg: Message, allowlist: list[str]) -> dict | None:
    """Validate + parse one message into a contribution dict.

    Returns None if the sender isn't allowed or every section ends up empty.
    Contribution dict shape:
        {"sender": str, "timestamp": "YYYY-MM-DDTHH:MM", "sections": {must, soft, use_up}}
    """
    sender = extract_sender(msg)
    if not is_allowed(sender, allowlist):
        return None

    body = extract_text_body(msg)
    normalized = normalize_reply_body(body)
    sections = parse_sections(normalized)
    if not any(sections.values()):
        return None

    date_header = msg.get("Date")
    if date_header:
        try:
            ts = parsedate_to_datetime(date_header).strftime("%Y-%m-%dT%H:%M")
        except (TypeError, ValueError):
            ts = ""
    else:
        ts = ""

    return {"sender": sender, "timestamp": ts, "sections": sections}


def render_output(monday: date, contributions: list[dict]) -> str | None:
    """Render the captured contributions to requests-inbox.md content.

    Returns None if no contribution has any non-empty section.
    """
    if not contributions:
        return None

    has_any_content = any(
        c["sections"][k].strip()
        for c in contributions
        for k in SECTION_KEYS
    )
    if not has_any_content:
        return None

    lines: list[str] = [f"# Captured requests for the week of {monday.isoformat()}", ""]
    for key in SECTION_KEYS:
        lines.append(f"## {_SECTION_TITLES[key]}")
        for c in contributions:
            content = c["sections"][key].strip()
            if not content:
                continue
            lines.append(f"<!-- from: {c['sender']} at {c['timestamp']} -->")
            lines.append(content)
            lines.append("")
        # Trim trailing blank if this section had nothing
        if lines[-1] == f"## {_SECTION_TITLES[key]}":
            lines.append("")  # keep heading visible
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def load_config() -> dict | None:
    """Load config.yml. Return None if no `requests:` block (opt-out)."""
    if not CONFIG_PATH.exists():
        print("fetch_requests: config.yml not found, skipping", file=sys.stderr)
        return None
    config = yaml.safe_load(CONFIG_PATH.read_text())
    if not config.get("requests"):
        print("fetch_requests: no `requests:` block in config.yml, skipping", file=sys.stderr)
        return None
    return config


def fetch_messages(gmail_user: str, app_password: str, tag: str) -> list[Message]:
    """Connect to Gmail, return parsed Message objects matching the subject tag.

    Searches by subject tag regardless of read state. An earlier `UNSEEN`
    filter here silently dropped any reply a human had already opened between
    the Friday prompt and the Saturday run — the common case, not the edge
    case. Idempotence instead comes from the weekly run rebuilding
    requests-inbox.md from scratch, so reprocessing already-seen messages is
    harmless. The \\Seen mark is still set, purely as inbox housekeeping.
    """
    imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        imap.login(gmail_user, app_password)
        imap.select("INBOX")
        # IMAP SEARCH SUBJECT performs a substring match. No read-state filter:
        # UNSEEN dropped replies a human had already opened (see docstring).
        typ, data = imap.search(None, "SUBJECT", f'"{tag}"')
        if typ != "OK":
            print(f"fetch_requests: IMAP search returned {typ}", file=sys.stderr)
            return []
        uids = data[0].split()
        messages: list[Message] = []
        for uid in uids:
            typ, msg_data = imap.fetch(uid, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw_bytes = msg_data[0][1]
            messages.append(email_pkg.message_from_bytes(raw_bytes))
            imap.store(uid, "+FLAGS", "\\Seen")
        return messages
    finally:
        try:
            imap.close()
        except Exception:
            pass
        imap.logout()


def main() -> None:
    config = load_config()
    if config is None:
        return

    requests_cfg = config["requests"]
    gmail_user = requests_cfg.get("gmail_user")
    if not gmail_user:
        print("fetch_requests: requests.gmail_user missing in config.yml", file=sys.stderr)
        return

    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not app_password:
        print("fetch_requests: GMAIL_APP_PASSWORD env var not set", file=sys.stderr)
        return

    allowlist = requests_cfg.get("allowlist") or config.get("email_recipients") or []
    if not allowlist:
        print("fetch_requests: no allowlist or email_recipients configured", file=sys.stderr)
        return

    tz_name = config.get("timezone", "America/New_York")
    now = datetime.now(ZoneInfo(tz_name))
    try:
        monday = run_target_monday(tz_name, now)
    except ValueError as e:
        print(f"fetch_requests: invalid {ENV_VAR}: {e}", file=sys.stderr)
        return
    tag = subject_tag(monday)
    print(f"fetch_requests: looking for messages with subject {tag!r}")

    try:
        messages = fetch_messages(gmail_user, app_password, tag)
    except Exception as e:
        print(f"fetch_requests: IMAP fetch failed: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return

    print(f"fetch_requests: {len(messages)} matching message(s)")
    contributions = []
    for msg in messages:
        result = process_message(msg, allowlist)
        if result is None:
            sender = extract_sender(msg) or "<unknown>"
            print(f"fetch_requests: skipped message from {sender} (disallowed or empty)")
            continue
        contributions.append(result)

    output = render_output(monday, contributions)
    if output is None:
        print("fetch_requests: no usable content; not writing requests-inbox.md")
        return

    OUTPUT_PATH.write_text(output)
    print(f"fetch_requests: wrote {OUTPUT_PATH} ({len(contributions)} contribution(s))")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Belt-and-suspenders: any escape from main() is caught here so
        # the workflow step always exits 0 and the weekly run continues.
        print(f"fetch_requests: top-level error: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(0)
