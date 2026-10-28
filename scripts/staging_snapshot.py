"""Create a private, consistent SQLite backup and an isolated working copy.

Run on the volume host, never in public CI with real records. No network,
provider calls, environment secrets, migrations or writes to the source DB.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from datetime import datetime, timezone


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_snapshot(database, uploads, destination):
    database, uploads, destination = (Path(p).resolve() for p in (database, uploads, destination))
    if not database.is_file() or not uploads.is_dir():
        raise ValueError("A readable source database and uploads directory are required.")
    if destination.exists() or destination == uploads or destination.is_relative_to(uploads):
        raise ValueError("Use a new, empty destination outside the source uploads directory.")
    if any((parent / ".git").exists() for parent in [destination, *destination.parents]):
        raise ValueError("Private snapshots must be outside a Git repository.")
    destination.mkdir(parents=True, mode=0o700)
    copied_uploads = destination / "uploads"
    copied_uploads.mkdir(mode=0o700)
    original = destination / "original.db"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as source:
        source.execute("PRAGMA query_only=ON")
        with sqlite3.connect(original) as target:
            source.backup(target)
    manifest = {"format": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                "database_sha256": sha256(original), "documents": [], "complete": False}
    with sqlite3.connect(original) as backup:
        backup.row_factory = sqlite3.Row
        if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Snapshot database integrity check failed.")
        rows = backup.execute("SELECT * FROM deal_documents ORDER BY id").fetchall()
    # A deleted or concurrently changed original causes failure, never a partial
    # success. Byte hashes, not filenames, verify that the package was copied.
    for row in rows:
        source_file = Path(row["file_path"]).resolve()
        if not source_file.is_relative_to(uploads) or not source_file.is_file():
            raise ValueError(f"Document {row['id']} is missing or outside the approved uploads directory.")
        digest = sha256(source_file)
        expected = row["file_sha256"] if "file_sha256" in row.keys() else ""
        if expected and digest != expected:
            raise ValueError(f"Document {row['id']} differs from its stored byte hash.")
        target_file = copied_uploads / f"{row['id']}-{source_file.name}"
        shutil.copyfile(source_file, target_file)
        if sha256(target_file) != digest or sha256(source_file) != digest:
            raise ValueError(f"Document {row['id']} changed during copying.")
        manifest["documents"].append({"id": row["id"], "filename": row["filename"],
                                      "file": str(target_file.relative_to(destination)), "sha256": digest})
    working = destination / "deal_analyzer.db"
    shutil.copyfile(original, working)
    with sqlite3.connect(working) as copy_db:
        for item in manifest["documents"]:
            copy_db.execute("UPDATE deal_documents SET file_path=? WHERE id=?", (str(destination / item["file"]), item["id"]))
        tables = {r[0] for r in copy_db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "review_jobs" in tables:
            copy_db.execute("UPDATE review_jobs SET status='cancelled', lease_token=NULL, lease_until=NULL")
    manifest["complete"] = True
    (destination / "snapshot-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (destination / "staging.env.example").write_text(
        f"DB_DIR={destination}\nUPLOADS_DIR={copied_uploads}\nREVIEW_WORKERS_ENABLED=0\nDEAL_REVIEW_AUTO_AFTER_UPLOAD=0\n"
        "# Configure staging authentication before exposing a service. No production secrets are copied.\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--uploads", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    result = create_snapshot(args.database, args.uploads, args.destination)
    print(f"Private snapshot complete: {len(result['documents'])} originals verified. Workers remain disabled.")
