"""Tests for validate_recipe_urls stripped-link rendering (issue #4).

When a recipe URL is definitively broken, the validator rewrites the line to
point at the description and must NOT surface the raw dead URL in the plan.
"""
from validate_recipe_urls import RECIPE_LINE, stripped_recipe_line


class TestStrippedRecipeLine:
    def test_points_to_description_and_drops_dead_url(self):
        out = stripped_recipe_line("- **Recipe:** ")
        assert out == "- **Recipe:** no link — see description"
        # The raw dead URL and the old diagnostic phrasing must not leak.
        assert "http" not in out
        assert "did not resolve" not in out

    def test_preserves_bullet_prefix_style(self):
        out = stripped_recipe_line("  * **Recipe:** ")
        assert out.startswith("  * **Recipe:** ")
        assert out.endswith("no link — see description")


class TestRecipeLinePattern:
    def test_matches_url_line_and_captures_prefix_and_url(self):
        line = "- **Recipe:** https://example.com/pasta"
        m = RECIPE_LINE.match(line)
        assert m is not None
        assert m.group("prefix") == "- **Recipe:** "
        assert m.group("url") == "https://example.com/pasta"

    def test_ignores_no_link_method_line(self):
        # A "no link — <method>" line has no URL, so validation skips it —
        # the planner's method fallback survives untouched.
        line = "- **Recipe:** no link — sear the chops, then braise 20 min"
        assert RECIPE_LINE.match(line) is None

    def test_end_to_end_sub_removes_dead_url_from_text(self):
        # Simulate the strip path without network: substitute the matched line
        # inside a realistic multi-line plan block.
        text = (
            "## Monday 2026-07-06 — Dish\n"
            "- **Recipe:** https://dead.example/gone\n"
            "- **Notes:** kid version\n"
        )
        new = RECIPE_LINE.sub(lambda m: stripped_recipe_line(m.group("prefix")), text)
        assert "- **Recipe:** no link — see description\n" in new
        assert "dead.example" not in new
        assert "- **Notes:** kid version" in new  # surrounding lines untouched
