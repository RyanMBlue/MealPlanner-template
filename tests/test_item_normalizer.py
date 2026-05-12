"""Tests for item_normalizer.normalize.

Normalization's job: collapse the MANY ways the same grocery item
appears in a shopping list so we can dedupe against Bring! items.

Tuned toward false negatives (occasional duplicate) rather than
false positives (skipping something we should have added).
"""
import pytest

from item_normalizer import normalize


class TestCaseFolding:
    def test_lowercases(self):
        assert normalize("MILK") == "milk"

    def test_strips_whitespace(self):
        assert normalize("  milk  ") == "milk"


class TestQuantityStripping:
    def test_strips_leading_integer(self):
        """Singularization applies, so 'apples' becomes 'apple'."""
        assert normalize("3 apples") == "apple"

    def test_strips_leading_decimal(self):
        assert normalize("1.5 lb apples") == "apple"

    def test_strips_leading_fraction_ascii(self):
        assert normalize("1/2 lb apples") == "apple"

    def test_strips_unicode_fraction(self):
        assert normalize("½ lb apples") == "apple"

    def test_strips_unit_lb(self):
        assert normalize("1 lb ground beef") == "ground beef"

    def test_strips_unit_lbs(self):
        assert normalize("2 lbs ground beef") == "ground beef"

    def test_strips_unit_oz(self):
        assert normalize("8 oz pecorino") == "pecorino"

    def test_strips_unit_bunch(self):
        assert normalize("1 bunch parsley") == "parsley"

    def test_strips_unit_bunches(self):
        assert normalize("2 bunches parsley") == "parsley"

    def test_strips_unit_head(self):
        assert normalize("1 head garlic") == "garlic"

    def test_strips_unit_can(self):
        """Singularization applies to the last word."""
        assert normalize("1 can black beans") == "black bean"

    def test_strips_unit_jar(self):
        assert normalize("1 jar salsa verde") == "salsa verde"

    def test_strips_unit_pkg(self):
        """Singularization applies to the last word."""
        assert normalize("1 pkg corn tortillas") == "corn tortilla"


class TestModifierStripping:
    def test_strips_organic(self):
        assert normalize("organic apples") == "apple"

    def test_strips_fresh(self):
        assert normalize("fresh parsley") == "parsley"

    def test_strips_local(self):
        assert normalize("local milk") == "milk"

    def test_strips_raw(self):
        assert normalize("raw honey") == "honey"

    def test_strips_modifier_in_middle(self):
        assert normalize("1 bunch fresh parsley") == "parsley"


class TestSingularization:
    def test_drops_trailing_s(self):
        assert normalize("eggs") == "egg"

    def test_preserves_short_stems(self):
        """'us' is 2 chars; dropping 's' leaves 'u', too aggressive. Keep."""
        assert normalize("us") == "us"

    def test_keeps_three_char_stems_without_s(self):
        """'oats' → 'oat' — stem 'oat' is 3 chars, OK to drop."""
        assert normalize("oats") == "oat"

    def test_handles_plural_phrase(self):
        """Only the last word gets singularized; catches 'apples' in 'red apples'."""
        assert normalize("red apples") == "red apple"


class TestParentheticalStripping:
    """Bring! items we push now carry '(quantity)' suffixes for at-a-glance
    shopping. Dedup must still collide those with plain names — both from
    our own parser and from voice-added items.
    """

    def test_strips_trailing_parens(self):
        assert normalize("apples (3)") == normalize("apples")

    def test_strips_trailing_parens_with_unit(self):
        assert normalize("ground beef (1.5 lb)") == normalize("1.5 lb ground beef")

    def test_strips_inline_parens(self):
        assert normalize("black beans (15 oz)") == normalize("black beans")


class TestWholeChain:
    def test_typical_shopping_list_line(self):
        """Naive singularization just drops trailing 's' — don't use
        words with '-oes' plurals (e.g. 'potatoes' → 'potatoe'), those
        are documented false negatives below.
        """
        assert normalize("3 lemons") == "lemon"

    def test_idempotent(self):
        once = normalize("2 bunches fresh parsley")
        assert normalize(once) == once

    def test_matches_between_phrasings(self):
        """The whole point: '2 lb organic apples' and 'Apples' should collide."""
        assert normalize("2 lb organic apples") == normalize("Apples")


class TestCollisionsWeAccept:
    """Documented false-negative cases — we accept these duplicates.

    If normalize() ever becomes clever enough to collide these correctly,
    update the tests. For now they live here as regression guards.
    """

    def test_whole_milk_and_milk_do_not_collide(self):
        assert normalize("whole milk") != normalize("milk")

    def test_cheddar_and_sharp_cheddar_do_not_collide(self):
        assert normalize("sharp cheddar") != normalize("cheddar")

    def test_oes_plurals_do_not_collide_with_singular(self):
        """Naive singularization drops only trailing 's', so 'potatoes'
        becomes 'potatoe' rather than 'potato'. Accepted duplicate.
        """
        assert normalize("baby potatoes") != normalize("baby potato")
