from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from sqlalchemy import func, select

from src.crypto_breadth_v2.bootstrap import GateBootstrapService
from src.crypto_breadth_v2.candles import CanonicalCandle
from src.crypto_breadth_v2.contracts import load_contract_bundle
from src.crypto_breadth_v2.providers.gate import GateCandleEnvelope, GateRequestStats, load_gate_mappings
from src.crypto_breadth_v2.storage.models import CanonicalCandleRecord
from src.crypto_breadth_v2.timeframes import Timeframe, duration


UTC = timezone.utc
AS_OF = datetime(2026, 8, 20, 12, tzinfo=UTC)


class FakeGateClient:
    def __init__(self, mapping, *, conflict=False):
        self.mapping = mapping
        self.conflict = conflict
        self.stats = GateRequestStats()

    def fetch_range(self, symbol, *, timeframe, start, end, as_of, allow_empty_pages):
        self.stats.http_calls += 1
        rows = []
        current = start
        index = 0
        while current < end:
            value = Decimal("100") + Decimal(index) / Decimal("1000")
            candle = CanonicalCandle(
                asset_id=self.mapping.canonical_id,
                timeframe=timeframe,
                open_time=current,
                close_time=current + duration(timeframe),
                open=value,
                high=value + Decimal("1"),
                low=value - Decimal("1"),
                close=value + Decimal("0.1"),
                base_volume=Decimal("10"),
                quote_volume=Decimal("100"),
                trade_count=1,
            )
            payload_hash = sha256(f"{symbol}|{timeframe.value}|{current.isoformat()}".encode()).hexdigest()
            if self.conflict and index == 0:
                payload_hash = "f" * 64
            rows.append(GateCandleEnvelope(self.mapping, candle, payload_hash, ("fixture",)))
            current += duration(timeframe)
            index += 1
        return tuple(reversed(rows))


class OneAssetBootstrap(GateBootstrapService):
    @property
    def symbols(self):
        return ("BTC",)


def test_bootstrap_replay_is_resumable_and_conflicts_are_quarantined(clean_database):
    bundle = load_contract_bundle(Path("config/v2"), bundle="v2-40")
    mapping = load_gate_mappings(bundle)["BTC"]
    client = FakeGateClient(mapping)
    service = OneAssetBootstrap(clean_database, client, bundle, as_of=AS_OF)
    service.ensure_metadata()

    first = service._bootstrap_native("BTC", Timeframe.DAILY)
    second = service._bootstrap_native("BTC", Timeframe.DAILY)
    assert first.received == 1500
    assert second.received == 1500
    assert second.valid == 1500
    with clean_database.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(CanonicalCandleRecord)) == 1500

    client.conflict = True
    conflict = service._bootstrap_native("BTC", Timeframe.DAILY)
    assert conflict.quarantined == 1
    assert conflict.valid == 1499

    weekly = service._derive_weekly("BTC")
    assert weekly.timeframe is Timeframe.WEEKLY
    assert weekly.diagnostics.total_candles >= 200
    assert weekly.diagnostics.eligible
