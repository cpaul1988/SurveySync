from __future__ import annotations

import json
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Any
from uuid import uuid4

from .audit import utc_now
from .project import SurveyProject

_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="surveysync")
_LOCK = threading.RLock()


def _insert(project: SurveyProject, task_id: str, kind: str, label: str, payload: dict | None = None) -> None:
    with project.db.connect() as conn:
        conn.execute(
            "INSERT INTO background_tasks(task_id,created_utc,updated_utc,kind,label,status,progress,message,payload_json,result_json,error_text,cancel_requested) VALUES(?,?,?,?,?,?,?,?,?,?,?,0)",
            (task_id, utc_now(), utc_now(), kind, label, "QUEUED", 0.0, "Queued", json.dumps(payload or {}, sort_keys=True), "{}", ""),
        )
    project.db.audit("Core", "BACKGROUND_TASK_QUEUED", object_type="background_task", object_id=task_id, details={"kind": kind, "label": label})


def _update(project: SurveyProject, task_id: str, **fields) -> None:
    allowed = {"status", "progress", "message", "result_json", "error_text", "cancel_requested"}
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return
    clean["updated_utc"] = utc_now()
    sql = "UPDATE background_tasks SET " + ",".join(f"{k}=?" for k in clean) + " WHERE task_id=?"
    with project.db.connect() as conn:
        conn.execute(sql, tuple(clean.values()) + (task_id,))


def is_cancel_requested(project: SurveyProject, task_id: str) -> bool:
    with project.db.connect() as conn:
        row = conn.execute("SELECT cancel_requested FROM background_tasks WHERE task_id=?", (task_id,)).fetchone()
    return bool(row and row[0])


def submit(project: SurveyProject, kind: str, label: str, func: Callable[..., Any], *, payload: dict | None = None) -> dict:
    task_id = uuid4().hex
    _insert(project, task_id, kind, label, payload)

    def progress(value: float, message: str = "") -> None:
        _update(project, task_id, progress=max(0.0, min(1.0, float(value))), message=message or "Running")

    def runner():
        _update(project, task_id, status="RUNNING", progress=0.01, message="Running")
        try:
            if is_cancel_requested(project, task_id):
                _update(project, task_id, status="CANCELLED", progress=0.0, message="Cancelled before start")
                return
            result = func(progress=progress, cancelled=lambda: is_cancel_requested(project, task_id))
            if is_cancel_requested(project, task_id):
                _update(project, task_id, status="CANCELLED", message="Cancelled", result_json=json.dumps(result or {}, default=str))
            else:
                _update(project, task_id, status="COMPLETED", progress=1.0, message="Completed", result_json=json.dumps(result or {}, default=str))
                project.db.audit("Core", "BACKGROUND_TASK_COMPLETED", object_type="background_task", object_id=task_id, details={"kind": kind})
        except Exception as exc:
            tb = traceback.format_exc(limit=12)
            _update(project, task_id, status="FAILED", message=str(exc), error_text=tb)
            project.db.audit("Core", "BACKGROUND_TASK_FAILED", object_type="background_task", object_id=task_id, details={"kind": kind, "error": str(exc)})
    _EXECUTOR.submit(runner)
    return {"task_id": task_id, "kind": kind, "label": label, "status": "QUEUED"}


def list_tasks(project: SurveyProject, limit: int = 100) -> list[dict]:
    with project.db.connect() as conn:
        rows = conn.execute("SELECT * FROM background_tasks ORDER BY created_utc DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for src, dst in (("payload_json", "payload"), ("result_json", "result")):
            try: d[dst] = json.loads(d.pop(src) or "{}")
            except Exception: d[dst] = {}
        d["cancel_requested"] = bool(d.get("cancel_requested"))
        out.append(d)
    return out


def cancel(project: SurveyProject, task_id: str) -> dict:
    with project.db.connect() as conn:
        row = conn.execute("SELECT status FROM background_tasks WHERE task_id=?", (task_id,)).fetchone()
    if not row:
        raise ValueError("Background task was not found.")
    if row[0] in {"COMPLETED", "FAILED", "CANCELLED"}:
        return {"task_id": task_id, "status": row[0], "cancel_requested": False}
    _update(project, task_id, cancel_requested=1, message="Cancellation requested")
    return {"task_id": task_id, "status": row[0], "cancel_requested": True}
