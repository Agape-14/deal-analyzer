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
        conn.execute(sa.text("INSERT INTO deals (id, metrics) VALUES (1, :metrics)"), {"metrics": original})
        op = Operations(MigrationContext.configure(conn))
        for _ in range(2):
            for filename in ("c210925a001_analysis_snapshots.py", "c210925a002_review_jobs.py"):
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
    engine.dispose()
