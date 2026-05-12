"""Tests for send_weekly_plan helpers.

The interesting logic to verify is the date-bracketing behavior of
`expected_plan_monday`, which determines which week's plan we expect
to be in `current-week.md` at the moment we're about to email it.

The full email path hits Resend and isn't worth mocking out for one
helper — the bug we're guarding against (#27) is purely a freshness
check.
"""
from datetime import date

from send_weekly_plan import expected_plan_monday


class TestExpectedPlanMonday:
    """The function returns the Monday whose week the current plan
    should cover at the moment send_weekly_plan.py runs.

    On Saturday/Sunday, that's the upcoming Monday (workflow just made
    next week's plan). On Monday–Friday, that's the current week's
    Monday (manual rerun of the already-sent plan).
    """

    def test_saturday_returns_upcoming_monday(self):
        # 2026-04-25 is a Saturday; next Monday is 2026-04-27.
        assert expected_plan_monday("UTC", date(2026, 4, 25)) == date(2026, 4, 27)

    def test_sunday_returns_upcoming_monday(self):
        # 2026-04-26 is a Sunday; next Monday is 2026-04-27.
        assert expected_plan_monday("UTC", date(2026, 4, 26)) == date(2026, 4, 27)

    def test_monday_returns_today(self):
        # 2026-04-27 is a Monday — the plan covers this Monday.
        assert expected_plan_monday("UTC", date(2026, 4, 27)) == date(2026, 4, 27)

    def test_tuesday_returns_this_weeks_monday(self):
        # 2026-04-28 is a Tuesday; this week's Monday is 2026-04-27.
        assert expected_plan_monday("UTC", date(2026, 4, 28)) == date(2026, 4, 27)

    def test_friday_returns_this_weeks_monday(self):
        # 2026-05-01 is a Friday; this week's Monday is 2026-04-27.
        assert expected_plan_monday("UTC", date(2026, 5, 1)) == date(2026, 4, 27)
