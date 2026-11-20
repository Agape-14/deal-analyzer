"""Add analysis history and optimistic deal revisions without rewriting facts."""
from alembic import op
import sqlalchemy as sa

revision = "c210925a001"
down_revision = "11d30a33e2fc"
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent with the application's conservative add-only startup patches.
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("deals")}
    for column in (sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
                   sa.Column("analysis_version", sa.Integer(), nullable=False, server_default="0"),
                   sa.Column("analysis_snapshot", sa.JSON(), nullable=True)):
        if column.name not in columns:
            op.add_column("deals", column)
    if not inspector.has_table("analysis_snapshots"):
        op.create_table("analysis_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("deal_id", sa.Integer(), sa.ForeignKey("deals.id"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("input_hash", sa.String(64), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("deal_id", "version", name="uq_analysis_deal_version"))
        op.create_index("ix_analysis_snapshots_deal_id", "analysis_snapshots", ["deal_id"])


def downgrade():
    op.drop_table("analysis_snapshots")
    with op.batch_alter_table("deals") as batch:
        batch.drop_column("analysis_snapshot")
        batch.drop_column("analysis_version")
        batch.drop_column("revision")
