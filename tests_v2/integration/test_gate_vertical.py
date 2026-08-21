from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy import text

from src.crypto_breadth_v2.gate_vertical import (
    GatePersistenceContext,
    persist_gate_candles_and_indicators,
)
from src.crypto_breadth_v2.providers.gate import (
    GATE_SOURCE_ID,
    GateClient,
    GateHttpResponse,
    GateMapping,
)
from src.crypto_breadth_v2.storage.models import (
    Asset,
    AssetIndicator,
    CanonicalCandleRecord,
    DataSource,
    IngestionRun,
    ProviderMapping,
    SeriesDefinition,
    SourcePolicyMapping,
    SourcePolicyVersion,
    SourceVersion,
    UniverseMembership,
    UniverseVersion,
)
from src.crypto_breadth_v2.storage.repositories import CanonicalCandleConflictError
from src.crypto_breadth_v2.timeframes import Timeframe


UTC = timezone.utc
ASSET_ID = UUID("01000000-0000-0000-0000-000000000001")
SOURCE_VERSION_ID = UUID("11000000-0000-0000-0000-000000000001")
MAPPING_ID = UUID("21000000-0000-0000-0000-000000000001")
RUN_ID = UUID("31000000-0000-0000-0000-000000000001")
START = datetime(2025, 1, 1, tzinfo=UTC)


class OneResponseTransport:
    def __init__(self, payload):
        self.payload = payload

    def get(self, url, *, params, timeout):
        return GateHttpResponse(200, {}, json.dumps(self.payload).encode())


def gate_daily_rows(count=200):
    rows = []
    for index in range(count):
        open_time = START + timedelta(days=index)
        close = Decimal("100") + Decimal(index) / Decimal("1000")
        open_ = close - Decimal("0.1")
        rows.append(
            [
                str(int(open_time.timestamp())),
                "1000.000000000000000001",
                str(close),
                str(close + Decimal("1")),
                str(open_ - Decimal("1")),
                str(open_),
                "10.000000000000000001",
                "true",
            ]
        )
    return rows


@pytest.fixture()
def gate_seeded_database(clean_database):
    with clean_database.begin() as connection:
        connection.execute(
            Asset.__table__.insert().values(
                asset_id=ASSET_ID,
                canonical_id="bitcoin",
                symbol="BTC",
                display_name="Bitcoin",
                status="ACTIVE",
            )
        )
        connection.execute(
            DataSource.__table__.insert().values(
                source_id=GATE_SOURCE_ID,
                provider="gate",
                venue="gate",
                market_type="SPOT",
                api_base_url="https://api.gateio.ws/api/v4",
                terms_url="https://www.gate.com/docs/agreement.pdf",
                terms_review_status="ACCEPTED",
                active=True,
            )
        )
        connection.execute(
            SourceVersion.__table__.insert().values(
                source_version_id=SOURCE_VERSION_ID,
                source_id=GATE_SOURCE_ID,
                adapter_version="gate-adapter-v1",
                api_contract_date=START,
                api_schema_hash="1" * 64,
                archive_release="NONE",
                effective_from=START,
            )
        )
        connection.execute(
            ProviderMapping.__table__.insert().values(
                mapping_id=MAPPING_ID,
                asset_id=ASSET_ID,
                source_id=GATE_SOURCE_ID,
                provider_asset_id="BTC",
                base_code="BTC",
                quote_code="USDT",
                instrument_id="BTC_USDT",
                mapping_version="BR1-SOURCE-POLICY-v2-GATE-ONLY",
                valid_from=START,
                status="ACTIVE",
            )
        )
        connection.execute(
            UniverseVersion.__table__.insert().values(
                universe_version="BR1-BREADTH-UNIVERSE-v2-40",
                name="BR1 Breadth Universe v2-40",
                series_kind="LIVE",
                status="DRAFT",
                inception_at=None,
                expected_size=40,
                definition_hash="2" * 64,
            )
        )
        connection.execute(
            UniverseMembership.__table__.insert().values(
                universe_version="BR1-BREADTH-UNIVERSE-v2-40",
                asset_id=ASSET_ID,
                ordinal=1,
                included_from=START,
            )
        )
        connection.execute(
            SourcePolicyVersion.__table__.insert().values(
                source_policy_version="BR1-SOURCE-POLICY-v2-GATE-ONLY",
                status="DRAFT",
                definition_hash="3" * 64,
                effective_from=START,
            )
        )
        connection.execute(
            SourcePolicyMapping.__table__.insert().values(
                source_policy_version="BR1-SOURCE-POLICY-v2-GATE-ONLY",
                asset_id=ASSET_ID,
                mapping_id=MAPPING_ID,
            )
        )
        connection.execute(
            SeriesDefinition.__table__.insert().values(
                series_version="BR1-LIVE-v2-40-CANDIDATE",
                series_kind="LIVE",
                universe_version="BR1-BREADTH-UNIVERSE-v2-40",
                source_policy_version="BR1-SOURCE-POLICY-v2-GATE-ONLY",
                formula_version="BR1-BREADTH-FORMULA-v1",
                normalizer_version="BR1-CANDLE-NORMALIZER-v2",
                methodology_version="BR1-METHODOLOGY-v2",
                inception_at=None,
                definition_hash="4" * 64,
                status="CANDIDATE",
            )
        )
        connection.execute(
            IngestionRun.__table__.insert().values(
                run_id=RUN_ID,
                run_type="RECOMPUTE",
                series_version="BR1-LIVE-v2-40-CANDIDATE",
                source_id=GATE_SOURCE_ID,
                timeframe="1d",
                target_start=START,
                target_end=START + timedelta(days=200),
                started_at=START + timedelta(days=201),
                status="RUNNING",
                attempt=1,
                expected_count=200,
                received_count=200,
                valid_count=200,
                quarantined_count=0,
                code_sha="5" * 40,
                config_hash="6" * 64,
                metrics={},
            )
        )
    yield clean_database
    with clean_database.begin() as connection:
        tables = connection.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'breadth_v2' AND tablename <> 'alembic_version'"
            )
        ).scalars().all()
        qualified = ", ".join(f'breadth_v2."{table}"' for table in tables)
        if qualified:
            connection.exec_driver_sql(f"TRUNCATE {qualified} RESTART IDENTITY CASCADE")


def parse_rows(rows):
    mapping = GateMapping("bitcoin", "BTC", "BTC_USDT", "USDT")
    as_of = START + timedelta(days=201)
    return GateClient(
        {"BTC": mapping}, transport=OneResponseTransport(rows)
    ).fetch_candles(
        "BTC", timeframe=Timeframe.DAILY, as_of=as_of, limit=len(rows)
    )


def persistence_context():
    timestamp = START + timedelta(days=201)
    return GatePersistenceContext(
        asset_id=ASSET_ID,
        mapping_id=MAPPING_ID,
        source_version_id=SOURCE_VERSION_ID,
        run_id=RUN_ID,
        series_version="BR1-LIVE-v2-40-CANDIDATE",
        universe_version="BR1-BREADTH-UNIVERSE-v2-40",
        formula_version="BR1-BREADTH-FORMULA-v1",
        normalizer_version="BR1-CANDLE-NORMALIZER-v2",
        ingested_at=timestamp,
        computed_at=timestamp,
    )


def test_gate_fixture_to_postgresql_to_available_ema200(gate_seeded_database):
    envelopes = parse_rows(gate_daily_rows())
    result = persist_gate_candles_and_indicators(
        gate_seeded_database, envelopes, context=persistence_context()
    )
    assert len(result.candle_ids) == 200
    assert result.inserted_indicators == 200
    assert result.latest_close == Decimal("100.199")
    assert result.latest_ema20 is not None
    assert result.latest_ema50 is not None
    assert result.latest_ema200 == Decimal("100.0995")

    with gate_seeded_database.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(CanonicalCandleRecord)) == 200
        assert connection.scalar(select(func.count()).select_from(AssetIndicator)) == 200
        latest = connection.execute(
            select(AssetIndicator)
            .order_by(AssetIndicator.candle_time.desc())
            .limit(1)
        ).mappings().one()
        series = connection.execute(select(SeriesDefinition)).mappings().one()
    assert latest["close"] == Decimal("100.199000000000000000")
    assert latest["ema200"] == Decimal("100.099500000000000000")
    assert latest["ema200_state"] == "AVAILABLE"
    assert series["status"] == "CANDIDATE"
    assert series["inception_at"] is None


def test_gate_vertical_replay_is_idempotent_and_conflict_is_rejected(gate_seeded_database):
    rows = gate_daily_rows()
    envelopes = parse_rows(rows)
    first = persist_gate_candles_and_indicators(
        gate_seeded_database, envelopes, context=persistence_context()
    )
    second = persist_gate_candles_and_indicators(
        gate_seeded_database, envelopes, context=persistence_context()
    )
    assert second.candle_ids == first.candle_ids
    assert second.inserted_indicators == 0

    conflicting_rows = gate_daily_rows()
    conflicting_rows[-1][2] = "999.999"
    conflicting_rows[-1][3] = "1000.999"
    conflicting = parse_rows(conflicting_rows)
    with pytest.raises(CanonicalCandleConflictError, match="different payload"):
        persist_gate_candles_and_indicators(
            gate_seeded_database, conflicting, context=persistence_context()
        )
    with gate_seeded_database.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(CanonicalCandleRecord)) == 200
        assert connection.scalar(select(func.count()).select_from(AssetIndicator)) == 200
