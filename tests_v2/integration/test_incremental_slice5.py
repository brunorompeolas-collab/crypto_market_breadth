from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select, text

from src.crypto_breadth_v2.bootstrap import GateBootstrapService
from src.crypto_breadth_v2.candles import CanonicalCandle
from src.crypto_breadth_v2.contracts import load_contract_bundle
from src.crypto_breadth_v2.incremental import CandidateShadowService
from src.crypto_breadth_v2.providers.gate import GateCandleEnvelope, GateRequestStats, load_gate_mappings
from src.crypto_breadth_v2.storage.models import BreadthSnapshot, TimeframeCohort
from src.crypto_breadth_v2.timeframes import Timeframe, duration, expected_latest_close

from .conftest import UTC_NOW


class OneCandleGate:
    def __init__(self, mappings, *, history: bool = False):
        self.mappings = mappings
        self.history = history
        self.stats = GateRequestStats()

    def fetch_range(self, symbol, *, timeframe, start, end, as_of, allow_empty_pages):
        self.stats.http_calls += 1
        count = 200 if self.history else 1
        result = []
        for index in range(count):
            open_time = end - duration(timeframe) * (count - index)
            value = Decimal("100") + Decimal(index) / Decimal("10")
            candle = CanonicalCandle(
                asset_id=self.mappings[symbol].canonical_id,
                timeframe=timeframe,
                open_time=open_time,
                close_time=open_time + duration(timeframe),
                open=value,
                high=value + 1,
                low=value - Decimal("1"),
                close=value,
                base_volume=Decimal("1"),
                quote_volume=Decimal("100"),
                trade_count=1,
            )
            digest = sha256(f"{symbol}:{timeframe.value}:{open_time.isoformat()}".encode()).hexdigest()
            result.append(GateCandleEnvelope(self.mappings[symbol], candle, digest, ("fixture",)))
        return tuple(result)


def test_incremental_candidate_shadow_rejects_warmup_and_replay_is_idempotent(clean_database):
    bundle = load_contract_bundle(Path("config/v2"), bundle="v2-40")
    metadata = GateBootstrapService(clean_database, OneCandleGate(load_gate_mappings(bundle)), bundle, as_of=UTC_NOW)
    metadata.ensure_metadata()
    with clean_database.begin() as connection:
        universe = bundle.definition("universe")
        assets = {row["id"]: metadata.asset_uuid_by_id[row["id"]] for row in universe["members"]}
        for timeframe, included in (("4h", True), ("1d", True), ("1w", False)):
            for row in universe["members"]:
                connection.execute(TimeframeCohort.__table__.insert().values(
                    series_version=metadata.series_version,
                    timeframe=timeframe,
                    asset_id=assets[row["id"]],
                    included_in_denominator=included if timeframe != "1w" else row["symbol"] not in {"GRAM", "TAO", "SUI", "HYPE", "ONDO"},
                    history_count_at_inception=1,
                    eligibility_reason="FIXTURE",
                    frozen_at=UTC_NOW,
                ))
    client = OneCandleGate(load_gate_mappings(bundle))
    service = CandidateShadowService(clean_database, client, bundle, as_of=UTC_NOW)
    first = service.run(Timeframe.FOUR_HOUR)
    second = service.run(Timeframe.FOUR_HOUR)
    assert first.status == "SUCCEEDED"
    assert first.publication_status == "REJECTED"
    assert first.snapshot_id is not None
    assert second.snapshot_id == first.snapshot_id
    assert second.rejection_reason == "DUPLICATE_REPLAY"
    with clean_database.connect() as connection:
        snapshots = connection.execute(select(BreadthSnapshot).where(BreadthSnapshot.series_version == metadata.series_version)).all()
    assert len(snapshots) == 1
    # This test creates the candidate identity with a NULL inception. Leave
    # the shared PostgreSQL acceptance database empty so the migration-cycle
    # tests can intentionally exercise their pre-activation downgrade.
    with clean_database.begin() as connection:
        tables = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='breadth_v2' AND tablename <> 'alembic_version'")).scalars().all()
        connection.exec_driver_sql("TRUNCATE " + ", ".join(f'breadth_v2."{table}"' for table in tables) + " RESTART IDENTITY CASCADE")


def test_incremental_candidate_shadow_publishes_with_complete_ema_history(clean_database):
    bundle = load_contract_bundle(Path("config/v2"), bundle="v2-40")
    metadata = GateBootstrapService(clean_database, OneCandleGate(load_gate_mappings(bundle)), bundle, as_of=UTC_NOW)
    metadata.ensure_metadata()
    with clean_database.begin() as connection:
        assets = {row["id"]: metadata.asset_uuid_by_id[row["id"]] for row in bundle.definition("universe")["members"]}
        for timeframe, excluded in (("4h", set()), ("1d", set()), ("1w", {"GRAM", "TAO", "SUI", "HYPE", "ONDO"})):
            for member in bundle.definition("universe")["members"]:
                connection.execute(TimeframeCohort.__table__.insert().values(
                    series_version=metadata.series_version, timeframe=timeframe,
                    asset_id=assets[member["id"]], included_in_denominator=member["symbol"] not in excluded,
                    history_count_at_inception=200, eligibility_reason="FIXTURE", frozen_at=UTC_NOW,
                ))
    service = CandidateShadowService(clean_database, OneCandleGate(load_gate_mappings(bundle), history=True), bundle, as_of=UTC_NOW)
    report = service.run(Timeframe.FOUR_HOUR)
    assert report.status == "SUCCEEDED"
    assert report.publication_status == "PUBLISHED"
    assert report.rejection_reason is None
    with clean_database.begin() as connection:
        tables = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='breadth_v2' AND tablename <> 'alembic_version'")).scalars().all()
        connection.exec_driver_sql("TRUNCATE " + ", ".join(f'breadth_v2."{table}"' for table in tables) + " RESTART IDENTITY CASCADE")
