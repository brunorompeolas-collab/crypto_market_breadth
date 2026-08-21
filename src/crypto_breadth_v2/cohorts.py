"""Deterministic candidate cohort diagnostics and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import Connection, select
from sqlalchemy.dialects.postgresql import insert

from .candles import CanonicalCandle, WeeklyDerivation, derive_weekly_candle
from .timeframes import Timeframe, duration, next_open, require_utc
from .storage.models import TimeframeCohort


EMA200_OBSERVATIONS = 200
MINIMUM_WEEKLY_COVERAGE = 32
UTC = timezone.utc


@dataclass(frozen=True)
class Gap:
    previous_open: datetime
    next_open: datetime
    missing_periods: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "previous_open": self.previous_open.isoformat(),
            "next_open": self.next_open.isoformat(),
            "missing_periods": self.missing_periods,
        }


@dataclass(frozen=True)
class CoverageDiagnostics:
    asset_id: str
    symbol: str
    timeframe: Timeframe
    total_candles: int
    first_open: datetime | None
    last_close: datetime | None
    longest_consecutive: int
    ending_consecutive: int
    candidate_boundary: datetime
    eligible: bool
    reason: str
    gaps: tuple[Gap, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "total_candles": self.total_candles,
            "first_open": self.first_open.isoformat() if self.first_open else None,
            "last_close": self.last_close.isoformat() if self.last_close else None,
            "longest_consecutive": self.longest_consecutive,
            "ending_consecutive": self.ending_consecutive,
            "candidate_boundary": self.candidate_boundary.isoformat(),
            "eligible": self.eligible,
            "reason": self.reason,
            "gaps": [gap.as_dict() for gap in self.gaps],
        }


@dataclass(frozen=True)
class WeeklyDerived:
    candle: CanonicalCandle
    source_payload_hash: str
    source_candle_ids: tuple[str, ...]


@dataclass(frozen=True)
class CohortReport:
    timeframe: Timeframe
    universe_size: int
    rows: tuple[CoverageDiagnostics, ...]

    @property
    def eligible_asset_ids(self) -> tuple[str, ...]:
        return tuple(row.asset_id for row in self.rows if row.eligible)

    @property
    def eligible_symbols(self) -> tuple[str, ...]:
        return tuple(row.symbol for row in self.rows if row.eligible)

    @property
    def coverage(self) -> float:
        return len(self.eligible_asset_ids) / self.universe_size

    @property
    def coverage_passes(self) -> bool:
        return len(self.eligible_asset_ids) >= MINIMUM_WEEKLY_COVERAGE

    def as_dict(self) -> dict[str, Any]:
        return {
            "timeframe": self.timeframe.value,
            "universe_size": self.universe_size,
            "eligible_count": len(self.eligible_asset_ids),
            "coverage": self.coverage,
            "coverage_threshold": MINIMUM_WEEKLY_COVERAGE / self.universe_size,
            "coverage_passes": self.coverage_passes,
            "eligible_asset_ids": list(self.eligible_asset_ids),
            "eligible_symbols": list(self.eligible_symbols),
            "assets": [row.as_dict() for row in self.rows],
        }


def diagnose_candles(
    candles: Sequence[CanonicalCandle],
    *,
    asset_id: str,
    symbol: str,
    timeframe: Timeframe,
    candidate_boundary: datetime,
) -> CoverageDiagnostics:
    """Measure internal gaps and the consecutive sequence ending at the boundary."""
    timeframe = Timeframe(timeframe)
    require_utc(candidate_boundary)
    ordered = tuple(sorted(candles, key=lambda candle: candle.open_time))
    gaps: list[Gap] = []
    longest = 0
    run = 0
    previous = None
    for candle in ordered:
        if previous is None or candle.open_time == next_open(previous, timeframe):
            run += 1
        else:
            missing = int((candle.open_time - next_open(previous, timeframe)) / duration(timeframe))
            gaps.append(Gap(previous, candle.open_time, max(1, missing)))
            longest = max(longest, run)
            run = 1
        previous = candle.open_time
    longest = max(longest, run)
    expected_last_open = candidate_boundary - duration(timeframe)
    ending = 0
    if ordered and ordered[-1].close_time == candidate_boundary:
        ending = 1
        for index in range(len(ordered) - 2, -1, -1):
            if ordered[index + 1].open_time == next_open(ordered[index].open_time, timeframe):
                ending += 1
            else:
                break
    if not ordered:
        reason = "NO_CANONICAL_HISTORY"
    elif ordered[-1].open_time != expected_last_open:
        reason = "DOES_NOT_END_AT_CANDIDATE_BOUNDARY"
    elif ending < EMA200_OBSERVATIONS:
        reason = "INSUFFICIENT_CONSECUTIVE_HISTORY"
    else:
        reason = "EMA200_ELIGIBLE"
    return CoverageDiagnostics(
        asset_id=asset_id,
        symbol=symbol,
        timeframe=timeframe,
        total_candles=len(ordered),
        first_open=ordered[0].open_time if ordered else None,
        last_close=ordered[-1].close_time if ordered else None,
        longest_consecutive=longest,
        ending_consecutive=ending,
        candidate_boundary=candidate_boundary,
        eligible=reason == "EMA200_ELIGIBLE",
        reason=reason,
        gaps=tuple(gaps),
    )


def derive_weekly_series(
    daily_candles: Sequence[Mapping[str, Any]],
    *,
    asset_id: str,
    as_of: datetime,
) -> tuple[WeeklyDerived, ...]:
    """Derive only complete Monday-to-Monday weeks from stored daily rows."""
    require_utc(as_of)
    by_open: dict[datetime, tuple[CanonicalCandle, str]] = {}
    for row in daily_candles:
        candle = row["candle"] if isinstance(row.get("candle"), CanonicalCandle) else CanonicalCandle(
            asset_id=asset_id,
            timeframe=Timeframe.DAILY,
            open_time=row["open_time"],
            close_time=row["close_time"],
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            base_volume=row.get("base_volume"),
            quote_volume=row.get("quote_volume"),
            trade_count=row.get("trade_count"),
            provider_complete=row.get("provider_closed", True),
        )
        if candle.asset_id != asset_id:
            raise ValueError("weekly derivation cannot stitch predecessor or replacement assets")
        by_open[candle.open_time] = (candle, row["source_payload_hash"])
    mondays = sorted(open_time for open_time in by_open if open_time.weekday() == 0 and open_time.hour == 0)
    derived: list[WeeklyDerived] = []
    for monday in mondays:
        week_rows = []
        hashes: list[str] = []
        source_ids: list[str] = []
        for offset in range(7):
            item = by_open.get(monday + timedelta(days=offset))
            if item is None:
                week_rows = []
                break
            week_rows.append(item[0])
            hashes.append(item[1])
            source_ids.append(str(item[0].open_time))
        if len(week_rows) != 7:
            continue
        result: WeeklyDerivation = derive_weekly_candle(week_rows, as_of=as_of)
        if not result.available:
            continue
        payload_hash = sha256(
            json.dumps(hashes, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        derived.append(WeeklyDerived(result.candle, payload_hash, tuple(source_ids)))
    return tuple(derived)


class CohortConflictError(RuntimeError):
    pass


def persist_candidate_cohorts(
    connection: Connection,
    *,
    series_version: str,
    frozen_at: datetime,
    reports: Iterable[CohortReport],
    asset_uuid_by_id: Mapping[str, Any],
) -> None:
    """Insert frozen candidate rows once; a changed row is an explicit conflict."""
    for report in reports:
        for row in report.rows:
            values = {
                "series_version": series_version,
                "timeframe": report.timeframe.value,
                "asset_id": asset_uuid_by_id[row.asset_id],
                "included_in_denominator": row.eligible,
                "history_count_at_inception": row.ending_consecutive,
                "eligibility_reason": row.reason,
                "frozen_at": frozen_at,
            }
            statement = (
                insert(TimeframeCohort)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["series_version", "timeframe", "asset_id"])
            )
            connection.execute(statement)
            existing = connection.execute(
                select(
                    TimeframeCohort.included_in_denominator,
                    TimeframeCohort.history_count_at_inception,
                    TimeframeCohort.eligibility_reason,
                ).filter_by(
                    series_version=series_version,
                    timeframe=report.timeframe.value,
                    asset_id=asset_uuid_by_id[row.asset_id],
                )
            ).one()
            if (
                existing.included_in_denominator != values["included_in_denominator"]
                or existing.history_count_at_inception != values["history_count_at_inception"]
                or existing.eligibility_reason != values["eligibility_reason"]
            ):
                raise CohortConflictError(
                    f"candidate cohort changed for {row.asset_id}/{report.timeframe.value}"
                )
