from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

CURRENT_SCHEMA_VERSION = 6


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


AUDIT_HASH_VERSION = 1
AUDIT_GENESIS_HASH = "0" * 64


def _audit_hash(
    *,
    seq: int,
    event_id: str,
    ts_utc: str,
    actor: str,
    module: str,
    action: str,
    object_type: str,
    object_id: str,
    revision: int,
    details_json: str,
    prev_hash: str,
) -> str:
    """Compute a canonical SHA-256 chain hash for one project audit event.

    The design is inspired by Block's Apache-2.0 Buzz tamper-evident audit
    chain, adapted here for SurveySync's local SQLite project database.
    """

    payload = {
        "hash_version": AUDIT_HASH_VERSION,
        "seq": int(seq),
        "event_id": str(event_id),
        "ts_utc": str(ts_utc),
        "actor": str(actor),
        "module": str(module),
        "action": str(action),
        "object_type": str(object_type or ""),
        "object_id": str(object_id or ""),
        "revision": int(revision or 0),
        "details_json": str(details_json or "{}"),
        "prev_hash": str(prev_hash or AUDIT_GENESIS_HASH),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    actor TEXT NOT NULL,
    module TEXT NOT NULL,
    action TEXT NOT NULL,
    object_type TEXT,
    object_id TEXT,
    revision INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_events(ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_audit_module ON audit_events(module, ts_utc DESC);

CREATE TABLE IF NOT EXISTS audit_chain (
    seq INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    hash_version INTEGER NOT NULL DEFAULT 1,
    prev_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES audit_events(event_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_audit_chain_event ON audit_chain(event_id);

CREATE TABLE IF NOT EXISTS source_registry (
    source_id TEXT PRIMARY KEY,
    added_utc TEXT NOT NULL,
    module TEXT NOT NULL,
    original_name TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    media_type TEXT,
    byte_size INTEGER NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_source_hash_path ON source_registry(sha256, stored_path);

CREATE TABLE IF NOT EXISTS canonical_points (
    point_uuid TEXT PRIMARY KEY,
    point_id TEXT NOT NULL,
    northing REAL,
    easting REAL,
    elevation REAL,
    description TEXT NOT NULL DEFAULT '',
    point_class TEXT NOT NULL DEFAULT 'survey',
    source_id TEXT,
    derived_from_json TEXT NOT NULL DEFAULT '[]',
    crs TEXT NOT NULL DEFAULT '',
    horizontal_units TEXT NOT NULL DEFAULT '',
    vertical_units TEXT NOT NULL DEFAULT '',
    review_state TEXT NOT NULL DEFAULT 'UNREVIEWED',
    revision INTEGER NOT NULL DEFAULT 1,
    created_utc TEXT NOT NULL,
    modified_utc TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES source_registry(source_id)
);
CREATE INDEX IF NOT EXISTS idx_point_id ON canonical_points(point_id);

CREATE TABLE IF NOT EXISTS qa_issues (
    issue_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    module TEXT NOT NULL,
    severity TEXT NOT NULL,
    code TEXT NOT NULL,
    object_id TEXT,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_qa_status ON qa_issues(status, severity);

CREATE TABLE IF NOT EXISTS control_observations (
    observation_id TEXT PRIMARY KEY,
    control_id TEXT NOT NULL,
    source_id TEXT,
    northing REAL NOT NULL,
    easting REAL NOT NULL,
    elevation REAL,
    h_sigma REAL,
    v_sigma REAL,
    observed_utc TEXT,
    method TEXT NOT NULL DEFAULT '',
    include INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT '',
    point_id TEXT NOT NULL DEFAULT '',
    shot_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    observed_time_provided INTEGER NOT NULL DEFAULT 0,
    epoch_count INTEGER,
    duration_seconds REAL,
    satellite_count INTEGER,
    pdop REAL,
    hdop REAL,
    vdop REAL,
    fix_type TEXT NOT NULL DEFAULT '',
    receiver_model TEXT NOT NULL DEFAULT '',
    receiver_serial TEXT NOT NULL DEFAULT '',
    antenna_type TEXT NOT NULL DEFAULT '',
    antenna_height REAL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(source_id) REFERENCES source_registry(source_id)
);
CREATE INDEX IF NOT EXISTS idx_control_id ON control_observations(control_id);



CREATE TABLE IF NOT EXISTS control_solutions (
    solution_id TEXT PRIMARY KEY,
    control_id TEXT NOT NULL,
    ts_utc TEXT NOT NULL,
    revision INTEGER NOT NULL,
    method TEXT NOT NULL,
    northing REAL NOT NULL,
    easting REAL NOT NULL,
    elevation REAL,
    pass INTEGER NOT NULL,
    settings_json TEXT NOT NULL DEFAULT '{}',
    residuals_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_control_solution_id ON control_solutions(control_id, revision DESC);

CREATE TABLE IF NOT EXISTS level_runs (
    run_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    source_id TEXT,
    start_point TEXT NOT NULL DEFAULT '',
    end_point TEXT NOT NULL DEFAULT '',
    start_elevation REAL,
    known_end_elevation REAL,
    adjustment_method TEXT NOT NULL DEFAULT 'setups',
    status TEXT NOT NULL DEFAULT 'IMPORTED',
    notes TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(source_id) REFERENCES source_registry(source_id)
);
CREATE TABLE IF NOT EXISTS level_observations (
    observation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    point_id TEXT NOT NULL DEFAULT '',
    backsight REAL,
    foresight REAL,
    bs_upper REAL,
    bs_middle REAL,
    bs_lower REAL,
    fs_upper REAL,
    fs_middle REAL,
    fs_lower REAL,
    distance_bs REAL,
    distance_fs REAL,
    notes TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(run_id) REFERENCES level_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_level_obs_run ON level_observations(run_id, sequence_no);
CREATE TABLE IF NOT EXISTS level_solutions (
    solution_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    ts_utc TEXT NOT NULL,
    revision INTEGER NOT NULL,
    closure REAL,
    adjusted INTEGER NOT NULL DEFAULT 0,
    method TEXT NOT NULL DEFAULT '',
    settings_json TEXT NOT NULL DEFAULT '{}',
    results_json TEXT NOT NULL DEFAULT '[]',
    qc_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(run_id) REFERENCES level_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_level_solution_run ON level_solutions(run_id, revision DESC);

CREATE TABLE IF NOT EXISTS solution_selections (
    solution_kind TEXT NOT NULL,
    object_id TEXT NOT NULL,
    solution_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    selected_utc TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(solution_kind, object_id)
);
CREATE INDEX IF NOT EXISTS idx_solution_selection_id ON solution_selections(solution_id);

CREATE TABLE IF NOT EXISTS traverse_runs (
    run_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_utc TEXT NOT NULL,
    source_id TEXT,
    start_n REAL NOT NULL,
    start_e REAL NOT NULL,
    end_n REAL,
    end_e REAL,
    adjustment_method TEXT NOT NULL DEFAULT 'bowditch',
    status TEXT NOT NULL DEFAULT 'IMPORTED',
    notes TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(source_id) REFERENCES source_registry(source_id)
);
CREATE TABLE IF NOT EXISTS traverse_courses (
    course_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    sequence_no INTEGER NOT NULL,
    from_point TEXT NOT NULL DEFAULT '',
    to_point TEXT NOT NULL DEFAULT '',
    azimuth_deg REAL NOT NULL,
    distance REAL NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(run_id) REFERENCES traverse_runs(run_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS traverse_solutions (
    solution_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    ts_utc TEXT NOT NULL,
    revision INTEGER NOT NULL,
    closure_n REAL,
    closure_e REAL,
    linear_closure REAL,
    precision_ratio REAL,
    adjusted INTEGER NOT NULL DEFAULT 0,
    method TEXT NOT NULL DEFAULT '',
    results_json TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY(run_id) REFERENCES traverse_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS utility_structures (
    structure_id TEXT PRIMARY KEY,
    point_id TEXT NOT NULL DEFAULT '',
    source_kind TEXT NOT NULL DEFAULT 'survey',
    northing REAL,
    easting REAL,
    elevation REAL,
    code TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'UNREVIEWED',
    attributes_json TEXT NOT NULL DEFAULT '{}',
    created_utc TEXT NOT NULL,
    modified_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_utility_point ON utility_structures(point_id);
CREATE TABLE IF NOT EXISTS utility_pipes (
    pipe_id TEXT PRIMARY KEY,
    structure_id TEXT NOT NULL,
    pipe_index INTEGER NOT NULL,
    dip REAL,
    invert_elevation REAL,
    diameter_in REAL,
    material TEXT,
    azimuth_deg REAL,
    connected_structure_id TEXT,
    grade_percent REAL,
    source_kind TEXT NOT NULL DEFAULT 'fieldbook',
    status TEXT NOT NULL DEFAULT 'UNREVIEWED',
    attributes_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(structure_id) REFERENCES utility_structures(structure_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_utility_pipe_structure ON utility_pipes(structure_id);

CREATE TABLE IF NOT EXISTS attachments (
    attachment_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    module TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    source_path TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_attachment_object ON attachments(object_type, object_id, ts_utc DESC);

CREATE TABLE IF NOT EXISTS spatial_layers (
    layer_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    name TEXT NOT NULL,
    source_id TEXT,
    source_format TEXT NOT NULL DEFAULT '',
    source_crs TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'reference',
    feature_count INTEGER NOT NULL DEFAULT 0,
    schema_json TEXT NOT NULL DEFAULT '{}',
    stored_json_path TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(source_id) REFERENCES source_registry(source_id)
);

CREATE TABLE IF NOT EXISTS scale_factor_solutions (
    solution_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    name TEXT NOT NULL,
    revision INTEGER NOT NULL,
    target_crs TEXT NOT NULL DEFAULT '',
    project_factor REAL NOT NULL,
    max_abs_ppm REAL NOT NULL,
    rms_ppm REAL NOT NULL,
    samples_json TEXT NOT NULL DEFAULT '[]',
    settings_json TEXT NOT NULL DEFAULT '{}',
    review_state TEXT NOT NULL DEFAULT 'UNREVIEWED'
);

CREATE TABLE IF NOT EXISTS deliverables (
    deliverable_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    module TEXT NOT NULL,
    kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'FINAL',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_deliverables_ts ON deliverables(ts_utc DESC);

CREATE TABLE IF NOT EXISTS notification_events (
    notification_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    deliverable_id TEXT,
    channel TEXT NOT NULL,
    recipients TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(deliverable_id) REFERENCES deliverables(deliverable_id)
);

CREATE TABLE IF NOT EXISTS cloud_sync_log (
    sync_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    provider TEXT NOT NULL,
    remote_project_id TEXT NOT NULL DEFAULT '',
    remote_item_id TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'download',
    local_path TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS feedback_items (
    feedback_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    module TEXT NOT NULL,
    version TEXT NOT NULL,
    build TEXT NOT NULL,
    environment TEXT NOT NULL,
    release_channel TEXT NOT NULL,
    branding_profile TEXT NOT NULL,
    project_id TEXT NOT NULL,
    include_project_data INTEGER NOT NULL DEFAULT 0,
    sync_status TEXT NOT NULL DEFAULT 'LOCAL_ONLY'
);

CREATE TABLE IF NOT EXISTS import_staging (
    stage_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'points',
    headers_json TEXT NOT NULL DEFAULT '[]',
    mapping_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'READY',
    row_count INTEGER NOT NULL DEFAULT 0,
    analysis_json TEXT NOT NULL DEFAULT '{}',
    preview_json TEXT NOT NULL DEFAULT '[]',
    committed_source_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_import_staging_ts ON import_staging(ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_import_staging_status ON import_staging(status, ts_utc DESC);

CREATE TABLE IF NOT EXISTS background_tasks (
    task_id TEXT PRIMARY KEY,
    created_utc TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    kind TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'QUEUED',
    progress REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    error_text TEXT NOT NULL DEFAULT '',
    cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_background_tasks_status ON background_tasks(status, created_utc DESC);
"""


MIGRATIONS = {
    1: """
CREATE TABLE IF NOT EXISTS project_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    updated_utc TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS data_edit_history (
    edit_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'local-user',
    table_name TEXT NOT NULL,
    record_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    old_value_json TEXT NOT NULL DEFAULT 'null',
    new_value_json TEXT NOT NULL DEFAULT 'null',
    reason TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_data_edit_record ON data_edit_history(table_name, record_id, ts_utc DESC);
""",
    2: """
CREATE TABLE IF NOT EXISTS derived_result_state (
    result_kind TEXT NOT NULL,
    object_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'CURRENT',
    reason TEXT NOT NULL DEFAULT '',
    changed_utc TEXT NOT NULL,
    source_table TEXT NOT NULL DEFAULT '',
    source_record_id TEXT NOT NULL DEFAULT '',
    details_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY(result_kind, object_id)
);
CREATE INDEX IF NOT EXISTS idx_derived_state ON derived_result_state(state, result_kind);
""",
    3: """
CREATE TABLE IF NOT EXISTS project_coordinate_settings (
    setting_id TEXT PRIMARY KEY,
    updated_utc TEXT NOT NULL,
    crs TEXT NOT NULL DEFAULT '',
    crs_name TEXT NOT NULL DEFAULT '',
    horizontal_units TEXT NOT NULL DEFAULT 'us_survey_feet',
    vertical_units TEXT NOT NULL DEFAULT 'us_survey_feet',
    local_site_enabled INTEGER NOT NULL DEFAULT 0,
    local_site_name TEXT NOT NULL DEFAULT '',
    grid_origin_northing REAL NOT NULL DEFAULT 0,
    grid_origin_easting REAL NOT NULL DEFAULT 0,
    local_origin_northing REAL NOT NULL DEFAULT 0,
    local_origin_easting REAL NOT NULL DEFAULT 0,
    grid_to_ground_factor REAL NOT NULL DEFAULT 1,
    rotation_deg REAL NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS control_qc_runs (
    run_id TEXT PRIMARY KEY,
    ts_utc TEXT NOT NULL,
    method TEXT NOT NULL,
    horizontal_tolerance REAL NOT NULL,
    vertical_tolerance REAL NOT NULL,
    crs TEXT NOT NULL DEFAULT '',
    horizontal_units TEXT NOT NULL DEFAULT '',
    local_site_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_control_qc_runs_ts ON control_qc_runs(ts_utc DESC);

CREATE TABLE IF NOT EXISTS control_qc_candidates (
    candidate_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    control_id TEXT NOT NULL,
    rank_no INTEGER NOT NULL,
    selected INTEGER NOT NULL DEFAULT 0,
    passed INTEGER NOT NULL DEFAULT 0,
    point_ids_json TEXT NOT NULL DEFAULT '[]',
    observation_ids_json TEXT NOT NULL DEFAULT '[]',
    northing REAL,
    easting REAL,
    elevation REAL,
    max_horizontal_residual REAL,
    max_vertical_residual REAL,
    rms_horizontal_residual REAL,
    rms_vertical_residual REAL,
    residuals_json TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY(run_id) REFERENCES control_qc_runs(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_control_qc_candidate_control ON control_qc_candidates(run_id, control_id, rank_no);
""",
    4: """
-- Control field-observation metadata columns are added in _migrate because
-- ALTER TABLE ... ADD COLUMN needs to be conditional for fresh/template databases.
""",
    5: """
CREATE TABLE IF NOT EXISTS control_group_overrides (
    observation_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'CONFIRMED',
    assigned_control_id TEXT NOT NULL DEFAULT '',
    assigned_point_id TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    updated_utc TEXT NOT NULL,
    FOREIGN KEY(observation_id) REFERENCES control_observations(observation_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_control_override_status ON control_group_overrides(status, assigned_control_id);

CREATE TABLE IF NOT EXISTS control_qc_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    is_default INTEGER NOT NULL DEFAULT 0,
    horizontal_tolerance REAL NOT NULL DEFAULT 0.045,
    vertical_tolerance REAL NOT NULL DEFAULT 0.045,
    spatial_group_tolerance REAL,
    vertical_group_tolerance REAL,
    require_field_metadata INTEGER NOT NULL DEFAULT 1,
    min_time_separation_minutes REAL NOT NULL DEFAULT 60,
    min_epochs INTEGER NOT NULL DEFAULT 300,
    min_observation_seconds REAL NOT NULL DEFAULT 300,
    min_satellites INTEGER NOT NULL DEFAULT 5,
    max_pdop REAL,
    max_hdop REAL,
    max_vdop REAL,
    updated_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS control_import_diagnostics (
    diagnostic_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    ts_utc TEXT NOT NULL,
    format TEXT NOT NULL DEFAULT '',
    source_kind TEXT NOT NULL DEFAULT '',
    summary_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(source_id) REFERENCES source_registry(source_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_control_import_diag_source ON control_import_diagnostics(source_id, ts_utc DESC);
CREATE INDEX IF NOT EXISTS idx_control_point_id ON control_observations(point_id);
CREATE INDEX IF NOT EXISTS idx_control_xy ON control_observations(northing, easting);
CREATE INDEX IF NOT EXISTS idx_control_observed_time ON control_observations(observed_utc);
""",
    6: """
CREATE TABLE IF NOT EXISTS audit_chain (
    seq INTEGER PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    hash_version INTEGER NOT NULL DEFAULT 1,
    prev_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES audit_events(event_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_audit_chain_event ON audit_chain(event_id);
""",
}


class AuditDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    @staticmethod
    def read_schema_version(path: Path) -> int:
        path = Path(path)
        if not path.exists():
            return 0
        conn = sqlite3.connect(str(path), timeout=10)
        try:
            return int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
        finally:
            conn.close()

    def _migrate(self, conn: sqlite3.Connection) -> None:
        current = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
        if current > CURRENT_SCHEMA_VERSION:
            raise RuntimeError(f"Project database schema {current} is newer than this SurveySync build supports ({CURRENT_SCHEMA_VERSION}).")
        for version in range(current + 1, CURRENT_SCHEMA_VERSION + 1):
            if version == 3:
                existing = {str(row[1]) for row in conn.execute("PRAGMA table_info(control_observations)").fetchall()}
                for name in ("point_id", "shot_id", "session_id"):
                    if name not in existing:
                        conn.execute(f"ALTER TABLE control_observations ADD COLUMN {name} TEXT NOT NULL DEFAULT ''")
            if version == 4:
                existing = {str(row[1]) for row in conn.execute("PRAGMA table_info(control_observations)").fetchall()}
                additions = {
                    "observed_time_provided": "INTEGER NOT NULL DEFAULT 0",
                    "epoch_count": "INTEGER",
                    "duration_seconds": "REAL",
                    "satellite_count": "INTEGER",
                }
                for name, sql_type in additions.items():
                    if name not in existing:
                        conn.execute(f"ALTER TABLE control_observations ADD COLUMN {name} {sql_type}")
            if version == 5:
                existing = {str(row[1]) for row in conn.execute("PRAGMA table_info(control_observations)").fetchall()}
                additions = {
                    "pdop": "REAL",
                    "hdop": "REAL",
                    "vdop": "REAL",
                    "fix_type": "TEXT NOT NULL DEFAULT ''",
                    "receiver_model": "TEXT NOT NULL DEFAULT ''",
                    "receiver_serial": "TEXT NOT NULL DEFAULT ''",
                    "antenna_type": "TEXT NOT NULL DEFAULT ''",
                    "antenna_height": "REAL",
                    "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
                }
                for name, sql_type in additions.items():
                    if name not in existing:
                        conn.execute(f"ALTER TABLE control_observations ADD COLUMN {name} {sql_type}")
            script = MIGRATIONS.get(version)
            if script:
                conn.executescript(script)
            if version == 6:
                self._backfill_audit_chain(conn)
            conn.execute(f"PRAGMA user_version={version}")
        conn.commit()

    def _backfill_audit_chain(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """SELECT event_id,ts_utc,actor,module,action,object_type,object_id,
                      revision,details_json
               FROM audit_events
               ORDER BY ts_utc ASC, rowid ASC"""
        ).fetchall()
        conn.execute("DELETE FROM audit_chain")
        prev_hash = AUDIT_GENESIS_HASH
        for seq, row in enumerate(rows, start=1):
            event_hash = _audit_hash(
                seq=seq,
                event_id=row["event_id"],
                ts_utc=row["ts_utc"],
                actor=row["actor"],
                module=row["module"],
                action=row["action"],
                object_type=row["object_type"] or "",
                object_id=row["object_id"] or "",
                revision=int(row["revision"] or 0),
                details_json=row["details_json"] or "{}",
                prev_hash=prev_hash,
            )
            conn.execute(
                """INSERT INTO audit_chain(
                       seq,event_id,hash_version,prev_hash,event_hash
                   ) VALUES(?,?,?,?,?)""",
                (seq, row["event_id"], AUDIT_HASH_VERSION, prev_hash, event_hash),
            )
            prev_hash = event_hash

    def schema_version(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(str(self.path), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def audit(self, module: str, action: str, *, actor: str = "local-user", object_type: str = "", object_id: str = "", revision: int = 0, details: dict | None = None) -> str:
        event_id = uuid4().hex
        ts_utc = utc_now()
        details_json = json.dumps(details or {}, ensure_ascii=False, sort_keys=True)
        with self.connect() as conn:
            head = conn.execute(
                "SELECT seq,event_hash FROM audit_chain ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            seq = int(head["seq"]) + 1 if head else 1
            prev_hash = str(head["event_hash"]) if head else AUDIT_GENESIS_HASH
            event_hash = _audit_hash(
                seq=seq,
                event_id=event_id,
                ts_utc=ts_utc,
                actor=actor,
                module=module,
                action=action,
                object_type=object_type,
                object_id=object_id,
                revision=revision,
                details_json=details_json,
                prev_hash=prev_hash,
            )
            conn.execute(
                "INSERT INTO audit_events(event_id,ts_utc,actor,module,action,object_type,object_id,revision,details_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (event_id, ts_utc, actor, module, action, object_type, object_id, revision, details_json),
            )
            conn.execute(
                "INSERT INTO audit_chain(seq,event_id,hash_version,prev_hash,event_hash) VALUES(?,?,?,?,?)",
                (seq, event_id, AUDIT_HASH_VERSION, prev_hash, event_hash),
            )
        return event_id

    def verify_audit_chain(self) -> dict:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT c.seq,c.event_id,c.hash_version,c.prev_hash,c.event_hash,
                          e.ts_utc,e.actor,e.module,e.action,e.object_type,e.object_id,
                          e.revision,e.details_json
                   FROM audit_chain c
                   JOIN audit_events e ON e.event_id=c.event_id
                   ORDER BY c.seq ASC"""
            ).fetchall()
            event_count = int(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])

        if len(rows) != event_count:
            return {
                "ok": False,
                "event_count": event_count,
                "chain_count": len(rows),
                "broken_seq": None,
                "reason": "Audit event count does not match chained event count.",
            }

        expected_prev = AUDIT_GENESIS_HASH
        for row in rows:
            seq = int(row["seq"])
            if int(row["hash_version"]) != AUDIT_HASH_VERSION:
                return {
                    "ok": False,
                    "event_count": event_count,
                    "chain_count": len(rows),
                    "broken_seq": seq,
                    "reason": f"Unsupported audit hash version at sequence {seq}.",
                }
            if str(row["prev_hash"]) != expected_prev:
                return {
                    "ok": False,
                    "event_count": event_count,
                    "chain_count": len(rows),
                    "broken_seq": seq,
                    "reason": f"Previous-hash link mismatch at sequence {seq}.",
                }
            computed = _audit_hash(
                seq=seq,
                event_id=row["event_id"],
                ts_utc=row["ts_utc"],
                actor=row["actor"],
                module=row["module"],
                action=row["action"],
                object_type=row["object_type"] or "",
                object_id=row["object_id"] or "",
                revision=int(row["revision"] or 0),
                details_json=row["details_json"] or "{}",
                prev_hash=expected_prev,
            )
            if computed != str(row["event_hash"]):
                return {
                    "ok": False,
                    "event_count": event_count,
                    "chain_count": len(rows),
                    "broken_seq": seq,
                    "reason": f"Audit event hash mismatch at sequence {seq}.",
                }
            expected_prev = computed

        return {
            "ok": True,
            "event_count": event_count,
            "chain_count": len(rows),
            "broken_seq": None,
            "head_hash": expected_prev if rows else AUDIT_GENESIS_HASH,
            "hash_version": AUDIT_HASH_VERSION,
        }

    def recent_audit(self, limit: int = 100) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM audit_events ORDER BY ts_utc DESC LIMIT ?", (max(1, min(limit, 1000)),)).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["details"] = json.loads(item.pop("details_json") or "{}")
            out.append(item)
        return out

    def add_qa(self, module: str, severity: str, code: str, message: str, *, object_id: str = "", details: dict | None = None) -> str:
        issue_id = uuid4().hex
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO qa_issues(issue_id,ts_utc,module,severity,code,object_id,message,details_json) VALUES(?,?,?,?,?,?,?,?)",
                (issue_id, utc_now(), module, severity.upper(), code, object_id, message, json.dumps(details or {}, ensure_ascii=False)),
            )
        return issue_id

    def qa_issues(self, status: str = "OPEN") -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM qa_issues WHERE status=? ORDER BY CASE severity WHEN 'ERROR' THEN 0 WHEN 'WARN' THEN 1 ELSE 2 END, ts_utc DESC", (status,)).fetchall()
        out=[]
        for r in rows:
            d=dict(r); d["details"] = json.loads(d.pop("details_json") or "{}"); out.append(d)
        return out

    def get_qa_issue(self, issue_id: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM qa_issues WHERE issue_id=?", (issue_id,)).fetchone()
        if not row:
            return None
        d = dict(row); d["details"] = json.loads(d.pop("details_json") or "{}")
        return d

    def set_qa_status(self, issue_id: str, status: str) -> dict:
        status = str(status or "OPEN").upper()
        if status not in {"OPEN", "ACKNOWLEDGED", "RESOLVED", "IGNORED", "SUPERSEDED"}:
            raise ValueError("Unsupported QA issue status.")
        with self.connect() as conn:
            row = conn.execute("SELECT issue_id FROM qa_issues WHERE issue_id=?", (issue_id,)).fetchone()
            if not row:
                raise ValueError("QA issue was not found.")
            conn.execute("UPDATE qa_issues SET status=? WHERE issue_id=?", (status, issue_id))
        item = self.get_qa_issue(issue_id)
        self.audit("QASync", "QA_ISSUE_STATUS_CHANGED", object_type="qa_issue", object_id=issue_id, details={"status": status})
        return item or {"issue_id": issue_id, "status": status}

    def supersede_qa_by_prefix(self, module: str, prefix: str) -> int:
        with self.connect() as conn:
            cur = conn.execute("UPDATE qa_issues SET status='SUPERSEDED' WHERE module=? AND status='OPEN' AND code LIKE ?", (module, f"{prefix}%"))
            return int(cur.rowcount or 0)
