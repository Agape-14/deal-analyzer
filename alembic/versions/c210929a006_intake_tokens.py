"""Make upload-first retries reuse their original deal."""
from alembic import op
import sqlalchemy as sa
revision = "c210929a006"
down_revision = "c210929a005"
branch_labels = None
depends_on = None

def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("deals"):
        return
    if "intake_token" not in {c["name"] for c in inspector.get_columns("deals")}:
        op.add_column("deals", sa.Column("intake_token", sa.String(64), nullable=True))
    if "uq_deals_intake_token" not in {i["name"] for i in inspector.get_indexes("deals")}:
        op.create_index("uq_deals_intake_token", "deals", ["intake_token"], unique=True)

def downgrade():
    op.drop_index("uq_deals_intake_token", table_name="deals")
    with op.batch_alter_table("deals") as batch:
        batch.drop_column("intake_token")
