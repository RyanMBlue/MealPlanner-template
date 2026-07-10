"""Tests for regenerate_guard target-week resolution (issue #3).

The guard scrubs a prior attempt for the week about to be planned. On a manual
backfill it must scrub the *target* week (from $TARGET_MONDAY), not the
wall-clock upcoming week, so re-runs are deterministic.
"""
from datetime import date

from regenerate_guard import target_week


class TestTargetWeek:
    def test_honors_explicit_target_monday_env(self, monkeypatch):
        monkeypatch.setenv("TARGET_MONDAY", "2026-08-03")
        monday, sunday = target_week("America/New_York")
        assert monday == date(2026, 8, 3)
        assert sunday == date(2026, 8, 9)

    def test_falls_back_to_upcoming_when_unset(self, monkeypatch):
        monkeypatch.delenv("TARGET_MONDAY", raising=False)
        monday, sunday = target_week("America/New_York")
        # Without an explicit target it's the strictly-next Monday; assert the
        # shape rather than a wall-clock-dependent date.
        assert monday.weekday() == 0
        assert (sunday - monday).days == 6

    def test_blank_env_falls_back_to_upcoming(self, monkeypatch):
        monkeypatch.setenv("TARGET_MONDAY", "")
        monday, sunday = target_week("America/New_York")
        assert monday.weekday() == 0
        assert (sunday - monday).days == 6
