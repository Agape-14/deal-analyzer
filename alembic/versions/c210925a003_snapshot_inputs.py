"""Keep source inputs for explicit, revision-checked restoration."""
from alembic import op
import sqlalchemy as sa

revision = "c210925a003"
down_revision = "c210925a002"
branch_labels = None
depends_on = None


def upgrade():
    if "input_metrics" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("analysis_snapshots")}:
        op.add_column("analysis_snapshots", sa.Column("input_metrics", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("analysis_snapshots") as batch:
        batch.drop_column("input_metrics")
