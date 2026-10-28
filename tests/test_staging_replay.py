import json
from pathlib import Path
import sqlite3
import pytest

from scripts.staging_snapshot import create_snapshot, sha256
from scripts.replay_staging import replay


def legacy_package(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    uploads = source / "uploads"
    uploads.mkdir()
    file = uploads / "original.csv"
    file.write_text("Metric,Value\nUnits,12\n", encoding="utf-8")
    database = source / "legacy.db"
    metrics = {"target_returns": {"primary_strategy": "hold"}, "project_details": {"unit_count": 12},
               "_locks": {"project_details.unit_count": True}, "_provenance": {"project_details.unit_count": {"status": "manual"}}}
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE deals (id INTEGER PRIMARY KEY, project_name TEXT, property_type TEXT, metrics JSON, deleted_at TEXT)")
        db.executemany("INSERT INTO deals VALUES (?,?,?,?,?)", [(1, "Synthetic A", "multifamily", json.dumps(metrics), None),
            (2, "Synthetic B", "multifamily", json.dumps(metrics), None), (3, "Archived", "multifamily", "{}", "2025-01-01")])
        db.execute("CREATE TABLE deal_documents (id INTEGER PRIMARY KEY, deal_id INTEGER, filename TEXT, file_path TEXT, file_sha256 TEXT, extracted_text TEXT, page_count INTEGER, extraction_quality JSON)")
        db.execute("INSERT INTO deal_documents VALUES (1,1,'original.csv',?,?,?,1,'{}')", (str(file), sha256(file), "--- Page 1 ---\nUnits 12"))
    return database, uploads


def test_snapshot_and_all_deal_replay_preserve_source_and_locks(tmp_path):
    database, uploads = legacy_package(tmp_path)
    before = sha256(database)
    target = tmp_path / "private-copy"
    manifest = create_snapshot(database, uploads, target)
    assert manifest["complete"] and len(manifest["documents"]) == 1
    assert sha256(database) == before
    working_before = sha256(target / "deal_analyzer.db")
    result = replay(target)
    assert result["deal_count"] == 2
    assert result["database_writes"] == result["provider_calls"] == 0
    assert result["factual_accuracy_verified"] is False
    assert result["deals"][0]["candidate"]["facts"]["project_details.unit_count"]["locked"]
    assert result["deals"][0]["candidate"]["facts"]["project_details.unit_count"]["value"] == 12
    assert sha256(database) == before
    assert sha256(target / "deal_analyzer.db") == working_before
    assert "REVIEW_WORKERS_ENABLED=0" in (target / "staging.env.example").read_text()


def test_missing_original_fails_without_claiming_a_complete_copy(tmp_path):
    database, uploads = legacy_package(tmp_path)
    (uploads / "original.csv").unlink()
    target = tmp_path / "incomplete"
    with pytest.raises(ValueError, match="missing"):
        create_snapshot(database, uploads, target)
    assert not (target / "snapshot-manifest.json").exists()


def test_tampered_original_blocks_replay(tmp_path):
    database, uploads = legacy_package(tmp_path)
    target = tmp_path / "copy"
    manifest = create_snapshot(database, uploads, target)
    (target / manifest["documents"][0]["file"]).write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        replay(target)


def test_snapshot_cannot_overwrite_existing_data_or_write_inside_git(tmp_path):
    database, uploads = legacy_package(tmp_path)
    with pytest.raises(ValueError, match="new, empty"):
        create_snapshot(database, uploads, uploads)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    with pytest.raises(ValueError, match="outside a Git"):
        create_snapshot(database, uploads, repo / "private")
