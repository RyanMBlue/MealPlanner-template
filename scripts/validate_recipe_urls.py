#!/usr/bin/env python3
"""Validate recipe URLs in current-week.md and rewrite definitively-broken ones.

Runs after Claude exits but before the workflow commits the plan. For each
`**Recipe:** http...` line, HEAD/GET the URL and classify the result:

  - 2xx/3xx                                         → OK, leave alone
  - 404 / 410 / 451 / DNS+connect+timeout failures  → STRIP (definitively gone)
  - 401 / 403 / 429 / 5xx                           → SKIP (can't verify; warn)

The "skip" bucket exists because some recipe sites (Serious Eats, Smitten
Kitchen) bot-block datacenter IPs with 403/429 regardless of whether the
URL is real. Stripping on those would falsely flag every working link from
those sources. Better to let an occasional bad URL through than to nuke
every working one.

Always exits 0 — the email should send even if some links got stripped.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import requests

PLAN = Path("current-week.md")
TIMEOUT_SECONDS = 15
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Status codes that mean the page is definitively gone.
STRIP_STATUSES = {404, 410, 451}

# Match a Recipe line carrying a real URL. Captures the leading prefix
# (`- **Recipe:** `) so we can preserve indentation/bullet style.
RECIPE_LINE = re.compile(
    r"^(?P<prefix>\s*[-*]\s+\*\*Recipe:\*\*\s+)(?P<url>https?://\S+?)\s*$",
    re.MULTILINE,
)


def classify(url: str) -> tuple[str, str]:
    """Return (verdict, reason). verdict is 'ok' | 'strip' | 'skip'."""
    try:
        resp = requests.head(
            url, allow_redirects=True, timeout=TIMEOUT_SECONDS, headers=HEADERS
        )
        # Some sites refuse HEAD; retry with GET.
        if resp.status_code in (403, 405, 501):
            resp = requests.get(
                url,
                allow_redirects=True,
                timeout=TIMEOUT_SECONDS,
                headers=HEADERS,
                stream=True,
            )
            resp.close()
    except (requests.ConnectionError, requests.Timeout) as exc:
        # DNS failure, connection refused, or timeout — the URL is
        # effectively broken from anywhere we'd send users.
        return "strip", f"network: {exc.__class__.__name__}"
    except requests.RequestException as exc:
        # Any other request error: be conservative, don't strip.
        return "skip", f"request error: {exc.__class__.__name__}"

    code = resp.status_code
    if code < 400:
        return "ok", f"HTTP {code}"
    if code in STRIP_STATUSES:
        return "strip", f"HTTP {code}"
    # 401/403/429/5xx — can't tell if URL is bad or just bot-blocked.
    return "skip", f"HTTP {code} (could not verify)"


def stripped_recipe_line(prefix: str) -> str:
    """Replacement for a Recipe line whose URL was definitively broken.

    Points the reader at the dish description instead of the dead link. Unlike
    the earlier behavior, it does **not** echo the raw dead URL into the
    user-facing plan (issue #4) — a broken link is noise there. The URL is still
    printed in the run logs and the end-of-run "Stripped" summary for debugging.
    """
    return f"{prefix}no link — see description"


def main() -> None:
    if not PLAN.exists():
        print(f"ERROR: {PLAN} not found — nothing to validate", file=sys.stderr)
        return

    text = PLAN.read_text()
    matches = list(RECIPE_LINE.finditer(text))
    if not matches:
        print("No Recipe URLs found in current-week.md.")
        return

    print(f"Validating {len(matches)} recipe URL(s)...")

    stripped: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []
    ok_count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal ok_count
        prefix, url = match.group("prefix"), match.group("url")
        verdict, reason = classify(url)
        if verdict == "ok":
            print(f"  OK     [{reason}] {url}")
            ok_count += 1
            return f"{prefix}{url}"
        if verdict == "skip":
            print(f"  SKIP   [{reason}] {url}")
            skipped.append((url, reason))
            return f"{prefix}{url}"
        # strip
        print(f"  STRIP  [{reason}] {url}")
        stripped.append((url, reason))
        return stripped_recipe_line(prefix)

    new_text = RECIPE_LINE.sub(replace, text)

    if new_text != text:
        PLAN.write_text(new_text)

    print(
        f"\nSummary: {ok_count} OK, {len(skipped)} unverified, "
        f"{len(stripped)} stripped."
    )
    if stripped:
        print("Stripped (definitively broken):")
        for url, reason in stripped:
            print(f"  - {url}  ({reason})")
    if skipped:
        print("Unverified (bot-blocked or transient — left as-is):")
        for url, reason in skipped:
            print(f"  - {url}  ({reason})")


if __name__ == "__main__":
    main()
