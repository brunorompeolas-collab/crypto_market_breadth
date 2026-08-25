"""Exact SMA-seeded recursive EMA with integrity-gap blocking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Iterable, Optional, Sequence

from .domain import Availability, PricePoint
from .timeframes import Timeframe, next_open, require_utc


EMA_PERIODS = (20, 50, 200)
DECIMAL_PRECISION = 50


@dataclass(frozen=True)
class EmaPoint:
    open_time: datetime
    value: Optional[Decimal]
    status: Availability
    observation_count: int
    reason: Optional[str] = None


def _validate_point_order(points: Sequence[PricePoint]) -> None:
    previous = None
    for point in points:
        if not isinstance(point.open_time, datetime):
            raise TypeError("PricePoint.open_time must be a datetime")
        require_utc(point.open_time)
        if previous is not None and point.open_time <= previous:
            raise ValueError("Price points must be unique and strictly chronological")
        if point.close is not None and (not point.close.is_finite() or point.close <= 0):
            raise ValueError("Close must be finite and positive when present")
        previous = point.open_time


def compute_ema(
    points: Iterable[PricePoint], *, period: int, timeframe: Timeframe
) -> tuple[EmaPoint, ...]:
    """Compute an exact EMA, blocking forever after an unresolved canonical gap.

    Recovery is represented by rerunning this pure function with the repaired,
    complete chronological input. It does not discard valid pre-gap state and
    it never silently starts a new warm-up sequence after a permanent gap.
    """
    if period <= 0:
        raise ValueError("EMA period must be positive")
    timeframe = Timeframe(timeframe)
    point_list = tuple(points)
    _validate_point_order(point_list)

    results: list[EmaPoint] = []
    closes: list[Decimal] = []
    current_ema: Optional[Decimal] = None
    blocked = False
    previous_time: Optional[datetime] = None
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        for point in point_list:
            if previous_time is not None and point.open_time != next_open(previous_time, timeframe):
                blocked = True
            if point.close is None:
                blocked = True

            if blocked:
                results.append(
                    EmaPoint(
                        open_time=point.open_time,
                        value=None,
                        status=Availability.GAP_BLOCKED,
                        observation_count=len(closes),
                        reason="UNRESOLVED_CANONICAL_GAP",
                    )
                )
                previous_time = point.open_time
                continue

            closes.append(point.close)
            if len(closes) < period:
                results.append(
                    EmaPoint(
                        open_time=point.open_time,
                        value=None,
                        status=Availability.WARMUP,
                        observation_count=len(closes),
                    )
                )
            elif len(closes) == period:
                current_ema = sum(closes, Decimal("0")) / Decimal(period)
                results.append(
                    EmaPoint(
                        open_time=point.open_time,
                        value=current_ema,
                        status=Availability.AVAILABLE,
                        observation_count=len(closes),
                    )
                )
            else:
                assert current_ema is not None
                # Algebraically identical to alpha*C + (1-alpha)*EMA, but
                # evaluates the exact integer numerator before the one
                # unavoidable Decimal division. This avoids avoidable alpha
                # pre-rounding and is frozen by BR1-METHODOLOGY-v2.
                current_ema = current_ema + (
                    Decimal(2) * (point.close - current_ema) / Decimal(period + 1)
                )
                results.append(
                    EmaPoint(
                        open_time=point.open_time,
                        value=current_ema,
                        status=Availability.AVAILABLE,
                        observation_count=len(closes),
                    )
                )
            previous_time = point.open_time
    return tuple(results)


def compute_standard_emas(
    points: Iterable[PricePoint], *, timeframe: Timeframe
) -> dict[int, tuple[EmaPoint, ...]]:
    point_list = tuple(points)
    return {
        period: compute_ema(point_list, period=period, timeframe=timeframe)
        for period in EMA_PERIODS
    }
