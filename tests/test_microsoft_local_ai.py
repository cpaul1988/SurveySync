from surveysync.ai_runtime import _ready_state_flags, resolve_automatic_plan
from surveysync.config import ConfigStore
from fieldbook_sync.models import AppState, BatchJob, DipStatus, FieldBookPage, SurveyPoint
import fieldbook_sync.app as fieldbook_app
from fieldbook_sync.app import _windows_ocr_candidates_from_payload


def _status(*, windows=False, foundry=False):
    return {
        "windows_ocr": {"ready": windows},
        "foundry_local": {"ready": foundry},
    }


def test_windows_ready_state_mapping():
    assert _ready_state_flags(0) == (True, True, False, "ready")
    assert _ready_state_flags(1) == (True, False, True, "not_ready")
    assert _ready_state_flags(5)[0:3] == (False, False, False)


def test_auto_prefers_document_specialized_pipeline_when_both_ready():
    plan = resolve_automatic_plan(_status(windows=True, foundry=True), hybrid_ready=True, paddle_ready=True, ollama_ready=True)
    assert plan.effective_provider == "hybrid"
    assert plan.ocr_provider == "windows_ai+paddle_vl_1_6"
    assert plan.vision_provider == "qwen3_vl"
    assert "Evidence-First Local" in plan.label


def test_auto_uses_windows_ocr_with_existing_local_vision_when_paddle_missing():
    plan = resolve_automatic_plan(_status(windows=True, foundry=False), hybrid_ready=False, paddle_ready=False, ollama_ready=True)
    assert plan.effective_provider == "windows_ocr_ollama"


def test_auto_keeps_windows_foundry_as_fallback_when_hybrid_is_unavailable():
    plan = resolve_automatic_plan(_status(windows=True, foundry=True), hybrid_ready=False, paddle_ready=False, ollama_ready=False)
    assert plan.effective_provider == "microsoft_auto"
    assert plan.local_only is True


def test_auto_falls_back_without_cloud():
    plan = resolve_automatic_plan(_status(), hybrid_ready=True, paddle_ready=True, ollama_ready=True)
    assert plan.effective_provider == "hybrid"
    assert plan.local_only is True
    plan2 = resolve_automatic_plan(_status(), hybrid_ready=False, paddle_ready=False, ollama_ready=False)
    assert plan2.effective_provider == "manual"


def test_shared_config_defaults_to_auto(tmp_path):
    cfg = ConfigStore(tmp_path).load()
    assert cfg.ai_provider == "auto"


def test_windows_ocr_candidates_require_exact_token():
    page = FieldBookPage(page_id="p1", source_name="book.pdf", page_number=1, image_path="x.jpg", mime_type="image/jpeg")
    payload = {
        "width": 1000,
        "height": 2000,
        "lines": [
            {"text": "MH 2437 DIP 4.62", "confidence": 0.94, "polygon": [[100,200],[400,200],[400,260],[100,260]]},
            {"text": "2438A", "confidence": 0.90, "polygon": [[100,300],[300,300],[300,350],[100,350]]},
            {"text": "note 243", "confidence": 0.80, "polygon": [[100,400],[300,400],[300,450],[100,450]]},
        ],
    }
    hits = _windows_ocr_candidates_from_payload(page, payload, ["2437", "2438", "243"])
    ids = [x.point_id for x in hits]
    assert "2437" in ids
    assert "243" in ids
    assert "2438" not in ids  # must not match the prefix of 2438A
    h = next(x for x in hits if x.point_id == "2437")
    assert h.exact_match is True and h.engine == "windows-ai-ocr"
    assert h.bbox == [100, 100, 400, 130]


def test_fieldbook_jobs_default_to_automatic():
    job = BatchJob(job_id="b1", name="demo")
    assert job.provider == "auto"


def test_batch_automatic_resolves_before_processing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        fieldbook_app,
        "_automatic_ai_status",
        lambda force=False: {"automatic_plan": {"provider": "manual", "label": "Manual Review"}},
    )
    state = AppState(
        survey_points=[SurveyPoint(point_id="100", code="MH")],
        fieldbook_pages=[FieldBookPage(page_id="p1", source_name="book.pdf", page_number=1, image_path="missing.jpg", mime_type="image/jpeg")],
    )
    job = BatchJob(job_id="b2", name="automatic batch", provider="auto")
    fieldbook_app._batch_analyze_state(job, state, tmp_path)
    assert state.results and state.results[0].point_id == "100"
    assert state.results[0].status == DipStatus.REVIEW
    assert "Automatic selected" in job.message or "Manual" in job.message
