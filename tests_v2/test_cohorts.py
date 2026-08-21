from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from crypto_breadth_v2.candles import CanonicalCandle
from crypto_breadth_v2.cohorts import diagnose_candles, derive_weekly_series
from crypto_breadth_v2.timeframes import Timeframe


UTC = timezone.utc
START = datetime(2023, 1, 2, tzinfo=UTC)  # Monday


def daily(open_time: datetime, value: int, *, asset_id: str = "asset") -> CanonicalCandle:
    price = Decimal(value)
    return CanonicalCandle(
        asset_id=asset_id,
        timeframe=Timeframe.DAILY,
        open_time=open_time,
        close_time=open_time + timedelta(days=1),
        open=price,
        high=price + 1,
        low=price - 1,
        close=price,
        base_volume=Decimal("1"),
        quote_volume=Decimal("2"),
        trade_count=1,
    )


def test_199_vs_200_ending_observations_are_distinct():
    candles = [daily(START + timedelta(days=index), index + 1) for index in range(200)]
    boundary = START + timedelta(days=200)
    eligible = diagnose_candles(
        candles,
        asset_id="asset",
        symbol="APT",
        timeframe=Timeframe.DAILY,
        candidate_boundary=boundary,
    )
    assert eligible.ending_consecutive == 200
    assert eligible.eligible

    ineligible = diagnose_candles(
        candles[:-1],
        asset_id="asset",
        symbol="APT",
        timeframe=Timeframe.DAILY,
        candidate_boundary=boundary,
    )
    assert ineligible.ending_consecutive == 0
    assert ineligible.reason == "DOES_NOT_END_AT_CANDIDATE_BOUNDARY"
    assert not ineligible.eligible


def test_internal_missing_day_is_reported_and_blocks_ending_sequence():
    candles = [daily(START + timedelta(days=index), index + 1) for index in range(201)]
    candles.pop(100)
    report = diagnose_candles(
        candles,
        asset_id="asset",
        symbol="TAO",
        timeframe=Timeframe.DAILY,
        candidate_boundary=START + timedelta(days=201),
    )
    assert report.gaps[0].missing_periods == 1
    assert report.longest_consecutive == 100
    assert report.reason == "INSUFFICIENT_CONSECUTIVE_HISTORY"


def test_weekly_requires_exactly_seven_daily_rows_and_never_stitches_assets():
    rows = []
    for index in range(14):
        candle = daily(START + timedelta(days=index), index + 10)
        rows.append({
            "candle": candle,
            "open_time": candle.open_time,
            "close_time": candle.close_time,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "base_volume": candle.base_volume,
            "quote_volume": candle.quote_volume,
            "trade_count": candle.trade_count,
            "provider_closed": True,
            "source_payload_hash": str(index),
        })
    result = derive_weekly_series(rows, asset_id="asset", as_of=START + timedelta(days=14))
    assert len(result) == 2
    missing = rows[:6] + rows[7:]
    assert len(derive_weekly_series(missing, asset_id="asset", as_of=START + timedelta(days=14))) == 1
    other = [dict(row, candle=daily(row["open_time"], 100, asset_id="other")) for row in rows]
    with pytest.raises(ValueError, match="cannot stitch"):
        derive_weekly_series(other, asset_id="asset", as_of=START + timedelta(days=14))
