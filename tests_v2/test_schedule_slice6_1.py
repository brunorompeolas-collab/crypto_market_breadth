from datetime import datetime, timezone

from crypto_breadth_v2.schedule import recovery_eligible_at, scheduled_at_for
from crypto_breadth_v2.timeframes import Timeframe


UTC = timezone.utc


def test_approved_utc_offsets():
    now = datetime(2026, 8, 21, 16, 12, tzinfo=UTC)
    assert scheduled_at_for(now, Timeframe.FOUR_HOUR).isoformat() == "2026-08-21T16:10:00+00:00"
    assert scheduled_at_for(now, Timeframe.DAILY).isoformat() == "2026-08-21T00:15:00+00:00"
    assert scheduled_at_for(now, Timeframe.WEEKLY).isoformat() == "2026-08-17T00:25:00+00:00"


def test_schedule_rejects_non_utc_clock():
    local = datetime(2026, 8, 21, 16, 12)
    try:
        scheduled_at_for(local, Timeframe.FOUR_HOUR)
    except ValueError as exc:
        assert "UTC" in str(exc)
    else:
        raise AssertionError("naive scheduler clock must be rejected")


def test_recovery_does_not_preempt_fresh_4h_boundary():
    boundary = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    assert not recovery_eligible_at(datetime(2026, 8, 23, 12, 0, tzinfo=UTC), boundary, Timeframe.FOUR_HOUR)
    assert not recovery_eligible_at(datetime(2026, 8, 23, 12, 10, 59, tzinfo=UTC), boundary, Timeframe.FOUR_HOUR)
    assert recovery_eligible_at(datetime(2026, 8, 23, 12, 11, tzinfo=UTC), boundary, Timeframe.FOUR_HOUR)


def test_daily_and_weekly_grace_windows():
    daily = datetime(2026, 8, 23, 0, 0, tzinfo=UTC)
    weekly = datetime(2026, 8, 24, 0, 0, tzinfo=UTC)
    assert not recovery_eligible_at(datetime(2026, 8, 23, 0, 15, 59, tzinfo=UTC), daily, Timeframe.DAILY)
    assert recovery_eligible_at(datetime(2026, 8, 23, 0, 16, tzinfo=UTC), daily, Timeframe.DAILY)
    assert not recovery_eligible_at(datetime(2026, 8, 24, 0, 25, 59, tzinfo=UTC), weekly, Timeframe.WEEKLY)
    assert recovery_eligible_at(datetime(2026, 8, 24, 0, 26, tzinfo=UTC), weekly, Timeframe.WEEKLY)


def test_older_gap_is_immediately_recoverable():
    boundary = datetime(2026, 8, 23, 4, 0, tzinfo=UTC)
    assert recovery_eligible_at(datetime(2026, 8, 23, 12, 0, tzinfo=UTC), boundary, Timeframe.FOUR_HOUR)


def test_normal_job_then_recovery_has_no_fresh_boundary_claim():
    boundary = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    normal_job_at = datetime(2026, 8, 23, 12, 10, 2, tzinfo=UTC)
    recovery_tick_at = datetime(2026, 8, 23, 13, 0, tzinfo=UTC)
    assert not recovery_eligible_at(normal_job_at, boundary, Timeframe.FOUR_HOUR)
    assert recovery_eligible_at(recovery_tick_at, boundary, Timeframe.FOUR_HOUR)
