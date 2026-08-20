"""Small PostgreSQL repositories with explicit transactional contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, Select, select, text
from sqlalchemy.dialects.postgresql import insert

from .database import transaction
from .models import (
    BreadthSnapshot,
    CanonicalCandleRecord,
    IngestionError,
    IngestionRun,
    ScannerStateRecord,
    SnapshotMember,
)


class CanonicalCandleConflictError(RuntimeError):
    """The canonical key already exists with different normalized content."""


class CanonicalCandleRepository:
    _key_columns = ("mapping_id", "timeframe", "open_time", "normalizer_version")

    def put(self, connection: Connection, values: Mapping[str, Any]) -> UUID:
        """Insert once, or return the existing identical record.

        The canonical key is idempotent only when the source payload hash is
        identical. A changed payload must enter an explicit future repair flow;
        it is never silently overwritten.
        """
        statement = (
            insert(CanonicalCandleRecord)
            .values(**values)
            .on_conflict_do_nothing(index_elements=list(self._key_columns))
            .returning(CanonicalCandleRecord.candle_id)
        )
        candle_id = connection.execute(statement).scalar_one_or_none()
        if candle_id is not None:
            return candle_id

        key = {column: values[column] for column in self._key_columns}
        existing = connection.execute(
            select(
                CanonicalCandleRecord.candle_id,
                CanonicalCandleRecord.source_payload_hash,
            ).filter_by(**key)
        ).one()
        if existing.source_payload_hash != values["source_payload_hash"]:
            raise CanonicalCandleConflictError(
                "canonical candle key already contains a different payload hash"
            )
        return existing.candle_id


class IngestionRunRepository:
    def start(self, connection: Connection, values: Mapping[str, Any]) -> UUID:
        return connection.execute(
            insert(IngestionRun).values(**values).returning(IngestionRun.run_id)
        ).scalar_one()

    def finish(
        self,
        connection: Connection,
        run_id: UUID,
        *,
        status: str,
        finished_at: Any,
        counts: Mapping[str, int],
        error_summary: str | None = None,
    ) -> None:
        connection.execute(
            IngestionRun.__table__.update()
            .where(IngestionRun.run_id == run_id)
            .values(
                status=status,
                finished_at=finished_at,
                error_summary=error_summary,
                **counts,
            )
        )

    def record_error(self, connection: Connection, values: Mapping[str, Any]) -> int:
        return connection.execute(
            insert(IngestionError).values(**values).returning(IngestionError.error_id)
        ).scalar_one()


class SnapshotRepository:
    def publish_atomic(
        self,
        engine: Engine,
        snapshot: Mapping[str, Any],
        members: Iterable[Mapping[str, Any]],
        scanner_rows: Iterable[Mapping[str, Any]] = (),
    ) -> UUID:
        """Persist snapshot, members, and scanner projection in one transaction."""
        with transaction(engine) as connection:
            snapshot_id = connection.execute(
                insert(BreadthSnapshot)
                .values(**snapshot)
                .returning(BreadthSnapshot.snapshot_id)
            ).scalar_one()
            member_values = list(members)
            if member_values:
                connection.execute(insert(SnapshotMember), member_values)
            for row in scanner_rows:
                statement = insert(ScannerStateRecord).values(**row)
                connection.execute(
                    statement.on_conflict_do_update(
                        index_elements=["series_version", "timeframe", "asset_id"],
                        set_={
                            column.name: getattr(statement.excluded, column.name)
                            for column in ScannerStateRecord.__table__.columns
                            if column.name not in {"series_version", "timeframe", "asset_id"}
                        },
                    )
                )
        return snapshot_id


class SnapshotQueryRepository:
    @staticmethod
    def latest_published_statement(series_version: str, timeframe: str) -> Select[Any]:
        return (
            select(BreadthSnapshot)
            .where(
                BreadthSnapshot.series_version == series_version,
                BreadthSnapshot.timeframe == timeframe,
                BreadthSnapshot.status == "PUBLISHED",
            )
            .order_by(BreadthSnapshot.candle_time.desc())
            .limit(1)
        )

    def latest_published(
        self, connection: Connection, series_version: str, timeframe: str
    ) -> Mapping[str, Any] | None:
        row = connection.execute(
            self.latest_published_statement(series_version, timeframe)
        ).mappings().one_or_none()
        return row


class AdvisoryLockRepository:
    def try_transaction_lock(self, connection: Connection, lock_key: int) -> bool:
        return bool(
            connection.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
                {"lock_key": lock_key},
            ).scalar_one()
        )
