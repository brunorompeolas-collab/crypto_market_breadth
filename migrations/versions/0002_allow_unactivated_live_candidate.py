"""allow unactivated LIVE candidate without inception

Revision ID: 0002
Revises: 0001
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_series_definitions_live_requires_inception"),
        "series_definitions",
        schema="breadth_v2",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_series_definitions_live_requires_inception"),
        "series_definitions",
        "series_kind <> 'LIVE' OR status <> 'ACTIVE' OR inception_at IS NOT NULL",
        schema="breadth_v2",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_series_definitions_live_requires_inception"),
        "series_definitions",
        schema="breadth_v2",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_series_definitions_live_requires_inception"),
        "series_definitions",
        "series_kind <> 'LIVE' OR inception_at IS NOT NULL",
        schema="breadth_v2",
    )
