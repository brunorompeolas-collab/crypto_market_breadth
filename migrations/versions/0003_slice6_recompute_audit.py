"""explicit canonical repair audit for Slice 6 recompute

Revision ID: 0003
Revises: 0002
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_candle_repairs",
        sa.Column("repair_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("replacement_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("original_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("replacement_values", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("repaired_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candle_id"], ["breadth_v2.canonical_candles.candle_id"]),
        sa.ForeignKeyConstraint(["run_id"], ["breadth_v2.ingestion_runs.run_id"]),
        sa.PrimaryKeyConstraint("repair_id"),
        sa.UniqueConstraint("run_id", "candle_id"),
        schema="breadth_v2",
    )


def downgrade() -> None:
    op.drop_table("canonical_candle_repairs", schema="breadth_v2")
