from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .storage import workspace


def _root() -> Path:
    root, _ = workspace()
    path = root / "profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _profile_id(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-").lower()
    if not clean:
        raise ValueError("Profile name is required.")
    return clean[:80]


def list_profiles() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(_root().glob("*.json"), key=lambda p: p.name.lower()):
        try:
            item = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if isinstance(item, dict):
            items.append(item)
    return items


def save_profile(
    *,
    profile_id: str,
    name: str,
    settings: dict[str, Any],
    rules: list[dict[str, Any]],
    description: str = "",
) -> dict[str, Any]:
    pid = _profile_id(profile_id or name)
    if not name.strip():
        raise ValueError("Profile name is required.")
    payload = {
        "profile_id": pid,
        "name": name.strip()[:120],
        "description": description.strip()[:500],
        "settings": dict(settings or {}),
        "rules": list(rules or []),
        "advisory_only": True,
    }
    path = _root() / f"{pid}.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)
    return payload


def delete_profile(profile_id: str) -> dict[str, Any]:
    pid = _profile_id(profile_id)
    path = _root() / f"{pid}.json"
    existed = path.is_file()
    path.unlink(missing_ok=True)
    return {"profile_id": pid, "deleted": existed}
