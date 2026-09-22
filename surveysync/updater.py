from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .config import ConfigStore, DEFAULT_UPDATE_MANIFEST_URL


def version_tuple(value: str) -> tuple[int, int, int, int]:
    """Return a normalized four-part numeric version for stable comparisons.

    ``9.1``, ``9.1.0`` and ``9.1.0.0`` therefore compare as the same release.
    """
    nums = [int(x) for x in re.findall(r"\d+", str(value or ""))[:4]]
    nums.extend([0] * (4 - len(nums)))
    return tuple(nums[:4])  # type: ignore[return-value]


def _https(url: str) -> str:
    u=str(url or "").strip()
    if not u.lower().startswith("https://"):
        raise ValueError("Update URLs must use HTTPS.")
    return u


def fetch_manifest(store: ConfigStore) -> dict:
    cfg=store.load(); url=_https(cfg.update_manifest_url or DEFAULT_UPDATE_MANIFEST_URL)
    req=urllib.request.Request(url,headers={"User-Agent":f"SurveySync/{__version__}","Accept":"application/json","Cache-Control":"no-cache"})
    with urllib.request.urlopen(req,timeout=20) as r:
        raw=r.read(1024*1024)
    data=json.loads(raw.decode("utf-8-sig"))
    if not isinstance(data,dict): raise ValueError("Update manifest must be a JSON object.")
    return data


def select_release(manifest: dict, channel: str) -> dict:
    channels=manifest.get("channels")
    if isinstance(channels,dict): rel=channels.get(channel)
    else: rel=manifest if str(manifest.get("channel") or "stable")==channel else None
    if not isinstance(rel,dict): raise ValueError(f"Manifest does not contain release channel '{channel}'.")
    version=str(rel.get("version") or "").strip(); url=_https(str(rel.get("installer_url") or "")); sha=str(rel.get("sha256") or "").lower().strip(); size=int(rel.get("size_bytes") or 0)
    if not version: raise ValueError("Release version is missing.")
    if not re.fullmatch(r"[0-9a-f]{64}",sha): raise ValueError("Release SHA-256 is invalid.")
    if size<=0: raise ValueError("Release size_bytes must be positive.")
    return {**rel,"version":version,"installer_url":url,"sha256":sha,"size_bytes":size,"channel":channel,"update_available":version_tuple(version)>version_tuple(__version__)}


def check(store: ConfigStore) -> dict:
    cfg=store.load()
    rel=select_release(fetch_manifest(store),cfg.release_channel)
    return {"configured":True,"current_version":__version__,**rel}


def stage(store: ConfigStore) -> dict:
    rel=check(store)
    if not rel.get("configured"): raise ValueError(rel["message"])
    if not rel.get("update_available"): raise ValueError("No newer SurveySync release is available on the selected channel.")
    root=store.root/"updates";root.mkdir(parents=True,exist_ok=True)
    name=f"SurveySync_Setup_{rel['version'].replace('.','_')}.exe"; dest=root/name; tmp=dest.with_suffix('.download')
    req=urllib.request.Request(rel["installer_url"],headers={"User-Agent":f"SurveySync/{__version__}"})
    h=hashlib.sha256();total=0
    try:
        with urllib.request.urlopen(req,timeout=60) as r, tmp.open('wb') as f:
            while True:
                chunk=r.read(1024*1024)
                if not chunk:break
                total+=len(chunk);h.update(chunk);f.write(chunk)
                if total>rel['size_bytes']+1024*1024:
                    raise ValueError("Downloaded installer exceeded manifest size.")
    except Exception:
        # Clean only after file handles are closed so this works on Windows too.
        tmp.unlink(missing_ok=True)
        raise
    digest=h.hexdigest()
    if total!=rel['size_bytes'] or digest.lower()!=rel['sha256'].lower():
        tmp.unlink(missing_ok=True);raise ValueError("Downloaded installer failed size/SHA-256 verification.")
    with tmp.open('rb') as f:
        if f.read(2)!=b'MZ': tmp.unlink(missing_ok=True);raise ValueError("Downloaded file is not a Windows executable.")
    tmp.replace(dest)
    pending={"version":rel['version'],"installer_path":str(dest),"sha256":digest,"size_bytes":total}
    p=store.root/'pending_update.json';t=p.with_suffix('.tmp');t.write_text(json.dumps(pending,indent=2),encoding='utf-8');t.replace(p)
    return {"staged":True,"pending_file":str(p),**pending}
