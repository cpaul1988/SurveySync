from __future__ import annotations
import logging

import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class JobSummary:
    job_id: str
    status: str
    provider: str
    stage: str
    current_page: int
    total_pages: int
    message: str
    error_code: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    failed_pages: int = 0
    input_signature: str = ""
    updated_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class AnalysisJobStore:
    """Crash-safe SQLite ledger for long-running analysis work.

    SQLite is deliberately used only for orchestration/status/error metadata; the
    existing project JSON and content-addressed AI caches remain the source of truth
    for committed project results.  WAL mode keeps frequent progress writes from
    blocking readers.
    """

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        try:
            self._open_connection()
            self._init_db()
        except sqlite3.DatabaseError:
            # A damaged reliability ledger must never make FieldBook Sync itself
            # unlaunchable. Preserve it for diagnostics, then start a clean ledger.
            self.close()
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            corrupt = self.path.with_name(f"{self.path.stem}.corrupt_{stamp}{self.path.suffix}")
            try:
                if self.path.exists():
                    self.path.replace(corrupt)
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(str(self.path) + suffix)
                    if sidecar.exists():
                        sidecar.unlink(missing_ok=True)
            except OSError:
                pass
            self._open_connection()
            self._init_db()

    def _open_connection(self) -> sqlite3.Connection:
        """Open/configure the one process-local ledger connection.

        AnalysisJobStore access is already serialized by ``self._lock``. v8.0.11
        nevertheless opened a new SQLite connection and re-ran four PRAGMAs for
        every status/page/error write. Keeping one ``check_same_thread=False``
        connection removes that repeated setup cost while preserving the same
        transaction and locking semantics.
        """
        if self._conn is not None:
            return self._conn
        conn = sqlite3.connect(self.path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        self._conn = conn
        return conn

    @contextmanager
    def _connect(self):
        conn = self._open_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def checkpoint(self) -> None:
        """Flush committed WAL frames opportunistically (safe for diagnostics/shutdown)."""
        with self._lock:
            if self._conn is None:
                return
            try:
                self._conn.commit()
                self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except sqlite3.Error:
                pass

    def close(self) -> None:
        """Close the persistent SQLite connection. Safe to call repeatedly."""
        with self._lock:
            conn, self._conn = self._conn, None
            if conn is None:
                return
            try:
                conn.commit()
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except sqlite3.Error:
                pass
            try:
                conn.close()
            except sqlite3.Error:
                pass

    def __del__(self) -> None:
        # Best-effort cleanup for short-lived stores (notably tests/tools). The OS
        # also closes SQLite cleanly at process exit; explicit ``close`` remains
        # available to callers that own the store lifecycle.
        try:
            self.close()
        except Exception:
            logging.getLogger(__name__).warning("Recovery fallback in job_engine; operation did not complete.", exc_info=True)

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    stage TEXT NOT NULL DEFAULT 'queued',
                    input_signature TEXT NOT NULL DEFAULT '',
                    project_name TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    total_pages INTEGER NOT NULL DEFAULT 0,
                    current_page INTEGER NOT NULL DEFAULT 0,
                    total_requests INTEGER NOT NULL DEFAULT 0,
                    current_request INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    error_code TEXT,
                    error_message TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    failed_pages INTEGER NOT NULL DEFAULT 0,
                    cancelled INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_jobs_updated
                    ON analysis_jobs(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_analysis_jobs_signature
                    ON analysis_jobs(input_signature, updated_at DESC);
                CREATE TABLE IF NOT EXISTS page_steps (
                    job_id TEXT NOT NULL,
                    page_id TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    source_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    stage TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    cache_hit INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_message TEXT,
                    started_at TEXT,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    PRIMARY KEY(job_id, page_id),
                    FOREIGN KEY(job_id) REFERENCES analysis_jobs(job_id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_page_steps_job_status
                    ON page_steps(job_id, status, page_number);
                CREATE TABLE IF NOT EXISTS error_events (
                    event_id TEXT PRIMARY KEY,
                    job_id TEXT,
                    page_id TEXT,
                    created_at TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    component TEXT NOT NULL,
                    code TEXT NOT NULL,
                    message TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    recoverable INTEGER NOT NULL DEFAULT 0,
                    retry_number INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_error_events_job_time
                    ON error_events(job_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS validation_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    app_version TEXT NOT NULL,
                    project_name TEXT NOT NULL,
                    baseline_name TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT ''
                );
                """
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                (str(self.SCHEMA_VERSION),),
            )

    def recover_interrupted_jobs(self) -> int:
        """Convert orphaned RUNNING/STARTING jobs from a prior process to INTERRUPTED."""
        now = _utc_now()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """UPDATE analysis_jobs
                   SET status='INTERRUPTED', stage='interrupted', updated_at=?,
                       message=CASE WHEN message='' THEN 'Application closed before analysis finished. Resume is available.'
                                    ELSE message || ' · Application closed before analysis finished.' END
                   WHERE status IN ('RUNNING','STARTING','CANCELLING')""",
                (now,),
            )
            return int(cur.rowcount or 0)

    def create_job(
        self,
        *,
        provider: str,
        input_signature: str,
        project_name: str,
        pages: Iterable[Any],
        metadata: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> str:
        job_id = job_id or uuid4().hex
        now = _utc_now()
        page_rows = list(pages)
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO analysis_jobs(
                    job_id,status,provider,stage,input_signature,project_name,
                    created_at,updated_at,total_pages,message,metadata_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job_id, "STARTING", provider, "starting", input_signature,
                    project_name, now, now, len(page_rows), "Preparing analysis worker…",
                    json.dumps(metadata or {}, ensure_ascii=False, default=str),
                ),
            )
            conn.executemany(
                """INSERT OR REPLACE INTO page_steps(
                    job_id,page_id,page_number,source_name,status,stage,updated_at
                ) VALUES(?,?,?,?,?,?,?)""",
                [
                    (
                        job_id,
                        str(getattr(page, "page_id", "")),
                        int(getattr(page, "page_number", idx + 1)),
                        str(getattr(page, "source_name", "")),
                        "PENDING", "pending", now,
                    )
                    for idx, page in enumerate(page_rows)
                ],
            )
        return job_id

    def resume_job(self, job_id: str) -> None:
        now = _utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """UPDATE analysis_jobs SET status='STARTING', stage='starting',
                   started_at=COALESCE(started_at,?), updated_at=?, completed_at=NULL,
                   cancelled=0, error_code=NULL, error_message=NULL,
                   message='Resuming interrupted analysis from persistent checkpoints.'
                   WHERE job_id=?""",
                (now, now, job_id),
            )
            # A page that was in-flight at process death is safe to retry. Completed
            # page OCR remains protected by the content-addressed Paddle cache.
            conn.execute(
                """UPDATE page_steps SET status='PENDING', stage='pending', updated_at=?
                   WHERE job_id=? AND status IN ('RUNNING','RETRYING')""",
                (now, job_id),
            )

    def update_job(self, job_id: str, **changes: Any) -> None:
        if not job_id:
            return
        allowed = {
            "status", "provider", "stage", "started_at", "completed_at", "total_pages",
            "current_page", "total_requests", "current_request", "message", "error_code",
            "error_message", "retry_count", "failed_pages", "cancelled", "metadata_json",
        }
        values = {k: v for k, v in changes.items() if k in allowed}
        if not values:
            return
        if isinstance(values.get("metadata_json"), (dict, list)):
            values["metadata_json"] = json.dumps(values["metadata_json"], ensure_ascii=False, default=str)
        values["updated_at"] = _utc_now()
        assignments = ", ".join(f"{key}=?" for key in values)
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE analysis_jobs SET {assignments} WHERE job_id=?",
                (*values.values(), job_id),
            )

    def mark_page(
        self,
        job_id: str,
        page_id: str,
        *,
        status: str,
        stage: str,
        cache_hit: bool | None = None,
        increment_attempt: bool = False,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        now = _utc_now()
        sets = ["status=?", "stage=?", "updated_at=?", "error_code=?", "error_message=?"]
        params: list[Any] = [status, stage, now, error_code, error_message]
        if cache_hit is not None:
            sets.append("cache_hit=?")
            params.append(1 if cache_hit else 0)
        if increment_attempt:
            sets.append("attempts=attempts+1")
        if status == "RUNNING":
            sets.append("started_at=COALESCE(started_at,?)")
            params.append(now)
        if status in {"COMPLETE", "FAILED", "SKIPPED"}:
            sets.append("completed_at=?")
            params.append(now)
        params.extend([job_id, page_id])
        with self._lock, self._connect() as conn:
            conn.execute(
                f"UPDATE page_steps SET {', '.join(sets)} WHERE job_id=? AND page_id=?",
                params,
            )

    def record_error(
        self,
        *,
        job_id: str | None,
        component: str,
        code: str,
        message: str,
        detail: str = "",
        severity: str = "ERROR",
        recoverable: bool = False,
        page_id: str | None = None,
        retry_number: int = 0,
    ) -> str:
        event_id = uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO error_events(
                    event_id,job_id,page_id,created_at,severity,component,code,message,detail,recoverable,retry_number
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_id, job_id, page_id, _utc_now(), severity, component, code,
                    message, detail[-12000:], 1 if recoverable else 0, int(retry_number),
                ),
            )
        return event_id

    def has_resumable_jobs(self) -> bool:
        """Cheap existence test used on startup before hashing the active project."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM analysis_jobs WHERE status IN ('INTERRUPTED','ERROR','CANCELLED') LIMIT 1"
            ).fetchone()
            return row is not None

    def latest_resumable(self, input_signature: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT * FROM analysis_jobs WHERE status IN ('INTERRUPTED','ERROR','CANCELLED')"
        params: list[Any] = []
        if input_signature:
            sql += " AND input_signature=?"
            params.append(input_signature)
        sql += " ORDER BY updated_at DESC LIMIT 1"
        with self._lock, self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM analysis_jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            steps = conn.execute(
                "SELECT * FROM page_steps WHERE job_id=? ORDER BY page_number,page_id", (job_id,)
            ).fetchall()
            data["pages"] = [dict(x) for x in steps]
            return data

    def list_jobs(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM analysis_jobs ORDER BY updated_at DESC LIMIT ?", (max(1, min(200, int(limit))),)
            ).fetchall()
            return [dict(r) for r in rows]

    def list_errors(self, job_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            if job_id:
                rows = conn.execute(
                    "SELECT * FROM error_events WHERE job_id=? ORDER BY created_at DESC LIMIT ?",
                    (job_id, max(1, min(500, int(limit)))),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM error_events ORDER BY created_at DESC LIMIT ?",
                    (max(1, min(500, int(limit))),),
                ).fetchall()
            return [dict(r) for r in rows]

    def status_counts(self) -> dict[str, int]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT status,COUNT(*) AS n FROM analysis_jobs GROUP BY status").fetchall()
            return {str(r["status"]): int(r["n"]) for r in rows}

    def record_validation_run(
        self,
        *,
        app_version: str,
        project_name: str,
        baseline_name: str,
        metrics: dict[str, Any],
        notes: str = "",
    ) -> str:
        run_id = uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO validation_runs(run_id,created_at,app_version,project_name,baseline_name,metrics_json,notes)
                   VALUES(?,?,?,?,?,?,?)""",
                (run_id, _utc_now(), app_version, project_name, baseline_name, json.dumps(metrics, ensure_ascii=False), notes),
            )
        return run_id
