#!/usr/bin/env python3
"""Parse the shopping-list section of current-week.md.

Returns a list of (name, specification) tuples suitable for Bring!'s
save_item(list_uuid, item_name, specification) API.
"""
from __future__ import annotations

import re

_SHOPPING_HEADING_RE = re.compile(r"^##\s+Shopping list\b", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")

# Same unit list as item_normalizer, kept here to avoid a cross-module
# coupling — the parser splits leading quantity+unit; the normalizer does
# its own stripping for different purposes (dedup comparison).
_UNIT_WORDS = (
    "lb", "lbs", "pound", "pounds",
    "oz", "ounce", "ounces",
    "g", "kg", "gram", "grams",
    "cup", "cups",
    "tbsp", "tsp",
    "tablespoon", "tablespoons", "teaspoon", "teaspoons",
    "bunch", "bunches",
    "pkg", "package", "packages",
    "can", "cans",
    "jar", "jars",
    "bottle", "bottles",
    "head", "heads",
    "clove", "cloves",
    "bag", "bags",
    "box", "boxes",
    "dozen",
)

# Alternation order matters: "lb" would match before "lbs" and leave a
# dangling "s". Sort longest-first so longer variants win.
_UNIT_WORDS_RE_ALT = "|".join(sorted(_UNIT_WORDS, key=len, reverse=True))

# Match a leading quantity: a number (int, decimal, fraction), optional
# range ("1-2"), optional unit word. Captures the quantity so we can
# use it as `specification`. The \u2044 in the char class handles
# NFKC-decomposed vulgar fractions (e.g. "½" → "1⁄2").
_QUANTITY_PREFIX_RE = re.compile(
    r"^\s*"
    r"(?P<qty>"
    r"(?:[\d./\u2044]+|[¼½¾⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞])"
    r"(?:\s*[-–]\s*(?:[\d./\u2044]+|[¼½¾⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞]))?"
    r"(?:\s+(?:" + _UNIT_WORDS_RE_ALT + r")\b)?"
    r")"
    r"\s+",
    re.IGNORECASE,
)

# Any parenthetical group. Claude's plans use parens freely for both
# trailing notes ("(Mon + Fri)") and inline clarifications ("1 can (15 oz)
# black beans"), neither of which belongs in the Bring! item name.
_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*")

# Trailing em-dash / en-dash / hyphen clause used for side notes
# ("— if not already in freezer", "— organic"). Must be surrounded by
# whitespace so we don't eat hyphens inside a name ("flat-leaf parsley").
_TRAILING_DASH_NOTE_RE = re.compile(r"\s+[—–-]\s+.*$")


def _shopping_list_section(md: str) -> str:
    """Extract the `## Shopping list` section up to the next `## ` heading."""
    start_match = _SHOPPING_HEADING_RE.search(md)
    if not start_match:
        return ""
    start = start_match.end()
    # Find the next `## ` after the shopping-list heading.
    rest = md[start:]
    next_h2 = _H2_RE.search(rest)
    if next_h2:
        return rest[: next_h2.start()]
    return rest


def _clean_name(name: str) -> str:
    """Remove parenthetical groups and trailing dash-notes from a name.

    Applied after the leading-quantity split so inline parens
    ("1 can (15 oz) black beans") don't confuse the quantity match.
    """
    cleaned = _PARENS_RE.sub(" ", name)
    cleaned = _TRAILING_DASH_NOTE_RE.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _split_quantity(bullet_text: str) -> tuple[str, str]:
    """Return (name, specification). Parenthetical notes and trailing
    dash-clauses are stripped from the name side.
    """
    text = bullet_text.strip()
    match = _QUANTITY_PREFIX_RE.match(text)
    if not match:
        return _clean_name(text), ""
    spec = match.group("qty").strip()
    name = _clean_name(text[match.end():])
    if not name:
        # Defensive: the bullet was quantity-only; treat original as name.
        return _clean_name(text), ""
    return name, spec


def parse(md: str) -> list[tuple[str, str]]:
    """Parse current-week.md and return (name, spec) tuples from the
    shopping-list section only.
    """
    section = _shopping_list_section(md)
    if not section:
        return []
    items: list[tuple[str, str]] = []
    for line in section.splitlines():
        bullet_match = _BULLET_RE.match(line)
        if not bullet_match:
            continue
        bullet_text = bullet_match.group(1).strip()
        if not bullet_text:
            continue
        items.append(_split_quantity(bullet_text))
    return items


if __name__ == "__main__":
    import sys
    from pathlib import Path

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("current-week.md")
    for name, spec in parse(path.read_text()):
        print(f"{name!r:40s} spec={spec!r}")
