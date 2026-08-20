"""PostgreSQL engine and transaction boundaries."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.engine import make_url


class UnsupportedDatabaseError(ValueError):
    pass


def create_postgres_engine(database_url: str, **kwargs: object) -> Engine:
    """Create a PostgreSQL engine and force UTC session semantics.

    V2 intentionally rejects SQLite and other dialects so they cannot become
    accidental semantic authorities for persistence behavior.
    """
    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise UnsupportedDatabaseError("breadth_v2 persistence requires PostgreSQL")
    connect_args = dict(kwargs.pop("connect_args", {}))
    # Set UTC in PostgreSQL's startup packet. A connect-event SET can be rolled
    # back by a driver's initial transaction reset before first checkout.
    connect_args.setdefault("options", "-c timezone=UTC")
    engine = create_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
        **kwargs,
    )

    @event.listens_for(engine, "connect")
    def _set_utc(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET TIME ZONE 'UTC'")
        finally:
            cursor.close()

    return engine


@contextmanager
def transaction(engine: Engine) -> Iterator[Connection]:
    """Atomic writer transaction; exceptions always roll back."""
    with engine.begin() as connection:
        yield connection
