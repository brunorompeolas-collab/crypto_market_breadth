"""Independent pandas reference check for the frozen SMA-seeded EMA contract."""

from datetime import datetime, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from crypto_breadth_v2.domain import PricePoint
from crypto_breadth_v2.ema import compute_ema
from crypto_breadth_v2.timeframes import Timeframe, duration


ASSETS = ("BTC", "ETH", "SOL", "XRP", "AAVE")
TIMEFRAMES = (Timeframe.FOUR_HOUR, Timeframe.DAILY, Timeframe.WEEKLY)
PERIODS = (20, 50, 200)
UTC = timezone.utc


def _values(asset_index: int, timeframe_index: int) -> list[Decimal]:
    return [
        Decimal("100")
        + Decimal(asset_index * 7)
        + Decimal(timeframe_index * 3)
        + Decimal(index) * Decimal("0.37")
        + Decimal((index * index + asset_index * 11 + timeframe_index * 5) % 17) / Decimal("100")
        for index in range(260)
    ]


@pytest.mark.parametrize("asset_index", range(len(ASSETS)))
@pytest.mark.parametrize("timeframe_index", range(len(TIMEFRAMES)))
@pytest.mark.parametrize("period", PERIODS)
def test_sma_seeded_ema_matches_independent_pandas_recurrence(asset_index, timeframe_index, period):
    timeframe = TIMEFRAMES[timeframe_index]
    values = _values(asset_index, timeframe_index)
    points = tuple(
        PricePoint(datetime(2020, 1, 6, tzinfo=UTC) + index * duration(timeframe), value)
        for index, value in enumerate(values)
    )
    ours = compute_ema(points, period=period, timeframe=timeframe)

    # pandas is used as an independent recurrence engine.  Its standard
    # ewm(seed=first observation) is intentionally not the BR1 seed.  Inject
    # the frozen SMA seed at p-1, then ask pandas to apply the same alpha.
    seeded = [np.nan] * (period - 1) + [sum(float(value) for value in values[:period]) / period]
    seeded.extend(float(value) for value in values[period:])
    reference = pd.Series(seeded).ewm(span=period, adjust=False, min_periods=1).mean()
    maximum = max(
        abs(float(ours[index].value) - float(reference.iloc[index]))
        for index in range(period - 1, len(values))
    )
    assert maximum <= 3e-12


def test_pandas_default_seed_difference_is_explicit_and_not_silently_adopted():
    values = _values(1, 1)
    points = tuple(
        PricePoint(datetime(2020, 1, 6, tzinfo=UTC) + index * duration(Timeframe.DAILY), value)
        for index, value in enumerate(values)
    )
    ours = compute_ema(points, period=200, timeframe=Timeframe.DAILY)
    default = pd.Series([float(value) for value in values]).ewm(span=200, adjust=False, min_periods=200).mean()
    maximum = max(
        abs(float(ours[index].value) - float(default.iloc[index]))
        for index in range(199, len(values))
    )
    # pandas' documented first-observation seed is different from BR1's
    # frozen SMA seed; this is evidence, not permission to change methodology.
    assert maximum > 5
