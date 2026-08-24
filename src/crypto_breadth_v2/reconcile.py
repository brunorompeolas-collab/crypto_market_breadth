"""Stateless Gate -> deterministic compute -> Firestore reconciliation job."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .breadth import MemberSignals, calculate_breadth
from .cohort import FrozenCohort
from .cohorts_config import included_asset_ids, load_frozen_cohorts
from .contracts import ContractBundle, load_contract_bundle
from .domain import PricePoint, ScannerState, scanner_state
from .ema import compute_standard_emas
from .firestore import SnapshotStore, snapshot_document
from .providers.gate import GATE_SOURCE_ID, GateClient, GateCandleEnvelope, load_gate_mappings
from .quality import calculate_data_quality
from .timeframes import Timeframe, duration, expected_latest_close, require_utc
from .weekly import derive_weekly_series


UTC = timezone.utc
PERIODS = (20, 50, 200)
DEFAULT_HISTORY_OBSERVATIONS = 220
TIMEFRAME_ORDER = {"4h": 0, "1d": 1, "1w": 2}


def _parse_boundary(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require_utc(parsed)
    return parsed.astimezone(UTC)


def _boundary_from_document(document: Mapping[str, Any]) -> datetime:
    value = document.get("boundary")
    if not isinstance(value, str):
        raise ValueError("Firestore snapshot has no boundary")
    return _parse_boundary(value)


@dataclass(frozen=True)
class BoundaryResult:
    timeframe: str
    boundary: datetime
    status: str
    document_path: str | None
    provider_calls: int
    skipped_existing: bool = False
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["boundary"] = self.boundary.isoformat().replace("+00:00", "Z")
        return result


@dataclass(frozen=True)
class ReconcileReport:
    started_at: datetime
    finished_at: datetime
    job_sha: str
    results: tuple[BoundaryResult, ...]

    @property
    def succeeded(self) -> bool:
        return all(item.status in {"PUBLISHED", "SKIPPED"} for item in self.results)

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "finished_at": self.finished_at.isoformat().replace("+00:00", "Z"),
            "job_sha": self.job_sha,
            "succeeded": self.succeeded,
            "results": [item.as_dict() for item in self.results],
        }


class Reconciler:
    """Catch up missing boundaries in chronological order.

    No process state is required: Firestore is queried for the latest
    successful boundary each invocation, and Gate history is fetched for the
    exact target boundary.  A failure stops the chronological catch-up before
    later boundaries can be published out of order.
    """

    def __init__(
        self,
        store: SnapshotStore,
        client: GateClient,
        bundle: ContractBundle,
        *,
        cohort_exclusions: Mapping[str, frozenset[str]],
        now: datetime,
        job_sha: str,
        history_observations: int = DEFAULT_HISTORY_OBSERVATIONS,
    ) -> None:
        require_utc(now)
        if history_observations < 200:
            raise ValueError("history_observations must support EMA200")
        self.store = store
        self.client = client
        self.bundle = bundle
        self.now = now.astimezone(UTC)
        self.job_sha = job_sha
        self.history_observations = history_observations
        self.cohort_exclusions = cohort_exclusions
        universe = bundle.definition("universe")
        self.members = tuple(universe["members"])
        self.asset_ids = tuple(member["id"] for member in self.members)
        self.by_id = {member["id"]: member for member in self.members}
        self.by_symbol = {member["symbol"]: member for member in self.members}
        self.mappings = load_gate_mappings(bundle)
        self.series_version = bundle.definition("series")["series_version"]
        self.universe_version = universe["version"]
        self.source_policy_version = bundle.definition("source_policy")["version"]
        self.formula_version = bundle.definition("formula")["version"]
        self.normalizer_version = bundle.definition("normalizer")["version"]

    def due_boundaries(self, timeframe: Timeframe | str, *, start: datetime | None = None) -> tuple[datetime, ...]:
        timeframe = Timeframe(timeframe)
        latest = self.store.latest(self.series_version, timeframe.value, status="PUBLISHED")
        if start is None:
            first = _boundary_from_document(latest) + duration(timeframe) if latest else expected_latest_close(self.now, timeframe)
        else:
            require_utc(start)
            first = start.astimezone(UTC)
        expected = expected_latest_close(self.now, timeframe)
        if first > expected:
            return ()
        result: list[datetime] = []
        cursor = first
        while cursor <= expected:
            result.append(cursor)
            cursor += duration(timeframe)
        return tuple(result)

    def _fetch_native_history(self, symbol: str, timeframe: Timeframe, target_boundary: datetime) -> tuple[GateCandleEnvelope, ...]:
        target_open = target_boundary - duration(timeframe)
        start = target_open - duration(timeframe) * (self.history_observations - 1)
        return self.client.fetch_range(symbol, timeframe=timeframe, start=start, end=target_boundary, as_of=self.now)

    @staticmethod
    def _weekly_history(envelopes: Sequence[GateCandleEnvelope], *, asset_id: str, as_of: datetime) -> tuple[Any, ...]:
        rows = [
            {
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
                "source_payload_hash": envelope.source_payload_hash,
            }
            for envelope in envelopes
        ]
        return tuple(item.candle for item in derive_weekly_series(rows, asset_id=asset_id, as_of=as_of))

    def _history(self, timeframe: Timeframe, boundary: datetime) -> dict[str, tuple[Any, ...]]:
        histories: dict[str, tuple[Any, ...]] = {}
        for symbol, mapping in self.mappings.items():
            if timeframe is Timeframe.WEEKLY:
                # Weekly is derived strictly from native daily Gate candles.
                target_open = boundary - duration(timeframe)
                start = target_open - duration(timeframe) * (self.history_observations - 1)
                daily = self.client.fetch_range(symbol, timeframe=Timeframe.DAILY, start=start, end=boundary, as_of=self.now)
                histories[mapping.canonical_id] = self._weekly_history(daily, asset_id=mapping.canonical_id, as_of=self.now)
            else:
                native = self._fetch_native_history(symbol, timeframe, boundary)
                histories[mapping.canonical_id] = tuple(envelope.candle for envelope in native)
        return histories

    def _member_rows(self, timeframe: Timeframe, boundary: datetime, histories: Mapping[str, Sequence[Any]]) -> tuple[list[dict[str, Any]], dict[str, MemberSignals]]:
        target_open = boundary - duration(timeframe)
        rows: list[dict[str, Any]] = []
        signals: dict[str, MemberSignals] = {}
        included = set(included_asset_ids(self.asset_ids, self.cohort_exclusions, timeframe.value))
        for member in self.members:
            asset_id = member["id"]
            candles = tuple(histories.get(asset_id, ()))
            points = tuple(PricePoint(candle.open_time, candle.close) for candle in candles)
            indicator = None
            if points:
                emas = compute_standard_emas(points, timeframe=timeframe)
                indexes = {candle.open_time: index for index, candle in enumerate(candles)}
                index = indexes.get(target_open)
                if index is not None:
                    candle = candles[index]
                    indicator = (candle, *(emas[period][index] for period in PERIODS))
            if indicator is None:
                close = ema20 = ema50 = ema200 = None
                states = (ScannerState.UNAVAILABLE,) * 3
                candle_time = None
            else:
                candle, point20, point50, point200 = indicator
                close = candle.close
                ema20, ema50, ema200 = point20.value, point50.value, point200.value
                states = tuple(scanner_state(close, value) for value in (ema20, ema50, ema200))
                candle_time = candle.open_time
            signals[asset_id] = MemberSignals(*states)
            rows.append({
                "asset_id": asset_id,
                "symbol": member["symbol"],
                "display_name": member["display_name"],
                "candle_time": candle_time,
                "price": close,
                "ema20": ema20,
                "ema50": ema50,
                "ema200": ema200,
                "state20": states[0].value,
                "state50": states[1].value,
                "state200": states[2].value,
                "included_in_breadth": asset_id in included,
                "source_id": GATE_SOURCE_ID,
                "instrument": self.mappings[member["symbol"]].instrument,
            })
        return rows, signals

    def _compute_document(self, timeframe: Timeframe, boundary: datetime) -> dict[str, Any]:
        histories = self._history(timeframe, boundary)
        rows, signals = self._member_rows(timeframe, boundary, histories)
        included = included_asset_ids(self.asset_ids, self.cohort_exclusions, timeframe.value)
        cohort = FrozenCohort.create(universe_size=len(self.members), asset_ids=included)
        breadth = calculate_breadth(cohort, {asset_id: signals[asset_id] for asset_id in included})
        target_open = boundary - duration(timeframe)
        included_rows = [row for row in rows if row["included_in_breadth"]]
        valid_counts = {
            period: sum(row[f"state{period}"] != ScannerState.UNAVAILABLE.value for row in included_rows)
            for period in PERIODS
        }
        fresh = all(row["candle_time"] == target_open for row in included_rows)
        btc = next(row for row in rows if row["symbol"] == "BTC")
        eth = next(row for row in rows if row["symbol"] == "ETH")
        aligned = btc["candle_time"] == target_open and eth["candle_time"] == target_open
        quality = calculate_data_quality(
            universe_size=len(self.members),
            cohort_size=len(included),
            valid_ema20=valid_counts[20],
            valid_ema50=valid_counts[50],
            valid_ema200=valid_counts[200],
            fresh=fresh,
            aligned=aligned,
            last_known_good_exists=self.store.latest(self.series_version, timeframe.value, status="PUBLISHED") is not None,
        )
        status = "PUBLISHED" if breadth.score is not None and quality.publishable else "UNAVAILABLE"
        reason = None if status == "PUBLISHED" else (";".join(breadth.unavailable_assets) or "COMPONENT_COVERAGE_BELOW_100")
        return snapshot_document(
            boundary=boundary,
            computed_at=self.now,
            series_version=self.series_version,
            universe_version=self.universe_version,
            source_policy_version=self.source_policy_version,
            formula_version=self.formula_version,
            normalizer_version=self.normalizer_version,
            timeframe=timeframe.value,
            status=status,
            breadth_score=breadth.score if status == "PUBLISHED" else None,
            pct_above_ema20=breadth.percentages[20] if status == "PUBLISHED" else None,
            pct_above_ema50=breadth.percentages[50] if status == "PUBLISHED" else None,
            pct_above_ema200=breadth.percentages[200] if status == "PUBLISHED" else None,
            data_quality_score=quality.score,
            data_quality_label=quality.label.value,
            structural_coverage=quality.structural_coverage,
            component_coverage=quality.component_coverage,
            btc_close=btc["price"] if status == "PUBLISHED" else None,
            eth_close=eth["price"] if status == "PUBLISHED" else None,
            universe_size=len(self.members),
            cohort_denominator=len(included),
            members=rows,
            source={"provider": "Gate", "source_id": GATE_SOURCE_ID, "instruments_frozen": True},
            job_sha=self.job_sha,
            rejection_reason=reason,
        )

    def run(
        self,
        *,
        start: datetime | None = None,
        max_boundaries: int = 24,
        timeframes: Sequence[Timeframe | str] | None = None,
    ) -> ReconcileReport:
        started = datetime.now(UTC)
        due: list[tuple[datetime, Timeframe]] = []
        selected = tuple(Timeframe(item) for item in timeframes) if timeframes is not None else tuple(Timeframe)
        for timeframe in selected:
            due.extend((boundary, timeframe) for boundary in self.due_boundaries(timeframe, start=start))
        due.sort(key=lambda item: (item[0], TIMEFRAME_ORDER[item[1].value]))
        due = due[:max_boundaries]
        results: list[BoundaryResult] = []
        for boundary, timeframe in due:
            existing = self.store.get(self.series_version, timeframe.value, boundary)
            if existing is not None and existing.get("status") == "PUBLISHED":
                results.append(BoundaryResult(timeframe.value, boundary, "SKIPPED", existing.get("document_path"), 0, True))
                continue
            calls_before = self.client.stats.http_calls
            try:
                document = self._compute_document(timeframe, boundary)
                path = self.store.put(document)
                results.append(BoundaryResult(timeframe.value, boundary, document["status"], path, self.client.stats.http_calls - calls_before))
                if document["status"] != "PUBLISHED":
                    break
            except Exception as exc:
                # No document is written on provider/schema/compute failure;
                # the next hourly run will retry this same boundary.
                results.append(BoundaryResult(timeframe.value, boundary, "FAILED", None, self.client.stats.http_calls - calls_before, error=f"{type(exc).__name__}: {exc}"))
                break
        return ReconcileReport(started, datetime.now(UTC), self.job_sha, tuple(results))


def run_reconcile(
    *,
    contracts_root: Path,
    cohorts_path: Path,
    now: datetime,
    start: datetime | None = None,
    max_boundaries: int = 24,
    job_sha: str | None = None,
) -> ReconcileReport:
    from .firestore import FirestoreSnapshotStore

    bundle = load_contract_bundle(contracts_root, bundle="v2-40")
    cohorts = load_frozen_cohorts(cohorts_path, series_version=bundle.definition("series")["series_version"])
    mappings = load_gate_mappings(bundle)
    store = FirestoreSnapshotStore.from_environment()
    client = GateClient(mappings)
    return Reconciler(store, client, bundle, cohort_exclusions=cohorts, now=now, job_sha=job_sha or os.environ.get("GITHUB_SHA", "local"),).run(start=start, max_boundaries=max_boundaries)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile missing deterministic Breadth v2 snapshots into Firestore")
    parser.add_argument("--contracts-root", default="config/v2")
    parser.add_argument("--cohorts", default="config/v2/cohorts/br1-live-v2-40-frozen.yaml")
    parser.add_argument("--now", help="UTC ISO timestamp for deterministic runs")
    parser.add_argument("--start", help="optional first UTC boundary to catch up")
    parser.add_argument("--max-boundaries", type=int, default=24)
    parser.add_argument("--job-sha", default=None)
    args = parser.parse_args(argv)
    now = _parse_boundary(args.now) if args.now else datetime.now(UTC)
    report = run_reconcile(
        contracts_root=Path(args.contracts_root),
        cohorts_path=Path(args.cohorts),
        now=now,
        start=_parse_boundary(args.start) if args.start else None,
        max_boundaries=args.max_boundaries,
        job_sha=args.job_sha,
    )
    print(json.dumps(report.as_dict(), sort_keys=True))
    return 0 if report.succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
