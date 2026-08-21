"""Transactional Gate fixture/live payload to canonical candle and indicator slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Sequence
from uuid import UUID, uuid4

from sqlalchemy import Engine, select

from .domain import PricePoint
from .ema import compute_standard_emas
from .providers.gate import GATE_SOURCE_ID, GateCandleEnvelope
from .storage.database import transaction
from .storage.models import CanonicalCandleRecord
from .storage.repositories import AssetIndicatorRepository, CanonicalCandleRepository


@dataclass(frozen=True)
class GatePersistenceContext:
    asset_id: UUID
    mapping_id: UUID
    source_version_id: UUID
    run_id: UUID
    series_version: str
    universe_version: str
    formula_version: str
    normalizer_version: str
    ingested_at: datetime
    computed_at: datetime
    source_id: str = GATE_SOURCE_ID


@dataclass(frozen=True)
class GateVerticalResult:
    candle_ids: tuple[UUID, ...]
    inserted_indicators: int
    latest_close: Decimal
    latest_ema20: Decimal | None
    latest_ema50: Decimal | None
    latest_ema200: Decimal | None


def persist_gate_candles_and_indicators(
    engine: Engine,
    envelopes: Sequence[GateCandleEnvelope],
    *,
    context: GatePersistenceContext,
) -> GateVerticalResult:
    """Persist valid Gate candles and recompute immutable indicators atomically."""
    if not envelopes:
        raise ValueError("At least one validated Gate candle is required")
    first = envelopes[0]
    if any(item.mapping != first.mapping for item in envelopes):
        raise ValueError("A vertical-slice batch must contain one frozen mapping")
    if any(item.candle.timeframe != first.candle.timeframe for item in envelopes):
        raise ValueError("A vertical-slice batch must contain one timeframe")
    if any(item.candle.asset_id != first.mapping.canonical_id for item in envelopes):
        raise ValueError("Canonical asset identity does not match the frozen mapping")

    candle_repository = CanonicalCandleRepository()
    indicator_repository = AssetIndicatorRepository()
    candle_ids: list[UUID] = []
    with transaction(engine) as connection:
        for envelope in sorted(envelopes, key=lambda item: item.candle.open_time):
            candle = envelope.candle
            candle_id = candle_repository.put(
                connection,
                {
                    "candle_id": uuid4(),
                    "asset_id": context.asset_id,
                    "mapping_id": context.mapping_id,
                    "source_version_id": context.source_version_id,
                    "source_id": context.source_id,
                    "normalizer_version": context.normalizer_version,
                    "timeframe": candle.timeframe.value,
                    "open_time": candle.open_time,
                    "close_time": candle.close_time,
                    "open": candle.open,
                    "high": candle.high,
                    "low": candle.low,
                    "close": candle.close,
                    "base_volume": candle.base_volume,
                    "quote_volume": candle.quote_volume,
                    "trade_count": candle.trade_count,
                    "provider_closed": candle.provider_complete,
                    "status": "VALID",
                    "source_payload_hash": envelope.source_payload_hash,
                    "ingested_at": context.ingested_at,
                    "run_id": context.run_id,
                },
            )
            candle_ids.append(candle_id)

        rows = connection.execute(
            select(
                CanonicalCandleRecord.candle_id,
                CanonicalCandleRecord.open_time,
                CanonicalCandleRecord.close,
            )
            .where(
                CanonicalCandleRecord.asset_id == context.asset_id,
                CanonicalCandleRecord.mapping_id == context.mapping_id,
                CanonicalCandleRecord.timeframe == first.candle.timeframe.value,
                CanonicalCandleRecord.normalizer_version == context.normalizer_version,
                CanonicalCandleRecord.status == "VALID",
            )
            .order_by(CanonicalCandleRecord.open_time)
        ).all()
        points = tuple(PricePoint(row.open_time, row.close) for row in rows)
        emas = compute_standard_emas(points, timeframe=first.candle.timeframe)
        inserted_indicators = 0
        for index, row in enumerate(rows):
            ema20 = emas[20][index]
            ema50 = emas[50][index]
            ema200 = emas[200][index]
            inserted_indicators += indicator_repository.put(
                connection,
                {
                    "series_version": context.series_version,
                    "universe_version": context.universe_version,
                    "formula_version": context.formula_version,
                    "normalizer_version": context.normalizer_version,
                    "asset_id": context.asset_id,
                    "mapping_id": context.mapping_id,
                    "timeframe": first.candle.timeframe.value,
                    "candle_time": row.open_time,
                    "candle_id": row.candle_id,
                    "close": row.close,
                    "ema20": ema20.value,
                    "ema50": ema50.value,
                    "ema200": ema200.value,
                    "ema20_state": ema20.status.value,
                    "ema50_state": ema50.status.value,
                    "ema200_state": ema200.status.value,
                    "consecutive_count": ema200.observation_count,
                    "computed_at": context.computed_at,
                    "run_id": context.run_id,
                },
            )

    latest_index = len(rows) - 1
    return GateVerticalResult(
        candle_ids=tuple(candle_ids),
        inserted_indicators=inserted_indicators,
        latest_close=rows[-1].close,
        latest_ema20=emas[20][latest_index].value,
        latest_ema50=emas[50][latest_index].value,
        latest_ema200=emas[200][latest_index].value,
    )
