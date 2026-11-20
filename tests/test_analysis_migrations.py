"""Apply the additive migrations to an existing row, twice, without rewriting it."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_analysis_migrations_preserve_legacy_metrics_and_are_idempotent(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    original = '{"deal_structure":{"debt_amount":123},"_locks":{"deal_structure.debt_amount":true}}'
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE deals (id INTEGER PRIMARY KEY, metrics JSON)"))
        conn.execute(sa.text("CREATE TABLE deal_documents (id INTEGER PRIMARY KEY, filename TEXT)"))
        conn.execute(sa.text("CREATE TABLE deal_chats (id INTEGER PRIMARY KEY, content TEXT)"))
        conn.execute(sa.text("INSERT INTO deal_chats VALUES (1, 'Old conversation retained')"))
        conn.execute(sa.text("INSERT INTO deal_documents VALUES (1, 'existing.pdf')"))
        conn.execute(sa.text("INSERT INTO deals (id, metrics) VALUES (1, :metrics)"), {"metrics": original})
        op = Operations(MigrationContext.configure(conn))
        for _ in range(2):
            for filename in ("c210925a001_analysis_snapshots.py", "c210925a002_review_jobs.py", "c210925a003_snapshot_inputs.py", "c210925a004_document_versions.py", "c210929a005_chat_revisions.py", "c210929a006_intake_tokens.py"):
                path = Path(__file__).parents[1] / "alembic" / "versions" / filename
                spec = importlib.util.spec_from_file_location(filename[:-3], path)
                migration = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(migration)
                monkeypatch.setattr(migration, "op", op)
                migration.upgrade()
        row = conn.execute(sa.text("SELECT metrics, revision, analysis_version, analysis_snapshot FROM deals WHERE id=1")).one()
        assert row.metrics == original
        assert (row.revision, row.analysis_version, row.analysis_snapshot) == (1, 0, None)
        assert {"analysis_snapshots", "review_jobs"}.issubset(sa.inspect(conn).get_table_names())
        assert conn.execute(sa.text("SELECT count(*) FROM analysis_snapshots")).scalar() == 0
        assert conn.execute(sa.text("SELECT filename, source_role, superseded_by_id FROM deal_documents")).one() == ("existing.pdf", "active", None)
        assert conn.execute(sa.text('SELECT content, analysis_version, "references" FROM deal_chats')).one() == ("Old conversation retained", None, None)
        assert conn.execute(sa.text("SELECT intake_token FROM deals")).scalar() is None
        assert any(index["name"] == "uq_deals_intake_token" and index["unique"] for index in sa.inspect(conn).get_indexes("deals"))
    engine.dispose()


def test_investment_migration_preserves_cash_and_links_deal_sponsor(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'positions.db'}")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE deals (id INTEGER PRIMARY KEY, developer_id INTEGER)"))
        conn.execute(sa.text("CREATE TABLE investments (id INTEGER PRIMARY KEY, deal_id INTEGER, amount_invested FLOAT, exit_amount FLOAT)"))
        conn.execute(sa.text("INSERT INTO deals VALUES (1, 7)"))
        conn.execute(sa.text("INSERT INTO investments VALUES (1, 1, 1000, 1200), (2, NULL, 2000, NULL)"))
        spec = importlib.util.spec_from_file_location("context_migration", Path(__file__).parents[1] / "alembic/versions/c211028a007_investment_context.py")
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
        migration.upgrade()
        migration.upgrade()
        rows = conn.execute(sa.text("SELECT amount_invested, exit_amount, developer_id, residual_value, valuation_date FROM investments ORDER BY id")).all()
        assert rows == [(1000, 1200, 7, None, None), (2000, None, None, None, None)]
    engine.dispose()
