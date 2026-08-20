from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from src.crypto_breadth_v2.storage.database import transaction
from src.crypto_breadth_v2.storage.models import (
    Asset,
    BreadthSnapshot,
    CanonicalCandleRecord,
    DataSource,
    ScannerStateRecord,
    SnapshotMember,
    SourceVersion,
)
from src.crypto_breadth_v2.storage.repositories import (
    AdvisoryLockRepository,
    CanonicalCandleConflictError,
    CanonicalCandleRepository,
    IngestionRunRepository,
    SnapshotQueryRepository,
    SnapshotRepository,
)

from .conftest import (
    ALEMBIC_CONFIG,
    ASSET_ID,
    MAPPING_ID,
    OTHER_ASSET_ID,
    RUN_ID,
    UTC_NOW,
    candle_values,
)


EXPECTED_TABLES = {
    "assets",
    "asset_indicators",
    "breadth_snapshots",
    "canonical_candles",
    "data_sources",
    "ingestion_errors",
    "ingestion_runs",
    "provider_mappings",
    "scanner_state",
    "series_definitions",
    "snapshot_members",
    "source_artifacts",
    "source_policy_mappings",
    "source_policy_versions",
    "source_versions",
    "timeframe_cohorts",
    "universe_memberships",
    "universe_versions",
}


def snapshot_values(*, snapshot_id=None, candle_time=UTC_NOW):
    return {
        "snapshot_id": snapshot_id or UUID("50000000-0000-0000-0000-000000000001"),
        "series_version": "breadth-live-v2",
        "series_kind": "LIVE",
        "universe_version": "BR1-BREADTH-UNIVERSE-v1",
        "source_policy_version": "source-policy-v1",
        "formula_version": "Breadth-Formula-v1",
        "normalizer_version": "normalizer-v2",
        "timeframe": "4h",
        "candle_time": candle_time,
        "pct_above_ema20": Decimal("50.000000"),
        "pct_above_ema50": Decimal("50.000000"),
        "pct_above_ema200": Decimal("50.000000"),
        "breadth_score": Decimal("50.000000"),
        "numerator20": 1,
        "numerator50": 1,
        "numerator200": 1,
        "universe_size": 2,
        "cohort_size": 1,
        "structural_coverage": Decimal("0.50000000"),
        "component_coverage": Decimal("1.00000000"),
        "data_quality_score": Decimal("80.0"),
        "data_quality_label": "HIGH",
        "btc_close": Decimal("12349.987654321098765432"),
        "eth_close": Decimal("2500.000000000000000000"),
        "status": "PUBLISHED",
        "computed_at": UTC_NOW,
        "run_id": RUN_ID,
    }


def member_values(snapshot_id, *, asset_id=ASSET_ID, mapping_id=MAPPING_ID):
    return {
        "snapshot_id": snapshot_id,
        "asset_id": asset_id,
        "mapping_id": mapping_id,
        "source_id": "kraken-spot-usd",
        "close": Decimal("12349.987654321098765432"),
        "ema20": Decimal("12000.000000000000000000"),
        "ema50": Decimal("11000.000000000000000000"),
        "ema200": Decimal("10000.000000000000000000"),
        "above20": True,
        "above50": True,
        "above200": True,
        "state20": "ABOVE",
        "state50": "ABOVE",
        "state200": "ABOVE",
        "included_in_denominator": True,
    }


def scanner_values(snapshot_id, *, candle_time=UTC_NOW):
    return {
        "series_version": "breadth-live-v2",
        "timeframe": "4h",
        "asset_id": ASSET_ID,
        "candle_time": candle_time,
        "price": Decimal("12349.987654321098765432"),
        "ema20": Decimal("12000.000000000000000000"),
        "ema50": Decimal("11000.000000000000000000"),
        "ema200": Decimal("10000.000000000000000000"),
        "state20": "ABOVE",
        "state50": "ABOVE",
        "state200": "ABOVE",
        "included_in_breadth": True,
        "mapping_id": MAPPING_ID,
        "source_id": "kraken-spot-usd",
        "snapshot_id": snapshot_id,
        "updated_at": candle_time,
    }


def test_fresh_migration_and_reversible_cycle(engine):
    command.downgrade(ALEMBIC_CONFIG, "base")
    with engine.connect() as connection:
        assert inspect(connection).get_table_names(schema="breadth_v2") == ["alembic_version"]
    command.upgrade(ALEMBIC_CONFIG, "head")
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names(schema="breadth_v2"))
    assert tables == EXPECTED_TABLES | {"alembic_version"}


def test_migration_coexists_with_legacy_public_table(engine):
    command.downgrade(ALEMBIC_CONFIG, "base")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS public.breadth_snapshots "
            "(probe_id integer PRIMARY KEY, marker text NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO public.breadth_snapshots VALUES (1, 'legacy') "
            "ON CONFLICT (probe_id) DO UPDATE SET marker = EXCLUDED.marker"
        )
    command.upgrade(ALEMBIC_CONFIG, "head")
    with engine.begin() as connection:
        marker = connection.exec_driver_sql(
            "SELECT marker FROM public.breadth_snapshots WHERE probe_id = 1"
        ).scalar_one()
        assert marker == "legacy"
        connection.exec_driver_sql("DROP TABLE public.breadth_snapshots")


def test_numeric_and_timestamptz_round_trip_without_loss(seeded_database):
    offset_time = UTC_NOW.astimezone(timezone(timedelta(hours=2)))
    values = candle_values()
    values["ingested_at"] = offset_time
    with seeded_database.begin() as connection:
        connection.execute(CanonicalCandleRecord.__table__.insert().values(**values))
        row = connection.execute(
            select(CanonicalCandleRecord).where(
                CanonicalCandleRecord.candle_id == values["candle_id"]
            )
        ).mappings().one()
    assert row["open"] == Decimal("12345.123456789012345678")
    assert row["close"] == Decimal("12349.987654321098765432")
    assert row["base_volume"] == Decimal("0.000000000000000001")
    assert row["ingested_at"] == UTC_NOW
    assert row["ingested_at"].utcoffset() == timedelta(0)


def test_canonical_candle_idempotency_and_conflict(seeded_database):
    repository = CanonicalCandleRepository()
    values = candle_values()
    with seeded_database.begin() as connection:
        first = repository.put(connection, values)
        second = repository.put(connection, {**values, "candle_id": uuid4()})
        assert first == second
        with pytest.raises(CanonicalCandleConflictError):
            repository.put(
                connection,
                {**values, "candle_id": uuid4(), "source_payload_hash": "9" * 64},
            )


def test_mapping_asset_foreign_key_integrity(seeded_database):
    values = candle_values()
    values["asset_id"] = OTHER_ASSET_ID
    with pytest.raises(IntegrityError):
        with seeded_database.begin() as connection:
            connection.execute(CanonicalCandleRecord.__table__.insert().values(**values))


def test_candle_mapping_and_source_version_must_share_source(seeded_database):
    other_source_version = uuid4()
    with seeded_database.begin() as connection:
        connection.execute(
            DataSource.__table__.insert().values(
                source_id="other-spot-usd",
                provider="other",
                venue="other",
                market_type="SPOT",
                api_base_url="https://example.invalid/other",
                terms_url="https://example.invalid/other/terms",
                terms_review_status="ACCEPTED",
                active=True,
            )
        )
        connection.execute(
            SourceVersion.__table__.insert().values(
                source_version_id=other_source_version,
                source_id="other-spot-usd",
                adapter_version="other-v1",
                api_contract_date=UTC_NOW,
                api_schema_hash="7" * 64,
                archive_release="NONE",
                effective_from=UTC_NOW,
            )
        )
    values = candle_values()
    values["source_version_id"] = other_source_version
    with pytest.raises(IntegrityError):
        with seeded_database.begin() as connection:
            connection.execute(CanonicalCandleRecord.__table__.insert().values(**values))


def test_versioned_identity_is_immutable(seeded_database):
    with pytest.raises(DBAPIError) as caught:
        with seeded_database.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE breadth_v2.series_definitions "
                "SET formula_version = 'mutated' WHERE series_version = 'breadth-live-v2'"
            )
    assert getattr(caught.value.orig, "sqlstate", None) == "55000"


def test_transaction_rolls_back(seeded_database):
    marker = uuid4()
    with pytest.raises(RuntimeError, match="force rollback"):
        with transaction(seeded_database) as connection:
            connection.execute(
                Asset.__table__.insert().values(
                    asset_id=marker,
                    canonical_id="rollback-probe",
                    symbol="ROLLBACK",
                    display_name="Rollback Probe",
                    status="ACTIVE",
                )
            )
            raise RuntimeError("force rollback")
    with seeded_database.connect() as connection:
        assert connection.scalar(select(Asset.asset_id).where(Asset.asset_id == marker)) is None


def test_ingestion_run_lifecycle_and_error_persistence(seeded_database):
    repository = IngestionRunRepository()
    run_id = uuid4()
    with seeded_database.begin() as connection:
        returned_id = repository.start(
            connection,
            {
                "run_id": run_id,
                "run_type": "INCREMENTAL",
                "series_version": "breadth-live-v2",
                "source_id": "kraken-spot-usd",
                "timeframe": "4h",
                "target_start": UTC_NOW,
                "target_end": UTC_NOW,
                "started_at": UTC_NOW,
                "status": "RUNNING",
                "attempt": 1,
                "expected_count": 1,
                "received_count": 0,
                "valid_count": 0,
                "quarantined_count": 0,
                "code_sha": "a" * 40,
                "config_hash": "b" * 64,
                "metrics": {},
            },
        )
        assert returned_id == run_id
        error_id = repository.record_error(
            connection,
            {
                "run_id": run_id,
                "source_id": "kraken-spot-usd",
                "mapping_id": MAPPING_ID,
                "asset_id": ASSET_ID,
                "timeframe": "4h",
                "candle_time": UTC_NOW,
                "error_code": "FIXTURE_ERROR",
                "retryable": True,
                "message": "provider fixture rejected",
                "occurred_at": UTC_NOW,
            },
        )
        assert error_id > 0
        repository.finish(
            connection,
            run_id,
            status="SUCCEEDED",
            finished_at=UTC_NOW,
            counts={
                "received_count": 1,
                "valid_count": 1,
                "quarantined_count": 0,
            },
        )
    with seeded_database.connect() as connection:
        row = connection.execute(
            text(
                "SELECT status, received_count, valid_count "
                "FROM breadth_v2.ingestion_runs WHERE run_id = :run_id"
            ),
            {"run_id": run_id},
        ).one()
    assert row == ("SUCCEEDED", 1, 1)


def test_duplicate_snapshot_prevented(seeded_database):
    first = snapshot_values()
    second = snapshot_values(snapshot_id=uuid4())
    with pytest.raises(IntegrityError):
        with seeded_database.begin() as connection:
            connection.execute(BreadthSnapshot.__table__.insert().values(**first))
            connection.execute(BreadthSnapshot.__table__.insert().values(**second))


def test_snapshot_member_atomic_rollback(seeded_database):
    repository = SnapshotRepository()
    snapshot = snapshot_values()
    invalid_member = member_values(
        snapshot["snapshot_id"], asset_id=OTHER_ASSET_ID, mapping_id=MAPPING_ID
    )
    with pytest.raises(IntegrityError):
        repository.publish_atomic(seeded_database, snapshot, [invalid_member])
    with seeded_database.connect() as connection:
        assert connection.scalar(
            select(BreadthSnapshot.snapshot_id).where(
                BreadthSnapshot.snapshot_id == snapshot["snapshot_id"]
            )
        ) is None


def test_scanner_key_upsert_and_read_query(seeded_database):
    repository = SnapshotRepository()
    query = SnapshotQueryRepository()
    first = snapshot_values()
    repository.publish_atomic(
        seeded_database,
        first,
        [member_values(first["snapshot_id"])],
        [scanner_values(first["snapshot_id"])],
    )
    later_time = UTC_NOW + timedelta(hours=4)
    second = snapshot_values(snapshot_id=uuid4(), candle_time=later_time)
    repository.publish_atomic(
        seeded_database,
        second,
        [member_values(second["snapshot_id"])],
        [scanner_values(second["snapshot_id"], candle_time=later_time)],
    )
    with seeded_database.connect() as connection:
        scanner_rows = connection.scalar(select(text("count(*)")).select_from(ScannerStateRecord))
        scanner_time = connection.scalar(select(ScannerStateRecord.candle_time))
        latest = query.latest_published(connection, "breadth-live-v2", "4h")
    assert scanner_rows == 1
    assert scanner_time == later_time
    assert latest is not None
    assert latest["snapshot_id"] == second["snapshot_id"]


def test_advisory_transaction_lock_excludes_concurrent_writer(seeded_database):
    locks = AdvisoryLockRepository()
    first = seeded_database.connect()
    second = seeded_database.connect()
    first_tx = first.begin()
    second_tx = second.begin()
    try:
        assert locks.try_transaction_lock(first, 84102002) is True
        assert locks.try_transaction_lock(second, 84102002) is False
        first_tx.commit()
        assert locks.try_transaction_lock(second, 84102002) is True
        second_tx.commit()
    finally:
        if first_tx.is_active:
            first_tx.rollback()
        if second_tx.is_active:
            second_tx.rollback()
        first.close()
        second.close()


def test_reader_role_can_select_but_not_write(seeded_database):
    roles_sql = (Path(__file__).resolve().parents[2] / "sql" / "breadth_v2_roles.sql").read_text()
    with seeded_database.begin() as connection:
        connection.exec_driver_sql(roles_sql)
        current_user = connection.exec_driver_sql("SELECT current_user").scalar_one()
        quoted_user = connection.dialect.identifier_preparer.quote(current_user)
        connection.exec_driver_sql(f"GRANT breadth_v2_reader TO {quoted_user}")
    with pytest.raises(DBAPIError):
        with seeded_database.connect() as connection:
            transaction_handle = connection.begin()
            connection.exec_driver_sql("SET LOCAL ROLE breadth_v2_reader")
            assert connection.exec_driver_sql(
                "SELECT count(*) FROM breadth_v2.assets"
            ).scalar_one() == 2
            connection.exec_driver_sql(
                "INSERT INTO breadth_v2.assets "
                "(asset_id, canonical_id, symbol, display_name, status) "
                "VALUES ('90000000-0000-0000-0000-000000000001', 'forbidden', 'NOPE', 'Nope', 'ACTIVE')"
            )
            transaction_handle.commit()
