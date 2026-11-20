"""Persist revocable login sessions without storing browser identifiers."""
from alembic import op
import sqlalchemy as sa

revision = "c211120a009"
down_revision = "c211119a008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade():
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_table("auth_sessions")
