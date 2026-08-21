"""Candidate-only operational scheduler.

This is a small UTC worker around the accepted ``crypto_breadth_v2.shadow``
entrypoint. It has no LIVE activation path, provider selection, cohort
mutation, or UI dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence
import argparse
import json
import os
import socket
import time
from uuid import UUID

from sqlalchemy import func, select

from .contracts import ContractBundle, load_contract_bundle
from .incremental import CANDIDATE_COHORT_SIZES, ShadowRunReport, stable_uuid
from .providers.gate import GATE_SOURCE_ID, load_gate_mappings
from .shadow import run_shadow
from .storage.database import create_postgres_engine
from .storage.models import BreadthSnapshot, CanonicalCandleRecord, ScannerStateRecord
from .timeframes import Timeframe, duration, expected_latest_close


UTC = timezone.utc


@dataclass(frozen=True)
class ShadowSchedule:
    """UTC post-boundary offsets approved for candidate shadow operation."""

    four_hour_delay: timedelta = timedelta(minutes=10)
    daily_delay: timedelta = timedelta(minutes=15)
    weekly_delay: timedelta = timedelta(minutes=25)
    recovery_interval: timedelta = timedelta(hours=1)


SCHEDULE = ShadowSchedule()


def _floor_hour(value: datetime, hour_step: int) -> datetime:
    value = value.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    return value.replace(hour=value.hour - value.hour % hour_step)


def scheduled_at_for(now: datetime, timeframe: Timeframe) -> datetime:
    """Return the latest approved scheduled execution time at or before now."""
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise ValueError("scheduler clock must be timezone-aware UTC")
    now = now.astimezone(UTC)
    timeframe = Timeframe(timeframe)
    if timeframe is Timeframe.FOUR_HOUR:
        return _floor_hour(now, 4) + SCHEDULE.four_hour_delay
    if timeframe is Timeframe.DAILY:
        return now.replace(hour=0, minute=0, second=0, microsecond=0) + SCHEDULE.daily_delay
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0) + SCHEDULE.weekly_delay


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, UUID)):
        return value.isoformat()
    if hasattr(value, "as_tuple"):
        return str(value)
    return value


class CandidateShadowScheduler:
    """Single-worker scheduler with durable cumulative JSON evidence."""

    def __init__(self, database_url: str, *, contracts_root: Path, report_path: Path,
                 scheduler_id: str, code_sha: str, sleep_seconds: float = 30.0,
                 now: Callable[[], datetime] | None = None,
                 forced_timeframe: Timeframe | None = None,
                 force_recovery: bool = False) -> None:
        self.database_url = database_url
        self.contracts_root = contracts_root
        self.report_path = report_path
        self.scheduler_id = scheduler_id
        self.code_sha = code_sha
        self.sleep_seconds = sleep_seconds
        self.now = now or (lambda: datetime.now(UTC))
        self.forced_timeframe = Timeframe(forced_timeframe) if forced_timeframe else None
        self.force_recovery = force_recovery
        self.engine = create_postgres_engine(database_url)
        self.bundle: ContractBundle = load_contract_bundle(contracts_root, bundle="v2-40")
        self._completed_slots: set[str] = set()
        self._activated_at = self.now().astimezone(UTC)
        self._activation_skip_pending = True
        self._report: dict[str, Any] = {
            "scheduler_id": scheduler_id,
            "host": socket.gethostname(),
            "database_target": database_url.split("@")[-1],
            "code_sha": code_sha,
            "series_version": self.bundle.definition("series")["series_version"],
            "series_status": "CANDIDATE",
            "inception_at": None,
            "activated_at": self._activated_at.isoformat(),
            "cycles": [],
        }
        self._load_report()

    def _load_report(self) -> None:
        if not self.report_path.exists():
            return
        try:
            previous = json.loads(self.report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if previous.get("scheduler_id") == self.scheduler_id:
            self._report.update(previous)
            self._completed_slots = {item["slot_key"] for item in previous.get("cycles", []) if item.get("slot_key")}

    def _write_report(self) -> None:
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._report, indent=2, sort_keys=True, default=_json_value) + "\n"
        temporary = self.report_path.with_suffix(self.report_path.suffix + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(self.report_path)

    def _missing_expected_candle(self, timeframe: Timeframe, boundary: datetime) -> bool:
        if timeframe is Timeframe.WEEKLY:
            return False
        target_open = boundary - duration(timeframe)
        mappings = load_gate_mappings(self.bundle)
        asset_ids = [stable_uuid("asset", mapping.canonical_id) for mapping in mappings.values()]
        with self.engine.connect() as connection:
            latest = dict(connection.execute(
                select(CanonicalCandleRecord.asset_id, func.max(CanonicalCandleRecord.open_time))
                .where(CanonicalCandleRecord.asset_id.in_(asset_ids),
                       CanonicalCandleRecord.source_id == GATE_SOURCE_ID,
                       CanonicalCandleRecord.timeframe == timeframe.value,
                       CanonicalCandleRecord.normalizer_version == self.bundle.definition("normalizer")["version"],
                       CanonicalCandleRecord.status == "VALID")
                .group_by(CanonicalCandleRecord.asset_id)
            ).all())
        return any(latest.get(asset_id) is None or latest[asset_id] < target_open for asset_id in asset_ids)

    def _enrich(self, report: ShadowRunReport, scheduled_at: datetime, started_at: datetime) -> dict[str, Any]:
        ended_at = self.now().astimezone(UTC)
        snapshot = None
        scanner_count = 0
        previous_snapshot_time = None
        if report.snapshot_id is not None:
            with self.engine.connect() as connection:
                snapshot = connection.execute(select(BreadthSnapshot).where(BreadthSnapshot.snapshot_id == report.snapshot_id)).mappings().first()
                scanner_count = connection.execute(select(func.count()).select_from(ScannerStateRecord).where(
                    ScannerStateRecord.series_version == self.bundle.definition("series")["series_version"],
                    ScannerStateRecord.timeframe == report.timeframe)).scalar_one()
                previous_snapshot_time = connection.execute(select(func.max(BreadthSnapshot.candle_time)).where(
                    BreadthSnapshot.series_version == self.bundle.definition("series")["series_version"],
                    BreadthSnapshot.timeframe == report.timeframe,
                    BreadthSnapshot.candle_time < report.boundary,
                    BreadthSnapshot.status == "PUBLISHED")).scalar_one_or_none()
        expected_cohort = CANDIDATE_COHORT_SIZES[report.timeframe]
        return {
            "slot_key": f"{report.timeframe}:{report.boundary.isoformat()}",
            "run_id": str(report.run_id), "code_sha": self.code_sha,
            "timeframe": report.timeframe, "scheduled_at": scheduled_at.isoformat(),
            "start": started_at.isoformat(), "end": ended_at.isoformat(),
            "expected_boundary": report.boundary.isoformat(), "duration_seconds": report.duration_seconds,
            "gate_calls": report.request_stats.get("http_calls", 0), "retries": report.request_stats.get("retries", 0),
            "errors": list(report.errors), "canonical_inserts": report.inserted, "canonical_replays": report.replayed,
            "gaps": report.missing_before, "conflicts": sum("Conflict" in error for error in report.errors),
            "publication_status": report.publication_status,
            "breadth_score": _json_value(snapshot["breadth_score"]) if snapshot else None,
            "components": {key: _json_value(snapshot[key]) for key in ("pct_above_ema20", "pct_above_ema50", "pct_above_ema200")} if snapshot else {},
            "cohort": {"size": snapshot["cohort_size"] if snapshot else 0, "denominator": expected_cohort},
            "timestamp_aligned": bool(snapshot and snapshot["candle_time"] == report.boundary),
            "data_quality": _json_value(snapshot["data_quality_score"]) if snapshot else None,
            "scanner_rows": scanner_count,
            "last_known_good_age_seconds": (ended_at - previous_snapshot_time).total_seconds() if previous_snapshot_time else None,
            "denominator_drift": bool(snapshot and snapshot["cohort_size"] != expected_cohort),
            "partial_publication": report.publication_status == "PUBLISHED" and not snapshot,
            "status": report.status,
        }

    def run_cycle(self, timeframe: Timeframe, scheduled_at: datetime, *, recovery: bool = False) -> dict[str, Any]:
        started = self.now().astimezone(UTC)
        report = run_shadow(self.database_url, timeframe=timeframe, as_of=started, contracts_root=self.contracts_root)
        evidence = self._enrich(report, scheduled_at, started)
        evidence["recovery"] = recovery
        self._report["cycles"].append(evidence)
        self._write_report()
        return evidence

    def run_due(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = (now or self.now()).astimezone(UTC)
        completed: list[dict[str, Any]] = []
        timeframes = (self.forced_timeframe,) if self.forced_timeframe else (Timeframe.FOUR_HOUR, Timeframe.DAILY, Timeframe.WEEKLY)
        for timeframe in timeframes:
            scheduled_at = scheduled_at_for(now, timeframe)
            slot_key = f"{timeframe.value}:{expected_latest_close(now, timeframe).isoformat()}"
            if self._activation_skip_pending and not self.forced_timeframe and scheduled_at < self._activated_at:
                self._completed_slots.add(slot_key)
                continue
            if scheduled_at <= now and slot_key not in self._completed_slots:
                self._completed_slots.add(slot_key)
                completed.append(self.run_cycle(timeframe, scheduled_at))
        hourly = now.replace(minute=0, second=0, microsecond=0)
        recovery_key = f"recovery:{hourly.isoformat()}"
        if self._activation_skip_pending and not self.force_recovery and hourly < self._activated_at:
            self._completed_slots.add(recovery_key)
        elif recovery_key not in self._completed_slots:
            self._completed_slots.add(recovery_key)
            for timeframe in (Timeframe.FOUR_HOUR, Timeframe.DAILY):
                boundary = expected_latest_close(now, timeframe)
                if self._missing_expected_candle(timeframe, boundary):
                    completed.append(self.run_cycle(timeframe, hourly, recovery=True))
        self._activation_skip_pending = False
        if completed:
            self._write_report()
        return completed

    def run_forever(self) -> None:
        self._write_report()
        while True:
            self.run_due()
            time.sleep(self.sleep_seconds)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the candidate-only UTC shadow scheduler")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--contracts-root", default="config/v2")
    parser.add_argument("--report-path", default="reports/shadow_status.json")
    parser.add_argument("--scheduler-id", default=os.environ.get("BREADTH_V2_SCHEDULER_ID", "breadth-v2-candidate-shadow"))
    parser.add_argument("--code-sha", default=os.environ.get("BREADTH_V2_CODE_SHA", "unknown"))
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--once", action="store_true", help="evaluate due slots once and exit")
    parser.add_argument("--timeframe", choices=[item.value for item in Timeframe], help="cron slot to evaluate")
    parser.add_argument("--recovery", action="store_true", help="evaluate the hourly missing-candle recovery slot")
    args = parser.parse_args(argv)
    scheduler = CandidateShadowScheduler(args.database_url, contracts_root=Path(args.contracts_root), report_path=Path(args.report_path), scheduler_id=args.scheduler_id, code_sha=args.code_sha, sleep_seconds=args.poll_seconds, forced_timeframe=Timeframe(args.timeframe) if args.timeframe else None, force_recovery=args.recovery)
    if args.once:
        scheduler.run_due()
    else:
        scheduler.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
