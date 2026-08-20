"""UTC candle boundary rules with no provider or clock dependencies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum


UTC = timezone.utc


class Timeframe(str, Enum):
    FOUR_HOUR = "4h"
    DAILY = "1d"
    WEEKLY = "1w"


_DURATIONS = {
    Timeframe.FOUR_HOUR: timedelta(hours=4),
    Timeframe.DAILY: timedelta(days=1),
    Timeframe.WEEKLY: timedelta(days=7),
}


def require_utc(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("Timestamp must be timezone-aware UTC")


def duration(timeframe: Timeframe) -> timedelta:
    return _DURATIONS[Timeframe(timeframe)]


def is_open_boundary(value: datetime, timeframe: Timeframe) -> bool:
    require_utc(value)
    timeframe = Timeframe(timeframe)
    if value.minute or value.second or value.microsecond:
        return False
    if timeframe is Timeframe.FOUR_HOUR:
        return value.hour in {0, 4, 8, 12, 16, 20}
    if timeframe is Timeframe.DAILY:
        return value.hour == 0
    return value.weekday() == 0 and value.hour == 0


def close_time(open_time: datetime, timeframe: Timeframe) -> datetime:
    if not is_open_boundary(open_time, timeframe):
        raise ValueError(f"{open_time!r} is not a {Timeframe(timeframe).value} UTC boundary")
    return open_time + duration(timeframe)


def next_open(open_time: datetime, timeframe: Timeframe) -> datetime:
    return close_time(open_time, timeframe)


def expected_latest_close(as_of: datetime, timeframe: Timeframe) -> datetime:
    """Return the most recent exclusive close boundary at or before ``as_of``."""
    require_utc(as_of)
    timeframe = Timeframe(timeframe)
    as_of = as_of.astimezone(UTC)
    if timeframe is Timeframe.FOUR_HOUR:
        hour = as_of.hour - (as_of.hour % 4)
        return as_of.replace(hour=hour, minute=0, second=0, microsecond=0)
    if timeframe is Timeframe.DAILY:
        return as_of.replace(hour=0, minute=0, second=0, microsecond=0)
    monday = as_of - timedelta(days=as_of.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)
