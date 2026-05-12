"""Tests for shopping_list_parser.parse.

Extracts (name, specification) tuples from the `## Shopping list` section
of current-week.md. Skips the pantry-check section, day plans, and any
other markdown.
"""
import textwrap

import pytest

from shopping_list_parser import parse


def _md(s: str) -> str:
    return textwrap.dedent(s).strip()


class TestSectionSelection:
    def test_returns_empty_when_no_shopping_list_section(self):
        md = _md(
            """
            # Current Week

            ## Monday — Dinner
            - **Recipe:** something
            """
        )
        assert parse(md) == []

    def test_ignores_pantry_check_section(self):
        md = _md(
            """
            ## Pantry check — make sure you have
            - Olive oil
            - Salt

            ## Shopping list

            ### Produce
            - 3 lemons
            """
        )
        assert parse(md) == [("lemons", "3")]

    def test_stops_at_next_h2(self):
        md = _md(
            """
            ## Shopping list

            ### Produce
            - 3 lemons

            ## Plan notes
            - Something irrelevant
            - 2 more bullets that should not appear
            """
        )
        assert parse(md) == [("lemons", "3")]


class TestQuantitySplitting:
    def test_splits_integer_count(self):
        md = _md(
            """
            ## Shopping list

            ### Produce
            - 3 lemons
            """
        )
        assert parse(md) == [("lemons", "3")]

    def test_splits_unit_quantity(self):
        md = _md(
            """
            ## Shopping list

            ### Produce
            - 1.5 lb baby potatoes
            """
        )
        assert parse(md) == [("baby potatoes", "1.5 lb")]

    def test_splits_bunch(self):
        md = _md(
            """
            ## Shopping list

            ### Produce
            - 1 large bunch flat-leaf parsley
            """
        )
        # "large" is not in our unit list; it stays with the name side.
        result = parse(md)
        assert len(result) == 1
        name, spec = result[0]
        assert spec == "1"
        assert "parsley" in name

    def test_no_quantity_keeps_whole_string_as_name(self):
        md = _md(
            """
            ## Shopping list

            ### Produce
            - Unsalted butter
            """
        )
        assert parse(md) == [("Unsalted butter", "")]

    def test_strips_trailing_parenthetical_from_name(self):
        """Parentheticals like '(Mon + Fri)' are just notes, not part of the name."""
        md = _md(
            """
            ## Shopping list

            ### Produce
            - 1.5 lb baby potatoes (Mon + Fri)
            """
        )
        assert parse(md) == [("baby potatoes", "1.5 lb")]

    def test_strips_inline_parenthetical_from_name(self):
        """Inline parens (size clarification) are noise — not part of the name."""
        md = _md(
            """
            ## Shopping list

            - 1 can (15 oz) black beans (enchiladas)
            """
        )
        assert parse(md) == [("black beans", "1 can")]

    def test_strips_trailing_dash_note(self):
        """Trailing ' — if not already in freezer'-style notes are scrubbed."""
        md = _md(
            """
            ## Shopping list

            - 12 corn tortillas (enchiladas) — if not already in freezer
            """
        )
        assert parse(md) == [("corn tortillas", "12")]

    def test_strips_dash_note_without_quantity(self):
        """No leading quantity + trailing ' — organic' note → name only."""
        md = _md(
            """
            ## Shopping list

            - apples — organic
            """
        )
        assert parse(md) == [("apples", "")]

    def test_strips_multiple_parenthetical_groups(self):
        """Two adjacent parens on the name side both get dropped."""
        md = _md(
            """
            ## Shopping list

            - 1 bag rice (long-grain) (bulk section)
            """
        )
        assert parse(md) == [("rice", "1 bag")]


class TestSubheadings:
    def test_sub_headings_do_not_become_items(self):
        md = _md(
            """
            ## Shopping list

            ### Produce
            - 3 lemons

            ### Meat & Seafood
            - 1.5 lb ground beef
            """
        )
        result = parse(md)
        assert ("lemons", "3") in result
        assert ("ground beef", "1.5 lb") in result
        # Make sure no item came from a heading.
        names = [n for n, _ in result]
        assert "Produce" not in names
        assert "Meat & Seafood" not in names


class TestBulletVariants:
    def test_asterisk_bullets(self):
        md = _md(
            """
            ## Shopping list

            * 3 lemons
            * 1 lb ground beef
            """
        )
        assert parse(md) == [("lemons", "3"), ("ground beef", "1 lb")]

    def test_dash_bullets(self):
        md = _md(
            """
            ## Shopping list

            - 3 lemons
            """
        )
        assert parse(md) == [("lemons", "3")]


class TestRealWorldSample:
    def test_from_current_week_md_sample(self):
        """Regression test using a slice of the real current-week.md format."""
        md = _md(
            """
            # Current Week: 2026-04-20 to 2026-04-26

            ## Monday 2026-04-20 — Sheet-Pan Salmon
            - **Recipe:** https://example.com

            ## Pantry check — make sure you have
            - Olive oil, kosher salt

            ## Shopping list

            ### Produce
            - 3 lemons
            - 1 large bunch flat-leaf parsley

            ### Meat & Seafood
            - 4 salmon fillets (~1.5 lb total)

            ## Plan notes
            - Not an item.
            """
        )
        result = parse(md)
        names = [n for n, _ in result]
        assert "lemons" in names
        assert any("parsley" in n for n in names)
        assert any("salmon" in n for n in names)
        assert "Not an item." not in names
        assert "Olive oil, kosher salt" not in names
