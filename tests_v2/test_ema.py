from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext

import pytest

from crypto_breadth_v2.domain import Availability, PricePoint
from crypto_breadth_v2.ema import DECIMAL_PRECISION, compute_ema, compute_standard_emas
from crypto_breadth_v2.timeframes import Timeframe


UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)


def points(values, *, missing_index=None):
    result = []
    for index, value in enumerate(values):
        if index == missing_index:
            continue
        result.append(
            PricePoint(
                open_time=START + timedelta(days=index),
                close=Decimal(str(value)) if value is not None else None,
            )
        )
    return result


@pytest.mark.parametrize(
    ("period", "prior_count", "seed", "next_value"),
    [
        (20, 19, Decimal("10.5"), Decimal("11.5")),
        (50, 49, Decimal("25.5"), Decimal("26.5")),
        (200, 199, Decimal("100.5"), Decimal("101.5")),
    ],
)
def test_exact_warmup_boundary_sma_seed_and_recursive_value(period, prior_count, seed, next_value):
    result = compute_ema(points(range(1, period + 2)), period=period, timeframe=Timeframe.DAILY)
    assert len(result[:prior_count]) == prior_count
    assert all(item.status is Availability.WARMUP and item.value is None for item in result[:prior_count])
    assert result[period - 1].status is Availability.AVAILABLE
    assert result[period - 1].value == seed
    assert result[period].value == next_value


def test_flat_vector_remains_flat():
    result = compute_ema(points(["42.125"] * 30), period=20, timeframe=Timeframe.DAILY)
    assert all(item.value == Decimal("42.125") for item in result[19:])


def test_decimal_increasing_vector_is_exact():
    values = [Decimal(index) / Decimal("10") for index in range(1, 22)]
    result = compute_ema(points(values), period=20, timeframe=Timeframe.DAILY)
    assert result[19].value == Decimal("1.05")
    assert result[20].value == Decimal("1.15")


def test_step_change_vector_uses_recursive_alpha():
    result = compute_ema(points([10] * 20 + [20]), period=20, timeframe=Timeframe.DAILY)
    assert result[19].value == Decimal("10")
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        expected = Decimal(230) / Decimal(21)
    assert result[20].value == expected


def test_recoverable_gap_blocks_then_repair_matches_full_recompute():
    values = list(range(1, 31))
    complete = compute_ema(points(values), period=20, timeframe=Timeframe.DAILY)
    broken = compute_ema(points(values, missing_index=24), period=20, timeframe=Timeframe.DAILY)
    assert broken[24].status is Availability.GAP_BLOCKED
    assert all(item.value is None for item in broken[24:])

    repaired = compute_ema(points(values), period=20, timeframe=Timeframe.DAILY)
    assert repaired == complete
    assert repaired[24].status is Availability.AVAILABLE
    assert repaired[25].status is Availability.AVAILABLE


def test_permanent_gap_never_silently_rewarms_after_n_future_observations():
    values = list(range(1, 70))
    broken = compute_ema(points(values, missing_index=24), period=20, timeframe=Timeframe.DAILY)
    first_blocked = 24
    assert broken[first_blocked].status is Availability.GAP_BLOCKED
    assert broken[-1].status is Availability.GAP_BLOCKED
    assert broken[-1].value is None
    assert len(broken) - first_blocked > 20


def test_explicit_missing_close_is_an_integrity_gap():
    result = compute_ema(points(list(range(1, 25)) + [None] + list(range(26, 50))), period=20, timeframe=Timeframe.DAILY)
    assert result[24].status is Availability.GAP_BLOCKED
    assert result[-1].status is Availability.GAP_BLOCKED


def test_standard_bundle_is_repeatable_and_contains_only_frozen_periods():
    source = points(range(1, 205))
    left = compute_standard_emas(source, timeframe=Timeframe.DAILY)
    right = compute_standard_emas(source, timeframe=Timeframe.DAILY)
    assert left == right
    assert set(left) == {20, 50, 200}
