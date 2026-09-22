from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field
from .models import StatusRule, DipStatus, ReviewState, PipeMeasurement
from .profiles import CodeProfile
from .field_note_profiles import FieldNoteProfile, AUTO_PROFILE_ID, FieldNoteTrainingAnnotation

DEFAULT_OLLAMA_MODEL = "qwen3-vl:4b-instruct"


class SettingsIn(BaseModel):
    # SurveySync 9.1.3 defaults to Automatic local AI: Windows AI first when ready, then proven local fallbacks.
    provider: str = "auto"
    gemini_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    ollama_model: str = DEFAULT_OLLAMA_MODEL
    ollama_profile: str = "auto"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_batch_pages: int = Field(default=1, ge=1, le=4)
    gemini_model: str = "gemini-3.8-flash"
    openai_model: str = "gpt-5.6-luna"
    anthropic_model: str = "claude-sonnet-5"
    gemini_batch_pages: int = Field(default=4, ge=1, le=8)
    confidence_threshold: float = Field(default=0.85, ge=0.5, le=0.99)
    status_rule: StatusRule = StatusRule.POINT_ID_FOUND
    elevation_is_rim: bool = False
    network_max_distance: float = Field(default=1500.0, gt=0, le=1000000)
    network_bearing_tolerance: float = Field(default=25.0, ge=1, le=90)
    performance_mode: str = "auto"
    rod_bust_enabled: bool = True
    rod_bust_search_radius: float = Field(default=15.0, gt=0, le=10000)
    rod_bust_max_slope_percent: float = Field(default=8.0, ge=0, le=1000)
    rod_bust_increment_tolerance: float = Field(default=0.08, ge=0, le=10)
    rod_bust_min_neighbors: int = Field(default=2, ge=1, le=20)
    # Backward compatibility.
    api_key: Optional[str] = None
    model: Optional[str] = None


class SelectProfileIn(BaseModel):
    name: str


class ProfileSaveIn(CodeProfile):
    original_name: Optional[str] = None


class FieldNoteProfileSaveIn(FieldNoteProfile):
    original_profile_id: Optional[str] = None


class FieldNoteProfileSelectIn(BaseModel):
    profile_id: str = AUTO_PROFILE_ID


class FieldBookProfileAssignmentIn(BaseModel):
    source_name: str
    profile_id: str = AUTO_PROFILE_ID
    mode: str = "user"


class FieldNotePageOverrideIn(BaseModel):
    profile_id: str = AUTO_PROFILE_ID


class FieldNoteProfileDuplicateIn(BaseModel):
    new_name: str


class FieldNoteTrainingSaveIn(BaseModel):
    profile_id: str
    page_id: str
    annotations: List[FieldNoteTrainingAnnotation] = Field(default_factory=list)
    notes: str = ""


class TeachCorrectionIn(BaseModel):
    profile_id: str
    notes: str = ""


class UpdateSourceIn(BaseModel):
    manifest_url: str = ""
    release_url: str = ""
    drive_folder_url: str = ""  # legacy compatibility with v8.1.7-v8.1.9 UI


class UpdateInstallIn(BaseModel):
    confirm_install: bool = False


class FeedbackOpenIn(BaseModel):
    url: str = ""


class FeedbackRetryIn(BaseModel):
    report_id: str
    endpoint_url: str = ""
    form_url: str = ""  # legacy alias for v8.1.18/v8.1.19 clients


class ResultEditIn(BaseModel):
    # Optional reviewed PointID. When it differs from the route PointID, SurveySync
    # performs an audited reassignment to another imported survey point.
    point_id: Optional[str] = None
    reassignment_reason: str = ""
    status: DipStatus
    dip_status: DipStatus = DipStatus.NOT_FOUND
    review_state: ReviewState = ReviewState.EDITED
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    notes: str = ""
    pipes: List[PipeMeasurement] = Field(default_factory=list)


class ProjectNameIn(BaseModel):
    name: str


class ProjectSaveAsIn(BaseModel):
    path: str


class MapCrsIn(BaseModel):
    crs: str = ""


class MapAlignmentIn(BaseModel):
    enabled: bool = False
    scale_factor: float = 1.0
    rotation_deg: float = 0.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    origin_x: float = 0.0
    origin_y: float = 0.0
    label: str = "Survey alignment"


class MapControlPairIn(BaseModel):
    name: str = ""
    local_x: float
    local_y: float
    grid_x: float
    grid_y: float


class MapAlignmentSolveIn(BaseModel):
    pairs: List[MapControlPairIn] = Field(default_factory=list)


class MapLayerSettingsIn(BaseModel):
    visible: Optional[bool] = None
    opacity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    name: Optional[str] = None


class MapLayerOrderIn(BaseModel):
    layer_ids: List[str] = Field(default_factory=list)


class MapBookmarkIn(BaseModel):
    name: str
    center_lon: Optional[float] = None
    center_lat: Optional[float] = None
    center_x: Optional[float] = None
    center_y: Optional[float] = None
    zoom: float = 15.0


class MapTransformIn(BaseModel):
    x: Optional[float] = None
    y: Optional[float] = None
    lon: Optional[float] = None
    lat: Optional[float] = None
    direction: str = "to_wgs84"


class ManualEdgeIn(BaseModel):
    from_point: str
    to_point: str
    notes: str = "Manual connection"


class ValidationNameIn(BaseModel):
    name: str = "Reviewed Ground Truth"


class BatchAddIn(BaseModel):
    name: Optional[str] = None


class ArcGISMapsIn(BaseModel):
    project_path: Optional[str] = None
    aprx_path: Optional[str] = None  # v6.x compatibility

    def resolved_path(self) -> str:
        return (self.project_path or self.aprx_path or "").strip()


class ArcGISExportIn(BaseModel):
    output_folder: str
    project_path: Optional[str] = None
    aprx_path: Optional[str] = None  # v6.x compatibility
    map_name: Optional[str] = None
    include_network: bool = True
    assign_map_crs: bool = False
    replace_existing: bool = True
    create_project_subfolder: bool = True
    backup_project: bool = True
    backup_aprx: Optional[bool] = None  # v6.x compatibility
    open_project_after: bool = False

    def resolved_project_path(self) -> Optional[str]:
        value = (self.project_path or self.aprx_path or "").strip()
        return value or None


class ImportJob(BaseModel):
    running: bool = False
    kind: str = ""
    phase: str = "idle"
    percent: int = 0
    current_file: int = 0
    total_files: int = 0
    current_page: int = 0
    total_pages: int = 0
    message: str = "Ready"
    error: Optional[str] = None
    started_at: Optional[str] = None
