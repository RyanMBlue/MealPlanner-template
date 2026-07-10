"""Tests for week_target — the shared target-Monday resolver (issue #3)."""
import pytest
from datetime import date

from week_target import (
    parse_monday,
    render_target_file,
    resolve_target_monday,
    upcoming_monday,
)


class TestUpcomingMonday:
    def test_friday_returns_following_monday(self):
        # Fri 2026-07-03 → Mon 2026-07-06
        assert upcoming_monday("UTC", date(2026, 7, 3)) == date(2026, 7, 6)

    def test_saturday_returns_two_days_later(self):
        # Sat 2026-07-04 → Mon 2026-07-06
        assert upcoming_monday("UTC", date(2026, 7, 4)) == date(2026, 7, 6)

    def test_sunday_returns_next_day(self):
        # Sun 2026-07-05 → Mon 2026-07-06
        assert upcoming_monday("UTC", date(2026, 7, 5)) == date(2026, 7, 6)

    def test_monday_returns_strictly_next_monday(self):
        # Mon 2026-07-06 → Mon 2026-07-13 (never the same day)
        assert upcoming_monday("UTC", date(2026, 7, 6)) == date(2026, 7, 13)


class TestParseMonday:
    def test_valid_monday(self):
        assert parse_monday("2026-07-06") == date(2026, 7, 6)

    def test_strips_surrounding_whitespace(self):
        assert parse_monday("  2026-07-06 ") == date(2026, 7, 6)

    def test_non_monday_raises(self):
        # 2026-07-07 is a Tuesday
        with pytest.raises(ValueError, match="not a Monday"):
            parse_monday("2026-07-07")

    def test_malformed_date_raises(self):
        with pytest.raises(ValueError, match="valid YYYY-MM-DD"):
            parse_monday("not-a-date")

    def test_non_iso_format_raises(self):
        with pytest.raises(ValueError):
            parse_monday("07/06/2026")


class TestResolveTargetMonday:
    def test_explicit_valid_monday_wins(self):
        assert resolve_target_monday("UTC", "2026-07-06", today=date(2026, 1, 1)) == date(2026, 7, 6)

    def test_none_falls_back_to_upcoming(self):
        assert resolve_target_monday("UTC", None, today=date(2026, 7, 3)) == date(2026, 7, 6)

    def test_empty_string_falls_back_to_upcoming(self):
        # The workflow passes "" when the dispatch input is left blank.
        assert resolve_target_monday("UTC", "   ", today=date(2026, 7, 3)) == date(2026, 7, 6)

    def test_explicit_invalid_raises(self):
        with pytest.raises(ValueError):
            resolve_target_monday("UTC", "2026-07-07", today=date(2026, 7, 3))


class TestRenderTargetFile:
    def test_contains_monday_and_sunday(self):
        out = render_target_file(date(2026, 7, 6))
        assert "2026-07-06" in out
        assert "2026-07-12" in out  # the following Sunday
        assert "authoritative" in out
