from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import shutil
import subprocess

import pytest

from crypto_breadth_v2.schedule import scheduled_at_for
from crypto_breadth_v2.timeframes import Timeframe


UTC = timezone.utc
MADRID = ZoneInfo("Europe/Madrid")


def test_4h_daily_weekly_slots_are_utc_across_dst():
    # Both local representations must resolve to the same UTC schedule.
    summer = datetime(2026, 7, 15, 3, 10, tzinfo=MADRID).astimezone(UTC)
    winter = datetime(2026, 12, 15, 1, 10, tzinfo=MADRID).astimezone(UTC)
    assert scheduled_at_for(summer, Timeframe.FOUR_HOUR).hour == 0
    assert scheduled_at_for(winter, Timeframe.FOUR_HOUR).hour == 0

    summer_daily = datetime(2026, 7, 15, 2, 15, tzinfo=MADRID).astimezone(UTC)
    winter_daily = datetime(2026, 12, 15, 1, 15, tzinfo=MADRID).astimezone(UTC)
    assert scheduled_at_for(summer_daily, Timeframe.DAILY).isoformat() == "2026-07-15T00:15:00+00:00"
    assert scheduled_at_for(winter_daily, Timeframe.DAILY).isoformat() == "2026-12-15T00:15:00+00:00"


def test_systemd_calendar_expressions_are_explicit_utc():
    if shutil.which("systemd-analyze") is None:
        pytest.skip("systemd-analyze unavailable")
    expressions = (
        "*-*-* 00,04,08,12,16,20:10:00 UTC",
        "*-*-* 00:15:00 UTC",
        "Mon *-*-* 00:25:00 UTC",
        "*-*-* *:00:00 UTC",
    )
    for expression in expressions:
        result = subprocess.run(
            ["systemd-analyze", "calendar", expression],
            check=True,
            capture_output=True,
            text=True,
        )
        assert "UTC" in result.stdout
        assert "Normalized form" in result.stdout


def test_exact_4h_trigger_hours():
    for hour in (0, 4, 8, 12, 16, 20):
        now = datetime(2026, 8, 23, hour, 10, tzinfo=UTC)
        assert scheduled_at_for(now, Timeframe.FOUR_HOUR).hour == hour
        assert scheduled_at_for(now, Timeframe.FOUR_HOUR).minute == 10
