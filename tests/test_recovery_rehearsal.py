"""A recovery rehearsal leaves original files unchanged and emits no contents."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3

import pytest

from scripts import recovery_rehearsal
from scripts.staging_snapshot import sha256


def synthetic_source(tmp_path):
    root = tmp_path / "source"
    uploads = root / "uploads"
    uploads.mkdir(parents=True)
    original = uploads / "private-source.csv"
    original.write_text("Metric,Value\nUnits,12\n", encoding="utf-8")
    database = root / "original.db"
    metrics = json.dumps({"project_details": {"unit_count": 12}, "_locks": {"project_details.unit_count": True}})
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE deals (id INTEGER PRIMARY KEY, project_name TEXT, property_type TEXT, metrics JSON, deleted_at TEXT)")
        connection.execute("INSERT INTO deals VALUES (1,'Private synthetic deal','multifamily',?,NULL)", (metrics,))
        connection.execute("CREATE TABLE deal_documents (id INTEGER PRIMARY KEY, deal_id INTEGER, filename TEXT, file_path TEXT, file_sha256 TEXT, extracted_text TEXT, page_count INTEGER, extraction_quality JSON)")
        connection.execute("INSERT INTO deal_documents VALUES (1,1,'private-source.csv',?,?,?,1,'{}')", (str(original), sha256(original), "--- Page 1 ---\nUnits 12"))
        connection.execute("CREATE TABLE analysis_snapshots (id INTEGER PRIMARY KEY, payload JSON)")
        connection.execute("INSERT INTO analysis_snapshots VALUES (1,?)", (metrics,))
        connection.execute("CREATE TABLE investments (id INTEGER PRIMARY KEY, amount_invested REAL)")
        connection.execute("INSERT INTO investments VALUES (1,1234.56)")
        connection.commit()
    return database, uploads, original


def use_temporary_root(tmp_path, monkeypatch):
    factory = recovery_rehearsal.tempfile.TemporaryDirectory
    monkeypatch.setattr(recovery_rehearsal.tempfile, "TemporaryDirectory", lambda **kwargs: factory(dir=tmp_path, **kwargs))


def test_bounded_restore_replay_preserves_source_records_and_deletes_private_copy(tmp_path, monkeypatch):
    database, uploads, original = synthetic_source(tmp_path)
    before = sha256(database), sha256(original)
    use_temporary_root(tmp_path, monkeypatch)

    result = recovery_rehearsal.rehearse_recovery(database, uploads)

    assert result["passed"] and result["temporary_copy_removed"]
    assert result["business_rows_preserved"] and result["original_document_hashes_verified"]
    assert result["deal_count"] == result["document_count"] == 1
    assert result["source_database_writes"] == result["provider_calls"] == 0
    assert not result["provider_backup_schedule_verified"] and not result["source_content_accuracy_verified"]
    assert (sha256(database), sha256(original)) == before
    assert not list(tmp_path.glob("kenyon-recovery-*"))
    assert "Private synthetic" not in json.dumps(result) and str(tmp_path) not in json.dumps(result)


@pytest.mark.parametrize("limits", [{"max_copy_bytes": 1}, {"max_documents": 0}])
def test_limits_fail_safely_and_remove_partial_copy(tmp_path, monkeypatch, limits):
    database, uploads, original = synthetic_source(tmp_path)
    before = sha256(database), sha256(original)
    use_temporary_root(tmp_path, monkeypatch)

    with pytest.raises(recovery_rehearsal.RecoveryRehearsalBlocked):
        recovery_rehearsal.rehearse_recovery(database, uploads, **limits)

    assert (sha256(database), sha256(original)) == before
    assert not list(tmp_path.glob("kenyon-recovery-*"))


def test_bad_original_hash_is_redacted_and_never_replayed(tmp_path, monkeypatch):
    database, uploads, original = synthetic_source(tmp_path)
    original.write_text("changed private contents", encoding="utf-8")
    before = sha256(database), sha256(original)
    use_temporary_root(tmp_path, monkeypatch)

    with pytest.raises(recovery_rehearsal.RecoveryRehearsalBlocked) as error:
        recovery_rehearsal.rehearse_recovery(database, uploads)

    assert str(error.value) == "recovery_rehearsal_failed"
    assert (sha256(database), sha256(original)) == before
    assert not list(tmp_path.glob("kenyon-recovery-*"))


def test_a_replay_that_writes_its_copy_cannot_claim_read_only_success(tmp_path, monkeypatch):
    from scripts import replay_staging

    database, uploads, original = synthetic_source(tmp_path)
    before = sha256(database), sha256(original)
    use_temporary_root(tmp_path, monkeypatch)

    def writing_replay(snapshot):
        with closing(sqlite3.connect(Path(snapshot) / "deal_analyzer.db")) as connection:
            connection.execute("UPDATE deals SET metrics='{}'")
            connection.commit()
        return {"deal_count": 1, "provider_calls": 0, "database_writes": 0}

    monkeypatch.setattr(replay_staging, "replay", writing_replay)
    with pytest.raises(recovery_rehearsal.RecoveryRehearsalBlocked, match="replay_not_read_only"):
        recovery_rehearsal.rehearse_recovery(database, uploads)

    assert (sha256(database), sha256(original)) == before
    assert not list(tmp_path.glob("kenyon-recovery-*"))
