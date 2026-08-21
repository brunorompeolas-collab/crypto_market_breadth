"""Gate-only incremental compute and candidate shadow publication.

This module deliberately stops at the candidate series.  It has no Streamlit,
activation, or provider-fallback behavior.  PostgreSQL is the only state
authority; a run is resumable because canonical candles and indicators are
immutable and keyed by their versioned identity.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import argparse
import json
import time
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4, uuid5

from sqlalchemy import Engine, func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from .breadth import MemberSignals, calculate_breadth
from .candles import CanonicalCandle
from .cohort import FrozenCohort
from .cohorts import derive_weekly_series
from .contracts import ContractBundle, load_contract_bundle
from .domain import Availability, PricePoint, ScannerState, scanner_state
from .ema import compute_standard_emas
from .providers.gate import (
    GATE_SOURCE_ID,
    GateCandleEnvelope,
    GateClient,
    GateError,
    load_gate_mappings,
)
from .quality import QualityLabel, calculate_data_quality
from .storage.database import transaction
from .storage.models import (
    AssetIndicator,
    BreadthSnapshot,
    CanonicalCandleRecord,
    IngestionError,
    IngestionRun,
    ScannerStateRecord,
    SnapshotMember,
    TimeframeCohort,
)
from .storage.repositories import (
    AssetIndicatorRepository,
    CanonicalCandleConflictError,
)
from .timeframes import Timeframe, duration, expected_latest_close, require_utc


UTC = timezone.utc
INCREMENTAL_CODE_SHA = sha256(b"crypto_breadth_v2.incremental.slice5.v1").hexdigest()
NAMESPACE = UUID("7f0d6db9-0d35-4c9f-9d2a-5f4b2bcb4d21")
CANDIDATE_COHORT_SIZES = {"4h": 40, "1d": 40, "1w": 35}


def stable_uuid(kind: str, value: str) -> UUID:
    return uuid5(NAMESPACE, f"{kind}:{value}")


@dataclass(frozen=True)
class ShadowRunReport:
    run_id: UUID
    timeframe: str
    boundary: datetime
    target_open: datetime
    status: str
    fetched: int
    inserted: int
    replayed: int
    quarantined: int
    missing_before: int
    gap_recovered: bool
    snapshot_id: UUID | None
    publication_status: str | None
    rejection_reason: str | None
    last_known_good_snapshot_id: UUID | None
    request_stats: Mapping[str, int]
    errors: tuple[str, ...]
    duration_seconds: float

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["run_id"] = str(self.run_id)
        result["boundary"] = self.boundary.isoformat()
        result["target_open"] = self.target_open.isoformat()
        result["request_stats"] = dict(self.request_stats)
        for key in ("snapshot_id", "last_known_good_snapshot_id"):
            if result[key] is not None:
                result[key] = str(result[key])
        return result


class ShadowRunError(RuntimeError):
    pass


class CandidateShadowService:
    """Run one closed boundary for one native/derived timeframe."""

    def __init__(
        self,
        engine: Engine,
        client: GateClient,
        bundle: ContractBundle,
        *,
        as_of: datetime,
        max_recovery_periods: int = 1000,
    ) -> None:
        require_utc(as_of)
        self.engine = engine
        self.client = client
        self.bundle = bundle
        self.as_of = as_of
        self.max_recovery_periods = max_recovery_periods
        universe = bundle.definition("universe")
        self.series_version = bundle.definition("series")["series_version"]
        self.universe_version = universe["version"]
        self.source_policy_version = bundle.definition("source_policy")["version"]
        self.formula_version = bundle.definition("formula")["version"]
        self.normalizer_version = bundle.definition("normalizer")["version"]
        self.methodology_version = bundle.definition("methodology")["version"]
        self.members = tuple(universe["members"])
        self.asset_uuid = {row["id"]: stable_uuid("asset", row["id"]) for row in self.members}
        self.mapping = load_gate_mappings(bundle)
        self.mapping_uuid = {symbol: stable_uuid("mapping", symbol) for symbol in self.mapping}
        # The bootstrap source version identity is frozen in the Gate adapter.
        from .bootstrap import GATE_API_SCHEMA_HASH
        self.source_version_id = stable_uuid("source-version", GATE_API_SCHEMA_HASH)

    def _run(self, timeframe: Timeframe, boundary: datetime) -> UUID:
        run_id = uuid4()
        with transaction(self.engine) as connection:
            connection.execute(
                insert(IngestionRun).values(
                    run_id=run_id,
                    run_type="INCREMENTAL",
                    series_version=self.series_version,
                    source_id=GATE_SOURCE_ID,
                    timeframe=timeframe.value,
                    target_start=boundary - duration(timeframe),
                    target_end=boundary,
                    started_at=datetime.now(UTC),
                    status="RUNNING",
                    attempt=1,
                    expected_count=len(self.members),
                    received_count=0,
                    valid_count=0,
                    quarantined_count=0,
                    code_sha=INCREMENTAL_CODE_SHA,
                    config_hash=self.bundle.hashes["series"],
                    metrics={"mode": "candidate-shadow", "as_of": self.as_of.isoformat()},
                )
            )
        return run_id

    def _rows(self, connection, symbol: str, timeframe: Timeframe) -> list[Mapping[str, Any]]:
        asset_id = self.asset_uuid[self.mapping[symbol].canonical_id]
        return list(
            connection.execute(
                select(CanonicalCandleRecord)
                .where(
                    CanonicalCandleRecord.asset_id == asset_id,
                    CanonicalCandleRecord.mapping_id == self.mapping_uuid[symbol],
                    CanonicalCandleRecord.timeframe == timeframe.value,
                    CanonicalCandleRecord.normalizer_version == self.normalizer_version,
                    CanonicalCandleRecord.status == "VALID",
                )
                .order_by(CanonicalCandleRecord.open_time)
            ).mappings()
        )

    def _missing_start(self, connection, symbol: str, timeframe: Timeframe, boundary: datetime) -> tuple[datetime, int]:
        rows = self._rows(connection, symbol, timeframe)
        target_open = boundary - duration(timeframe)
        if not rows:
            # An empty candidate series is an initial tail fill, not recovery
            # from a known gap.  It remains incremental because only the
            # currently closed candle is requested.
            return target_open, 0
        opens = {row["open_time"] for row in rows}
        latest = max(opens)
        if latest >= target_open:
            return target_open, 0
        # Recover a bounded trailing gap; never synthesize a missing candle.
        start = latest + duration(timeframe)
        expected = 0
        cursor = start
        while cursor <= target_open and expected < self.max_recovery_periods:
            if cursor not in opens:
                return cursor, expected + 1
            cursor += duration(timeframe)
            expected += 1
        return start, max(1, expected)

    def _candle_values(self, envelope: GateCandleEnvelope, run_id: UUID) -> dict[str, Any]:
        candle = envelope.candle
        symbol = envelope.mapping.symbol
        return {
            "candle_id": uuid4(),
            "asset_id": self.asset_uuid[envelope.mapping.canonical_id],
            "mapping_id": self.mapping_uuid[symbol],
            "source_version_id": self.source_version_id,
            "source_id": GATE_SOURCE_ID,
            "normalizer_version": self.normalizer_version,
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
            "ingested_at": self.as_of,
            "run_id": run_id,
        }

    def _persist_envelopes(self, envelopes: Sequence[GateCandleEnvelope], run_id: UUID) -> tuple[int, int, int, list[str]]:
        inserted = replayed = quarantined = 0
        errors: list[str] = []
        repository = __import__("crypto_breadth_v2.storage.repositories", fromlist=["CanonicalCandleRepository"]).CanonicalCandleRepository()
        with transaction(self.engine) as connection:
            for envelope in envelopes:
                try:
                    before = connection.execute(
                        select(CanonicalCandleRecord.candle_id).where(
                            CanonicalCandleRecord.mapping_id == self.mapping_uuid[envelope.mapping.symbol],
                            CanonicalCandleRecord.timeframe == envelope.candle.timeframe.value,
                            CanonicalCandleRecord.open_time == envelope.candle.open_time,
                            CanonicalCandleRecord.normalizer_version == self.normalizer_version,
                        )
                    ).scalar_one_or_none()
                    repository.put(connection, self._candle_values(envelope, run_id))
                    if before is None:
                        inserted += 1
                    else:
                        replayed += 1
                except CanonicalCandleConflictError as exc:
                    quarantined += 1
                    errors.append(str(exc))
                    connection.execute(
                        insert(IngestionError).values(
                            run_id=run_id,
                            source_id=GATE_SOURCE_ID,
                            mapping_id=self.mapping_uuid[envelope.mapping.symbol],
                            asset_id=self.asset_uuid[envelope.mapping.canonical_id],
                            timeframe=envelope.candle.timeframe.value,
                            candle_time=envelope.candle.open_time,
                            error_code="CANONICAL_CONFLICT",
                            retryable=False,
                            message=str(exc),
                            occurred_at=self.as_of,
                            payload_hash=envelope.source_payload_hash,
                        )
                    )
        return inserted, replayed, quarantined, errors

    def _derive_weekly(self, run_id: UUID, boundary: datetime) -> int:
        inserted = 0
        with transaction(self.engine) as connection:
            repository = __import__("crypto_breadth_v2.storage.repositories", fromlist=["CanonicalCandleRepository"]).CanonicalCandleRepository()
            for symbol in self.mapping:
                daily = self._rows(connection, symbol, Timeframe.DAILY)
                derived = derive_weekly_series(daily, asset_id=self.mapping[symbol].canonical_id, as_of=self.as_of)
                for item in derived:
                    if item.candle.close_time > boundary:
                        continue
                    values = {
                        "candle_id": uuid4(),
                        "asset_id": self.asset_uuid[item.candle.asset_id],
                        "mapping_id": self.mapping_uuid[symbol],
                        "source_version_id": self.source_version_id,
                        "source_id": GATE_SOURCE_ID,
                        "normalizer_version": self.normalizer_version,
                        "timeframe": Timeframe.WEEKLY.value,
                        "open_time": item.candle.open_time,
                        "close_time": item.candle.close_time,
                        "open": item.candle.open,
                        "high": item.candle.high,
                        "low": item.candle.low,
                        "close": item.candle.close,
                        "base_volume": item.candle.base_volume,
                        "quote_volume": item.candle.quote_volume,
                        "trade_count": item.candle.trade_count,
                        "provider_closed": True,
                        "status": "VALID",
                        "source_payload_hash": item.source_payload_hash,
                        "ingested_at": self.as_of,
                        "run_id": run_id,
                    }
                    before = connection.execute(
                        select(CanonicalCandleRecord.candle_id).where(
                            CanonicalCandleRecord.mapping_id == self.mapping_uuid[symbol],
                            CanonicalCandleRecord.timeframe == "1w",
                            CanonicalCandleRecord.open_time == item.candle.open_time,
                            CanonicalCandleRecord.normalizer_version == self.normalizer_version,
                        )
                    ).scalar_one_or_none()
                    repository.put(connection, values)
                    inserted += int(before is None)
        return inserted

    def _compute_indicators(self, connection, timeframe: Timeframe, run_id: UUID) -> None:
        repository = AssetIndicatorRepository()
        computed_at = datetime.now(UTC)
        for symbol in self.mapping:
            rows = self._rows(connection, symbol, timeframe)
            points = tuple(__import__("crypto_breadth_v2.domain", fromlist=["PricePoint"]).PricePoint(row["open_time"], row["close"]) for row in rows)
            emas = compute_standard_emas(points, timeframe=timeframe)
            for index, row in enumerate(rows):
                values = {
                    "series_version": self.series_version,
                    "universe_version": self.universe_version,
                    "formula_version": self.formula_version,
                    "normalizer_version": self.normalizer_version,
                    "asset_id": self.asset_uuid[self.mapping[symbol].canonical_id],
                    "mapping_id": self.mapping_uuid[symbol],
                    "timeframe": timeframe.value,
                    "candle_time": row["open_time"],
                    "candle_id": row["candle_id"],
                    "close": row["close"],
                    "ema20": emas[20][index].value,
                    "ema50": emas[50][index].value,
                    "ema200": emas[200][index].value,
                    "ema20_state": emas[20][index].status.value,
                    "ema50_state": emas[50][index].status.value,
                    "ema200_state": emas[200][index].status.value,
                    "consecutive_count": emas[200][index].observation_count,
                    "computed_at": computed_at,
                    "run_id": run_id,
                }
                repository.put(connection, values)

    def _publication(self, connection, timeframe: Timeframe, boundary: datetime, run_id: UUID, run_status: str, errors: Sequence[str]) -> tuple[UUID | None, str, str | None, UUID | None]:
        target_open = boundary - duration(timeframe)
        cohorts = list(connection.execute(select(TimeframeCohort).where(TimeframeCohort.series_version == self.series_version, TimeframeCohort.timeframe == timeframe.value)).mappings())
        if len(cohorts) != len(self.members):
            raise ShadowRunError(f"frozen cohort is incomplete: {len(cohorts)}/{len(self.members)}")
        indicators = {}
        for row in connection.execute(select(AssetIndicator).where(AssetIndicator.series_version == self.series_version, AssetIndicator.timeframe == timeframe.value, AssetIndicator.candle_time == target_open)).mappings():
            indicators[row["asset_id"]] = row
        by_id = {row["id"]: row for row in self.members}
        signals: dict[str, MemberSignals] = {}
        for cohort in cohorts:
            asset_id = cohort["asset_id"]
            definition = next(member for member in self.members if self.asset_uuid[member["id"]] == asset_id)
            row = indicators.get(asset_id)
            signals[definition["id"]] = MemberSignals(
                scanner_state(row["close"], row["ema20"]) if row else ScannerState.UNAVAILABLE,
                scanner_state(row["close"], row["ema50"]) if row else ScannerState.UNAVAILABLE,
                scanner_state(row["close"], row["ema200"]) if row else ScannerState.UNAVAILABLE,
            )
        included_ids = tuple(next(member for member in self.members if self.asset_uuid[member["id"]] == row["asset_id"])["id"] for row in cohorts if row["included_in_denominator"])
        expected_cohort = CANDIDATE_COHORT_SIZES[timeframe.value]
        if len(included_ids) != expected_cohort:
            raise ShadowRunError(f"frozen {timeframe.value} cohort is {len(included_ids)}; expected {expected_cohort}")
        breadth = calculate_breadth(FrozenCohort.create(universe_size=len(self.members), asset_ids=included_ids), {key: signals[key] for key in included_ids})
        btc_id = self.asset_uuid[next(member["id"] for member in self.members if member["symbol"] == "BTC")]
        eth_id = self.asset_uuid[next(member["id"] for member in self.members if member["symbol"] == "ETH")]
        aligned = all(indicators.get(asset_id, {}).get("candle_time") == target_open for asset_id in (btc_id, eth_id))
        valid_counts = {period: sum(1 for asset_id in included_ids if signals[asset_id].for_period(period) is not ScannerState.UNAVAILABLE) for period in (20, 50, 200)}
        lkg = connection.execute(select(BreadthSnapshot.snapshot_id).where(BreadthSnapshot.series_version == self.series_version, BreadthSnapshot.timeframe == timeframe.value, BreadthSnapshot.status == "PUBLISHED").order_by(BreadthSnapshot.candle_time.desc()).limit(1)).scalar_one_or_none()
        quality = calculate_data_quality(universe_size=len(self.members), cohort_size=len(included_ids), valid_ema20=valid_counts[20], valid_ema50=valid_counts[50], valid_ema200=valid_counts[200], fresh=not errors and all(indicators.get(self.asset_uuid[member["id"]], {}).get("candle_time") == target_open for member in self.members if self.asset_uuid[member["id"]] in {self.asset_uuid[i] for i in included_ids}), aligned=aligned, last_known_good_exists=lkg is not None)
        publication_status = "PUBLISHED" if quality.publishable and run_status == "SUCCEEDED" else ("UNAVAILABLE" if run_status == "FAILED" else "REJECTED")
        reason = None if publication_status == "PUBLISHED" else ";".join(errors) or ("BTC_ETH_MISALIGNED" if not aligned else ",".join(breadth.unavailable_assets) or "COMPONENT_COVERAGE_BELOW_100")
        lock_key = int.from_bytes(sha256(f"{self.series_version}:{timeframe.value}:{boundary.isoformat()}".encode()).digest()[:8], "big") % (2**63 - 1)
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        existing = connection.execute(select(BreadthSnapshot.snapshot_id, BreadthSnapshot.status).where(BreadthSnapshot.series_version == self.series_version, BreadthSnapshot.timeframe == timeframe.value, BreadthSnapshot.candle_time == boundary)).first()
        if existing:
            return existing[0], existing[1], "DUPLICATE_REPLAY", lkg
        snapshot_id = uuid4()
        values = {
            "snapshot_id": snapshot_id, "series_version": self.series_version, "series_kind": "LIVE", "universe_version": self.universe_version, "source_policy_version": self.source_policy_version,
            "formula_version": self.formula_version, "normalizer_version": self.normalizer_version, "timeframe": timeframe.value, "candle_time": boundary,
            "pct_above_ema20": breadth.percentages[20] if publication_status == "PUBLISHED" else None, "pct_above_ema50": breadth.percentages[50] if publication_status == "PUBLISHED" else None, "pct_above_ema200": breadth.percentages[200] if publication_status == "PUBLISHED" else None, "breadth_score": breadth.score if publication_status == "PUBLISHED" else None,
            "numerator20": breadth.numerators[20] if publication_status == "PUBLISHED" else None, "numerator50": breadth.numerators[50] if publication_status == "PUBLISHED" else None, "numerator200": breadth.numerators[200] if publication_status == "PUBLISHED" else None,
            "universe_size": len(self.members), "cohort_size": len(included_ids), "structural_coverage": quality.structural_coverage, "component_coverage": quality.component_coverage,
            "data_quality_score": quality.score, "data_quality_label": {QualityLabel.HIGH: "HIGH", QualityLabel.ACCEPTABLE: "MEDIUM", QualityLabel.DEGRADED: "LOW", QualityLabel.UNAVAILABLE: "UNAVAILABLE"}[quality.label],
            "btc_close": indicators.get(btc_id, {}).get("close") if publication_status == "PUBLISHED" else None, "eth_close": indicators.get(eth_id, {}).get("close") if publication_status == "PUBLISHED" else None,
            "status": publication_status, "rejection_reason": reason, "computed_at": datetime.now(UTC), "run_id": run_id,
        }
        connection.execute(insert(BreadthSnapshot).values(**values))
        member_values = []
        scanner_values = []
        for cohort in cohorts:
            asset_id = cohort["asset_id"]
            definition = next(member for member in self.members if self.asset_uuid[member["id"]] == asset_id)
            row = indicators.get(asset_id)
            states = tuple(scanner_state(row["close"], row[key]) if row else ScannerState.UNAVAILABLE for key in ("ema20", "ema50", "ema200"))
            included = bool(cohort["included_in_denominator"])
            member_values.append({"snapshot_id": snapshot_id, "asset_id": asset_id, "mapping_id": self.mapping_uuid[definition["symbol"]], "source_id": GATE_SOURCE_ID, "close": row["close"] if row else None, "ema20": row["ema20"] if row else None, "ema50": row["ema50"] if row else None, "ema200": row["ema200"] if row else None, "above20": None if states[0] is ScannerState.UNAVAILABLE else states[0] is ScannerState.ABOVE, "above50": None if states[1] is ScannerState.UNAVAILABLE else states[1] is ScannerState.ABOVE, "above200": None if states[2] is ScannerState.UNAVAILABLE else states[2] is ScannerState.ABOVE, "state20": states[0].value, "state50": states[1].value, "state200": states[2].value, "included_in_denominator": included, "exclusion_reason": None if included else "FROZEN_COHORT_EXCLUDED"})
            scanner_values.append({"series_version": self.series_version, "timeframe": timeframe.value, "asset_id": asset_id, "candle_time": target_open, "price": row["close"] if row else None, "ema20": row["ema20"] if row else None, "ema50": row["ema50"] if row else None, "ema200": row["ema200"] if row else None, "state20": states[0].value, "state50": states[1].value, "state200": states[2].value, "included_in_breadth": included, "mapping_id": self.mapping_uuid[definition["symbol"]], "source_id": GATE_SOURCE_ID, "snapshot_id": snapshot_id, "updated_at": datetime.now(UTC)})
        connection.execute(insert(SnapshotMember), member_values)
        for row in scanner_values:
            statement = insert(ScannerStateRecord).values(**row)
            connection.execute(statement.on_conflict_do_update(index_elements=["series_version", "timeframe", "asset_id"], set_={key: getattr(statement.excluded, key) for key in ("candle_time", "price", "ema20", "ema50", "ema200", "state20", "state50", "state200", "included_in_breadth", "mapping_id", "source_id", "snapshot_id", "updated_at")}))
        return snapshot_id, publication_status, reason, lkg

    def run(self, timeframe: Timeframe | str) -> ShadowRunReport:
        timeframe = Timeframe(timeframe)
        boundary = expected_latest_close(self.as_of, timeframe)
        target_open = boundary - duration(timeframe)
        started = time.monotonic()
        run_id = self._run(timeframe, boundary)
        fetched = inserted = replayed = quarantined = missing_before = 0
        errors: list[str] = []
        try:
            if timeframe is Timeframe.WEEKLY:
                self._derive_weekly(run_id, boundary)
            else:
                for symbol in self.mapping:
                    with self.engine.connect() as connection:
                        start, missing = self._missing_start(connection, symbol, timeframe, boundary)
                    missing_before += missing
                    if start > target_open:
                        continue
                    envelopes = self.client.fetch_range(symbol, timeframe=timeframe, start=start, end=boundary, as_of=self.as_of, allow_empty_pages=False)
                    fetched += len(envelopes)
                    values = self._persist_envelopes(envelopes, run_id)
                    inserted += values[0]; replayed += values[1]; quarantined += values[2]; errors.extend(values[3])
                if timeframe is Timeframe.DAILY:
                    self._derive_weekly(run_id, boundary)
            with transaction(self.engine) as connection:
                self._compute_indicators(connection, timeframe, run_id)
                snapshot_id, publication_status, reason, lkg = self._publication(connection, timeframe, boundary, run_id, "SUCCEEDED", errors)
                connection.execute(update(IngestionRun).where(IngestionRun.run_id == run_id).values(status="SUCCEEDED", finished_at=datetime.now(UTC), received_count=fetched, valid_count=inserted + replayed, quarantined_count=quarantined, metrics={"missing_before": missing_before, "gap_recovered": missing_before > 0, "publication_status": publication_status}))
            return ShadowRunReport(run_id, timeframe.value, boundary, target_open, "SUCCEEDED", fetched, inserted, replayed, quarantined, missing_before, missing_before > 0, snapshot_id, publication_status, reason, lkg, self.client.stats.snapshot(), tuple(errors), time.monotonic() - started)
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            snapshot_id = None
            publication_status = "UNAVAILABLE"
            rejection_reason = str(exc)
            lkg = None
            with transaction(self.engine) as connection:
                try:
                    snapshot_id, publication_status, rejection_reason, lkg = self._publication(
                        connection, timeframe, boundary, run_id, "FAILED", errors
                    )
                except Exception:
                    # A malformed/partial database state must not hide the
                    # original provider failure or prevent run finalization.
                    pass
                connection.execute(update(IngestionRun).where(IngestionRun.run_id == run_id).values(status="FAILED", finished_at=datetime.now(UTC), received_count=fetched, valid_count=inserted + replayed, quarantined_count=quarantined, error_summary=str(exc), metrics={"missing_before": missing_before}))
            return ShadowRunReport(run_id, timeframe.value, boundary, target_open, "FAILED", fetched, inserted, replayed, quarantined, missing_before, missing_before > 0, snapshot_id, publication_status, rejection_reason, lkg, self.client.stats.snapshot(), tuple(errors), time.monotonic() - started)


def run_shadow_once(database_url: str, *, timeframe: Timeframe, as_of: datetime, contracts_root: str = "config/v2") -> ShadowRunReport:
    from .storage.database import create_postgres_engine
    engine = create_postgres_engine(database_url)
    bundle = load_contract_bundle(__import__("pathlib").Path(contracts_root), bundle="v2-40")
    mappings = load_gate_mappings(bundle)
    return CandidateShadowService(engine, GateClient(mappings), bundle, as_of=as_of).run(timeframe)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Gate candidate shadow boundary")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--timeframe", choices=[item.value for item in Timeframe], required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--contracts-root", default="config/v2")
    args = parser.parse_args(argv)
    report = run_shadow_once(args.database_url, timeframe=Timeframe(args.timeframe), as_of=datetime.fromisoformat(args.as_of.replace("Z", "+00:00")), contracts_root=args.contracts_root)
    print(json.dumps(report.as_dict(), sort_keys=True))
    return 0 if report.status == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
