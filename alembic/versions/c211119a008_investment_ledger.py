"""Preserve accepted forecasts and support reversible, idempotent cash ledgers."""
from alembic import op
import sqlalchemy as sa

revision = "c211119a008"
down_revision = "c211028a007"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    for table, additions in {
        "investments": [("projected_cash_on_cash", sa.Float()), ("forecast_snapshot", sa.JSON()),
                        ("terms_overrides", sa.JSON())],
        "distributions": [("deleted_at", sa.DateTime()), ("request_id", sa.String(100)),
                          ("request_fingerprint", sa.String(64)), ("history", sa.JSON())],
    }.items():
        if not inspector.has_table(table):
            continue
        existing = {col["name"] for col in inspector.get_columns(table)}
        for name, kind in additions:
            if name not in existing:
                op.add_column(table, sa.Column(name, kind, nullable=True))
    if inspector.has_table("distributions"):
        if "revision" not in {c["name"] for c in inspector.get_columns("distributions")}:
            op.add_column("distributions", sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        if "uq_distributions_request" not in {i["name"] for i in inspector.get_indexes("distributions")}:
            op.create_index("uq_distributions_request", "distributions", ["investment_id", "request_id"], unique=True)


def downgrade():
    op.drop_index("uq_distributions_request", table_name="distributions")
    with op.batch_alter_table("distributions") as batch:
        for name in ("history", "request_fingerprint", "request_id", "revision", "deleted_at"):
            batch.drop_column(name)
    with op.batch_alter_table("investments") as batch:
        for name in ("terms_overrides", "forecast_snapshot", "projected_cash_on_cash"):
            batch.drop_column(name)
