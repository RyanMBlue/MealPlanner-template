"""Tests for send_daily_reminder helpers.

Focus: the meal-history.md fallback path (issue #35). When the Saturday
weekly-plan workflow has already rotated current-week.md forward, Sunday's
reminder needs to look up the trailing day in meal-history.md instead of
firing the missing-plan alert.
"""
import textwrap

from send_daily_reminder import find_in_history, find_todays_section


def _md(s: str) -> str:
    return textwrap.dedent(s).strip()


class TestFindInHistory:
    def test_returns_meal_dict_when_date_present(self):
        history = _md(
            """
            # Meal History

            ## Real entries start below this line

            ### 2026-04-26

            - **Meal:** Black Bean & Sweet Potato Enchiladas
            - **Description:** Baked enchiladas with black beans and roasted sweet potato.
            - **Active time:** 30 min  |  **Total time:** 45 min
            - **Protein:** Vegetarian
            - **Recipe:** https://example.com/enchiladas
            - **Rating:**
            - **Notes:**
            """
        )

        meal = find_in_history(history, "2026-04-26")

        assert meal is not None
        assert meal["dish"] == "Black Bean & Sweet Potato Enchiladas"
        assert meal["date"] == "2026-04-26"
        assert meal["description"].startswith("Baked enchiladas")
        assert meal["active_time"].startswith("30 min")
        assert meal["protein"] == "Vegetarian"
        assert meal["recipe"] == "https://example.com/enchiladas"

    def test_returns_none_when_date_absent(self):
        history = _md(
            """
            ### 2026-04-20

            - **Meal:** Salmon
            """
        )
        assert find_in_history(history, "2026-04-26") is None

    def test_handles_minimal_legacy_entry(self):
        """Pre-#34 entries may only carry a Meal line; fallback should still
        produce a usable dict with empty strings for the missing fields."""
        history = _md(
            """
            ### 2026-04-26

            - **Meal:** Leftover Stir-Fry
            """
        )

        meal = find_in_history(history, "2026-04-26")

        assert meal is not None
        assert meal["dish"] == "Leftover Stir-Fry"
        assert meal["recipe"] == ""
        assert meal["active_time"] == ""
        assert meal["description"] == ""

    def test_returns_none_on_empty_string(self):
        assert find_in_history("", "2026-04-26") is None

    def test_stops_at_next_date_heading(self):
        """Field extraction must not bleed into the following entry."""
        history = _md(
            """
            ### 2026-04-26

            - **Meal:** Enchiladas
            - **Recipe:** https://example.com/enchiladas

            ### 2026-04-27

            - **Meal:** Tacos
            - **Recipe:** https://example.com/tacos
            """
        )

        meal = find_in_history(history, "2026-04-26")
        assert meal is not None
        assert meal["dish"] == "Enchiladas"
        assert meal["recipe"] == "https://example.com/enchiladas"

    def test_entry_without_meal_line_returns_none(self):
        """A date heading with no `**Meal:**` line isn't usable — skip it."""
        history = _md(
            """
            ### 2026-04-26

            - **Notes:** placeholder, dish TBD
            """
        )
        assert find_in_history(history, "2026-04-26") is None


class TestFindTodaysSectionUnaffected:
    """Sanity: existing current-week.md parsing still works after the refactor."""

    def test_finds_meal(self):
        plan = _md(
            """
            ## Sunday 2026-04-26 — Enchiladas
            - **Description:** Baked enchiladas.
            - **Active time:** 30 min
            - **Recipe:** https://example.com/enchiladas
            """
        )

        meal = find_todays_section(plan, "Sunday", "2026-04-26")
        assert meal is not None
        assert meal["dish"] == "Enchiladas"
        assert meal["recipe"] == "https://example.com/enchiladas"
