from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from crypto_breadth_v2.candles import (
    CanonicalCandle,
    CandleContractError,
    derive_weekly_candle,
    validate_candle,
)
from crypto_breadth_v2.timeframes import (
    Timeframe,
    close_time,
    expected_latest_close,
    is_open_boundary,
)


UTC = timezone.utc


def dt(day=3, hour=0, minute=0):
    return datetime(2026, 8, day, hour, minute, tzinfo=UTC)


@pytest.mark.parametrize("hour", [0, 4, 8, 12, 16, 20])
def test_four_hour_utc_open_boundaries(hour):
    assert is_open_boundary(dt(hour=hour), Timeframe.FOUR_HOUR)


@pytest.mark.parametrize("hour", [1, 3, 5, 23])
def test_four_hour_rejects_non_boundaries(hour):
    assert not is_open_boundary(dt(hour=hour), Timeframe.FOUR_HOUR)


def test_daily_boundary_is_midnight_utc_only():
    assert is_open_boundary(dt(), Timeframe.DAILY)
    assert not is_open_boundary(dt(hour=4), Timeframe.DAILY)
    assert close_time(dt(), Timeframe.DAILY) == dt(day=4)


def test_weekly_boundary_is_monday_to_monday():
    monday = dt(day=3)
    assert monday.weekday() == 0
    assert is_open_boundary(monday, Timeframe.WEEKLY)
    assert close_time(monday, Timeframe.WEEKLY) == dt(day=10)
    assert not is_open_boundary(dt(day=4), Timeframe.WEEKLY)


def test_expected_latest_close_uses_exclusive_boundary():
    assert expected_latest_close(dt(hour=7, minute=59), Timeframe.FOUR_HOUR) == dt(hour=4)
    assert expected_latest_close(dt(day=5, hour=23), Timeframe.DAILY) == dt(day=5)
    assert expected_latest_close(dt(day=9, hour=23), Timeframe.WEEKLY) == dt(day=3)


def make_daily(day, price):
    value = Decimal(str(price))
    return CanonicalCandle(
        asset_id="bitcoin",
        timeframe=Timeframe.DAILY,
        open_time=dt(day=day),
        close_time=dt(day=day + 1),
        open=value,
        high=value + Decimal("1"),
        low=value - Decimal("1"),
        close=value + Decimal("0.5"),
        base_volume=Decimal("10"),
        quote_volume=Decimal("100"),
        trade_count=2,
    )


def test_canonical_candle_requires_completed_exact_boundary():
    candle = make_daily(3, 10)
    validate_candle(candle, as_of=dt(day=4))
    with pytest.raises(CandleContractError, match="not completed"):
        validate_candle(candle, as_of=dt(day=3, hour=23))


def test_weekly_derivation_uses_exactly_seven_contiguous_daily_candles():
    daily = [make_daily(day, 10 + index) for index, day in enumerate(range(3, 10))]
    result = derive_weekly_candle(daily, as_of=dt(day=10))
    assert result.available
    assert result.candle.open_time == dt(day=3)
    assert result.candle.close_time == dt(day=10)
    assert result.candle.open == Decimal("10")
    assert result.candle.close == Decimal("16.5")
    assert result.candle.high == Decimal("17")
    assert result.candle.low == Decimal("9")
    assert result.candle.base_volume == Decimal("70")
    assert result.candle.trade_count == 14


def test_weekly_derivation_rejects_missing_or_misaligned_day():
    daily = [make_daily(day, 10) for day in range(3, 10)]
    missing = daily[:3] + daily[4:]
    assert derive_weekly_candle(missing, as_of=dt(day=10)).reason == "EXACTLY_SEVEN_DAILY_CANDLES_REQUIRED"
    shifted = list(daily)
    shifted[3] = make_daily(7, 10)
    assert derive_weekly_candle(shifted, as_of=dt(day=10)).reason == "MISSING_OR_MISALIGNED_DAILY_CANDLE"
