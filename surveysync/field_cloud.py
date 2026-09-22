from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from uuid import uuid4

from .audit import utc_now
from .project import SurveyProject

TRIMBLE_PROJECTS_URL = "https://app.connect.trimble.com/tc/api/2.0/projects?fullyLoaded=false"


def _request_json(url: str, *, token: str, method: str = "GET", body: dict | None = None, retries: int = 2) -> dict | list:
    if not url.lower().startswith("https://"):
        raise ValueError("Cloud API URLs must use HTTPS.")
    payload = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    if payload is not None: headers["Content-Type"] = "application/json"
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=payload, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                raw = response.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            if exc.code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(min(3.0, 0.6 * (2 ** attempt)))
                continue
            raise RuntimeError(f"Cloud API HTTP {exc.code}: {body_text[:300] or exc.reason}") from exc
        except urllib.error.URLError as exc:
            if attempt < retries:
                time.sleep(min(3.0, 0.6 * (2 ** attempt)))
                continue
            raise RuntimeError(f"Cloud API unavailable: {exc.reason}") from exc
    raise RuntimeError("Cloud API request failed.")


def trimble_list_projects(access_token: str) -> list[dict]:
    token = str(access_token or "").strip()
    if not token: raise ValueError("Trimble Connect access token is required for this session.")
    data = _request_json(TRIMBLE_PROJECTS_URL, token=token)
    if isinstance(data, dict):
        # API responses have varied between a direct list and a collection object.
        for key in ("projects", "items", "data"):
            if isinstance(data.get(key), list): return data[key]
        return [data] if data else []
    return data if isinstance(data, list) else []


def download_authenticated_file(url: str, access_token: str, destination: Path) -> dict:
    token = str(access_token or "").strip()
    if not token: raise ValueError("Cloud access token is required for this session.")
    if not str(url).lower().startswith("https://"):
        raise ValueError("Cloud file URL must use HTTPS.")
    dest = Path(destination).expanduser().resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(str(url), headers={"Authorization": f"Bearer {token}", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response, dest.open("wb") as fh:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk: break
                fh.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return {"path": str(dest), "size_bytes": dest.stat().st_size}


def import_cloud_file(project: SurveyProject, *, provider: str, url: str, access_token: str, filename: str, module: str = "FieldBookSync") -> dict:
    provider = str(provider or "").strip().lower()
    if provider not in {"trimble", "leica"}:
        raise ValueError("Cloud provider must be trimble or leica.")
    if provider == "leica":
        # ConX supports field/office cloud transfer, but SurveySync intentionally
        # does not invent a private/undocumented REST contract. An organization
        # with an official Leica API/file URL can use the generic authenticated
        # download boundary here after configuration.
        if not url:
            raise ValueError("Leica ConX direct sync requires an official file/API URL supplied by your Leica account/integration configuration.")
    safe = Path(filename or f"{provider}_download.bin").name
    temp = project.paths.cache / "cloud" / provider / f"{uuid4().hex}_{safe}"
    downloaded = download_authenticated_file(url, access_token, temp)
    source = project.import_source(temp, module, f"Imported from {provider.title()} cloud integration.")
    temp.unlink(missing_ok=True)
    sync_id = uuid4().hex
    with project.db.connect() as conn:
        conn.execute(
            "INSERT INTO cloud_sync_log(sync_id,ts_utc,provider,remote_project_id,remote_item_id,direction,local_path,status,details_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (sync_id, utc_now(), provider, "", url, "download", source["stored_path"], "SUCCESS", json.dumps({"filename": safe, "size_bytes": downloaded["size_bytes"], "source_id": source["source_id"]}, sort_keys=True)),
        )
    project.db.audit("Core", "CLOUD_FILE_IMPORTED", object_type="source", object_id=source["source_id"], details={"provider": provider, "filename": safe, "sync_id": sync_id})
    return {"sync_id": sync_id, "provider": provider, **source}


def list_sync_log(project: SurveyProject, limit: int = 100) -> list[dict]:
    with project.db.connect() as conn:
        rows = conn.execute("SELECT * FROM cloud_sync_log ORDER BY ts_utc DESC LIMIT ?", (max(1, min(int(limit), 1000)),)).fetchall()
    out=[]
    for row in rows:
        item=dict(row)
        try:item["details"]=json.loads(item.pop("details_json") or "{}")
        except Exception:item["details"]={}
        out.append(item)
    return out
