from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, text

from src.crypto_breadth_v2.bootstrap import GateBootstrapService
from src.crypto_breadth_v2.contracts import load_contract_bundle
from src.crypto_breadth_v2.recompute import HistoricalRecomputeService
from src.crypto_breadth_v2.providers.gate import GateRequestStats, load_gate_mappings
from src.crypto_breadth_v2.storage.models import (
    AssetIndicator,
    CanonicalCandleRecord,
    CanonicalCandleRepair,
    RecomputeOutput,
)
from src.crypto_breadth_v2.timeframes import Timeframe, duration

from .conftest import UTC_NOW


class NoopClient:
    def __init__(self):
        self.stats = GateRequestStats()


def test_explicit_repair_recomputes_affected_ema_chain(clean_database):
    bundle = load_contract_bundle(Path("config/v2"), bundle="v2-40")
    metadata = GateBootstrapService(clean_database, NoopClient(), bundle, as_of=UTC_NOW)
    metadata.ensure_metadata()
    mapping = load_gate_mappings(bundle)["BTC"]
    mapping_id = metadata.mapping_uuid_by_symbol["BTC"]
    asset_id = metadata.asset_uuid_by_id[mapping.canonical_id]
    run_id = metadata._start_run("BTC", Timeframe.FOUR_HOUR, UTC_NOW - timedelta(days=40), UTC_NOW)
    first_open = datetime(2026, 7, 1, 0, tzinfo=timezone.utc)
    rows = []
    for index in range(210):
        open_time = first_open + duration(Timeframe.FOUR_HOUR) * index
        close = Decimal("100") + Decimal(index) / Decimal("10")
        rows.append({
            "candle_id": uuid4(), "asset_id": asset_id, "mapping_id": mapping_id,
            "source_version_id": metadata.source_version_id, "source_id": "gate-spot-usdt",
            "normalizer_version": metadata.normalizer_version, "timeframe": "4h",
            "open_time": open_time, "close_time": open_time + duration(Timeframe.FOUR_HOUR),
            "open": close, "high": close + 1, "low": close - 1, "close": close,
            "base_volume": Decimal("1"), "quote_volume": Decimal("100"), "trade_count": 1,
            "provider_closed": True, "status": "VALID",
            "source_payload_hash": sha256(f"{index}".encode()).hexdigest(),
            "ingested_at": UTC_NOW, "run_id": run_id,
        })
    with clean_database.begin() as connection:
        connection.execute(CanonicalCandleRecord.__table__.insert(), rows)
        metadata._persist_indicators(connection, symbol="BTC", timeframe=Timeframe.FOUR_HOUR, run_id=run_id, computed_at=UTC_NOW)
    target = rows[100]
    before = None
    with clean_database.connect() as connection:
        before = connection.execute(select(AssetIndicator.ema200).where(AssetIndicator.series_version == metadata.series_version, AssetIndicator.asset_id == asset_id, AssetIndicator.timeframe == "4h", AssetIndicator.candle_time == rows[209]["open_time"])).scalar_one()
    replacement = {
        "open": target["open"], "high": target["high"] + 20, "low": target["low"],
        "close": target["close"] + 20, "base_volume": target["base_volume"],
        "quote_volume": target["quote_volume"], "trade_count": target["trade_count"],
        "provider_closed": True, "close_time": target["close_time"],
        "source_payload_hash": "e" * 64,
    }
    report = HistoricalRecomputeService(clean_database, bundle, as_of=UTC_NOW).repair_and_recompute(
        asset_id=asset_id, timeframe=Timeframe.FOUR_HOUR, from_boundary=target["open_time"],
        mapping_id=mapping_id, replacement=replacement, reason="fixture historical repair",
    )
    assert report.status == "SUCCEEDED"
    assert report.repaired is True
    with clean_database.connect() as connection:
        output = connection.execute(select(RecomputeOutput).where(RecomputeOutput.run_id == report.run_id, RecomputeOutput.output_type == "INDICATOR", RecomputeOutput.asset_id == asset_id, RecomputeOutput.candle_time == rows[209]["open_time"])).mappings().one()
        audit = connection.execute(select(CanonicalCandleRepair).where(CanonicalCandleRepair.run_id == report.run_id)).mappings().one()
        earlier = connection.execute(select(AssetIndicator.ema200).where(AssetIndicator.series_version == metadata.series_version, AssetIndicator.asset_id == asset_id, AssetIndicator.timeframe == "4h", AssetIndicator.candle_time == rows[50]["open_time"])).scalar_one()
    assert Decimal(output["payload"]["ema200"]) != before
    assert audit["replacement_payload_hash"] == "e" * 64
    assert earlier is None
    with clean_database.begin() as connection:
        tables = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='breadth_v2' AND tablename <> 'alembic_version'")).scalars().all()
        connection.exec_driver_sql("TRUNCATE " + ", ".join(f'breadth_v2."{table}"' for table in tables) + " RESTART IDENTITY CASCADE")
