"""Bounded, resumable Gate bootstrap and candidate cohort determination."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4, uuid5

from sqlalchemy import Engine, select, update
from sqlalchemy.dialects.postgresql import insert

from .candles import CanonicalCandle
from .cohorts import (
    CohortReport,
    CoverageDiagnostics,
    MINIMUM_WEEKLY_COVERAGE,
    diagnose_candles,
    derive_weekly_series,
    persist_candidate_cohorts,
)
from .contracts import ContractBundle, load_contract_bundle
from .domain import PricePoint
from .ema import compute_standard_emas
from .providers.gate import (
    GATE_MAX_CANDLES,
    GATE_SOURCE_ID,
    GateCandleEnvelope,
    GateClient,
    GateError,
    GateMapping,
    GateRequestStats,
    load_gate_mappings,
)
from .storage.database import create_postgres_engine, transaction
from .storage.models import (
    Asset,
    AssetIndicator,
    CanonicalCandleRecord,
    DataSource,
    IngestionError,
    IngestionRun,
    ProviderMapping,
    SeriesDefinition,
    SourcePolicyMapping,
    SourcePolicyVersion,
    SourceVersion,
    TimeframeCohort,
    UniverseMembership,
    UniverseVersion,
)
from .storage.repositories import AssetIndicatorRepository, CanonicalCandleConflictError, CanonicalCandleRepository
from .timeframes import Timeframe, duration, expected_latest_close, require_utc


UTC = timezone.utc
BOOTSTRAP_NAMESPACE = UUID("7f0d6db9-0d35-4c9f-9d2a-5f4b2bcb4d21")
GATE_API_CONTRACT_DATE = datetime(2026, 8, 21, tzinfo=UTC)
GATE_ADAPTER_VERSION = "gate-adapter-v1"
GATE_API_SCHEMA_HASH = sha256(
    b"gate.spot.currency_pairs.v4|gate.spot.candlesticks.v4|8-string-candle-row"
).hexdigest()
BOOTSTRAP_CODE_SHA = sha256(b"crypto_breadth_v2.bootstrap.slice4.v1").hexdigest()
FOUR_HOUR_HISTORY = 1000
DAILY_HISTORY = 1500


class BootstrapContractMismatch(RuntimeError):
    pass


class BootstrapCoverageError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssetRunResult:
    symbol: str
    asset_id: str
    timeframe: Timeframe
    run_id: UUID
    status: str
    received: int
    valid: int
    quarantined: int
    diagnostics: CoverageDiagnostics
    metrics: Mapping[str, Any]


@dataclass(frozen=True)
class BootstrapReport:
    as_of: datetime
    candidate_boundary: Mapping[str, datetime]
    universe_version: str
    series_version: str
    candidate_status: str
    inception_at: None
    runs: tuple[AssetRunResult, ...]
    cohorts: tuple[CohortReport, ...]
    failures: tuple[Mapping[str, Any], ...]
    request_stats: Mapping[str, int]
    duration_seconds: float
    success: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of.isoformat(),
            "candidate_boundary": {key: value.isoformat() for key, value in self.candidate_boundary.items()},
            "universe_version": self.universe_version,
            "series_version": self.series_version,
            "candidate_status": self.candidate_status,
            "inception_at": None,
            "success": self.success,
            "duration_seconds": self.duration_seconds,
            "request_stats": dict(self.request_stats),
            "failures": list(self.failures),
            "runs": [
                {
                    "symbol": run.symbol,
                    "asset_id": run.asset_id,
                    "timeframe": run.timeframe.value,
                    "run_id": str(run.run_id),
                    "status": run.status,
                    "received": run.received,
                    "valid": run.valid,
                    "quarantined": run.quarantined,
                    "diagnostics": run.diagnostics.as_dict(),
                    "metrics": dict(run.metrics),
                }
                for run in self.runs
            ],
            "cohorts": [cohort.as_dict() for cohort in self.cohorts],
        }


def _stable_uuid(kind: str, value: str) -> UUID:
    return uuid5(BOOTSTRAP_NAMESPACE, f"{kind}:{value}")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


class GateBootstrapService:
    """Run a bounded Gate bootstrap; rerunning the same boundary is safe."""

    def __init__(
        self,
        engine: Engine,
        client: GateClient,
        bundle: ContractBundle,
        *,
        as_of: datetime,
        four_hour_history: int = FOUR_HOUR_HISTORY,
        daily_history: int = DAILY_HISTORY,
    ) -> None:
        require_utc(as_of)
        if not 1 <= four_hour_history <= GATE_MAX_CANDLES:
            raise ValueError("four_hour_history must be between 1 and Gate's page limit")
        if daily_history < 1400:
            raise ValueError("daily_history must cover at least 200 Monday-to-Monday weeks")
        self.engine = engine
        self.client = client
        self.bundle = bundle
        self.as_of = as_of
        self.four_hour_history = four_hour_history
        self.daily_history = daily_history
        self.mappings = load_gate_mappings(bundle)
        universe = bundle.definition("universe")
        self.universe_version = universe["version"]
        self.source_policy_version = bundle.definition("source_policy")["version"]
        self.series_version = bundle.definition("series")["series_version"]
        self.normalizer_version = bundle.definition("normalizer")["version"]
        self.formula_version = bundle.definition("formula")["version"]
        self.methodology_version = bundle.definition("methodology")["version"]
        self.asset_uuid_by_id = {
            member["id"]: _stable_uuid("asset", member["id"])
            for member in universe["members"]
        }
        self.mapping_uuid_by_symbol = {
            symbol: _stable_uuid("mapping", symbol)
            for symbol in self.mappings
        }
        self.source_version_id = _stable_uuid("source-version", GATE_API_SCHEMA_HASH)
        self.started_at = datetime.now(UTC)

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(self.mappings)

    def _assert_existing(self, connection, table, values: Mapping[str, Any], keys: Sequence[str]) -> None:
        existing = connection.execute(select(table).filter_by(**{key: values[key] for key in keys})).mappings().one_or_none()
        if existing is None:
            return
        for key, value in values.items():
            if key in {"created_at"}:
                continue
            if existing[key] != value:
                raise BootstrapContractMismatch(
                    f"existing {table.name}.{key} differs for {keys}: {existing[key]!r} != {value!r}"
                )

    def _insert_checked(self, connection, table, values: Mapping[str, Any], keys: Sequence[str]) -> None:
        connection.execute(insert(table).values(**values).on_conflict_do_nothing(index_elements=list(keys)))
        self._assert_existing(connection, table, values, keys)

    def ensure_metadata(self) -> None:
        universe = self.bundle.definition("universe")
        source_policy = self.bundle.definition("source_policy")
        series = self.bundle.definition("series")
        now = self.as_of
        with transaction(self.engine) as connection:
            self._insert_checked(
                connection,
                DataSource.__table__,
                {
                    "source_id": GATE_SOURCE_ID,
                    "provider": "gate",
                    "venue": "gate",
                    "market_type": "SPOT",
                    "api_base_url": "https://api.gateio.ws/api/v4",
                    "terms_url": "https://www.gate.com/docs/agreement.pdf",
                    "terms_review_status": "ACCEPTED",
                    "active": True,
                },
                ["source_id"],
            )
            self._insert_checked(
                connection,
                SourceVersion.__table__,
                {
                    "source_version_id": self.source_version_id,
                    "source_id": GATE_SOURCE_ID,
                    "adapter_version": GATE_ADAPTER_VERSION,
                    "api_contract_date": GATE_API_CONTRACT_DATE,
                    "api_schema_hash": GATE_API_SCHEMA_HASH,
                    "archive_release": "NONE",
                    "effective_from": GATE_API_CONTRACT_DATE,
                },
                ["source_version_id"],
            )
            members_by_symbol = {member["symbol"]: member for member in universe["members"]}
            self._insert_checked(
                connection,
                UniverseVersion.__table__,
                {
                    "universe_version": self.universe_version,
                    "name": "BR1 Breadth Universe v2-40",
                    "series_kind": "LIVE",
                    "status": "DRAFT",
                    "inception_at": None,
                    "expected_size": len(universe["members"]),
                    "definition_hash": self.bundle.hashes["universe"],
                },
                ["universe_version"],
            )
            self._insert_checked(
                connection,
                SourcePolicyVersion.__table__,
                {
                    "source_policy_version": self.source_policy_version,
                    "status": "DRAFT",
                    "definition_hash": self.bundle.hashes["source_policy"],
                    "effective_from": now,
                },
                ["source_policy_version"],
            )
            for symbol, member in members_by_symbol.items():
                asset_id = self.asset_uuid_by_id[member["id"]]
                self._insert_checked(
                    connection,
                    Asset.__table__,
                    {
                        "asset_id": asset_id,
                        "canonical_id": member["id"],
                        "symbol": symbol,
                        "display_name": member["display_name"],
                        "legacy_identity": {"entries": member.get("legacy_identities", [])},
                        "status": "ACTIVE",
                    },
                    ["asset_id"],
                )
                mapping = self.mappings[symbol]
                mapping_id = self.mapping_uuid_by_symbol[symbol]
                self._insert_checked(
                    connection,
                    ProviderMapping.__table__,
                    {
                        "mapping_id": mapping_id,
                        "asset_id": asset_id,
                        "source_id": GATE_SOURCE_ID,
                        "provider_asset_id": mapping.instrument,
                        "base_code": mapping.instrument.removesuffix(f"_{mapping.quote}"),
                        "quote_code": mapping.quote,
                        "instrument_id": mapping.instrument,
                        "mapping_version": self.source_policy_version,
                        "valid_from": now,
                        "status": "ACTIVE",
                    },
                    ["mapping_id"],
                )
                self._insert_checked(
                    connection,
                    UniverseMembership.__table__,
                    {
                        "universe_version": self.universe_version,
                        "asset_id": asset_id,
                        "ordinal": int(next(index for index, row in enumerate(universe["members"], 1) if row["symbol"] == symbol)),
                        "included_from": now,
                    },
                    ["universe_version", "asset_id"],
                )
                self._insert_checked(
                    connection,
                    SourcePolicyMapping.__table__,
                    {
                        "source_policy_version": self.source_policy_version,
                        "asset_id": asset_id,
                        "mapping_id": mapping_id,
                    },
                    ["source_policy_version", "asset_id"],
                )
            self._insert_checked(
                connection,
                SeriesDefinition.__table__,
                {
                    "series_version": self.series_version,
                    "series_kind": "LIVE",
                    "universe_version": self.universe_version,
                    "source_policy_version": self.source_policy_version,
                    "formula_version": self.formula_version,
                    "normalizer_version": self.normalizer_version,
                    "methodology_version": self.methodology_version,
                    "inception_at": None,
                    "definition_hash": self.bundle.hashes["series"],
                    "status": "CANDIDATE",
                },
                ["series_version"],
            )

    def _target_range(self, timeframe: Timeframe) -> tuple[datetime, datetime]:
        boundary = expected_latest_close(self.as_of, timeframe)
        if timeframe is Timeframe.FOUR_HOUR:
            return boundary - duration(timeframe) * self.four_hour_history, boundary
        if timeframe is Timeframe.DAILY:
            return boundary - timedelta(days=self.daily_history), boundary
        return boundary - duration(timeframe) * (self.daily_history // 7), boundary

    def _start_run(self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> UUID:
        run_id = uuid4()
        expected = ceil((end - start) / duration(timeframe))
        with transaction(self.engine) as connection:
            connection.execute(
                insert(IngestionRun).values(
                    run_id=run_id,
                    run_type="BOOTSTRAP",
                    series_version=self.series_version,
                    source_id=GATE_SOURCE_ID,
                    timeframe=timeframe.value,
                    target_start=start,
                    target_end=end,
                    started_at=datetime.now(UTC),
                    status="RUNNING",
                    attempt=1,
                    expected_count=expected,
                    received_count=0,
                    valid_count=0,
                    quarantined_count=0,
                    code_sha=BOOTSTRAP_CODE_SHA,
                    config_hash=self.bundle.hashes["series"],
                    metrics={"symbol": symbol, "asset_id": self.mappings[symbol].canonical_id},
                )
            )
        return run_id

    def _record_error(self, connection, *, run_id: UUID, symbol: str, timeframe: Timeframe, error: Exception, candle_time: datetime | None = None, payload_hash: str | None = None) -> None:
        connection.execute(
            insert(IngestionError).values(
                run_id=run_id,
                source_id=GATE_SOURCE_ID,
                mapping_id=self.mapping_uuid_by_symbol[symbol],
                asset_id=self.asset_uuid_by_id[self.mappings[symbol].canonical_id],
                timeframe=timeframe.value,
                candle_time=candle_time,
                error_code=type(error).__name__.upper(),
                retryable=isinstance(error, GateError),
                http_status=None,
                message=str(error),
                payload_hash=payload_hash,
                occurred_at=datetime.now(UTC),
            )
        )

    def _rows_for(self, connection, *, symbol: str, timeframe: Timeframe) -> list[Mapping[str, Any]]:
        rows = connection.execute(
            select(CanonicalCandleRecord)
            .where(
                CanonicalCandleRecord.asset_id == self.asset_uuid_by_id[self.mappings[symbol].canonical_id],
                CanonicalCandleRecord.mapping_id == self.mapping_uuid_by_symbol[symbol],
                CanonicalCandleRecord.timeframe == timeframe.value,
                CanonicalCandleRecord.normalizer_version == self.normalizer_version,
                CanonicalCandleRecord.status == "VALID",
            )
            .order_by(CanonicalCandleRecord.open_time)
        ).mappings().all()
        return list(rows)

    def _persist_indicators(self, connection, *, symbol: str, timeframe: Timeframe, run_id: UUID, computed_at: datetime) -> int:
        rows = self._rows_for(connection, symbol=symbol, timeframe=timeframe)
        points = tuple(PricePoint(row["open_time"], row["close"]) for row in rows)
        emas = compute_standard_emas(points, timeframe=timeframe)
        repository = AssetIndicatorRepository()
        inserted = 0
        for index, row in enumerate(rows):
            values = {
                "series_version": self.series_version,
                "universe_version": self.universe_version,
                "formula_version": self.formula_version,
                "normalizer_version": self.normalizer_version,
                "asset_id": self.asset_uuid_by_id[self.mappings[symbol].canonical_id],
                "mapping_id": self.mapping_uuid_by_symbol[symbol],
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
            inserted += int(repository.put(connection, values))
        return inserted

    def _finish_run(self, run_id: UUID, *, status: str, received: int, valid: int, quarantined: int, metrics: Mapping[str, Any], error_summary: str | None = None) -> None:
        with transaction(self.engine) as connection:
            connection.execute(
                update(IngestionRun)
                .where(IngestionRun.run_id == run_id)
                .values(
                    status=status,
                    finished_at=datetime.now(UTC),
                    received_count=received,
                    valid_count=valid,
                    quarantined_count=quarantined,
                    metrics=dict(metrics),
                    error_summary=error_summary,
                )
            )

    def _bootstrap_native(self, symbol: str, timeframe: Timeframe) -> AssetRunResult:
        start, end = self._target_range(timeframe)
        run_id = self._start_run(symbol, timeframe, start, end)
        stats_before = self.client.stats.snapshot()
        received = valid = quarantined = 0
        diagnostics: CoverageDiagnostics | None = None
        metrics: dict[str, Any] = {
            "target_start": start.isoformat(),
            "target_end": end.isoformat(),
            "empty_pages_allowed": True,
        }
        try:
            envelopes = self.client.fetch_range(
                symbol,
                timeframe=timeframe,
                start=start,
                end=end,
                as_of=self.as_of,
                allow_empty_pages=True,
            )
            received = len(envelopes)
            with transaction(self.engine) as connection:
                repository = CanonicalCandleRepository()
                for envelope in envelopes:
                    try:
                        repository.put(
                            connection,
                            {
                                "candle_id": uuid4(),
                                "asset_id": self.asset_uuid_by_id[envelope.mapping.canonical_id],
                                "mapping_id": self.mapping_uuid_by_symbol[symbol],
                                "source_version_id": self.source_version_id,
                                "source_id": GATE_SOURCE_ID,
                                "normalizer_version": self.normalizer_version,
                                "timeframe": timeframe.value,
                                "open_time": envelope.candle.open_time,
                                "close_time": envelope.candle.close_time,
                                "open": envelope.candle.open,
                                "high": envelope.candle.high,
                                "low": envelope.candle.low,
                                "close": envelope.candle.close,
                                "base_volume": envelope.candle.base_volume,
                                "quote_volume": envelope.candle.quote_volume,
                                "trade_count": envelope.candle.trade_count,
                                "provider_closed": envelope.candle.provider_complete,
                                "status": "VALID",
                                "source_payload_hash": envelope.source_payload_hash,
                                "ingested_at": self.as_of,
                                "run_id": run_id,
                            },
                        )
                        valid += 1
                    except CanonicalCandleConflictError as error:
                        quarantined += 1
                        self._record_error(
                            connection,
                            run_id=run_id,
                            symbol=symbol,
                            timeframe=timeframe,
                            error=error,
                            candle_time=envelope.candle.open_time,
                            payload_hash=envelope.source_payload_hash,
                        )
                indicator_count = self._persist_indicators(
                    connection, symbol=symbol, timeframe=timeframe, run_id=run_id, computed_at=self.as_of
                )
                rows = self._rows_for(connection, symbol=symbol, timeframe=timeframe)
                candles = tuple(
                    CanonicalCandle(
                        asset_id=self.mappings[symbol].canonical_id,
                        timeframe=timeframe,
                        open_time=row["open_time"],
                        close_time=row["close_time"],
                        open=row["open"],
                        high=row["high"],
                        low=row["low"],
                        close=row["close"],
                        base_volume=row["base_volume"],
                        quote_volume=row["quote_volume"],
                        trade_count=row["trade_count"],
                        provider_complete=row["provider_closed"],
                    )
                    for row in rows
                )
                diagnostics = diagnose_candles(
                    candles,
                    asset_id=self.mappings[symbol].canonical_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    candidate_boundary=expected_latest_close(self.as_of, timeframe),
                )
            metrics.update({
                "indicator_rows_inserted": indicator_count,
                "coverage": diagnostics.as_dict(),
                "request_stats_delta": {
                    key: self.client.stats.snapshot()[key] - stats_before[key]
                    for key in stats_before
                },
            })
            self._finish_run(
                run_id,
                status="SUCCEEDED",
                received=received,
                valid=valid,
                quarantined=quarantined,
                metrics=metrics,
            )
            return AssetRunResult(symbol, self.mappings[symbol].canonical_id, timeframe, run_id, "SUCCEEDED", received, valid, quarantined, diagnostics, metrics)
        except Exception as error:
            metrics["request_stats_delta"] = {
                key: self.client.stats.snapshot()[key] - stats_before[key]
                for key in stats_before
            }
            with transaction(self.engine) as connection:
                self._record_error(
                    connection,
                    run_id=run_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    error=error,
                )
            self._finish_run(
                run_id,
                status="FAILED",
                received=received,
                valid=valid,
                quarantined=quarantined,
                metrics=metrics,
                error_summary=str(error),
            )
            raise

    def _derive_weekly(self, symbol: str) -> AssetRunResult:
        timeframe = Timeframe.WEEKLY
        start, end = self._target_range(timeframe)
        run_id = self._start_run(symbol, timeframe, start, end)
        received = valid = quarantined = 0
        stats_before = self.client.stats.snapshot()
        metrics: dict[str, Any] = {"derived_from": "canonical_daily", "native_gate_requests": 0}
        try:
            with transaction(self.engine) as connection:
                daily_rows = self._rows_for(connection, symbol=symbol, timeframe=Timeframe.DAILY)
                derived = derive_weekly_series(
                    daily_rows,
                    asset_id=self.mappings[symbol].canonical_id,
                    as_of=self.as_of,
                )
                repository = CanonicalCandleRepository()
                for item in derived:
                    try:
                        repository.put(
                            connection,
                            {
                                "candle_id": uuid4(),
                                "asset_id": self.asset_uuid_by_id[item.candle.asset_id],
                                "mapping_id": self.mapping_uuid_by_symbol[symbol],
                                "source_version_id": self.source_version_id,
                                "source_id": GATE_SOURCE_ID,
                                "normalizer_version": self.normalizer_version,
                                "timeframe": timeframe.value,
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
                            },
                        )
                        valid += 1
                    except CanonicalCandleConflictError as error:
                        quarantined += 1
                        self._record_error(
                            connection,
                            run_id=run_id,
                            symbol=symbol,
                            timeframe=timeframe,
                            error=error,
                            candle_time=item.candle.open_time,
                            payload_hash=item.source_payload_hash,
                        )
                received = len(derived)
                indicator_count = self._persist_indicators(
                    connection, symbol=symbol, timeframe=timeframe, run_id=run_id, computed_at=self.as_of
                )
                rows = self._rows_for(connection, symbol=symbol, timeframe=timeframe)
                candles = tuple(
                    CanonicalCandle(
                        asset_id=self.mappings[symbol].canonical_id,
                        timeframe=timeframe,
                        open_time=row["open_time"],
                        close_time=row["close_time"],
                        open=row["open"], high=row["high"], low=row["low"], close=row["close"],
                        base_volume=row["base_volume"], quote_volume=row["quote_volume"],
                        trade_count=row["trade_count"], provider_complete=row["provider_closed"],
                    )
                    for row in rows
                )
                diagnostics = diagnose_candles(
                    candles,
                    asset_id=self.mappings[symbol].canonical_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    candidate_boundary=expected_latest_close(self.as_of, timeframe),
                )
            metrics.update({"derived_weeks": len(derived), "indicator_rows_inserted": indicator_count, "coverage": diagnostics.as_dict()})
            self._finish_run(run_id, status="SUCCEEDED", received=received, valid=valid, quarantined=quarantined, metrics=metrics)
            return AssetRunResult(symbol, self.mappings[symbol].canonical_id, timeframe, run_id, "SUCCEEDED", received, valid, quarantined, diagnostics, metrics)
        except Exception as error:
            with transaction(self.engine) as connection:
                self._record_error(
                    connection,
                    run_id=run_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    error=error,
                )
            self._finish_run(run_id, status="FAILED", received=received, valid=valid, quarantined=quarantined, metrics=metrics, error_summary=str(error))
            raise

    def run(self) -> BootstrapReport:
        self.ensure_metadata()
        results: list[AssetRunResult] = []
        failures: list[Mapping[str, Any]] = []
        for timeframe in (Timeframe.FOUR_HOUR, Timeframe.DAILY):
            for symbol in self.symbols:
                try:
                    results.append(self._bootstrap_native(symbol, timeframe))
                except Exception as error:
                    failures.append({"symbol": symbol, "timeframe": timeframe.value, "error": type(error).__name__, "message": str(error)})
        for symbol in self.symbols:
            try:
                results.append(self._derive_weekly(symbol))
            except Exception as error:
                failures.append({"symbol": symbol, "timeframe": "1w", "error": type(error).__name__, "message": str(error)})

        reports: list[CohortReport] = []
        with self.engine.connect() as connection:
            for timeframe in (Timeframe.FOUR_HOUR, Timeframe.DAILY, Timeframe.WEEKLY):
                diagnostics_rows: list[CoverageDiagnostics] = []
                for symbol in self.symbols:
                    rows = self._rows_for(connection, symbol=symbol, timeframe=timeframe)
                    candles = tuple(
                        CanonicalCandle(
                            asset_id=self.mappings[symbol].canonical_id,
                            timeframe=timeframe,
                            open_time=row["open_time"],
                            close_time=row["close_time"],
                            open=row["open"], high=row["high"], low=row["low"], close=row["close"],
                            base_volume=row["base_volume"], quote_volume=row["quote_volume"],
                            trade_count=row["trade_count"], provider_complete=row["provider_closed"],
                        )
                        for row in rows
                    )
                    diagnostics_rows.append(
                        diagnose_candles(
                            candles,
                            asset_id=self.mappings[symbol].canonical_id,
                            symbol=symbol,
                            timeframe=timeframe,
                            candidate_boundary=expected_latest_close(self.as_of, timeframe),
                        )
                    )
                reports.append(CohortReport(timeframe, len(self.symbols), tuple(diagnostics_rows)))
        with transaction(self.engine) as connection:
            persist_candidate_cohorts(
                connection,
                series_version=self.series_version,
                frozen_at=self.as_of,
                reports=reports,
                asset_uuid_by_id=self.asset_uuid_by_id,
            )
        weekly = next(report for report in reports if report.timeframe is Timeframe.WEEKLY)
        if not weekly.coverage_passes:
            failures.append({"error": "WEEKLY_COVERAGE_BELOW_THRESHOLD", "eligible": len(weekly.eligible_asset_ids), "required": MINIMUM_WEEKLY_COVERAGE})
        finished_at = datetime.now(UTC)
        return BootstrapReport(
            as_of=self.as_of,
            candidate_boundary={timeframe.value: expected_latest_close(self.as_of, timeframe) for timeframe in (Timeframe.FOUR_HOUR, Timeframe.DAILY, Timeframe.WEEKLY)},
            universe_version=self.universe_version,
            series_version=self.series_version,
            candidate_status="CANDIDATE_NOT_ACTIVATED",
            inception_at=None,
            runs=tuple(results),
            cohorts=tuple(reports),
            failures=tuple(failures),
            request_stats=self.client.stats.snapshot(),
            duration_seconds=(finished_at - self.started_at).total_seconds(),
            success=not failures,
        )


def _parse_as_of(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require_utc(parsed)
    return parsed


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the bounded Gate Slice 4 bootstrap")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--contracts-root", default="config/v2")
    parser.add_argument("--as-of", default=None, help="UTC ISO timestamp used as the candidate boundary")
    parser.add_argument("--report-path", default=None)
    parser.add_argument("--four-hour-history", type=int, default=FOUR_HOUR_HISTORY)
    parser.add_argument("--daily-history", type=int, default=DAILY_HISTORY)
    args = parser.parse_args(argv)
    import os

    database_url = args.database_url or os.environ.get("BREADTH_V2_DATABASE_URL") or os.environ.get("BREADTH_V2_TEST_DATABASE_URL")
    if not database_url:
        parser.error("--database-url or BREADTH_V2_DATABASE_URL is required")
    bundle = load_contract_bundle(Path(args.contracts_root), bundle="v2-40")
    engine = create_postgres_engine(database_url)
    stats = GateRequestStats()
    client = GateClient(load_gate_mappings(bundle), stats=stats)
    report = GateBootstrapService(
        engine,
        client,
        bundle,
        as_of=_parse_as_of(args.as_of),
        four_hour_history=args.four_hour_history,
        daily_history=args.daily_history,
    ).run()
    document = json.dumps(report.as_dict(), indent=2, sort_keys=True)
    if args.report_path:
        path = Path(args.report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document + "\n", encoding="utf-8")
    print(document)
    engine.dispose()
    return 0 if report.success else 2


if __name__ == "__main__":
    raise SystemExit(main())
