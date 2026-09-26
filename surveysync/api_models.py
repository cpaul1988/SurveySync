from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class CreateProjectIn(BaseModel):
    parent_folder: str
    name: str = Field(min_length=1, max_length=120)
    crs: str = ""
    horizontal_units: str = "us_survey_feet"
    vertical_units: str = "us_survey_feet"
    template_id: str = "standard"
    client: str = ""
    project_number: str = ""


class OpenProjectIn(BaseModel):
    path: str


class ProjectForgetIn(BaseModel):
    path: str


class ProjectDeleteIn(BaseModel):
    path: str
    confirm_name: str


class EnvIn(BaseModel):
    environment: str
    release_channel: Optional[str] = None


class BrandSelectIn(BaseModel):
    branding_profile: str


class BrandProfileIn(BaseModel):
    id: str
    name: str
    organization: str = ""
    accent: str = "#2563eb"
    tagline: str = ""
    demo_only: bool = True


class CrsUnitsIn(BaseModel):
    crs: str = ""
    horizontal_units: str
    vertical_units: str


class CogoInverseIn(BaseModel):
    n1: float
    e1: float
    n2: float
    e2: float


class CogoBDIn(BaseModel):
    northing: float
    easting: float
    azimuth_deg: float
    distance: float


class CogoIntersectIn(BaseModel):
    n1: float
    e1: float
    az1: float
    n2: float
    e2: float
    az2: float


class CogoCurveIn(BaseModel):
    radius: float | None = None
    delta_deg: float | None = None
    tangent: float | None = None
    arc_length: float | None = None
    long_chord: float | None = None
    external: float | None = None
    middle_ordinate: float | None = None
    degree_of_curve_100ft_arc: float | None = None


class CogoThreePointCurveIn(BaseModel):
    n1: float
    e1: float
    n2: float
    e2: float
    n3: float
    e3: float


class CogoPointIn(BaseModel):
    northing: float
    easting: float


class CogoPolygonIn(BaseModel):
    points: list[CogoPointIn] = Field(min_length=3)


class CogoStationOffsetIn(BaseModel):
    alignment: list[CogoPointIn] = Field(min_length=2)
    point: CogoPointIn
    start_station: float = 0.0


class CogoCurveStakeIn(BaseModel):
    pc_northing: float
    pc_easting: float
    tangent_azimuth_deg: float
    radius: float
    delta_deg: float
    direction: str = "LEFT"
    stake_interval: float
    start_station: float = 0.0


class CogoVerticalCurveIn(BaseModel):
    pvi_station: float
    pvi_elevation: float
    grade_in_percent: float
    grade_out_percent: float
    length: float = Field(gt=0)
    sample_interval: float | None = Field(default=None, gt=0)


class CogoGroundProfilePointIn(BaseModel):
    offset: float
    elevation: float


class CogoDesignProfilePointIn(BaseModel):
    offset: float
    relative_elevation: float


class CogoCrossSectionIn(BaseModel):
    ground_points: list[CogoGroundProfilePointIn] = Field(min_length=2)
    design_points: list[CogoDesignProfilePointIn] = Field(min_length=2)
    design_centerline_elevation: float


class CogoEarthworkSectionIn(BaseModel):
    station: float
    cut_area: float = Field(ge=0)
    fill_area: float = Field(ge=0)


class CogoEarthworkIn(BaseModel):
    sections: list[CogoEarthworkSectionIn] = Field(min_length=2)


class CogoSlopeCatchIn(CogoCrossSectionIn):
    side: str


class CogoAlignmentElementIn(BaseModel):
    kind: str
    length: float | None = Field(default=None, gt=0)
    radius: float | None = Field(default=None, gt=0)
    delta_deg: float | None = Field(default=None, gt=0)
    direction: str | None = None


class CogoAlignmentDefinitionIn(BaseModel):
    start_northing: float
    start_easting: float
    start_azimuth_deg: float
    start_station: float = 0.0
    elements: list[CogoAlignmentElementIn] = Field(min_length=1)


class CogoAlignmentStationIn(BaseModel):
    alignment: CogoAlignmentDefinitionIn
    station: float


class CogoAlignmentStationOffsetIn(BaseModel):
    alignment: CogoAlignmentDefinitionIn
    point_northing: float
    point_easting: float


class CogoAlignmentStakePointIn(BaseModel):
    alignment: CogoAlignmentDefinitionIn
    station: float
    offset: float = 0.0


class LandXmlPointIn(BaseModel):
    point_id: str = Field(min_length=1, max_length=120)
    northing: float
    easting: float
    elevation: float | None = None
    description: str = ""


class LandXmlParcelVertexIn(BaseModel):
    northing: float
    easting: float


class LandXmlParcelIn(BaseModel):
    name: str = ""
    vertices: list[LandXmlParcelVertexIn] = Field(min_length=3)


class LandXmlAlignmentIn(BaseModel):
    name: str = ""
    alignment: CogoAlignmentDefinitionIn


class LandXmlImportIn(BaseModel):
    file_path: str = Field(min_length=1)


class LandXmlExportIn(BaseModel):
    output_path: str = ""
    points: list[LandXmlPointIn] = []
    parcels: list[LandXmlParcelIn] = []
    alignments: list[LandXmlAlignmentIn] = []


class NetworkPointIn(BaseModel):
    point_id: str = Field(min_length=1, max_length=80)
    northing: float
    easting: float
    fixed: bool = False


class NetworkObservationIn(BaseModel):
    kind: str
    from_id: str = Field(min_length=1, max_length=80)
    to_id: str = Field(min_length=1, max_length=80)
    target2_id: str | None = None
    value: float
    sigma: float = Field(gt=0)


class ControlNetworkAdjustmentIn(BaseModel):
    points: list[NetworkPointIn] = Field(min_length=2)
    observations: list[NetworkObservationIn] = Field(min_length=1)
    max_iterations: int = Field(default=20, ge=1, le=100)
    tolerance: float = Field(default=1e-7, gt=0)
    robust: bool = False
    huber_k: float = Field(default=1.5, gt=0)
    review_threshold: float = Field(default=3.0, gt=0)


class LevelNetworkPointIn(BaseModel):
    point_id: str = Field(min_length=1, max_length=80)
    elevation: float
    fixed: bool = False


class LevelNetworkObservationIn(BaseModel):
    from_id: str = Field(min_length=1, max_length=80)
    to_id: str = Field(min_length=1, max_length=80)
    delta_elevation: float
    sigma: float = Field(gt=0)


class LevelNetworkAdjustmentIn(BaseModel):
    points: list[LevelNetworkPointIn] = Field(min_length=2)
    observations: list[LevelNetworkObservationIn] = Field(min_length=1)
    robust: bool = False
    huber_k: float = Field(default=1.5, gt=0)
    review_threshold: float = Field(default=3.0, gt=0)
    max_iterations: int = Field(default=20, ge=1, le=100)


class CrsInspectIn(BaseModel):
    crs: str


class CrsTransformIn(BaseModel):
    x: float
    y: float
    source_crs: str
    target_crs: str


class RangeIn(BaseModel):
    source_mode: str = "project"  # project / file
    file_path: str = ""
    start: Optional[int] = None
    end: Optional[int] = None
    min_run: int = 1
    min_capacity: int = 100
    sort_order: str = "ascending"


class ControlImportIn(BaseModel):
    file_path: str


class ControlAnalyzeAllIn(BaseModel):
    method: str = "arithmetic"
    horizontal_tolerance: float = 0.10
    vertical_tolerance: float = 0.10
    min_observations: int = 2


class ControlImportAnalyzeIn(ControlAnalyzeAllIn):
    file_path: str


class ControlSolveIn(BaseModel):
    control_id: str
    method: str = "arithmetic"
    horizontal_tolerance: float = 0.10
    vertical_tolerance: float = 0.10


class RonControlFromPointsIn(BaseModel):
    control_id: str
    point_ids: list[str]
    horizontal_tolerance: float = 0.10
    vertical_tolerance: float = 0.10


class ControlRevisionSelectIn(BaseModel):
    control_id: str
    solution_id: str
    note: str = "Restored from revision history"


class FeedbackIn(BaseModel):
    kind: str = "feature"
    title: str
    description: str
    module: str = "Core"
    include_project_data: bool = False


class SourceImportIn(BaseModel):
    file_path: str
    module: str = "Core"
    notes: str = ""


class PointImportIn(BaseModel):
    file_path: str
    source_id: Optional[str] = None
    point_class: str = "survey"


class TrimbleJobImportIn(BaseModel):
    file_path: str
    import_points: bool = True
    point_class: str = "survey"


class UpdateConfigIn(BaseModel):
    update_manifest_url: str = ""


class UpdateInstallIn(BaseModel):
    confirm_install: bool = False


class FeedbackConfigIn(BaseModel):
    feedback_endpoint: str = ""


class ErrorLogSyncIn(BaseModel):
    endpoint_url: str = ""
    limit: int = 50


class AiConfigIn(BaseModel):
    ai_provider: str = "auto"


class UiConfigIn(BaseModel):
    appearance: Optional[str] = None
    theme: Optional[str] = None
    accent: Optional[str] = None


class LevelImportIn(BaseModel):
    file_path: str
    name: str = "Level Run"
    start_elevation: Optional[float] = None
    known_end_elevation: Optional[float] = None
    start_point: str = ""
    end_point: str = ""
    adjustment_method: str = "none"


class LevelSolveIn(BaseModel):
    run_id: str
    start_elevation: Optional[float] = None
    known_end_elevation: Optional[float] = None
    adjustment_method: Optional[str] = None
    middle_wire_tolerance: float = 0.005
    max_distance_imbalance: Optional[float] = None
    closure_tolerance: Optional[float] = None
    stadia_multiplier: float = 100.0
    calculation_profile: str = "ron_workbook"


class LevelRevisionSelectIn(BaseModel):
    run_id: str
    solution_id: str
    note: str = "Restored from revision history"


class TraverseImportIn(BaseModel):
    file_path: str
    name: str = "Traverse"
    start_n: float
    start_e: float
    end_n: Optional[float] = None
    end_e: Optional[float] = None
    adjustment_method: str = "bowditch"


class TraverseSolveIn(BaseModel):
    run_id: str
    adjustment_method: Optional[str] = None


class ScaleSampleIn(BaseModel):
    label: str = ""
    factor: float
    weight: float = 1.0
    station: Optional[float] = None
    zone: str = ""
    source: str = "manual"


class ScaleFitIn(BaseModel):
    name: str = "Project Ground Factor"
    samples: list[ScaleSampleIn]
    max_distortion_ppm: float = 20.0
    target_crs: str = ""


class ProjectionSamplesIn(BaseModel):
    target_crs: str
    source_crs: str = "EPSG:4326"
    points: list[dict]


class SpatialImportIn(BaseModel):
    file_paths: list[str]
    role: str = "reference"


class FieldToFinishIn(BaseModel):
    file_path: str
    output_path: str = ""


class UtilitySyncIn(BaseModel):
    sync_from_fieldbook: bool = True


class UtilityAnalyzeIn(BaseModel):
    tolerance: float = 30.0
    angle_tolerance: float = 35.0


class UtilityInvertIn(BaseModel):
    survey_elevation_is_rim: bool = True


class UtilityKmlIn(BaseModel):
    output_path: str = ""
    match_tolerance: float = 25.0


class AttachmentIn(BaseModel):
    file_path: str
    module: str = "UtilitySync"
    object_type: str = "utility_structure"
    object_id: str
    caption: str = ""
    metadata: dict = Field(default_factory=dict)


class AutoPhotoIn(BaseModel):
    folder_path: str
    point_ids: list[str] = Field(default_factory=list)


class SurveyReportIn(BaseModel):
    output_path: str = ""
    title: str = "Survey Report"
    prepared_by: str = ""
    project_number: str = ""
    client: str = ""
    scope: str = ""
    methodology: str = ""
    findings: str = ""


class NotificationPolicyIn(BaseModel):
    enabled: bool = False
    recipients: list[str] = Field(default_factory=list)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    from_address: str = ""
    use_tls: bool = True
    attach_file: bool = False


class EmailNotificationIn(BaseModel):
    deliverable_id: str
    recipients: list[str]
    smtp_host: str
    smtp_port: int = 587
    smtp_user: str = ""
    from_address: str = ""
    subject: str = ""
    message: str = ""
    use_tls: bool = True
    attach_file: bool = False
    password: str = ""


class TrimbleProjectsIn(BaseModel):
    access_token: str


class CloudImportIn(BaseModel):
    provider: str
    url: str
    access_token: str
    filename: str
    module: str = "FieldBookSync"


class AnnotatedFieldbookIn(BaseModel):
    output_path: str = ""


class QaRulesIn(BaseModel):
    rules: dict = Field(default_factory=dict)


class QaIssueStatusIn(BaseModel):
    issue_id: str
    status: str


class StageImportIn(BaseModel):
    file_path: str
    kind: str = "points"
    mapping: dict = Field(default_factory=dict)
    preview_rows: int = 12


class CommitStageIn(BaseModel):
    stage_id: str
    learn: bool = True


class LearnMappingIn(BaseModel):
    headers: list[str]
    mapping: dict
    label: str = ""


class SnapshotCreateIn(BaseModel):
    label: str = ""
    kind: str = "manual"


class SnapshotRestoreIn(BaseModel):
    snapshot_id: str


class CompareFileIn(BaseModel):
    file_path: str
    horizontal_tolerance: float = 0.001
    vertical_tolerance: float = 0.001


class ExportProfileIn(BaseModel):
    id: str
    name: str
    formats: list[str]
    precision: int = 4
    include_reports: bool = False
    include_existing_exports: bool = False


class ExportRunIn(BaseModel):
    profile_id: str


class PackageBuildIn(BaseModel):
    profile_id: str = "client_deliverable"
    label: str = ""


class BatchIn(BaseModel):
    file_paths: list[str] = Field(default_factory=list)
    action: str = "stage_points"


class TaskCancelIn(BaseModel):
    task_id: str


class DataEditIn(BaseModel):
    dataset: str
    record_id: str
    changes: dict = Field(default_factory=dict)
    reason: str = ""
