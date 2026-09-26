from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .audit import AuditDB, CURRENT_SCHEMA_VERSION, utc_now
from .project_templates import get_template
from .crs import inspect_crs, normalize_local_site

logger = logging.getLogger(__name__)

PRODUCT = "SurveySync"
PROJECT_FORMAT = 1

DEFAULT_MODULES = [
    "FieldBookSync", "UtilitySync", "ControlSync", "TopoSync", "COGOSync",
    "BoundarySync", "GISSync", "ReportSync", "QASync", "CrewSync",
]


def safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._ -]+", "_", (value or "Survey Project")).strip(" .")
    return value[:120] or "Survey Project"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class ProjectPaths:
    root: Path

    @property
    def manifest(self): return self.root / "survey_sync_project.json"
    @property
    def db(self): return self.root / ".surveysync" / "survey_sync.db"
    @property
    def source(self): return self.root / "Source"
    @property
    def derived(self): return self.root / "Derived"
    @property
    def reports(self): return self.root / "Reports"
    @property
    def exports(self): return self.root / "Exports"
    @property
    def attachments(self): return self.root / "Attachments"
    @property
    def module_root(self): return self.root / "Modules"
    @property
    def fieldbook_root(self): return self.module_root / "FieldBookSync"
    @property
    def cache(self): return self.root / ".surveysync" / "cache"
    @property
    def logs(self): return self.root / ".surveysync" / "logs"
    @property
    def snapshots(self): return self.root / ".surveysync" / "snapshots"
    @property
    def migration_backups(self): return self.root / ".surveysync" / "migration_backups"
    @property
    def photos(self): return self.attachments / "Photos"
    @property
    def deliverables(self): return self.exports / "Deliverables"

    def ensure(self):
        for p in [self.root, self.db.parent, self.source, self.derived, self.reports, self.exports,
                  self.attachments, self.photos, self.deliverables, self.module_root, self.fieldbook_root, self.cache, self.logs, self.snapshots, self.migration_backups]:
            p.mkdir(parents=True, exist_ok=True)
        for module in DEFAULT_MODULES:
            (self.module_root / module).mkdir(parents=True, exist_ok=True)


class SurveyProject:
    def __init__(self, root: Path):
        self.paths = ProjectPaths(Path(root).expanduser().resolve())
        if not self.paths.manifest.exists():
            raise FileNotFoundError(f"Not a SurveySync project: {self.paths.root}")
        self.paths.ensure()
        self.manifest = self._load_manifest()
        prior_schema = AuditDB.read_schema_version(self.paths.db)
        migration_backup = ""
        if self.paths.db.exists() and prior_schema < CURRENT_SCHEMA_VERSION:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = self.paths.migration_backups / f"pre_schema_v{prior_schema}_{stamp}.db"
            shutil.copy2(self.paths.db, backup)
            migration_backup = str(backup)
        self.db = AuditDB(self.paths.db)
        actual_schema = self.db.schema_version()
        if "coordinate_system" not in self.manifest:
            self.manifest["coordinate_system"] = {
                "crs": self.manifest.get("crs", ""),
                "name": inspect_crs(self.manifest.get("crs", "")).get("name", "") if self.manifest.get("crs") else "",
                "authority": inspect_crs(self.manifest.get("crs", "")).get("authority", "") if self.manifest.get("crs") else "",
                "horizontal_units": self.manifest.get("horizontal_units", "us_survey_feet"),
                "vertical_units": self.manifest.get("vertical_units", "us_survey_feet"),
                "local_site": normalize_local_site(None),
            }
            self._atomic_json(self.paths.manifest, self.manifest)
        self._persist_coordinate_settings()
        if int(self.manifest.get("database_schema_version", 0) or 0) != actual_schema:
            self.manifest["database_schema_version"] = actual_schema
            self._atomic_json(self.paths.manifest, self.manifest)
            self.db.audit("Core", "DATABASE_SCHEMA_MIGRATED" if prior_schema < actual_schema else "DATABASE_SCHEMA_RECORDED", object_type="project_database", object_id=str(self.manifest.get("project_id") or ""), details={"from": prior_schema, "to": actual_schema, "backup": migration_backup})

    @classmethod
    def create(cls, parent: Path, name: str, *, crs: str = "", horizontal_units: str = "us_survey_feet", vertical_units: str = "us_survey_feet", environment: str = "beta", branding_profile: str = "surveysync", template_id: str = "standard", client: str = "", project_number: str = "", local_site: dict | None = None) -> "SurveyProject":
        parent = Path(parent).expanduser().resolve()
        parent.mkdir(parents=True, exist_ok=True)
        root = parent / safe_name(name)
        if root.exists() and any(root.iterdir()):
            raise FileExistsError(f"Project folder already exists and is not empty: {root}")
        paths = ProjectPaths(root)
        paths.ensure()
        template = get_template(template_id)
        template_db = Path(__file__).with_name("resources") / "project_template.db"
        if template_db.is_file():
            shutil.copy2(template_db, paths.db)
        # Bring the copied master template to the current schema before the
        # project is opened. Migration backups are reserved for real user
        # projects, not for a just-created copy of an older bundled template.
        AuditDB(paths.db)
        now = utc_now()
        enabled = set(template.get("enabled_modules") or DEFAULT_MODULES)
        manifest = {
            "product": PRODUCT,
            "format_version": PROJECT_FORMAT,
            "project_id": str(uuid4()),
            "name": safe_name(name),
            "created_utc": now,
            "modified_utc": now,
            "revision": 1,
            "environment_created": environment,
            "branding_profile": branding_profile,
            "client": str(client or ""),
            "project_number": str(project_number or ""),
            "project_template": {"id": template["id"], "name": template["name"], "version": 1},
            "database_schema_version": CURRENT_SCHEMA_VERSION,
            "crs": crs,
            "horizontal_units": horizontal_units,
            "vertical_units": vertical_units,
            "coordinate_system": {
                "crs": crs,
                "name": inspect_crs(crs).get("name", "") if crs else "",
                "authority": inspect_crs(crs).get("authority", "") if crs else "",
                "horizontal_units": horizontal_units,
                "vertical_units": vertical_units,
                "local_site": normalize_local_site(local_site),
            },
            "modules": {m: {"enabled": m in enabled, "schema_version": 1} for m in DEFAULT_MODULES},
            "fieldbook_migration": {"status": "NOT_MIGRATED", "source": ""},
            "notes": "",
        }
        cls._atomic_json(paths.manifest, manifest)
        project = cls(root)
        with project.db.connect() as conn:
            for key, value in {"project_id": manifest["project_id"], "project_name": manifest["name"], "client": str(client or ""), "project_number": str(project_number or ""), "template_id": template["id"], "template_name": template["name"]}.items():
                conn.execute("INSERT INTO project_metadata(key,value,updated_utc) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_utc=excluded.updated_utc", (key, value, now))
        qa_overrides = template.get("qa_overrides") or {}
        if qa_overrides:
            qa_path = project.paths.db.parent / "qa_rules.json"
            qa_path.write_text(json.dumps(qa_overrides, indent=2, sort_keys=True), encoding="utf-8")
        project._persist_coordinate_settings()
        project.db.audit("Core", "PROJECT_CREATED", object_type="project", object_id=manifest["project_id"], revision=1, details={"root": str(root), "crs": crs, "horizontal_units": horizontal_units, "vertical_units": vertical_units, "local_site": manifest["coordinate_system"]["local_site"], "template": template["id"], "client": client, "project_number": project_number})
        return project

    @staticmethod
    def _atomic_json(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def _load_manifest(self) -> dict:
        raw = json.loads(self.paths.manifest.read_text(encoding="utf-8-sig"))
        if raw.get("product") != PRODUCT or int(raw.get("format_version", 0)) != PROJECT_FORMAT:
            raise ValueError("Unsupported or invalid SurveySync project manifest.")
        return raw

    def save_manifest(self, *, action: str = "PROJECT_UPDATED", details: dict | None = None) -> None:
        self.manifest["modified_utc"] = utc_now()
        self.manifest["revision"] = int(self.manifest.get("revision", 0)) + 1
        self._atomic_json(self.paths.manifest, self.manifest)
        self.db.audit("Core", action, object_type="project", object_id=self.manifest["project_id"], revision=self.manifest["revision"], details=details or {})

    def coordinate_settings(self) -> dict:
        stored = dict(self.manifest.get("coordinate_system") or {})
        crs = str(stored.get("crs") or self.manifest.get("crs") or "").strip()
        info = inspect_crs(crs) if crs else {"valid": False, "name": "", "authority": ""}
        return {
            "crs": crs,
            "name": str(stored.get("name") or info.get("name") or ""),
            "authority": str(stored.get("authority") or info.get("authority") or ""),
            "horizontal_units": str(stored.get("horizontal_units") or self.manifest.get("horizontal_units") or "us_survey_feet"),
            "vertical_units": str(stored.get("vertical_units") or self.manifest.get("vertical_units") or "us_survey_feet"),
            "local_site": normalize_local_site(stored.get("local_site")),
        }

    def _persist_coordinate_settings(self) -> None:
        settings = self.coordinate_settings()
        site = settings["local_site"]
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO project_coordinate_settings(
                       setting_id,updated_utc,crs,crs_name,horizontal_units,vertical_units,
                       local_site_enabled,local_site_name,grid_origin_northing,grid_origin_easting,
                       local_origin_northing,local_origin_easting,grid_to_ground_factor,rotation_deg,notes
                   ) VALUES('active',?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(setting_id) DO UPDATE SET
                       updated_utc=excluded.updated_utc,crs=excluded.crs,crs_name=excluded.crs_name,
                       horizontal_units=excluded.horizontal_units,vertical_units=excluded.vertical_units,
                       local_site_enabled=excluded.local_site_enabled,local_site_name=excluded.local_site_name,
                       grid_origin_northing=excluded.grid_origin_northing,grid_origin_easting=excluded.grid_origin_easting,
                       local_origin_northing=excluded.local_origin_northing,local_origin_easting=excluded.local_origin_easting,
                       grid_to_ground_factor=excluded.grid_to_ground_factor,rotation_deg=excluded.rotation_deg,notes=excluded.notes""",
                (utc_now(), settings["crs"], settings["name"], settings["horizontal_units"], settings["vertical_units"],
                 1 if site["enabled"] else 0, site["name"], site["grid_origin_northing"], site["grid_origin_easting"],
                 site["local_origin_northing"], site["local_origin_easting"], site["grid_to_ground_factor"], site["rotation_deg"],
                 "Modified-ground/local-site settings. Factor direction is grid-to-ground."),
            )

    def set_coordinate_system(self, crs: str, horizontal_units: str, vertical_units: str, local_site: dict | None = None) -> None:
        raw_crs = str(crs or "").strip()
        if not raw_crs:
            raise ValueError("Choose a project coordinate system before saving project coordinates.")
        info = inspect_crs(raw_crs)
        if not info.get("valid"):
            raise ValueError(f"Invalid project coordinate system: {info.get('message', raw_crs)}")
        site = normalize_local_site(local_site)
        before = self.coordinate_settings()
        canonical_crs = str(info.get("authority") or raw_crs)
        settings = {
            "crs": canonical_crs,
            "name": info.get("name", ""),
            "authority": info.get("authority", ""),
            "horizontal_units": horizontal_units,
            "vertical_units": vertical_units,
            "local_site": site,
        }
        self.manifest.update(
            crs=canonical_crs, horizontal_units=horizontal_units, vertical_units=vertical_units,
            coordinate_system=settings,
        )
        self.save_manifest(action="PROJECT_COORDINATE_SYSTEM_CHANGED", details={"before": before, "after": settings})
        self._persist_coordinate_settings()

    def set_crs_units(self, crs: str, horizontal_units: str, vertical_units: str) -> None:
        # Compatibility endpoint: keep any existing local-site settings while updating
        # the underlying project CRS and units.
        self.set_coordinate_system(crs, horizontal_units, vertical_units, self.coordinate_settings().get("local_site"))

    def import_source(self, src: Path, module: str, notes: str = "") -> dict:
        src = Path(src).expanduser().resolve()
        if not src.is_file():
            raise FileNotFoundError(src)
        digest = sha256_file(src)
        module_dir = self.paths.source / safe_name(module)
        module_dir.mkdir(parents=True, exist_ok=True)
        dest = module_dir / src.name
        if dest.exists() and sha256_file(dest) != digest:
            dest = module_dir / f"{src.stem}_{digest[:8]}{src.suffix}"
        if not dest.exists():
            shutil.copy2(src, dest)
        try:
            dest.chmod(dest.stat().st_mode & ~0o222)
        except Exception:
            logger.debug("Could not mark immutable source read-only: %s", dest, exc_info=True)
        source_id = uuid4().hex
        with self.db.connect() as conn:
            prior = conn.execute("SELECT * FROM source_registry WHERE sha256=? AND stored_path=?", (digest, str(dest.relative_to(self.paths.root)))).fetchone()
            if prior:
                return dict(prior)
            conn.execute(
                "INSERT INTO source_registry(source_id,added_utc,module,original_name,sha256,stored_path,media_type,byte_size,notes) VALUES(?,?,?,?,?,?,?,?,?)",
                (source_id, utc_now(), module, src.name, digest, str(dest.relative_to(self.paths.root)), mimetypes.guess_type(src.name)[0] or "", src.stat().st_size, notes),
            )
        self.db.audit(module, "SOURCE_IMPORTED", object_type="source", object_id=source_id, revision=int(self.manifest.get("revision", 1)), details={"original_name": src.name, "sha256": digest, "stored_path": str(dest.relative_to(self.paths.root))})
        return {"source_id": source_id, "sha256": digest, "stored_path": str(dest), "original_name": src.name}

    def sources(self) -> list[dict]:
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM source_registry ORDER BY added_utc DESC").fetchall()]

    def summary(self) -> dict:
        with self.db.connect() as conn:
            counts = {
                "sources": conn.execute("SELECT COUNT(*) FROM source_registry").fetchone()[0],
                "points": conn.execute("SELECT COUNT(*) FROM canonical_points").fetchone()[0],
                "control_observations": conn.execute("SELECT COUNT(*) FROM control_observations").fetchone()[0],
                "open_qa": conn.execute("SELECT COUNT(*) FROM qa_issues WHERE status='OPEN'").fetchone()[0],
                "audit_events": conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0],
            }
        with self.db.connect() as conn:
            stale_results = int(conn.execute("SELECT COUNT(*) FROM derived_result_state WHERE state='STALE'").fetchone()[0])
        return {**self.manifest, "root": str(self.paths.root), "counts": counts, "database": {"path": str(self.paths.db), "schema_version": self.db.schema_version(), "required_schema_version": CURRENT_SCHEMA_VERSION, "size_bytes": self.paths.db.stat().st_size if self.paths.db.exists() else 0, "stale_results": stale_results}}
