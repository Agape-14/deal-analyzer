"""Add stable sponsor links and optional dated investment valuations."""
from alembic import op
import sqlalchemy as sa

revision = "c211028a007"
down_revision = "c210929a006"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("investments"):
        return
    columns = {c["name"] for c in inspector.get_columns("investments")}
    for name, kind in (("developer_id", sa.Integer()), ("residual_value", sa.Float()),
                       ("valuation_date", sa.Date()), ("source_analysis_version", sa.Integer()),
                       ("source_analysis_input_hash", sa.String(64)), ("terms_context", sa.JSON())):
        if name not in columns:
            op.add_column("investments", sa.Column(name, kind, nullable=True))
    if "ix_investments_developer_id" not in {i["name"] for i in inspector.get_indexes("investments")}:
        op.create_index("ix_investments_developer_id", "investments", ["developer_id"])
    # Link only existing deal-backed positions. No financial values are rewritten.
    if inspector.has_table("deals") and "deal_id" in columns and "developer_id" in {c["name"] for c in inspector.get_columns("deals")}:
        bind.execute(sa.text("UPDATE investments SET developer_id=(SELECT developer_id FROM deals WHERE deals.id=investments.deal_id) WHERE developer_id IS NULL AND deal_id IS NOT NULL"))
    if inspector.has_table("developers") and "sponsor_name" in columns:
        # An unambiguous existing exact-name relationship can acquire an ID.
        # Aliases and ambiguous names remain unmapped for explicit resolution.
        bind.execute(sa.text("UPDATE investments SET developer_id=(SELECT MIN(id) FROM developers WHERE lower(trim(developers.name))=lower(trim(investments.sponsor_name))) WHERE developer_id IS NULL AND trim(sponsor_name)<>'' AND (SELECT COUNT(*) FROM developers WHERE lower(trim(developers.name))=lower(trim(investments.sponsor_name)))=1"))


def downgrade():
    op.drop_index("ix_investments_developer_id", table_name="investments")
    with op.batch_alter_table("investments") as batch:
        for name in ("terms_context", "source_analysis_input_hash", "source_analysis_version", "valuation_date", "residual_value", "developer_id"):
            batch.drop_column(name)
