import pytest

pytest.importorskip("sqlalchemy")

from src.crypto_breadth_v2.storage.database import (
    UnsupportedDatabaseError,
    create_postgres_engine,
)


def test_v2_persistence_rejects_sqlite_as_semantic_authority():
    with pytest.raises(UnsupportedDatabaseError, match="requires PostgreSQL"):
        create_postgres_engine("sqlite+pysqlite:///:memory:")
