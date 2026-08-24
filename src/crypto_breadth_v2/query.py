"""Read-only PostgreSQL query service for the candidate dashboard.

The service accepts a frozen contract bundle and applies every version
identity in every query.  It deliberately has no provider imports or write
methods, so Streamlit cannot accidentally become an ingestion surface.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import Engine, and_, select

from .contracts import ContractBundle
from .view_models import DashboardView, ScannerView, SnapshotView
from .storage.models import (
    Asset,
    AssetIndicator,
    BreadthSnapshot,
    IngestionRun,
    ScannerStateRecord,
)
from .timeframes import Timeframe, expected_latest_close, require_utc


UTC = timezone.utc


class ReadOnlyQueryService:
    """Query candidate data without any mutation or provider/network access."""

    def __init__(self, engine: Engine, bundle: ContractBundle) -> None:
        self.engine = engine
        self.bundle = bundle
        self.series = bundle.definition("series")
        self.series_version = self.series["series_version"]
        self.universe_version = bundle.definition("universe")["version"]
        self.source_policy_version = bundle.definition("source_policy")["version"]
        self.formula_version = bundle.definition("formula")["version"]
        self.normalizer_version = bundle.definition("normalizer")["version"]
        self._asset_meta = {
            row["id"]: (row["symbol"], row["display_name"])
            for row in bundle.definition("universe")["members"]
        }

    def _snapshot_filter(self, timeframe: Timeframe):
        return and_(
            BreadthSnapshot.series_version == self.series_version,
            BreadthSnapshot.universe_version == self.universe_version,
            BreadthSnapshot.source_policy_version == self.source_policy_version,
            BreadthSnapshot.formula_version == self.formula_version,
            BreadthSnapshot.normalizer_version == self.normalizer_version,
            BreadthSnapshot.timeframe == timeframe.value,
        )

    def _view(self, row: Mapping[str, Any]) -> SnapshotView:
        return SnapshotView(
            snapshot_id=str(row["snapshot_id"]),
            timeframe=row["timeframe"],
            candle_time=row["candle_time"],
            status=row["status"],
            breadth_score=row["breadth_score"],
            pct_above_ema20=row["pct_above_ema20"],
            pct_above_ema50=row["pct_above_ema50"],
            pct_above_ema200=row["pct_above_ema200"],
            data_quality_score=row["data_quality_score"],
            data_quality_label=row["data_quality_label"],
            structural_coverage=row["structural_coverage"],
            component_coverage=row["component_coverage"],
            btc_close=row["btc_close"],
            eth_close=row["eth_close"],
            universe_size=row["universe_size"],
            cohort_size=row["cohort_size"],
            rejection_reason=row["rejection_reason"],
            computed_at=row["computed_at"],
            provenance={
                "series_version": row["series_version"],
                "universe_version": row["universe_version"],
                "source_policy_version": row["source_policy_version"],
                "formula_version": row["formula_version"],
                "normalizer_version": row["normalizer_version"],
            },
        )

    def latest_snapshot(self, timeframe: Timeframe | str) -> SnapshotView | None:
        timeframe = Timeframe(timeframe)
        with self.engine.connect() as connection:
            row = connection.execute(
                select(BreadthSnapshot)
                .where(self._snapshot_filter(timeframe))
                .order_by(BreadthSnapshot.candle_time.desc())
                .limit(1)
            ).mappings().one_or_none()
        return self._view(row) if row else None

    def last_known_good(self, timeframe: Timeframe | str) -> SnapshotView | None:
        timeframe = Timeframe(timeframe)
        with self.engine.connect() as connection:
            row = connection.execute(
                select(BreadthSnapshot)
                .where(self._snapshot_filter(timeframe), BreadthSnapshot.status == "PUBLISHED")
                .order_by(BreadthSnapshot.candle_time.desc())
                .limit(1)
            ).mappings().one_or_none()
        return self._view(row) if row else None

    def historical_series(self, timeframe: Timeframe | str, *, since: datetime | None = None) -> tuple[SnapshotView, ...]:
        timeframe = Timeframe(timeframe)
        if since is not None:
            require_utc(since)
        with self.engine.connect() as connection:
            statement = (
                select(BreadthSnapshot)
                .where(self._snapshot_filter(timeframe), BreadthSnapshot.status == "PUBLISHED")
                .order_by(BreadthSnapshot.candle_time)
            )
            if since is not None:
                statement = statement.where(BreadthSnapshot.candle_time >= since)
            rows = connection.execute(statement).mappings().all()
        return tuple(self._view(row) for row in rows)

    def scanner(self, timeframe: Timeframe | str) -> tuple[ScannerView, ...]:
        timeframe = Timeframe(timeframe)
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(ScannerStateRecord, Asset.canonical_id, Asset.symbol, Asset.display_name)
                .join(Asset, Asset.asset_id == ScannerStateRecord.asset_id)
                .where(
                    ScannerStateRecord.series_version == self.series_version,
                    ScannerStateRecord.timeframe == timeframe.value,
                    Asset.status == "ACTIVE",
                )
                .order_by(Asset.symbol)
            ).mappings().all()
        return tuple(
            ScannerView(
                asset_id=str(row["asset_id"]),
                symbol=row["symbol"],
                display_name=row["display_name"],
                candle_time=row["candle_time"],
                price=row["price"],
                ema20=row["ema20"],
                ema50=row["ema50"],
                ema200=row["ema200"],
                state20=row["state20"],
                state50=row["state50"],
                state200=row["state200"],
                included_in_breadth=row["included_in_breadth"],
            )
            for row in rows
        )

    def latest_failure(self, timeframe: Timeframe | str) -> Mapping[str, Any] | None:
        timeframe = Timeframe(timeframe)
        with self.engine.connect() as connection:
            run = connection.execute(
                select(IngestionRun)
                .where(
                    IngestionRun.series_version == self.series_version,
                    IngestionRun.timeframe == timeframe.value,
                    IngestionRun.status == "FAILED",
                )
                .order_by(IngestionRun.started_at.desc())
                .limit(1)
            ).mappings().one_or_none()
        if run:
            return {"kind": "INGESTION", "run_id": str(run["run_id"]), "message": run["error_summary"], "at": run["finished_at"]}
        latest = self.latest_snapshot(timeframe)
        if latest and latest.status != "PUBLISHED":
            return {"kind": "PUBLICATION", "snapshot_id": latest.snapshot_id, "message": latest.rejection_reason, "at": latest.computed_at}
        return None

    def dashboard(self, timeframe: Timeframe | str, *, now: datetime | None = None) -> DashboardView:
        timeframe = Timeframe(timeframe)
        now = now or datetime.now(UTC)
        require_utc(now)
        expected = expected_latest_close(now, timeframe)
        latest = self.latest_snapshot(timeframe)
        lkg = self.last_known_good(timeframe)
        basis = lkg or latest
        age = now - basis.candle_time if basis else None
        if latest is None:
            state = "UNAVAILABLE"
        elif latest.status == "PUBLISHED" and latest.candle_time == expected:
            state = "CURRENT"
        elif lkg is not None:
            state = "STALE"
        elif latest.status == "REJECTED":
            state = "DEGRADED"
        else:
            state = "UNAVAILABLE"
        return DashboardView(
            timeframe=timeframe.value,
            expected_boundary=expected,
            ui_state=state,
            latest=latest,
            last_known_good=lkg,
            age=age,
            latest_failure=self.latest_failure(timeframe),
            history=self.historical_series(timeframe),
            scanner=self.scanner(timeframe),
        )
