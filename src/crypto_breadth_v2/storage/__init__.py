"""PostgreSQL-only persistence foundation for the v2 core."""

from .database import create_postgres_engine, transaction
from .repositories import (
    AdvisoryLockRepository,
    CanonicalCandleConflictError,
    CanonicalCandleRepository,
    IngestionRunRepository,
    SnapshotQueryRepository,
    SnapshotRepository,
)

__all__ = [
    "AdvisoryLockRepository",
    "CanonicalCandleConflictError",
    "CanonicalCandleRepository",
    "IngestionRunRepository",
    "SnapshotQueryRepository",
    "SnapshotRepository",
    "create_postgres_engine",
    "transaction",
]
