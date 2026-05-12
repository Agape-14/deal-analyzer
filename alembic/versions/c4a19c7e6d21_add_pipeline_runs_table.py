"""add_pipeline_runs_table

Revision ID: c4a19c7e6d21
Revises: bd9429f9dfc7
Create Date: 2026-05-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4a19c7e6d21"
down_revision: Union[str, Sequence[str], None] = "bd9429f9dfc7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("pipeline_runs"):
        op.create_table(
            "pipeline_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("deal_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=True),
            sa.Column("current_step", sa.String(length=50), nullable=True),
            sa.Column("trigger", sa.String(length=50), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("steps", sa.JSON(), nullable=True),
            sa.Column("summary", sa.JSON(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["deal_id"], ["deals.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("pipeline_runs")}
    for index_name, columns in (
        ("ix_pipeline_runs_id", ["id"]),
        ("ix_pipeline_runs_deal_id", ["deal_id"]),
        ("ix_pipeline_runs_status", ["status"]),
        ("ix_pipeline_runs_started_at", ["started_at"]),
        ("ix_pipeline_runs_updated_at", ["updated_at"]),
        ("ix_pipeline_runs_finished_at", ["finished_at"]),
    ):
        if index_name not in existing_indexes:
            op.create_index(index_name, "pipeline_runs", columns, unique=False)


def downgrade() -> None:
    with op.batch_alter_table("pipeline_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pipeline_runs_finished_at"))
        batch_op.drop_index(batch_op.f("ix_pipeline_runs_updated_at"))
        batch_op.drop_index(batch_op.f("ix_pipeline_runs_started_at"))
        batch_op.drop_index(batch_op.f("ix_pipeline_runs_status"))
        batch_op.drop_index(batch_op.f("ix_pipeline_runs_deal_id"))
        batch_op.drop_index(batch_op.f("ix_pipeline_runs_id"))
    op.drop_table("pipeline_runs")
