"""Canonical candle validation and deterministic weekly derivation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from .timeframes import Timeframe, close_time, next_open, require_utc


class CandleContractError(ValueError):
    pass


@dataclass(frozen=True)
class CanonicalCandle:
    asset_id: str
    timeframe: Timeframe
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    base_volume: Optional[Decimal] = None
    quote_volume: Optional[Decimal] = None
    trade_count: Optional[int] = None
    provider_complete: bool = True


@dataclass(frozen=True)
class WeeklyDerivation:
    candle: Optional[CanonicalCandle]
    reason: Optional[str]

    @property
    def available(self) -> bool:
        return self.candle is not None


def validate_candle(candle: CanonicalCandle, *, as_of: datetime) -> None:
    require_utc(as_of)
    timeframe = Timeframe(candle.timeframe)
    expected_close = close_time(candle.open_time, timeframe)
    if candle.close_time != expected_close:
        raise CandleContractError("Candle close does not match its exclusive UTC boundary")
    if candle.close_time > as_of:
        raise CandleContractError("Candle has not completed as of the evaluation time")
    if not candle.provider_complete:
        raise CandleContractError("Provider marks candle incomplete")
    values = (candle.open, candle.high, candle.low, candle.close)
    if any(not value.is_finite() or value <= 0 for value in values):
        raise CandleContractError("OHLC prices must be finite and positive")
    if candle.low > min(candle.open, candle.close):
        raise CandleContractError("Low exceeds open or close")
    if candle.high < max(candle.open, candle.close):
        raise CandleContractError("High is below open or close")
    if candle.low > candle.high:
        raise CandleContractError("Low exceeds high")
    for volume in (candle.base_volume, candle.quote_volume):
        if volume is not None and (not volume.is_finite() or volume < 0):
            raise CandleContractError("Volumes must be finite and non-negative")
    if candle.trade_count is not None and candle.trade_count < 0:
        raise CandleContractError("Trade count must be non-negative")


def _sum_optional(values: Sequence[Optional[Decimal]]) -> Optional[Decimal]:
    if any(value is None for value in values):
        return None
    return sum((value for value in values if value is not None), Decimal("0"))


def derive_weekly_candle(
    daily_candles: Sequence[CanonicalCandle], *, as_of: datetime
) -> WeeklyDerivation:
    if len(daily_candles) != 7:
        return WeeklyDerivation(None, "EXACTLY_SEVEN_DAILY_CANDLES_REQUIRED")
    first = daily_candles[0]
    if Timeframe(first.timeframe) is not Timeframe.DAILY:
        return WeeklyDerivation(None, "NON_DAILY_INPUT")
    if first.open_time.weekday() != 0 or first.open_time.hour != 0:
        return WeeklyDerivation(None, "WEEK_MUST_OPEN_MONDAY_UTC")
    if any(candle.asset_id != first.asset_id for candle in daily_candles):
        return WeeklyDerivation(None, "ASSET_MISMATCH")

    expected_open = first.open_time
    for candle in daily_candles:
        if Timeframe(candle.timeframe) is not Timeframe.DAILY or candle.open_time != expected_open:
            return WeeklyDerivation(None, "MISSING_OR_MISALIGNED_DAILY_CANDLE")
        try:
            validate_candle(candle, as_of=as_of)
        except CandleContractError as exc:
            return WeeklyDerivation(None, f"INVALID_DAILY_CANDLE:{exc}")
        expected_open = next_open(expected_open, Timeframe.DAILY)

    weekly = CanonicalCandle(
        asset_id=first.asset_id,
        timeframe=Timeframe.WEEKLY,
        open_time=first.open_time,
        close_time=daily_candles[-1].close_time,
        open=first.open,
        high=max(candle.high for candle in daily_candles),
        low=min(candle.low for candle in daily_candles),
        close=daily_candles[-1].close,
        base_volume=_sum_optional([candle.base_volume for candle in daily_candles]),
        quote_volume=_sum_optional([candle.quote_volume for candle in daily_candles]),
        trade_count=(
            None
            if any(candle.trade_count is None for candle in daily_candles)
            else sum(candle.trade_count or 0 for candle in daily_candles)
        ),
        provider_complete=True,
    )
    try:
        validate_candle(weekly, as_of=as_of)
    except CandleContractError as exc:
        return WeeklyDerivation(None, f"INVALID_WEEKLY_CANDLE:{exc}")
    return WeeklyDerivation(weekly, None)
