"""Provider-independent weekly derivation for the stateless reconciler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from .candles import CanonicalCandle, WeeklyDerivation, derive_weekly_candle
from .timeframes import Timeframe, require_utc


@dataclass(frozen=True)
class WeeklyDerived:
    candle: CanonicalCandle
    source_payload_hash: str
    source_candle_ids: tuple[str, ...]


def derive_weekly_series(
    daily_candles: Sequence[Mapping[str, Any]], *, asset_id: str, as_of: datetime
) -> tuple[WeeklyDerived, ...]:
    """Derive only complete Monday-to-Monday weeks from native daily rows."""
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
        week_rows: list[CanonicalCandle] = []
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
        payload_hash = sha256(json.dumps(hashes, separators=(",", ":")).encode("utf-8")).hexdigest()
        derived.append(WeeklyDerived(result.candle, payload_hash, tuple(source_ids)))
    return tuple(derived)
