#!/usr/bin/env python3
"""Normalize grocery item names for dedup comparison.

The goal: collapse the many phrasings of the same item so we can
detect that "1 lb organic apples" and "Apples" refer to the same thing.

Tuned toward false negatives (occasional duplicate gets added) rather than
false positives (we skip something that should have been added). A duplicate
on the list is mildly annoying; a missing item means a second trip.
"""
from __future__ import annotations

import re
import unicodedata

# Leading quantity tokens: digits, fractions (ascii or unicode), decimals,
# followed by an optional unit. Stripped greedily from the start.
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

# Unicode fractions we need to recognize. After NFKC normalization, a
# vulgar fraction like "½" decomposes to "1⁄2" using U+2044 FRACTION SLASH,
# so we include both the composed glyphs and the fraction-slash character.
_UNICODE_FRACTIONS = "¼½¾⅓⅔⅕⅖⅗⅘⅙⅚⅛⅜⅝⅞"

# Alternation order matters in regex: "lb" would match before "lbs" and
# leave a dangling "s". Sort longest-first so longer variants win.
_UNIT_WORDS_RE_ALT = "|".join(sorted(_UNIT_WORDS, key=len, reverse=True))

_QUANTITY_RE = re.compile(
    r"^\s*"
    r"(?:[\d./\u2044]+|[" + _UNICODE_FRACTIONS + r"])"  # a number or fraction (incl. U+2044)
    r"(?:\s*[-–]\s*(?:[\d./\u2044]+|[" + _UNICODE_FRACTIONS + r"]))?"  # optional range "1-2"
    r"(?:\s+(?:" + _UNIT_WORDS_RE_ALT + r")\b)?"  # optional unit word (word-bounded)
    r"\s*",
    re.IGNORECASE,
)

_MODIFIERS = {"organic", "fresh", "local", "raw"}

# We now push items as "name (quantity)" for at-a-glance shopping, and
# Bring! stores that literal string. Strip parenthetical groups so dedup
# collides "apples (3)" with a plain "apples" that a user voice-added.
_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*")


def _singularize_last(word: str) -> str:
    """Naive singularization: drop trailing 's' if stem length >= 3."""
    if len(word) >= 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def normalize(s: str) -> str:
    """Normalize a grocery item string for dedup comparison."""
    # Unicode normalize so "½" and friends are handled consistently.
    s = unicodedata.normalize("NFKC", s)
    s = s.lower().strip()

    # Strip parenthetical groups (e.g. "apples (3)", "beans (15 oz)").
    s = _PARENS_RE.sub(" ", s).strip()

    # Strip leading quantity + unit.
    s = _QUANTITY_RE.sub("", s).strip()

    # Tokenize, drop modifier words, collapse whitespace.
    tokens = [t for t in s.split() if t not in _MODIFIERS]
    if not tokens:
        return ""

    # Singularize the last token only.
    tokens[-1] = _singularize_last(tokens[-1])
    return " ".join(tokens)


if __name__ == "__main__":
    import sys

    for line in sys.stdin:
        line = line.rstrip("\n")
        print(f"{line!r} -> {normalize(line)!r}")
