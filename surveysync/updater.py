"""Fail-closed HTTPS updater. Downloads are verified before an atomic handoff."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .release_identity import release_order, installed_release_id
from .config import ConfigStore, DEFAULT_UPDATE_MANIFEST_URL

_DOWNLOAD_LOCK = threading.Lock()
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_INSTALLER_BYTES = 4 * 1024 * 1024 * 1024


def version_tuple(value: str) -> tuple[int, int, int, int]:
    """Compare numeric releases without accepting arbitrary text or path characters."""
    text = str(value or "").strip()
    if not re.fullmatch(r"\d+(?:\.\d+){0,3}", text):
        raise ValueError("Release version must contain one to four numeric components.")
    nums = [int(x) for x in text.split(".")]
    if any(x > 65535 for x in nums):
        raise ValueError("Release version component is outside the supported range.")
    nums.extend([0] * (4 - len(nums)))
    return nums[0], nums[1], nums[2], nums[3]


def _https(url: str) -> str:
    text = str(url or "").strip()
    parsed = urlparse(text)
    if (parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.fragment or any(ord(c) < 33 for c in text)):
        raise ValueError("Update URLs must be credential-free HTTPS URLs.")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("Invalid update URL port.") from exc
    return text


class _HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(request, timeout):
    _https(request.full_url)
    return urllib.request.build_opener(_HTTPSRedirect()).open(request, timeout=timeout)


def fetch_manifest(store: ConfigStore) -> dict:
    cfg = store.load()
    url = _https(cfg.update_manifest_url or DEFAULT_UPDATE_MANIFEST_URL)
    req = urllib.request.Request(url, headers={"User-Agent": f"SurveySync/{__version__}",
                                              "Accept": "application/json", "Cache-Control": "no-cache"})
    with _open(req, timeout=20) as response:
        raw = response.read(MAX_MANIFEST_BYTES + 1)
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ValueError("Update manifest exceeds the supported size.")
    from .manifest_trust import decode_manifest
    data = decode_manifest(raw)
    if not isinstance(data, dict):
        raise ValueError("Update manifest must be a JSON object.")
    if data.get("product", "SurveySync") != "SurveySync":
        raise ValueError("Update manifest belongs to a different product.")
    return data


def select_release(manifest: dict, channel: str) -> dict:
    if channel not in {"stable", "beta", "developer"}:
        raise ValueError("Unknown release channel.")
    channels = manifest.get("channels")
    rel = channels.get(channel) if isinstance(channels, dict) else (
        manifest if str(manifest.get("channel") or "stable") == channel else None)
    if not isinstance(rel, dict):
        raise ValueError(f"Manifest does not contain release channel '{channel}'.")
    version = str(rel.get("version") or "").strip()
    numeric_version = version_tuple(version)
    identity = str(rel.get("release_id") or (rel.get("release_tag") if channel != "stable" else None) or version).removeprefix("v")
    order = release_order(identity)
    if order[0] != numeric_version:
        raise ValueError("Release identity does not match the numeric version.")
    # A promoted stable feed may explicitly retain the tested beta artifact's
    # physical build identity. Never pretend its installed stamp changed.
    current_id = installed_release_id(__version__)
    url = _https(str(rel.get("installer_url") or ""))
    sha = str(rel.get("sha256") or "").lower().strip()
    if channel == "stable" and order[1] != 1 and not (
        rel.get("promoted_from") == "beta" and rel.get("artifact_identity") == "sha256:" + sha
    ):
        raise ValueError("Stable prerelease identity requires an explicit exact-artifact Beta promotion.")
    size = rel.get("size_bytes")
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError("Release SHA-256 is invalid.")
    if isinstance(size, bool) or not isinstance(size, int) or not 0 < size <= MAX_INSTALLER_BYTES:
        raise ValueError("Release size_bytes must be a positive bounded integer.")
    return {**rel, "version": version, "installer_url": url, "sha256": sha,
            "size_bytes": size, "channel": channel,
            "release_id": identity, "current_release_id": current_id,
            "update_available": order > release_order(current_id)}


def check(store: ConfigStore) -> dict:
    cfg = store.load()
    rel = select_release(fetch_manifest(store), cfg.release_channel)
    # Verified helper receipt avoids reinstalling identical bytes on beta promotion.
    receipt_path = store.root / "installed_update.json"
    if receipt_path.is_file() and rel["version"] == __version__:
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (receipt.get("version") == __version__
                    and receipt.get("release_id") == rel["current_release_id"]
                    and receipt.get("sha256") == rel["sha256"]):
                rel["update_available"] = False
                rel["same_installed_artifact"] = True
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    return {"configured": True, "current_version": __version__, **rel}


def stage(store: ConfigStore) -> dict:
    if not _DOWNLOAD_LOCK.acquire(blocking=False):
        raise ValueError("An update download is already in progress.")
    try:
        return _stage(store)
    finally:
        _DOWNLOAD_LOCK.release()


def _stage(store: ConfigStore) -> dict:
    cfg = store.load()
    selected = (cfg.release_channel, cfg.update_manifest_url)
    rel = check(store)
    if not rel.get("update_available"):
        raise ValueError("No newer SurveySync release is available on the selected channel.")
    root = store.root / "updates"
    root.mkdir(parents=True, exist_ok=True)
    if not root.resolve().is_relative_to(store.root.resolve()):
        raise ValueError("Updates directory escapes the application data root.")
    # All filename inputs have already been strictly validated; distinct hashes do
    # not overwrite a previously approved executable with the same version label.
    name = f"SurveySync_Setup_{rel['version'].replace('.', '_')}_{rel['sha256'][:12]}.exe"
    dest = root / name
    request = urllib.request.Request(rel["installer_url"], headers={"User-Agent": f"SurveySync/{__version__}"})
    temporary = None
    handoff_tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix="stage-", suffix=".download", delete=False) as out:
            temporary = Path(out.name)
            digest = hashlib.sha256()
            total = 0
            header = b""
            with _open(request, timeout=60) as response:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > rel["size_bytes"]:
                        raise ValueError("Downloaded installer exceeded manifest size.")
                    if len(header) < 2:
                        header = (header + chunk)[:2]
                    digest.update(chunk)
                    out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        # Every handle is closed before cleanup/replacement, including invalid MZ.
        if total != rel["size_bytes"] or digest.hexdigest() != rel["sha256"]:
            raise ValueError("Downloaded installer failed size/SHA-256 verification.")
        if header != b"MZ":
            raise ValueError("Downloaded file is not a Windows executable.")
        current = store.load()
        if (current.release_channel, current.update_manifest_url) != selected:
            raise ValueError("Update configuration changed during download; check again.")
        temporary.replace(dest)
        temporary = None
        pending = {"version": rel["version"], "release_id": rel.get("release_id", rel["version"]), "installer_path": str(dest),
                   "sha256": rel["sha256"], "size_bytes": total}
        handoff = store.root / "pending_update.json"
        with tempfile.NamedTemporaryFile(mode="w", dir=store.root, prefix="pending-", suffix=".tmp",
                                         encoding="utf-8", delete=False) as out:
            handoff_tmp = Path(out.name)
            json.dump(pending, out, indent=2)
            out.flush()
            os.fsync(out.fileno())
        handoff_tmp.replace(handoff)
        handoff_tmp = None
        return {"staged": True, "pending_file": str(handoff), **pending}
    finally:
        for path in (temporary, handoff_tmp):
            if path is not None:
                path.unlink(missing_ok=True)
