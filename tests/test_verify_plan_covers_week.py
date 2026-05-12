"""Tests for verify_plan_covers_week.plan_covers_week.

The workflow uses this to fail fast if Claude finished its turn budget
without writing a plan for the upcoming week (issue #26).
"""
import textwrap
from datetime import date

from verify_plan_covers_week import plan_covers_week


def _md(s: str) -> str:
    return textwrap.dedent(s).strip()


class TestPlanCoversWeek:
    def test_returns_true_when_monday_heading_matches(self):
        md = _md(
            """
            # Current Week: 2026-04-27 to 2026-05-03

            ## Monday 2026-04-27 — Sheet-Pan Salmon
            - **Description:** stuff
            """
        )
        assert plan_covers_week(md, date(2026, 4, 27)) is True

    def test_returns_false_when_only_prior_week_heading(self):
        md = _md(
            """
            # Current Week: 2026-04-20 to 2026-04-26

            ## Monday 2026-04-20 — Last week's salmon
            """
        )
        assert plan_covers_week(md, date(2026, 4, 27)) is False

    def test_returns_false_on_empty_string(self):
        assert plan_covers_week("", date(2026, 4, 27)) is False

    def test_returns_false_when_file_lacks_monday_heading(self):
        md = "# Current Week\n\nSome other content with no day headings.\n"
        assert plan_covers_week(md, date(2026, 4, 27)) is False

    def test_accepts_em_dash(self):
        md = "## Monday 2026-04-27 — Dish\n"
        assert plan_covers_week(md, date(2026, 4, 27)) is True

    def test_accepts_en_dash(self):
        md = "## Monday 2026-04-27 \u2013 Dish\n"
        assert plan_covers_week(md, date(2026, 4, 27)) is True

    def test_accepts_hyphen(self):
        md = "## Monday 2026-04-27 - Dish\n"
        assert plan_covers_week(md, date(2026, 4, 27)) is True

    def test_rejects_when_date_present_without_monday_keyword(self):
        """A bare date heading without 'Monday' shouldn't satisfy the check —
        we want to confirm the day-of-week parser will see this row.
        """
        md = "## 2026-04-27 — Some heading\n"
        assert plan_covers_week(md, date(2026, 4, 27)) is False

    def test_rejects_close_date(self):
        """Off-by-one day must not match."""
        md = "## Monday 2026-04-26 — wrong week\n"
        assert plan_covers_week(md, date(2026, 4, 27)) is False
