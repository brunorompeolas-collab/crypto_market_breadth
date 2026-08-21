from datetime import datetime, timezone

from crypto_breadth_v2.schedule import scheduled_at_for
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
