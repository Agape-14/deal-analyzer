"""Persist document review jobs and recovery leases."""
from alembic import op
import sqlalchemy as sa

revision = "c210925a002"
down_revision = "c210925a001"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("review_jobs"):
        op.create_table("review_jobs",
            sa.Column("deal_id", sa.Integer(), sa.ForeignKey("deals.id"), primary_key=True),
            sa.Column("request_seq", sa.Integer(), nullable=False),
            sa.Column("mode", sa.String(20), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("auto_correct", sa.Integer(), nullable=False),
            sa.Column("lease_token", sa.String(64)),
            sa.Column("lease_until", sa.DateTime()),
            sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("error", sa.Text()))
        op.create_index("ix_review_jobs_status", "review_jobs", ["status"])


def downgrade():
    op.drop_table("review_jobs")
