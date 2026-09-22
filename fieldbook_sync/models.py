from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class MatchMode(str, Enum):
    EXACT = "exact"
    STARTS_WITH = "starts_with"
    CONTAINS = "contains"


class DipStatus(str, Enum):
    YES = "YES"
    NO = "NO"
    CNA = "CNA"  # Could Not Access
    CNL = "CNL"  # Could Not Locate
    NOT_FOUND = "NOT_FOUND"
    REVIEW = "REVIEW"


class StatusRule(str, Enum):
    POINT_ID_FOUND = "POINT_ID_FOUND"
    CONFIRMED_DIP = "CONFIRMED_DIP"


class EvidenceBasis(str, Enum):
    MEASUREMENT = "MEASUREMENT"
    EXPLICIT_YES = "EXPLICIT_YES"
    EXPLICIT_NO = "EXPLICIT_NO"
    EXPLICIT_CNA = "EXPLICIT_CNA"
    EXPLICIT_CNL = "EXPLICIT_CNL"
    AMBIGUOUS = "AMBIGUOUS"


class ReviewState(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    ACCEPTED = "ACCEPTED"
    EDITED = "EDITED"
    REJECTED = "REJECTED"


class CodeRule(BaseModel):
    code: str
    category: str = "Structure"
    include: bool = True
    match: MatchMode = MatchMode.EXACT


class CodeProfile(BaseModel):
    name: str
    client: str = ""
    notes: str = ""
    codes: List[CodeRule] = Field(default_factory=list)


class FieldNoteSymbolRule(BaseModel):
    label: str
    meaning: str = ""
    visual_cue: str = ""
    relationship: str = ""


class FieldNoteProfile(BaseModel):
    profile_id: str = ""
    name: str
    client: str = ""
    job_type: str = ""
    scope: str = "custom"  # built_in / company / project / custom
    locked: bool = False
    description: str = ""
    detection_cues: List[str] = Field(default_factory=list)
    vocabulary: List[str] = Field(default_factory=list)
    expected_fields: List[str] = Field(default_factory=list)
    extraction_instructions: List[str] = Field(default_factory=list)
    symbols: List[FieldNoteSymbolRule] = Field(default_factory=list)
    version: int = 1
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class FieldNoteTrainingAnnotation(BaseModel):
    annotation_id: str = ""
    label: str
    bbox: Optional[List[int]] = None  # normalized 0-1000
    text: str = ""
    value: str = ""
    pipe_index: Optional[int] = None
    notes: str = ""


class FieldNoteTrainingExample(BaseModel):
    example_id: str = ""
    profile_id: str
    page_id: Optional[str] = None
    source_name: str = ""
    page_number: int = 0
    image_path: Optional[str] = None
    annotations: List[FieldNoteTrainingAnnotation] = Field(default_factory=list)
    accepted_result: Dict[str, Any] = Field(default_factory=dict)
    origin: str = "trainer"  # trainer / teach_from_correction / import
    notes: str = ""
    created_at: str = Field(default_factory=utc_now_iso)


class SurveyPoint(BaseModel):
    point_id: str
    northing: Optional[float] = None
    easting: Optional[float] = None
    elevation: Optional[float] = None
    code: str
    category: str = ""
    source_file: str = ""
    source_row: int = 0


class SurveyImportIssue(BaseModel):
    source_file: str
    source_row: int
    message: str
    raw: str = ""


class PipeMeasurement(BaseModel):
    dip: Optional[float] = None
    dip_raw: Optional[str] = None
    diameter_in: Optional[float] = None
    diameter_raw: Optional[str] = None
    material: Optional[str] = None
    azimuth_deg: Optional[float] = None
    azimuth_raw: Optional[str] = None
    # v9.1.3 BRT/standard field-note geometry. Visual leader direction is kept
    # separately from a written azimuth so the two can be cross-checked rather
    # than silently substituting one for the other.
    leader_direction_deg: Optional[float] = None
    leader_direction_raw: Optional[str] = None
    leader_bbox: Optional[List[int]] = None
    connected_point_raw: Optional[str] = None
    notes: Optional[str] = None
    # v6 survey-intelligence fields. They are derived locally and never trusted from AI.
    invert_elevation: Optional[float] = None
    connected_point_id: Optional[str] = None
    connection_score: Optional[float] = None
    qc_flags: List[str] = Field(default_factory=list)


class PageEvidence(BaseModel):
    matched_point_id: str
    basis: EvidenceBasis = EvidenceBasis.AMBIGUOUS
    source_name: str
    page_number: int
    page_id: str
    point_id_raw: Optional[str] = None
    point_id_confidence: float = 0.0
    dipped: DipStatus = DipStatus.REVIEW
    dipped_confidence: float = 0.0
    evidence: Optional[str] = None
    structure_label: Optional[str] = None
    pipes: List[PipeMeasurement] = Field(default_factory=list)
    bbox: Optional[List[int]] = None
    # Standard field-note sketch metadata. ``field_note_template`` is advisory
    # evidence only; it never creates an authoritative match by itself.
    field_note_template: str = ""
    # v9.1.3 profile-aware field-note interpretation. The profile ID is advisory
    # evidence and never overrides PointID/OCR provenance or deterministic QC.
    field_note_profile: str = ""
    field_note_profile_confidence: float = 0.0
    structure_bbox: Optional[List[int]] = None
    north_arrow_deg: Optional[float] = None
    notes: Optional[str] = None
    # v6 records which engines observed/verified the evidence.
    primary_engine: Optional[str] = None
    secondary_engine: Optional[str] = None
    model_agreement: Optional[bool] = None
    ocr_text: Optional[str] = None
    # v9.0.2 evidence-first orchestration. These fields are derived locally from
    # independent OCR/model agreement and deterministic validation; model self-confidence
    # alone can never make a result authoritative.
    page_type: str = "unknown"
    page_type_confidence: float = 0.0
    evidence_score: float = 0.0
    evidence_decision: str = ""
    evidence_sources: List[str] = Field(default_factory=list)
    validation_flags: List[str] = Field(default_factory=list)


class EvidenceAttachment(BaseModel):
    attachment_id: str
    filename: str
    stored_path: str
    media_type: str = ""
    caption: str = ""
    pipe_index: Optional[int] = None
    source: str = "manual"
    created_at: str = Field(default_factory=utc_now_iso)


class ResultRecord(BaseModel):
    point_id: str
    northing: Optional[float] = None
    easting: Optional[float] = None
    elevation: Optional[float] = None
    code: str
    category: str = ""
    # Primary deliverable status. In POINT_ID_FOUND mode this is always YES/NO.
    status: DipStatus = DipStatus.NOT_FOUND
    # Semantic dip interpretation retained separately so advanced QA never blocks the basic report.
    dip_status: DipStatus = DipStatus.NOT_FOUND
    qa_needs_review: bool = False
    confidence: float = 0.0
    review_state: ReviewState = ReviewState.UNREVIEWED
    pipes: List[PipeMeasurement] = Field(default_factory=list)
    evidence_records: List[PageEvidence] = Field(default_factory=list)
    notes: str = ""
    manually_overridden: bool = False
    smart_confidence: float = 0.0
    confidence_factors: List[str] = Field(default_factory=list)
    qc_flags: List[str] = Field(default_factory=list)
    # Manual review provenance for PointID reassignment. Raw OCR/evidence is preserved
    # in history; these fields make the current reviewed association explicit.
    point_id_reassigned_from: Optional[str] = None
    point_id_reassigned_to: Optional[str] = None
    point_id_reassignment_note: str = ""
    # Photos and other visual QA evidence linked to this structure or a specific pipe.
    attachments: List[EvidenceAttachment] = Field(default_factory=list)


class UnmatchedEvidence(BaseModel):
    source_name: str
    page_number: int
    page_id: str
    point_id_raw: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""
    bbox: Optional[List[int]] = None


class FieldBookPage(BaseModel):
    page_id: str
    source_name: str
    page_number: int
    image_path: str
    mime_type: str
    enhanced_image_path: Optional[str] = None
    # Advisory page classification used to route specialized prompts. It never
    # overrides visible evidence or excludes an uncertain page from review.
    page_type: str = "unknown"
    page_type_confidence: float = 0.0
    page_type_reason: str = ""
    # v9.1.3 field-book default profile. This belongs to the imported book and is
    # separate from the page-specific override so mixed-format books remain possible.
    field_note_profile_book: str = ""
    # Optional reviewer-selected field-note grammar for this page. Empty/AUTO means
    # use the field-book default when present, otherwise the analysis catalog/global mode.
    field_note_profile_override: str = ""


class OcrCandidate(BaseModel):
    page_id: str
    source_name: str
    page_number: int
    point_id: str
    raw_text: str = ""
    confidence: float = 0.0
    bbox: Optional[List[int]] = None  # normalized 0-1000
    engine: str = "paddleocr-vl"
    exact_match: bool = True


class NetworkEdge(BaseModel):
    from_point: str
    to_point: str
    from_pipe_index: int
    to_pipe_index: Optional[int] = None
    distance: Optional[float] = None
    azimuth_from: Optional[float] = None
    azimuth_to_expected: Optional[float] = None
    reciprocal_error_deg: Optional[float] = None
    bearing_error_deg: Optional[float] = None
    leader_error_deg: Optional[float] = None
    score: float = 0.0
    status: str = "SUGGESTED"  # SUGGESTED / STRONG / REVIEW
    notes: str = ""


class HistoryEvent(BaseModel):
    event_id: str
    timestamp: str = Field(default_factory=utc_now_iso)
    action: str
    point_id: Optional[str] = None
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    detail: str = ""
    # Multi-record edits (for example PointID reassignment) need one atomic undo/redo
    # event. Older project files omit these fields and remain fully compatible.
    related_before: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    related_after: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class VerifiedExample(BaseModel):
    example_id: str
    created_at: str = Field(default_factory=utc_now_iso)
    point_id: str
    page_id: Optional[str] = None
    crop_path: Optional[str] = None
    accepted_result: Dict[str, Any] = Field(default_factory=dict)


class BatchJob(BaseModel):
    job_id: str
    name: str
    status: str = "QUEUED"  # QUEUED / RUNNING / COMPLETE / ERROR / CANCELLED
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    profile_name: Optional[str] = None
    provider: str = "auto"
    progress: float = 0.0
    message: str = ""
    project_file: Optional[str] = None
    source_type: str = "project"  # project / raw
    source_summary: Optional[str] = None
    error: Optional[str] = None


class AnalysisJob(BaseModel):
    # v8.0.11 persistent job identity and recovery telemetry.
    job_id: Optional[str] = None
    running: bool = False
    started_at: Optional[str] = None
    cancelled: bool = False
    paused: bool = False
    pause_requested: bool = False
    complete: bool = False
    provider: str = "auto"
    total_pages: int = 0
    current_page: int = 0
    total_requests: int = 0
    current_request: int = 0
    api_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    message: str = ""
    stage: str = "idle"
    error: Optional[str] = None
    # v8.0.8 live-analysis counters.  The browser uses live_update_seq to avoid
    # re-fetching Review/Map/Index data when only the progress clock changed.
    live_update_seq: int = 0
    live_candidate_count: int = 0
    live_interpreted_count: int = 0
    live_network_edge_count: int = 0
    # v8.0.9 performance telemetry. These are informational only and do not
    # change evidence/confidence decisions.
    ocr_cache_hits: int = 0
    interpretation_cache_hits: int = 0
    paddle_device: str = ""
    paddle_hpi: bool = False
    retry_count: int = 0
    failed_page_count: int = 0
    warning_count: int = 0
    recoverable: bool = False
    error_code: Optional[str] = None
    resumable: bool = False
    worker_heartbeat_at: Optional[str] = None
    # v8.1.21 local-model telemetry. These values are informational and are
    # updated while Ollama warms or streams a response.
    qwen_model: str = ""
    qwen_state: str = "idle"
    qwen_elapsed_seconds: float = 0.0
    qwen_output_tokens: int = 0
    qwen_output_chars: int = 0
    qwen_cpu_percent: float = 0.0
    qwen_gpu_percent: float = 0.0




class MapFeature(BaseModel):
    feature_id: str
    geometry: Dict[str, Any] = Field(default_factory=dict)  # GeoJSON geometry in WGS84
    properties: Dict[str, Any] = Field(default_factory=dict)


class MapLayer(BaseModel):
    layer_id: str = Field(default_factory=lambda: f"layer-{__import__('uuid').uuid4().hex[:12]}")
    name: str
    source_name: str = ""
    source_type: str = "GIS"
    source_crs: str = "EPSG:4326"
    visible: bool = True
    opacity: float = 0.85
    feature_count: int = 0
    geometry_types: List[str] = Field(default_factory=list)
    features: List[MapFeature] = Field(default_factory=list)
    bounds_wgs84: Optional[List[float]] = None
    warning: str = ""




class CustomCoordinateSystem(BaseModel):
    crs_id: str = Field(default_factory=lambda: f"crs-{__import__('uuid').uuid4().hex[:12]}")
    name: str
    definition: str
    authority: str = ""
    units: str = ""
    source_name: str = ""


class MapAlignmentSettings(BaseModel):
    enabled: bool = False
    mode: str = "similarity"
    scale_factor: float = 1.0
    rotation_deg: float = 0.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    origin_x: float = 0.0
    origin_y: float = 0.0
    label: str = "No alignment"
    residual_rms: Optional[float] = None

class MapBookmark(BaseModel):
    bookmark_id: str = Field(default_factory=lambda: f"bookmark-{__import__('uuid').uuid4().hex[:12]}")
    name: str
    center_lon: Optional[float] = None
    center_lat: Optional[float] = None
    center_x: Optional[float] = None
    center_y: Optional[float] = None
    zoom: float = 15.0


class ManualNetworkEdge(BaseModel):
    from_point: str
    to_point: str
    locked: bool = True
    notes: str = "Manual connection"


class ImportedFileRecord(BaseModel):
    name: str
    kind: str
    size_bytes: int = 0
    imported_at: str = Field(default_factory=utc_now_iso)
    records: int = 0
    pages: int = 0
    # Field-book profile assignment metadata (ignored for non-fieldbook imports).
    field_note_profile: str = "AUTO"
    field_note_profile_version: int = 0
    field_note_profile_mode: str = "auto"  # auto / user / trained
    field_note_profile_confidence: float = 0.0
    field_note_profile_reason: str = ""
    representative_page_ids: List[str] = Field(default_factory=list)

class AppState(BaseModel):
    project_name: str = "Untitled Project"
    project_created_at: str = Field(default_factory=utc_now_iso)
    project_modified_at: str = Field(default_factory=utc_now_iso)
    selected_profile: Optional[str] = None
    selected_field_note_profile: str = "AUTO"
    survey_files: List[ImportedFileRecord] = Field(default_factory=list)
    fieldbook_files: List[ImportedFileRecord] = Field(default_factory=list)
    survey_points: List[SurveyPoint] = Field(default_factory=list)
    survey_issues: List[SurveyImportIssue] = Field(default_factory=list)
    rod_height_busts: List[Dict[str, Any]] = Field(default_factory=list)
    fieldbook_pages: List[FieldBookPage] = Field(default_factory=list)
    ocr_candidates: List[OcrCandidate] = Field(default_factory=list)
    results: List[ResultRecord] = Field(default_factory=list)
    unmatched: List[UnmatchedEvidence] = Field(default_factory=list)
    network_edges: List[NetworkEdge] = Field(default_factory=list)
    history: List[HistoryEvent] = Field(default_factory=list)
    redo_stack: List[HistoryEvent] = Field(default_factory=list)
    verified_examples: List[VerifiedExample] = Field(default_factory=list)
    batch_jobs: List[BatchJob] = Field(default_factory=list)
    map_project_crs: str = ""
    map_project_crs_name: str = ""
    map_crs_warning: str = ""
    custom_coordinate_systems: List[CustomCoordinateSystem] = Field(default_factory=list)
    map_alignment: MapAlignmentSettings = Field(default_factory=MapAlignmentSettings)
    map_layers: List[MapLayer] = Field(default_factory=list)
    map_bookmarks: List[MapBookmark] = Field(default_factory=list)
    manual_network_edges: List[ManualNetworkEdge] = Field(default_factory=list)
