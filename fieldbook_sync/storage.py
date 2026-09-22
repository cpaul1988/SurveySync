from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from threading import RLock

from .models import AppState, utc_now_iso

logger = logging.getLogger(__name__)


class AppStorage:
    def __init__(self, root: Path | str | None = None) -> None:
        if root is not None:
            self.root = Path(root).expanduser().resolve()
        elif os.environ.get("SURVEYSYNC_FIELD_ROOT"):
            self.root = Path(os.environ["SURVEYSYNC_FIELD_ROOT"]).expanduser().resolve()
        else:
            base = os.environ.get("LOCALAPPDATA")
            if base:
                self.root = Path(base) / "FieldBookSync"
            else:
                self.root = Path.home() / ".fieldbook_sync"
        self.root.mkdir(parents=True, exist_ok=True)
        self.profile_dir = self.root / "profiles"
        self.field_note_profile_dir = self.root / "field_note_profiles"
        self.field_note_training_dir = self.root / "field_note_training"
        self.page_dir = self.root / "pages"
        self.enhanced_dir = self.page_dir / "enhanced"
        self.export_dir = self.root / "exports"
        self.project_dir = self.root / "projects"
        self.examples_dir = self.root / "verified_examples"
        self.batch_dir = self.root / "batch"
        self.feedback_dir = self.root / "feedback"
        self.state_path = self.root / "project.json"
        self.recovery_path = self.root / "project.recovery.json"
        self.settings_path = self.root / "settings.json"
        for d in [self.profile_dir, self.field_note_profile_dir, self.field_note_training_dir, self.page_dir, self.enhanced_dir, self.export_dir, self.project_dir, self.examples_dir, self.batch_dir, self.feedback_dir]:
            d.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.state = self._load_state()

    def _load_state(self) -> AppState:
        if not self.state_path.exists():
            return AppState()
        try:
            return AppState.model_validate_json(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            backup = self.state_path.with_suffix(".corrupt.json")
            try:
                shutil.copy2(self.state_path, backup)
            except Exception:
                logger.warning("Could not create FieldBookSync state backup %s.", backup, exc_info=True)
            if self.recovery_path.exists():
                try:
                    return AppState.model_validate_json(self.recovery_path.read_text(encoding="utf-8"))
                except Exception:
                    logger.warning("FieldBookSync recovery state %s could not be parsed.", self.recovery_path, exc_info=True)
            return AppState()

    def save(self) -> None:
        """Atomic autosave with a one-generation crash-recovery snapshot."""
        with self.lock:
            self.state.project_modified_at = utc_now_iso()
            if self.state_path.exists():
                try:
                    shutil.copy2(self.state_path, self.recovery_path)
                except Exception:
                    logger.warning("Could not preserve FieldBookSync recovery copy %s.", self.recovery_path, exc_info=True)
            temp = self.state_path.with_suffix(".tmp")
            temp.write_text(self.state.model_dump_json(indent=2), encoding="utf-8")
            temp.replace(self.state_path)

    def load_settings(self) -> dict:
        with self.lock:
            if not self.settings_path.exists():
                return {}
            try:
                data = json.loads(self.settings_path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except Exception:
                return {}

    def save_settings(self, data: dict) -> None:
        with self.lock:
            temp = self.settings_path.with_suffix(".tmp")
            temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            temp.replace(self.settings_path)

    def reset_project(self) -> None:
        with self.lock:
            selected = self.state.selected_profile
            batch_jobs = self.state.batch_jobs
            self.state = AppState(selected_profile=selected, batch_jobs=batch_jobs)
            if self.page_dir.exists():
                shutil.rmtree(self.page_dir)
            self.page_dir.mkdir(parents=True, exist_ok=True)
            self.enhanced_dir = self.page_dir / "enhanced"
            self.enhanced_dir.mkdir(parents=True, exist_ok=True)
            self.save()
