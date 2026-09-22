from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, asdict, field
from pathlib import Path
from threading import RLock

logger = logging.getLogger(__name__)

ENVIRONMENTS = ("developer", "beta", "production")
RELEASE_CHANNELS = ("developer", "beta", "stable")
DEFAULT_UPDATE_MANIFEST_URL = "https://raw.githubusercontent.com/cpaul1988/SurveySync/main/update.json"

DEFAULT_BRANDS = {
    "surveysync": {
        "id": "surveysync",
        "name": "SurveySync",
        "organization": "",
        "accent": "#2563eb",
        "tagline": "One project. Shared survey intelligence.",
        "demo_only": False,
    },
    "edsi-demo": {
        "id": "edsi-demo",
        "name": "SurveySync — EDSI Demo",
        "organization": "EDSI",
        "accent": "#0f766e",
        "tagline": "Client demonstration profile",
        "demo_only": True,
    },
}


def user_config_root() -> Path:
    override = os.environ.get("SURVEYSYNC_CONFIG_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "SurveySync"
    return Path.home() / ".surveysync"


@dataclass
class AppConfig:
    environment: str = "beta"
    release_channel: str = "beta"
    branding_profile: str = "surveysync"
    last_project: str = ""
    recent_projects: list[str] = field(default_factory=list)
    update_manifest_url: str = DEFAULT_UPDATE_MANIFEST_URL
    feedback_endpoint: str = ""
    ai_provider: str = "auto"
    ui_appearance: str = "system"
    ui_theme: str = "classic"
    ui_accent: str = "default"
    resource_environment: str = "beta"

    def normalize(self) -> "AppConfig":
        if self.environment not in ENVIRONMENTS:
            self.environment = "beta"
        if self.release_channel not in RELEASE_CHANNELS:
            self.release_channel = {"developer": "developer", "beta": "beta", "production": "stable"}[self.environment]
        if not self.branding_profile:
            self.branding_profile = "surveysync"
        # Keep a small, ordered MRU list for the project switcher. Older configs
        # did not have this field, so normalize defensively and deduplicate paths
        # without touching the project folders themselves.
        raw_recent = self.recent_projects if isinstance(self.recent_projects, list) else []
        normalized_recent: list[str] = []
        seen: set[str] = set()
        for value in raw_recent:
            text = str(value or "").strip()
            if not text:
                continue
            key = os.path.normcase(os.path.abspath(os.path.expanduser(text)))
            if key in seen:
                continue
            seen.add(key)
            normalized_recent.append(text)
            if len(normalized_recent) >= 24:
                break
        self.recent_projects = normalized_recent
        if self.ai_provider not in {"auto", "hybrid", "gemini", "openai", "anthropic", "manual"}:
            self.ai_provider = "auto"
        if self.ui_appearance not in {"system", "light", "dark"}:
            self.ui_appearance = "system"
        if self.ui_theme not in {"classic","edsi","slate","midnight","lightpro","contrast","carbon","obsidian","teal","violet","graphite","frost","arctic","sandstone","edsidark","edsilight"}:
            self.ui_theme = "classic"
        if self.ui_accent not in {"default","azure","teal","emerald","violet","amber","rose"}:
            self.ui_accent = "default"
        # Environment resources never carry across channels implicitly. Switching
        # Developer/Beta/Production clears remote update/feedback endpoints until
        # they are explicitly configured for the new environment.
        if self.resource_environment != self.environment:
            self.update_manifest_url = DEFAULT_UPDATE_MANIFEST_URL
            self.feedback_endpoint = ""
            self.resource_environment = self.environment
        return self


class ConfigStore:
    def __init__(self, root: Path | None = None):
        self.root = (root or user_config_root()).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "config.json"
        self.brands_path = self.root / "branding_profiles.json"
        self.lock = RLock()
        if not self.brands_path.exists():
            self._atomic_write(self.brands_path, DEFAULT_BRANDS)

    def _atomic_write(self, path: Path, payload) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def load(self) -> AppConfig:
        with self.lock:
            if not self.path.exists():
                cfg = AppConfig()
                self.save(cfg)
                return cfg
            try:
                data = json.loads(self.path.read_text(encoding="utf-8-sig"))
                return AppConfig(**{k: data.get(k, getattr(AppConfig(), k)) for k in asdict(AppConfig())}).normalize()
            except Exception:
                logger.warning("Could not parse SurveySync configuration %s; defaults will be used.", self.path, exc_info=True)
                return AppConfig()

    def save(self, cfg: AppConfig) -> None:
        with self.lock:
            cfg.normalize()
            self._atomic_write(self.path, asdict(cfg))

    def list_brands(self) -> list[dict]:
        with self.lock:
            try:
                raw = json.loads(self.brands_path.read_text(encoding="utf-8-sig"))
                if isinstance(raw, dict):
                    return [v for _, v in sorted(raw.items()) if isinstance(v, dict)]
            except Exception:
                logger.warning("Could not parse branding profiles %s; built-in profiles will be used.", self.brands_path, exc_info=True)
            return list(DEFAULT_BRANDS.values())

    def get_brand(self, brand_id: str) -> dict:
        for item in self.list_brands():
            if item.get("id") == brand_id:
                return item
        return dict(DEFAULT_BRANDS["surveysync"])

    def save_brand(self, profile: dict) -> dict:
        brand_id = str(profile.get("id") or "").strip().lower()
        if not brand_id or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in brand_id):
            raise ValueError("Brand profile id may contain only lowercase letters, numbers, hyphen and underscore.")
        with self.lock:
            try:
                raw = json.loads(self.brands_path.read_text(encoding="utf-8-sig"))
            except Exception:
                raw = dict(DEFAULT_BRANDS)
            raw[brand_id] = {
                "id": brand_id,
                "name": str(profile.get("name") or brand_id),
                "organization": str(profile.get("organization") or ""),
                "accent": str(profile.get("accent") or "#2563eb"),
                "tagline": str(profile.get("tagline") or ""),
                "demo_only": bool(profile.get("demo_only", True)),
            }
            self._atomic_write(self.brands_path, raw)
            return raw[brand_id]
