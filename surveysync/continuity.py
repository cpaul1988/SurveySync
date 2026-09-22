from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .audit import utc_now
from .project import SurveyProject, sha256_file

logger = logging.getLogger(__name__)

SNAPSHOT_INDEX_VERSION = 1
RECOVERY_INTERVAL_SECONDS = 300


def _snapshot_root(project: SurveyProject) -> Path:
    p = project.paths.db.parent / "snapshots"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _index_path(project: SurveyProject) -> Path:
    return _snapshot_root(project) / "index.json"


def _load_index(project: SurveyProject) -> dict:
    path = _index_path(project)
    if not path.exists():
        return {"version": SNAPSHOT_INDEX_VERSION, "items": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict) and isinstance(raw.get("items"), list):
            return raw
    except Exception:
        logger.warning("Could not read snapshot index %s; using an empty index.", path, exc_info=True)
    return {"version": SNAPSHOT_INDEX_VERSION, "items": []}


def _save_index(project: SurveyProject, data: dict) -> None:
    path = _index_path(project)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _db_backup(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # sqlite3.Connection is a transaction context manager, but its __exit__
    # does not close the OS file handle. That is observable on Windows: a
    # TemporaryDirectory containing the backup DB cannot be deleted while the
    # connection is still alive. Use closing() so snapshot temp databases are
    # deterministically released before cleanup.
    with closing(sqlite3.connect(str(src))) as source, closing(sqlite3.connect(str(dest))) as target:
        source.backup(target)
        target.commit()


def _add_if_exists(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
    if path.is_file():
        zf.write(path, arcname)


def _fieldbook_mutable_files(project: SurveyProject) -> list[Path]:
    root = project.paths.fieldbook_root
    if not root.exists():
        return []
    allowed_suffixes = {".json", ".csv", ".txt", ".fnp", ".yaml", ".yml"}
    out = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part.lower() in {"cache", "logs", "pages", "page_cache", "ocr_cache"} for part in rel.parts):
            continue
        if p.suffix.lower() in allowed_suffixes and p.stat().st_size <= 10 * 1024 * 1024:
            out.append(p)
    return out


def create_snapshot(project: SurveyProject, *, label: str = "", kind: str = "manual") -> dict:
    kind = str(kind or "manual").lower()
    if kind not in {"manual", "recovery", "pre_restore"}:
        raise ValueError("Snapshot kind must be manual, recovery, or pre_restore.")
    sid = uuid4().hex
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{kind}_{stamp}_{sid[:8]}.ssnap"
    output = _snapshot_root(project) / name
    with tempfile.TemporaryDirectory(prefix="surveysync_snapshot_") as td:
        tmp_db = Path(td) / "survey_sync.db"
        _db_backup(project.paths.db, tmp_db)
        manifest = dict(project.manifest)
        snapshot_meta = {
            "snapshot_id": sid,
            "created_utc": utc_now(),
            "kind": kind,
            "label": str(label or ""),
            "project_id": manifest.get("project_id", ""),
            "project_name": manifest.get("name", ""),
            "manifest_revision": int(manifest.get("revision", 0)),
            "surveysync_snapshot_version": 1,
        }
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.write(project.paths.manifest, "survey_sync_project.json")
            zf.write(tmp_db, ".surveysync/survey_sync.db")
            zf.writestr("snapshot.json", json.dumps(snapshot_meta, indent=2, sort_keys=True))
            for p in _fieldbook_mutable_files(project):
                zf.write(p, str(Path("Modules/FieldBookSync") / p.relative_to(project.paths.fieldbook_root)))
    digest = sha256_file(output)
    item = {**snapshot_meta, "filename": name, "path": str(output), "sha256": digest, "size_bytes": output.stat().st_size}
    index = _load_index(project)
    index["items"] = [item] + [x for x in index.get("items", []) if x.get("snapshot_id") != sid]
    # Keep automatic recovery bounded; manual snapshots are user-owned.
    recovery = [x for x in index["items"] if x.get("kind") == "recovery"]
    keep_recovery = {x["snapshot_id"] for x in recovery[:8]}
    pruned = []
    for x in index["items"]:
        if x.get("kind") == "recovery" and x.get("snapshot_id") not in keep_recovery:
            try: Path(x.get("path", "")).unlink(missing_ok=True)
            except Exception:
                logger.debug("Could not prune old recovery snapshot %s.", x.get("path", ""), exc_info=True)
        else:
            pruned.append(x)
    index["items"] = pruned
    _save_index(project, index)
    project.db.audit("Core", "PROJECT_SNAPSHOT_CREATED", object_type="snapshot", object_id=sid, revision=int(project.manifest.get("revision", 0)), details={"kind": kind, "label": label, "sha256": digest, "filename": name})
    return item


def list_snapshots(project: SurveyProject) -> list[dict]:
    index = _load_index(project)
    out = []
    for item in index.get("items", []):
        p = Path(item.get("path") or (_snapshot_root(project) / item.get("filename", "")))
        row = dict(item); row["exists"] = p.is_file(); row["path"] = str(p)
        out.append(row)
    return out


def autosave_tick(project: SurveyProject, *, interval_seconds: int = RECOVERY_INTERVAL_SECONDS) -> dict:
    items = [x for x in list_snapshots(project) if x.get("kind") == "recovery" and x.get("exists")]
    latest = items[0] if items else None
    latest_ts = 0.0
    if latest:
        try: latest_ts = datetime.fromisoformat(str(latest["created_utc"]).replace("Z", "+00:00")).timestamp()
        except Exception: latest_ts = 0.0
    newest_mutable = max(project.paths.db.stat().st_mtime if project.paths.db.exists() else 0, project.paths.manifest.stat().st_mtime if project.paths.manifest.exists() else 0)
    now = datetime.now(timezone.utc).timestamp()
    if latest and now - latest_ts < max(60, int(interval_seconds)):
        return {"created": False, "reason": "interval", "latest": latest}
    if latest and newest_mutable <= latest_ts:
        return {"created": False, "reason": "unchanged", "latest": latest}
    return {"created": True, "snapshot": create_snapshot(project, label="Automatic crash-recovery snapshot", kind="recovery")}


def inspect_snapshot(project: SurveyProject, snapshot_id: str) -> dict:
    item = next((x for x in list_snapshots(project) if x.get("snapshot_id") == snapshot_id), None)
    if not item or not item.get("exists"):
        raise ValueError("Snapshot was not found.")
    path = Path(item["path"])
    if sha256_file(path) != item.get("sha256"):
        raise ValueError("Snapshot checksum does not match its index entry.")
    with zipfile.ZipFile(path, "r") as zf:
        meta = json.loads(zf.read("snapshot.json").decode("utf-8"))
        manifest = json.loads(zf.read("survey_sync_project.json").decode("utf-8"))
    return {"index": item, "metadata": meta, "manifest": manifest}


def compare_snapshot(project: SurveyProject, snapshot_id: str) -> dict:
    info = inspect_snapshot(project, snapshot_id)
    path = Path(info["index"]["path"])
    with tempfile.TemporaryDirectory(prefix="surveysync_compare_") as td:
        with zipfile.ZipFile(path, "r") as zf:
            zf.extract(".surveysync/survey_sync.db", td)
        snap_db = Path(td) / ".surveysync" / "survey_sync.db"
        with closing(sqlite3.connect(str(snap_db))) as conn:
            snap_counts = {
                "points": conn.execute("SELECT COUNT(*) FROM canonical_points").fetchone()[0],
                "control_solutions": conn.execute("SELECT COUNT(*) FROM control_solutions").fetchone()[0],
                "level_solutions": conn.execute("SELECT COUNT(*) FROM level_solutions").fetchone()[0],
                "qa_open": conn.execute("SELECT COUNT(*) FROM qa_issues WHERE status='OPEN'").fetchone()[0],
            }
    with project.db.connect() as conn:
        current_counts = {
            "points": conn.execute("SELECT COUNT(*) FROM canonical_points").fetchone()[0],
            "control_solutions": conn.execute("SELECT COUNT(*) FROM control_solutions").fetchone()[0],
            "level_solutions": conn.execute("SELECT COUNT(*) FROM level_solutions").fetchone()[0],
            "qa_open": conn.execute("SELECT COUNT(*) FROM qa_issues WHERE status='OPEN'").fetchone()[0],
        }
    return {"snapshot": info["index"], "manifest_revision": {"snapshot": info["manifest"].get("revision", 0), "current": project.manifest.get("revision", 0)}, "counts": {k: {"snapshot": snap_counts[k], "current": current_counts[k], "delta": current_counts[k] - snap_counts[k]} for k in current_counts}}


def restore_snapshot(project: SurveyProject, snapshot_id: str) -> dict:
    info = inspect_snapshot(project, snapshot_id)
    if str(info["manifest"].get("project_id") or "") != str(project.manifest.get("project_id") or ""):
        raise ValueError("Snapshot belongs to a different SurveySync project.")
    safety = create_snapshot(project, label=f"Automatic safety snapshot before restoring {snapshot_id[:8]}", kind="pre_restore")
    path = Path(info["index"]["path"])
    with tempfile.TemporaryDirectory(prefix="surveysync_restore_") as td:
        tmp = Path(td)
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(tmp)
        restored_manifest = tmp / "survey_sync_project.json"
        restored_db = tmp / ".surveysync" / "survey_sync.db"
        if not restored_manifest.is_file() or not restored_db.is_file():
            raise ValueError("Snapshot is incomplete.")
        shutil.copy2(restored_manifest, project.paths.manifest.with_suffix(".json.restore_tmp"))
        project.paths.manifest.with_suffix(".json.restore_tmp").replace(project.paths.manifest)
        # Flush and remove WAL sidecars before replacing the SQLite database.
        # Otherwise SQLite can replay post-snapshot WAL frames onto the restored
        # main DB, making a restore appear to succeed while retaining newer data.
        try:
            with closing(sqlite3.connect(str(project.paths.db))) as live_conn:
                live_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            logger.warning("WAL checkpoint before snapshot restore failed for %s.", project.paths.db, exc_info=True)
        for suffix in ("-wal", "-shm"):
            try: Path(str(project.paths.db) + suffix).unlink(missing_ok=True)
            except Exception:
                logger.debug("Could not remove pre-restore SQLite sidecar %s%s.", project.paths.db, suffix, exc_info=True)
        db_tmp = project.paths.db.with_suffix(".db.restore_tmp")
        shutil.copy2(restored_db, db_tmp); db_tmp.replace(project.paths.db)
        for suffix in ("-wal", "-shm"):
            try: Path(str(project.paths.db) + suffix).unlink(missing_ok=True)
            except Exception:
                logger.debug("Could not remove post-restore SQLite sidecar %s%s.", project.paths.db, suffix, exc_info=True)
        fb = tmp / "Modules" / "FieldBookSync"
        if fb.exists():
            for src in fb.rglob("*"):
                if src.is_file():
                    dest = project.paths.fieldbook_root / src.relative_to(fb)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
    project.manifest = project._load_manifest()
    project.db.audit("Core", "PROJECT_SNAPSHOT_RESTORED", object_type="snapshot", object_id=snapshot_id, revision=int(project.manifest.get("revision", 0)), details={"safety_snapshot_id": safety["snapshot_id"]})
    return {"restored": True, "snapshot_id": snapshot_id, "safety_snapshot": safety, "project": project.summary()}
