"""versioned analytical outputs for explicit recompute

Revision ID: 0004
Revises: 0003
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recompute_outputs",
        sa.Column("output_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("output_type", sa.String(length=16), nullable=False),
        sa.Column("series_version", sa.String(length=120), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("timeframe", sa.String(length=4), nullable=False),
        sa.Column("candle_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("base_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("output_type IN ('INDICATOR','SNAPSHOT')", name="ck_recompute_outputs_output_type"),
        sa.ForeignKeyConstraint(["run_id"], ["breadth_v2.ingestion_runs.run_id"]),
        sa.ForeignKeyConstraint(["series_version"], ["breadth_v2.series_definitions.series_version"]),
        sa.ForeignKeyConstraint(["asset_id"], ["breadth_v2.assets.asset_id"]),
        sa.ForeignKeyConstraint(["base_snapshot_id"], ["breadth_v2.breadth_snapshots.snapshot_id"]),
        sa.PrimaryKeyConstraint("output_id"),
        sa.UniqueConstraint("run_id", "output_type", "asset_id", "timeframe", "candle_time"),
        schema="breadth_v2",
    )


def downgrade() -> None:
    op.drop_table("recompute_outputs", schema="breadth_v2")

