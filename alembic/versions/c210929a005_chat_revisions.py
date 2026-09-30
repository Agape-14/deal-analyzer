"""Label replies with their analysis; keep legacy history intact."""
from alembic import op
import sqlalchemy as sa
revision = "c210929a005"
down_revision = "c210925a004"
branch_labels = None
depends_on = None

def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("deal_chats"):
        return
    existing = {c["name"] for c in inspector.get_columns("deal_chats")}
    for column in (sa.Column("analysis_version", sa.Integer(), nullable=True),
                   sa.Column("analysis_input_hash", sa.String(64), nullable=True),
                   sa.Column("answer_kind", sa.String(30), nullable=True),
                   sa.Column("references", sa.JSON(), nullable=True)):
        if column.name not in existing:
            op.add_column("deal_chats", column)

def downgrade():
    with op.batch_alter_table("deal_chats") as batch:
        for name in ("references", "answer_kind", "analysis_input_hash", "analysis_version"):
            batch.drop_column(name)
