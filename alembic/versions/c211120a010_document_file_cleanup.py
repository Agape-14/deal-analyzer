"""Retry removal of document files after committed deletion."""
from alembic import op
import sqlalchemy as sa

revision = "c211120a010"
down_revision = "c211120a009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "document_file_cleanup",
        sa.Column("relative_path", sa.String(1024), primary_key=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_document_file_cleanup_next_attempt_at", "document_file_cleanup", ["next_attempt_at"])


def downgrade():
    op.drop_index("ix_document_file_cleanup_next_attempt_at", table_name="document_file_cleanup")
    op.drop_table("document_file_cleanup")
