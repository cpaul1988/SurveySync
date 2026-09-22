from __future__ import annotations

import json
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .models import AppState, CodeProfile


def _safe_name(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", (name or "Untitled Project")).strip()
    return name[:100] or "Untitled Project"


def create_project_bundle(state: AppState, page_dir: Path, out_dir: Path, profile: CodeProfile | None = None) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{_safe_name(state.project_name).replace(' ', '_')}_{stamp}.fbs"
    payload = state.model_dump(mode="json")
    # Paths inside the bundle are made relative and reconstructed on import.
    for page in payload.get("fieldbook_pages", []):
        page["image_path"] = f"pages/{Path(page['image_path']).name}"
        if page.get("enhanced_image_path"):
            page["enhanced_image_path"] = f"pages/{Path(page['enhanced_image_path']).name}"
    for ex in payload.get("verified_examples", []):
        if ex.get("crop_path"):
            ex["crop_path"] = f"examples/{Path(ex['crop_path']).name}"

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(payload, ensure_ascii=False, indent=2))
        if profile is not None:
            zf.writestr("profile.json", profile.model_dump_json(indent=2))
        if page_dir.exists():
            for file in page_dir.rglob("*"):
                if file.is_file():
                    zf.write(file, f"pages/{file.name}")
        # Verified crops can be outside page_dir.
        for ex in state.verified_examples:
            if ex.crop_path:
                p = Path(ex.crop_path)
                if p.exists():
                    zf.write(p, f"examples/{p.name}")
        zf.writestr("README.txt", "FieldBook Sync project bundle (.fbs). Open from FieldBook Sync; do not edit internal files manually.\n")
    return path


def load_project_bundle(bundle: Path, target_page_dir: Path, examples_dir: Path) -> tuple[AppState, CodeProfile | None]:
    work = target_page_dir.parent / f"project_import_{uuid4().hex}"
    work.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(bundle, "r") as zf:
            names = zf.namelist()
            if "project.json" not in names:
                raise ValueError("This .fbs file does not contain project.json.")
            # Prevent zip-slip paths.
            for name in names:
                p = Path(name)
                if p.is_absolute() or ".." in p.parts:
                    raise ValueError("Project contains an unsafe path.")
            zf.extractall(work)
        state = AppState.model_validate_json((work / "project.json").read_text(encoding="utf-8"))
        profile = None
        if (work / "profile.json").exists():
            profile = CodeProfile.model_validate_json((work / "profile.json").read_text(encoding="utf-8"))

        if target_page_dir.exists():
            shutil.rmtree(target_page_dir)
        target_page_dir.mkdir(parents=True, exist_ok=True)
        imported_pages = work / "pages"
        if imported_pages.exists():
            for p in imported_pages.iterdir():
                if p.is_file():
                    shutil.copy2(p, target_page_dir / p.name)
        examples_dir.mkdir(parents=True, exist_ok=True)
        imported_examples = work / "examples"
        if imported_examples.exists():
            for p in imported_examples.iterdir():
                if p.is_file():
                    shutil.copy2(p, examples_dir / p.name)

        for page in state.fieldbook_pages:
            page.image_path = str(target_page_dir / Path(page.image_path).name)
            if page.enhanced_image_path:
                page.enhanced_image_path = str(target_page_dir / Path(page.enhanced_image_path).name)
        for ex in state.verified_examples:
            if ex.crop_path:
                ex.crop_path = str(examples_dir / Path(ex.crop_path).name)
        return state, profile
    finally:
        shutil.rmtree(work, ignore_errors=True)
