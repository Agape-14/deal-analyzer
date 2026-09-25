"""Retain originals and record explicit document version choices."""
from alembic import op
import sqlalchemy as sa

revision = "c210925a004"
down_revision = "c210925a003"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("deal_documents"):
        return
    existing = {c["name"] for c in inspector.get_columns("deal_documents")}
    for column in (
        sa.Column("source_role", sa.String(20), nullable=False, server_default="active"),
        sa.Column("superseded_by_id", sa.Integer(), nullable=True),
        sa.Column("version_note", sa.Text(), nullable=False, server_default=""),
    ):
        if column.name not in existing:
            op.add_column("deal_documents", column)


def downgrade():
    with op.batch_alter_table("deal_documents") as batch:
        for name in ("version_note", "superseded_by_id", "source_role"):
            batch.drop_column(name)
