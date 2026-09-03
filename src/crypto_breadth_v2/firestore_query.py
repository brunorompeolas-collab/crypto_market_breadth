"""Read-only Firestore query service used by ``app_v2.py``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping

from .contracts import ContractBundle
from .firestore import SnapshotStore
from .view_models import DashboardView, ScannerView, SnapshotView
from .timeframes import Timeframe, expected_latest_close, require_utc


UTC = timezone.utc


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("Firestore timestamp is missing")
    require_utc(parsed)
    return parsed.astimezone(UTC)


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


class FirestoreReadOnlyQueryService:
    """Pure reader: it has no Gate/provider imports and no write method."""

    def __init__(self, store: SnapshotStore, bundle: ContractBundle) -> None:
        self.store = store
        series = bundle.definition("series")
        self.series_version = series["series_version"]
        self.universe_version = bundle.definition("universe")["version"]
        self.source_policy_version = bundle.definition("source_policy")["version"]
        self.formula_version = bundle.definition("formula")["version"]
        self.normalizer_version = bundle.definition("normalizer")["version"]
        self._asset_meta = {
            row["id"]: (row["symbol"], row["display_name"])
            for row in bundle.definition("universe")["members"]
        }

    def _view(self, row: Mapping[str, Any]) -> SnapshotView:
        return SnapshotView(
            snapshot_id=str(row.get("document_id") or row.get("document_path") or ""),
            timeframe=row["timeframe"],
            candle_time=_dt(row["boundary"]),
            status=row["status"],
            breadth_score=_decimal(row.get("breadth_score")),
            pct_above_ema20=_decimal(row.get("pct_above_ema20")),
            pct_above_ema50=_decimal(row.get("pct_above_ema50")),
            pct_above_ema200=_decimal(row.get("pct_above_ema200")),
            data_quality_score=_decimal(row.get("data_quality_score")) or Decimal("0"),
            data_quality_label=str(row.get("data_quality_label") or "UNAVAILABLE"),
            structural_coverage=_decimal(row.get("structural_coverage")) or Decimal("0"),
            component_coverage=_decimal(row.get("component_coverage")) or Decimal("0"),
            btc_close=_decimal(row.get("btc_close")),
            eth_close=_decimal(row.get("eth_close")),
            universe_size=int(row.get("universe_size") or 0),
            cohort_size=int(row.get("cohort_denominator") or 0),
            rejection_reason=row.get("rejection_reason"),
            computed_at=_dt(row["computed_at"]),
            provenance={
                "series_version": str(row.get("series_version")),
                "universe_version": str(row.get("universe_version")),
                "source_policy_version": str(row.get("source_policy_version")),
                "formula_version": str(row.get("formula_version")),
                "normalizer_version": str(row.get("normalizer_version")),
                "cohort_version": str(row.get("cohort_version", "")),
                "source_id": str((row.get("source") or {}).get("source_id", "")),
                "job_sha": str(row.get("job_sha", "")),
            },
        )

    def latest_snapshot(self, timeframe: Timeframe | str) -> SnapshotView | None:
        row = self.store.latest(self.series_version, Timeframe(timeframe).value)
        return self._view(row) if row else None

    def last_known_good(self, timeframe: Timeframe | str) -> SnapshotView | None:
        row = self.store.latest(self.series_version, Timeframe(timeframe).value, status="PUBLISHED")
        return self._view(row) if row else None

    def historical_series(
        self,
        timeframe: Timeframe | str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[SnapshotView, ...]:
        if since is not None:
            require_utc(since)
        if until is not None:
            require_utc(until)
        rows = self.store.history(
            self.series_version,
            Timeframe(timeframe).value,
            since=since,
            until=until,
            limit=limit,
        )
        views = tuple(self._view(row) for row in rows)
        return views

    def scanner(self, timeframe: Timeframe | str) -> tuple[ScannerView, ...]:
        row = self.store.latest(self.series_version, Timeframe(timeframe).value)
        if not row:
            return ()
        boundary = _dt(row["boundary"])
        result = []
        for member in row.get("scanner", row.get("members", [])):
            candle_time = _dt(member["candle_time"]) if member.get("candle_time") else boundary
            result.append(
                ScannerView(
                    asset_id=str(member["asset_id"]),
                    symbol=str(member["symbol"]),
                    display_name=str(member["display_name"]),
                    candle_time=candle_time,
                    price=_decimal(member.get("price")),
                    ema20=_decimal(member.get("ema20")),
                    ema50=_decimal(member.get("ema50")),
                    ema200=_decimal(member.get("ema200")),
                    state20=str(member.get("state20", "UNAVAILABLE")),
                    state50=str(member.get("state50", "UNAVAILABLE")),
                    state200=str(member.get("state200", "UNAVAILABLE")),
                    included_in_breadth=bool(member.get("included_in_breadth", False)),
                )
            )
        return tuple(sorted(result, key=lambda item: item.symbol))

    def latest_failure(self, timeframe: Timeframe | str) -> Mapping[str, Any] | None:
        row = self.store.latest(self.series_version, Timeframe(timeframe).value)
        if row and row.get("status") != "PUBLISHED":
            return {
                "kind": "PUBLICATION",
                "snapshot_id": row.get("document_path"),
                "message": row.get("rejection_reason") or "publication unavailable",
                "at": row.get("computed_at"),
            }
        return None

    def dashboard(
        self,
        timeframe: Timeframe | str,
        *,
        now: datetime | None = None,
        history_since: datetime | None = None,
        history_until: datetime | None = None,
        history_limit: int | None = None,
        history_window_days: int | None = None,
    ) -> DashboardView:
        timeframe = Timeframe(timeframe)
        now = now or datetime.now(UTC)
        require_utc(now)
        expected = expected_latest_close(now, timeframe)
        latest = self.latest_snapshot(timeframe)
        lkg = self.last_known_good(timeframe)
        if history_window_days is not None and history_window_days < 0:
            raise ValueError("history_window_days must be non-negative")
        # Historical windows are anchored to the latest usable published
        # boundary, never to wall-clock ``now``.  Freshness below continues to
        # compare against ``now`` so a stale dashboard cannot appear current.
        history_anchor = latest if latest is not None and latest.status == "PUBLISHED" else lkg
        if history_window_days is not None and history_anchor is not None:
            if history_since is None:
                history_since = history_anchor.candle_time - timedelta(days=history_window_days)
            if history_until is None:
                history_until = history_anchor.candle_time
        basis = lkg or latest
        age = now - basis.candle_time if basis else None
        if latest is None:
            state = "UNAVAILABLE"
        elif latest.status == "PUBLISHED" and latest.candle_time == expected:
            state = "CURRENT"
        elif lkg is not None:
            state = "STALE"
        elif latest.status != "PUBLISHED":
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
            history=self.historical_series(timeframe, since=history_since, until=history_until, limit=history_limit),
            scanner=self.scanner(timeframe),
        )
