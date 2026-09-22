from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

from .audit import utc_now
from .project import SurveyProject

logger = logging.getLogger(__name__)


def _smtp_password() -> str:
    return os.environ.get("SURVEYSYNC_SMTP_PASSWORD", "")


def send_deliverable_notification(
    project: SurveyProject,
    deliverable: dict,
    *,
    recipients: list[str],
    smtp_host: str,
    smtp_port: int = 587,
    smtp_user: str = "",
    from_address: str = "",
    subject: str = "",
    message: str = "",
    use_tls: bool = True,
    attach_file: bool = False,
    password: str = "",
) -> dict:
    recipients = [str(x).strip() for x in recipients if str(x).strip()]
    if not recipients:
        raise ValueError("At least one notification recipient is required.")
    if not smtp_host.strip():
        raise ValueError("SMTP host is required.")
    secret = password or _smtp_password()
    if smtp_user and not secret:
        raise ValueError("SMTP authentication password is not configured. Set SURVEYSYNC_SMTP_PASSWORD or provide a session-only password.")

    filename = str(deliverable.get("filename") or Path(str(deliverable.get("path") or "deliverable")).name)
    subject = subject.strip() or f"SurveySync deliverable ready: {filename}"
    body = message.strip() or (
        f"SurveySync has finalized a deliverable for project {project.manifest.get('name', '')}.\n\n"
        f"File: {filename}\n"
        f"Type: {deliverable.get('kind', '')}\n"
        f"SHA-256: {deliverable.get('sha256', '')}\n"
        f"Status: {deliverable.get('status', '')}\n\n"
        "The deliverable is ready for professional review/signature as applicable."
    )
    sender = from_address.strip() or smtp_user.strip()
    if not sender:
        raise ValueError("A From address or SMTP username is required.")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)

    path = Path(str(deliverable.get("path") or ""))
    if attach_file:
        if not path.is_file():
            raise ValueError("Deliverable file is not available to attach.")
        # Keep accidental giant email payloads from hanging the UI.
        if path.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("Deliverable is larger than 20 MB; send a file share/link instead of attaching it to email.")
        data = path.read_bytes()
        msg.add_attachment(data, maintype="application", subtype="octet-stream", filename=path.name)

    event_id = uuid4().hex
    ts = utc_now()
    status = "SENT"
    error = ""
    try:
        if use_tls:
            with smtplib.SMTP(smtp_host, int(smtp_port), timeout=25) as client:
                client.ehlo()
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
                if smtp_user:
                    client.login(smtp_user, secret)
                client.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, int(smtp_port), timeout=25) as client:
                if smtp_user:
                    client.login(smtp_user, secret)
                client.send_message(msg)
    except Exception as exc:
        status = "FAILED"
        error = str(exc)

    with project.db.connect() as conn:
        conn.execute(
            "INSERT INTO notification_events(notification_id,ts_utc,deliverable_id,channel,recipients,status,message,details_json) VALUES(?,?,?,?,?,?,?,?)",
            (
                event_id, ts, str(deliverable.get("deliverable_id") or ""), "email",
                json.dumps(recipients), status, error,
                json.dumps({"smtp_host": smtp_host, "smtp_port": int(smtp_port), "from_address": sender, "attached": bool(attach_file)}, sort_keys=True),
            ),
        )
    project.db.audit(
        "ReportSync", "STAKEHOLDER_NOTIFICATION_" + status,
        object_type="notification", object_id=event_id,
        details={"deliverable_id": deliverable.get("deliverable_id"), "recipients": recipients, "channel": "email", "error": error},
    )
    result = {"event_id": event_id, "status": status, "recipients": recipients, "error": error}
    if status != "SENT":
        raise RuntimeError(f"Email notification failed: {error}")
    return result


def list_notifications(project: SurveyProject, limit: int = 100) -> list[dict]:
    with project.db.connect() as conn:
        rows = conn.execute("SELECT * FROM notification_events ORDER BY ts_utc DESC LIMIT ?", (max(1, min(int(limit), 1000)),)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try: item["recipient_list"] = json.loads(item.get("recipients") or "[]")
        except Exception: item["recipients"] = []
        try: item["details"] = json.loads(item.pop("details_json") or "{}")
        except Exception: item["metadata"] = {}
        out.append(item)
    return out

POLICY_FILENAME = "notification_policy.json"


def policy_path(project: SurveyProject) -> Path:
    return project.paths.root / ".surveysync" / POLICY_FILENAME


def load_policy(project: SurveyProject) -> dict:
    path=policy_path(project)
    if not path.exists():
        return {"enabled":False,"recipients":[],"smtp_host":"","smtp_port":587,"smtp_user":"","from_address":"","use_tls":True,"attach_file":False}
    try:
        data=json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data,dict):return {"enabled":False,"recipients":[],"smtp_host":"","smtp_port":587,"smtp_user":"","from_address":"","use_tls":True,"attach_file":False,**data,"password_stored":False}
    except Exception:
        logger.warning("Could not load notification policy from %s; notifications remain disabled.", path, exc_info=True)
    return {"enabled":False,"recipients":[],"smtp_host":"","smtp_port":587,"smtp_user":"","from_address":"","use_tls":True,"attach_file":False,"password_stored":False}


def save_policy(project: SurveyProject, policy: dict) -> dict:
    clean={
        "enabled":bool(policy.get("enabled",False)),
        "recipients":[str(x).strip() for x in policy.get("recipients",[]) if str(x).strip()],
        "smtp_host":str(policy.get("smtp_host") or "").strip(),
        "smtp_port":int(policy.get("smtp_port") or 587),
        "smtp_user":str(policy.get("smtp_user") or "").strip(),
        "from_address":str(policy.get("from_address") or "").strip(),
        "use_tls":bool(policy.get("use_tls",True)),
        "attach_file":bool(policy.get("attach_file",False)),
    }
    path=policy_path(project);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(clean,indent=2),encoding='utf-8');tmp.replace(path)
    project.db.audit("ReportSync","NOTIFICATION_POLICY_UPDATED",object_type="notification_policy",object_id=project.manifest.get("project_id",""),details={k:v for k,v in clean.items() if k not in {"smtp_user"}})
    return {**clean,"password_stored":False,"password_source":"SURVEYSYNC_SMTP_PASSWORD environment variable or session-only send"}


def maybe_notify_deliverable(project: SurveyProject, deliverable: dict) -> dict:
    policy=load_policy(project)
    if not policy.get("enabled"):
        return {"status":"DISABLED"}
    if not policy.get("smtp_host") or not policy.get("recipients"):
        return {"status":"SKIPPED","reason":"Notification policy is incomplete."}
    try:
        return send_deliverable_notification(
            project,deliverable,recipients=policy.get("recipients") or [],smtp_host=policy.get("smtp_host") or "",
            smtp_port=int(policy.get("smtp_port") or 587),smtp_user=policy.get("smtp_user") or "",from_address=policy.get("from_address") or "",
            use_tls=bool(policy.get("use_tls",True)),attach_file=bool(policy.get("attach_file",False)),password="",
        )
    except Exception as exc:
        # Deliverable creation must never be rolled back just because email is unavailable.
        return {"status":"FAILED","reason":str(exc)}
