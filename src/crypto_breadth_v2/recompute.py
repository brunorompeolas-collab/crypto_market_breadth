"""Explicit historical repair and versioned deterministic recomputation.

Normal canonical and analytical rows remain immutable.  A repair records an
overlay in ``canonical_candle_repairs`` and writes replacement indicators and
snapshots to ``recompute_outputs`` under a RECOMPUTE run.  This preserves the
accepted candidate series until an independently reviewed promotion decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from .breadth import MemberSignals, calculate_breadth
from .cohort import FrozenCohort
from .contracts import ContractBundle
from .domain import PricePoint, ScannerState, scanner_state
from .ema import compute_standard_emas
from .incremental import CandidateShadowService
from .providers.gate import GATE_SOURCE_ID, GateClient, load_gate_mappings
from .quality import QualityLabel, calculate_data_quality
from .storage.database import transaction
from .storage.models import (
    AssetIndicator,
    BreadthSnapshot,
    CanonicalCandleRecord,
    CanonicalCandleRepair,
    IngestionRun,
    RecomputeOutput,
    TimeframeCohort,
)
from .timeframes import Timeframe, duration, is_open_boundary, require_utc


UTC = timezone.utc
RECOMPUTE_CODE_SHA = "recompute-slice6-v2"


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _json_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(value) for key, value in row.items() if str(key) != "candle_id"}


@dataclass(frozen=True)
class RecomputeReport:
    run_id: UUID
    asset_id: UUID
    timeframe: str
    from_boundary: datetime
    repaired: bool
    affected_indicator_count: int
    rebuilt_snapshot_count: int
    status: str


class HistoricalRecomputeService:
    """Create an auditable recompute result without mutating normal series rows."""

    def __init__(self, engine, bundle: ContractBundle, *, as_of: datetime) -> None:
        require_utc(as_of)
        self.engine = engine
        self.bundle = bundle
        self.as_of = as_of
        self.shadow = CandidateShadowService(
            engine, GateClient(load_gate_mappings(bundle)), bundle, as_of=as_of
        )

    def _snapshot_filter(self, timeframe: Timeframe):
        return (
            BreadthSnapshot.series_version == self.shadow.series_version,
            BreadthSnapshot.universe_version == self.shadow.universe_version,
            BreadthSnapshot.source_policy_version == self.shadow.source_policy_version,
            BreadthSnapshot.formula_version == self.shadow.formula_version,
            BreadthSnapshot.normalizer_version == self.shadow.normalizer_version,
            BreadthSnapshot.timeframe == timeframe.value,
        )

    def _effective_rows(self, rows: list[Mapping[str, Any]], target_open: datetime, replacement: Mapping[str, Any]) -> list[dict[str, Any]]:
        result = [dict(row) for row in rows]
        for row in result:
            if row["open_time"] == target_open:
                for key in ("open", "high", "low", "close", "base_volume", "quote_volume", "trade_count", "provider_closed", "close_time"):
                    if key in replacement:
                        row[key] = replacement[key]
        return result

    def _indicator_payload(self, row: Mapping[str, Any], emas: Mapping[int, Any], index: int) -> dict[str, Any]:
        return {
            "candle_id": str(row["candle_id"]),
            "close": _json_value(row["close"]),
            "ema20": _json_value(emas[20][index].value),
            "ema50": _json_value(emas[50][index].value),
            "ema200": _json_value(emas[200][index].value),
            "ema20_state": emas[20][index].status.value,
            "ema50_state": emas[50][index].status.value,
            "ema200_state": emas[200][index].status.value,
            "consecutive_count": emas[200][index].observation_count,
        }

    def repair_and_recompute(
        self,
        *,
        asset_id: UUID,
        timeframe: Timeframe | str,
        from_boundary: datetime,
        mapping_id: UUID,
        replacement: Mapping[str, Any],
        reason: str,
    ) -> RecomputeReport:
        timeframe = Timeframe(timeframe)
        require_utc(from_boundary)
        if not is_open_boundary(from_boundary, timeframe):
            raise ValueError("from_boundary must be an exact UTC candle boundary")
        replacement_hash = str(replacement.get("source_payload_hash", ""))
        if len(replacement_hash) != 64:
            raise ValueError("replacement must contain a 64-character source_payload_hash")
        run_id = uuid4()
        repaired = False
        affected_count = 0
        snapshot_count = 0
        with transaction(self.engine) as connection:
            connection.execute(insert(IngestionRun).values(
                run_id=run_id, run_type="RECOMPUTE", series_version=self.shadow.series_version,
                source_id=GATE_SOURCE_ID, timeframe=timeframe.value, target_start=from_boundary,
                target_end=self.as_of, started_at=datetime.now(UTC), status="RUNNING", attempt=1,
                expected_count=0, received_count=0, valid_count=0, quarantined_count=0,
                code_sha=RECOMPUTE_CODE_SHA, config_hash=self.bundle.hashes["series"],
                metrics={"action": "repair_and_recompute", "reason": reason},
            ))
            target = connection.execute(select(CanonicalCandleRecord).where(
                CanonicalCandleRecord.asset_id == asset_id,
                CanonicalCandleRecord.mapping_id == mapping_id,
                CanonicalCandleRecord.timeframe == timeframe.value,
                CanonicalCandleRecord.open_time == from_boundary,
                CanonicalCandleRecord.normalizer_version == self.shadow.normalizer_version,
            )).mappings().one_or_none()
            if target is None:
                raise ValueError("repair target canonical candle does not exist")
            if target["source_payload_hash"] != replacement_hash:
                connection.execute(insert(CanonicalCandleRepair).values(
                    repair_id=uuid4(), run_id=run_id, candle_id=target["candle_id"],
                    previous_payload_hash=target["source_payload_hash"], replacement_payload_hash=replacement_hash,
                    reason=reason, original_values=_json_row(target),
                    replacement_values={key: _json_value(value) for key, value in replacement.items()},
                    repaired_at=self.as_of,
                ))
                repaired = True

            rows = list(connection.execute(select(CanonicalCandleRecord).where(
                CanonicalCandleRecord.asset_id == asset_id,
                CanonicalCandleRecord.mapping_id == mapping_id,
                CanonicalCandleRecord.timeframe == timeframe.value,
                CanonicalCandleRecord.normalizer_version == self.shadow.normalizer_version,
                CanonicalCandleRecord.status == "VALID",
            ).order_by(CanonicalCandleRecord.open_time)).mappings())
            effective = self._effective_rows(rows, from_boundary, replacement)
            points = tuple(PricePoint(row["open_time"], row["close"]) for row in effective)
            emas = compute_standard_emas(points, timeframe=timeframe)
            for index, row in enumerate(effective):
                if row["open_time"] < from_boundary:
                    continue
                connection.execute(insert(RecomputeOutput).values(
                    output_id=uuid4(), run_id=run_id, output_type="INDICATOR",
                    series_version=self.shadow.series_version, asset_id=asset_id,
                    timeframe=timeframe.value, candle_time=row["open_time"],
                    base_snapshot_id=None, payload=self._indicator_payload(row, emas, index),
                    created_at=self.as_of,
                ))
                affected_count += 1

            cohort_rows = list(connection.execute(select(TimeframeCohort).where(
                TimeframeCohort.series_version == self.shadow.series_version,
                TimeframeCohort.timeframe == timeframe.value,
            )).mappings())
            included_ids = tuple(
                next(member["id"] for member in self.shadow.members if self.shadow.asset_uuid[member["id"]] == row["asset_id"])
                for row in cohort_rows if row["included_in_denominator"]
            )
            existing_snapshots = list(connection.execute(select(BreadthSnapshot).where(
                *self._snapshot_filter(timeframe),
                BreadthSnapshot.candle_time >= from_boundary + duration(timeframe),
            ).order_by(BreadthSnapshot.candle_time)).mappings())
            for snapshot in existing_snapshots:
                target_open = snapshot["candle_time"] - duration(timeframe)
                indicator_rows = {
                    row["asset_id"]: row for row in connection.execute(select(AssetIndicator).where(
                        AssetIndicator.series_version == self.shadow.series_version,
                        AssetIndicator.timeframe == timeframe.value,
                        AssetIndicator.candle_time == target_open,
                    )).mappings()
                }
                replacement_index = next((index for index, row in enumerate(effective) if row["open_time"] == target_open), None)
                if replacement_index is not None:
                    indicator_rows[asset_id] = {
                        "asset_id": asset_id, "close": effective[replacement_index]["close"],
                        "ema20": emas[20][replacement_index].value, "ema50": emas[50][replacement_index].value,
                        "ema200": emas[200][replacement_index].value,
                    }
                signals = {}
                scanner_payload = []
                for member in self.shadow.members:
                    member_id = self.shadow.asset_uuid[member["id"]]
                    indicator = indicator_rows.get(member_id)
                    states = tuple(scanner_state(indicator["close"], indicator[key]) if indicator else ScannerState.UNAVAILABLE for key in ("ema20", "ema50", "ema200"))
                    signals[member["id"]] = MemberSignals(*states)
                    scanner_payload.append({"asset_id": member["id"], "symbol": member["symbol"], "state20": states[0].value, "state50": states[1].value, "state200": states[2].value, "included_in_breadth": member["id"] in included_ids})
                breadth = calculate_breadth(FrozenCohort.create(universe_size=len(self.shadow.members), asset_ids=included_ids), {key: signals[key] for key in included_ids})
                valid_counts = {period: sum(1 for key in included_ids if signals[key].for_period(period) is not ScannerState.UNAVAILABLE) for period in (20, 50, 200)}
                quality = calculate_data_quality(universe_size=len(self.shadow.members), cohort_size=len(included_ids), valid_ema20=valid_counts[20], valid_ema50=valid_counts[50], valid_ema200=valid_counts[200], fresh=True, aligned=True, last_known_good_exists=True)
                payload = {
                    "base_snapshot_id": str(snapshot["snapshot_id"]),
                    "status": "PUBLISHED" if quality.publishable else "REJECTED",
                    "breadth_score": _json_value(breadth.score),
                    "pct_above_ema20": _json_value((breadth.percentages or {}).get(20)),
                    "pct_above_ema50": _json_value((breadth.percentages or {}).get(50)),
                    "pct_above_ema200": _json_value((breadth.percentages or {}).get(200)),
                    "data_quality_score": _json_value(quality.score),
                    "data_quality_label": quality.label.value,
                    "scanner": scanner_payload,
                }
                connection.execute(insert(RecomputeOutput).values(
                    output_id=uuid4(), run_id=run_id, output_type="SNAPSHOT",
                    series_version=self.shadow.series_version, asset_id=None,
                    timeframe=timeframe.value, candle_time=snapshot["candle_time"],
                    base_snapshot_id=snapshot["snapshot_id"], payload=payload, created_at=self.as_of,
                ))
                snapshot_count += 1
            connection.execute(update(IngestionRun).where(IngestionRun.run_id == run_id).values(
                status="SUCCEEDED", finished_at=datetime.now(UTC), expected_count=1,
                received_count=1, valid_count=1,
                metrics={"action": "repair_and_recompute", "repaired": repaired, "affected_indicator_count": affected_count, "rebuilt_snapshot_count": snapshot_count},
            ))
        return RecomputeReport(run_id, asset_id, timeframe.value, from_boundary, repaired, affected_count, snapshot_count, "SUCCEEDED")
