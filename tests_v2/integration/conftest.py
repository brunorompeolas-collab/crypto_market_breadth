from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")
pytest.importorskip("alembic")
pytest.importorskip("psycopg")

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from src.crypto_breadth_v2.storage.database import create_postgres_engine
from src.crypto_breadth_v2.storage.models import (
    Asset,
    DataSource,
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


DATABASE_URL = os.environ.get("BREADTH_V2_TEST_DATABASE_URL")
if not DATABASE_URL:
    pytest.skip(
        "set BREADTH_V2_TEST_DATABASE_URL to run PostgreSQL acceptance tests",
        allow_module_level=True,
    )

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG = Config(str(ROOT / "alembic.ini"))
ALEMBIC_CONFIG.set_main_option("script_location", str(ROOT / "migrations"))
ALEMBIC_CONFIG.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

ASSET_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_ASSET_ID = UUID("00000000-0000-0000-0000-000000000002")
SOURCE_VERSION_ID = UUID("10000000-0000-0000-0000-000000000001")
MAPPING_ID = UUID("20000000-0000-0000-0000-000000000001")
RUN_ID = UUID("30000000-0000-0000-0000-000000000001")
UTC_NOW = datetime(2026, 8, 20, 20, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="session")
def database_url() -> str:
    return DATABASE_URL


@pytest.fixture(scope="session")
def engine(database_url):
    result = create_postgres_engine(database_url)
    command.upgrade(ALEMBIC_CONFIG, "head")
    yield result
    result.dispose()


@pytest.fixture()
def clean_database(engine):
    with engine.begin() as connection:
        tables = connection.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'breadth_v2' AND tablename <> 'alembic_version'"
            )
        ).scalars().all()
        if tables:
            qualified = ", ".join(f'breadth_v2."{table}"' for table in tables)
            connection.exec_driver_sql(f"TRUNCATE {qualified} RESTART IDENTITY CASCADE")
    return engine


@pytest.fixture()
def seeded_database(clean_database):
    with clean_database.begin() as connection:
        connection.execute(
            Asset.__table__.insert(),
            [
                {
                    "asset_id": ASSET_ID,
                    "canonical_id": "bitcoin",
                    "symbol": "BTC",
                    "display_name": "Bitcoin",
                    "status": "ACTIVE",
                },
                {
                    "asset_id": OTHER_ASSET_ID,
                    "canonical_id": "ethereum",
                    "symbol": "ETH",
                    "display_name": "Ethereum",
                    "status": "ACTIVE",
                },
            ],
        )
        connection.execute(
            DataSource.__table__.insert().values(
                source_id="kraken-spot-usd",
                provider="kraken",
                venue="kraken",
                market_type="SPOT",
                api_base_url="https://example.invalid",
                terms_url="https://example.invalid/terms",
                terms_review_status="ACCEPTED",
                active=True,
            )
        )
        connection.execute(
            SourceVersion.__table__.insert().values(
                source_version_id=SOURCE_VERSION_ID,
                source_id="kraken-spot-usd",
                adapter_version="adapter-v1",
                api_contract_date=UTC_NOW,
                api_schema_hash="a" * 64,
                archive_release="NONE",
                effective_from=UTC_NOW,
            )
        )
        connection.execute(
            ProviderMapping.__table__.insert().values(
                mapping_id=MAPPING_ID,
                asset_id=ASSET_ID,
                source_id="kraken-spot-usd",
                provider_asset_id="XXBT",
                base_code="XBT",
                quote_code="USD",
                instrument_id="XXBTZUSD",
                mapping_version="mapping-v1",
                valid_from=UTC_NOW,
                status="ACTIVE",
            )
        )
        connection.execute(
            UniverseVersion.__table__.insert().values(
                universe_version="BR1-BREADTH-UNIVERSE-v1",
                name="BR1 Breadth Universe",
                series_kind="LIVE",
                status="ACTIVE",
                inception_at=UTC_NOW,
                expected_size=2,
                definition_hash="b" * 64,
            )
        )
        connection.execute(
            UniverseMembership.__table__.insert(),
            [
                {
                    "universe_version": "BR1-BREADTH-UNIVERSE-v1",
                    "asset_id": ASSET_ID,
                    "ordinal": 1,
                    "included_from": UTC_NOW,
                },
                {
                    "universe_version": "BR1-BREADTH-UNIVERSE-v1",
                    "asset_id": OTHER_ASSET_ID,
                    "ordinal": 2,
                    "included_from": UTC_NOW,
                },
            ],
        )
        connection.execute(
            SourcePolicyVersion.__table__.insert().values(
                source_policy_version="source-policy-v1",
                status="ACTIVE",
                definition_hash="c" * 64,
                effective_from=UTC_NOW,
            )
        )
        connection.execute(
            SourcePolicyMapping.__table__.insert().values(
                source_policy_version="source-policy-v1",
                asset_id=ASSET_ID,
                mapping_id=MAPPING_ID,
            )
        )
        connection.execute(
            SeriesDefinition.__table__.insert().values(
                series_version="breadth-live-v2",
                series_kind="LIVE",
                universe_version="BR1-BREADTH-UNIVERSE-v1",
                source_policy_version="source-policy-v1",
                formula_version="Breadth-Formula-v1",
                normalizer_version="normalizer-v2",
                methodology_version="methodology-v2",
                inception_at=UTC_NOW,
                definition_hash="d" * 64,
                status="ACTIVE",
            )
        )
        connection.execute(
            TimeframeCohort.__table__.insert().values(
                series_version="breadth-live-v2",
                timeframe="4h",
                asset_id=ASSET_ID,
                included_in_denominator=True,
                history_count_at_inception=200,
                eligibility_reason="EMA200_ELIGIBLE",
                frozen_at=UTC_NOW,
            )
        )
        connection.execute(
            IngestionRun.__table__.insert().values(
                run_id=RUN_ID,
                run_type="BOOTSTRAP",
                series_version="breadth-live-v2",
                source_id="kraken-spot-usd",
                timeframe="4h",
                target_start=UTC_NOW,
                target_end=UTC_NOW,
                started_at=UTC_NOW,
                status="RUNNING",
                attempt=1,
                expected_count=0,
                received_count=0,
                valid_count=0,
                quarantined_count=0,
                code_sha="e" * 40,
                config_hash="f" * 64,
                metrics={},
            )
        )
    return clean_database


def candle_values(*, payload_hash: str = "1" * 64, candle_id=None):
    return {
        "candle_id": candle_id or UUID("40000000-0000-0000-0000-000000000001"),
        "asset_id": ASSET_ID,
        "mapping_id": MAPPING_ID,
        "source_version_id": SOURCE_VERSION_ID,
        "source_id": "kraken-spot-usd",
        "normalizer_version": "normalizer-v2",
        "timeframe": "4h",
        "open_time": UTC_NOW,
        "close_time": datetime(2026, 8, 21, 0, 0, tzinfo=timezone.utc),
        "open": Decimal("12345.123456789012345678"),
        "high": Decimal("12350.123456789012345678"),
        "low": Decimal("12340.123456789012345678"),
        "close": Decimal("12349.987654321098765432"),
        "base_volume": Decimal("0.000000000000000001"),
        "quote_volume": Decimal("999.999999999999999999"),
        "trade_count": 42,
        "provider_closed": True,
        "status": "VALID",
        "source_payload_hash": payload_hash,
        "ingested_at": UTC_NOW,
        "run_id": RUN_ID,
    }
