from pathlib import Path

from fieldbook_sync.aggregate import aggregate_results, apply_status_rule_to_existing
from fieldbook_sync.models import StatusRule, CodeProfile, CodeRule, DipStatus, EvidenceBasis, MatchMode, PageEvidence, PipeMeasurement, SurveyPoint
from fieldbook_sync.profiles import import_profile_csv
from fieldbook_sync.survey import normalize_point_id, parse_survey_bytes


def test_normalize_point_id_excel_artifact():
    assert normalize_point_id("1000.0") == "1000"
    assert normalize_point_id("001000") == "001000"
    assert normalize_point_id("A-12") == "A-12"


def test_survey_profile_filtering_and_headerless():
    profile = CodeProfile(name="X", codes=[
        CodeRule(code="DBL GI", category="Double Grate Inlet", match=MatchMode.EXACT),
        CodeRule(code="STM", category="Storm", match=MatchMode.STARTS_WITH),
    ])
    raw = b"1000,1,2,3,DBL GI\n1001,4,5,6,EP\n1002,7,8,9,STM MH\n"
    points, issues = parse_survey_bytes(raw, "x.txt", profile)
    assert [p.point_id for p in points] == ["1000", "1002"]
    assert [p.category for p in points] == ["Double Grate Inlet", "Storm"]
    assert not issues


def test_no_silent_no_when_only_review_evidence():
    point = SurveyPoint(point_id="1000", northing=1, easting=2, elevation=3, code="MH", category="Manhole")
    ev = PageEvidence(
        matched_point_id="1000",
        source_name="book.pdf",
        page_number=1,
        page_id="abc",
        point_id_confidence=0.99,
        dipped=DipStatus.REVIEW,
        dipped_confidence=0.9,
        evidence="Structure visible but dip status unclear",
    )
    result = aggregate_results([point], [ev], .85, status_rule=StatusRule.CONFIRMED_DIP)[0]
    assert result.status == DipStatus.REVIEW


def test_high_confidence_yes_and_conflict_rules():
    point = SurveyPoint(point_id="1000", northing=1, easting=2, elevation=3, code="MH", category="Manhole")
    yes = PageEvidence(
        matched_point_id="1000", source_name="book.pdf", page_number=1, page_id="a",
        point_id_confidence=.98, dipped=DipStatus.YES, basis=EvidenceBasis.MEASUREMENT, dipped_confidence=.95,
        evidence="Dip 9.4 visible", pipes=[PipeMeasurement(dip=9.4)]
    )
    no = PageEvidence(
        matched_point_id="1000", source_name="book.pdf", page_number=2, page_id="b",
        point_id_confidence=.99, dipped=DipStatus.NO, basis=EvidenceBasis.EXPLICIT_NO, dipped_confidence=.96,
        evidence="Explicit NOT DIPPED note"
    )
    r1 = aggregate_results([point], [yes], .85, status_rule=StatusRule.CONFIRMED_DIP)[0]
    assert r1.status == DipStatus.YES
    assert r1.pipes[0].dip == 9.4
    r2 = aggregate_results([point], [yes, no], .85, status_rule=StatusRule.CONFIRMED_DIP)[0]
    assert r2.status == DipStatus.REVIEW


def test_profile_csv_import():
    raw = b"Code,Category,Include,Match\nMH,Manhole,Yes,exact\nSTM,Storm,Yes,prefix\nEP,Edge,No,exact\n"
    profile = import_profile_csv("Client", "Client", raw)
    assert len(profile.codes) == 3
    assert profile.codes[1].match == MatchMode.STARTS_WITH
    assert profile.codes[2].include is False

def test_yes_no_basis_gate_forces_review():
    point = SurveyPoint(point_id="2000", northing=1, easting=2, elevation=3, code="MH", category="Manhole")
    bad_yes = PageEvidence(
        matched_point_id="2000", source_name="book.pdf", page_number=1, page_id="x",
        point_id_confidence=.99, dipped=DipStatus.YES, basis=EvidenceBasis.AMBIGUOUS,
        dipped_confidence=.99, evidence="Unclear note"
    )
    result = aggregate_results([point], [bad_yes], .85, status_rule=StatusRule.CONFIRMED_DIP)[0]
    assert result.status == DipStatus.REVIEW

def test_ai_reader_blocks_non_target_and_bad_no_basis(tmp_path, monkeypatch):
    import json
    from PIL import Image
    import fieldbook_sync.ai_reader as ai_reader

    image_path = tmp_path / "page.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path)

    fake_payload = {
        "entries": [
            {
                "point_id": "1000",
                "point_id_raw": "1000",
                "point_id_confidence": 0.99,
                "structure_label": "MH",
                "dipped": "NO",
                "basis": "AMBIGUOUS",
                "dipped_confidence": 0.99,
                "evidence": "No measurement visible",
                "pipes": [],
                "bbox": None,
                "notes": None,
            },
            {
                "point_id": "9999",
                "point_id_raw": "9999",
                "point_id_confidence": 1.0,
                "structure_label": "MH",
                "dipped": "YES",
                "basis": "MEASUREMENT",
                "dipped_confidence": 1.0,
                "evidence": "Dip visible",
                "pipes": [],
                "bbox": None,
                "notes": None,
            },
        ],
        "unmatched": [],
    }

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(fake_payload)}]}]}

    monkeypatch.setattr(ai_reader.requests, "post", lambda *a, **k: FakeResponse())
    evidence, unmatched = ai_reader.read_page(
        image_path=str(image_path), mime_type="image/jpeg", source_name="book.jpg", page_number=1,
        page_id="p1", target_point_ids=["1000"], api_key="test", model="test-model"
    )
    assert len(evidence) == 1
    assert evidence[0].matched_point_id == "1000"
    assert evidence[0].dipped == DipStatus.REVIEW  # NO without EXPLICIT_NO is blocked.
    assert len(unmatched) == 1
    assert unmatched[0].point_id_raw == "9999"


def test_pipe_dedupe_preserves_identical_pipes_within_one_evidence():
    point = SurveyPoint(point_id="3000", northing=1, easting=2, elevation=3, code="MH", category="Manhole")
    pipe_a = PipeMeasurement(dip=4.20, diameter_in=15, material="RCP", azimuth_deg=90)
    pipe_b = PipeMeasurement(dip=4.20, diameter_in=15, material="RCP", azimuth_deg=90)
    ev = PageEvidence(
        matched_point_id="3000", source_name="book.pdf", page_number=1, page_id="p1",
        point_id_confidence=.99, dipped=DipStatus.YES, basis=EvidenceBasis.MEASUREMENT,
        dipped_confidence=.99, evidence="Two identical 15-inch RCP pipe measurements",
        pipes=[pipe_a, pipe_b],
    )
    result = aggregate_results([point], [ev], .85)[0]
    assert len(result.pipes) == 2


def test_pipe_dedupe_across_pages_uses_max_observed_multiplicity():
    point = SurveyPoint(point_id="3001", northing=1, easting=2, elevation=3, code="MH", category="Manhole")
    def evidence(page, count):
        return PageEvidence(
            matched_point_id="3001", source_name="book.pdf", page_number=page, page_id=f"p{page}",
            point_id_confidence=.99, dipped=DipStatus.YES, basis=EvidenceBasis.MEASUREMENT,
            dipped_confidence=.99, evidence="Repeated observation",
            pipes=[PipeMeasurement(dip=4.20, diameter_in=15, material="RCP", azimuth_deg=90) for _ in range(count)],
        )
    result = aggregate_results([point], [evidence(1, 1), evidence(2, 2), evidence(3, 2)], .85)[0]
    assert len(result.pipes) == 2


def test_profile_rename_removes_original_file(tmp_path):
    from fieldbook_sync.profiles import save_profile

    original = CodeProfile(name="Client A", client="A")
    renamed = CodeProfile(name="Client A Renamed", client="A")
    save_profile(tmp_path, original)
    save_profile(tmp_path, renamed, original_name="Client A")

    assert not (tmp_path / "Client_A.json").exists()
    assert (tmp_path / "Client_A_Renamed.json").exists()
    names = []
    for path in tmp_path.glob("*.json"):
        names.append(CodeProfile.model_validate_json(path.read_text(encoding="utf-8")).name)
    assert "Client A" not in names
    assert "Client A Renamed" in names


def test_profile_rename_refuses_existing_target(tmp_path):
    import pytest
    from fieldbook_sync.profiles import save_profile

    save_profile(tmp_path, CodeProfile(name="Client A"))
    save_profile(tmp_path, CodeProfile(name="Client B"))
    with pytest.raises(ValueError):
        save_profile(tmp_path, CodeProfile(name="Client B"), original_name="Client A")
    assert (tmp_path / "Client_A.json").exists()
    assert (tmp_path / "Client_B.json").exists()


def test_profile_save_rejected_while_analysis_running(tmp_path, monkeypatch):
    import importlib
    import pytest
    from fastapi import HTTPException
    from fieldbook_sync.models import AnalysisJob
    from fieldbook_sync.storage import AppStorage

    app_module = importlib.import_module("fieldbook_sync.app")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    storage = AppStorage()
    monkeypatch.setattr(app_module.runtime, "storage", storage)
    monkeypatch.setattr(app_module.runtime, "job", AnalysisJob(running=True))

    payload = app_module.ProfileSaveIn(name="Race Test", client="Race", codes=[])
    with pytest.raises(HTTPException) as exc:
        app_module.api_save_profile(payload)
    assert exc.value.status_code == 409
    assert not (storage.profile_dir / "Race_Test.json").exists()


def test_stale_analysis_revision_never_commits_results(tmp_path, monkeypatch):
    import importlib
    from fieldbook_sync.models import AnalysisJob, AppState, FieldBookPage
    from fieldbook_sync.storage import AppStorage

    app_module = importlib.import_module("fieldbook_sync.app")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    storage = AppStorage()
    storage.state = AppState(
        survey_points=[SurveyPoint(point_id="4000", northing=1, easting=2, elevation=3, code="MH", category="Manhole")],
        fieldbook_pages=[FieldBookPage(page_id="page", source_name="book.jpg", page_number=1, image_path="unused.jpg", mime_type="image/jpeg")],
        results=[],
        unmatched=[],
    )
    monkeypatch.setattr(app_module.runtime, "storage", storage)
    monkeypatch.setattr(app_module.runtime, "job", AnalysisJob(running=True, total_pages=1))
    monkeypatch.setattr(app_module.runtime, "project_revision", 10)
    app_module.runtime.cancel_event.clear()

    def fake_read_page(**kwargs):
        # Simulate a project-input mutation that escaped a future route guard while an
        # API request was in flight. The worker must discard everything from rev 10.
        from fieldbook_sync.ai_reader import ProviderUsage
        with app_module.runtime.lock:
            app_module.runtime.project_revision += 1
        ev = PageEvidence(
            matched_point_id="4000", source_name="book.jpg", page_number=1, page_id="page",
            point_id_confidence=.99, dipped=DipStatus.YES, basis=EvidenceBasis.MEASUREMENT,
            dipped_confidence=.99, evidence="Dip 4.2", pipes=[PipeMeasurement(dip=4.2)],
        )
        return [ev], [], ProviderUsage(requests=1)

    from fieldbook_sync import vision_pipeline
    monkeypatch.setattr(vision_pipeline, "read_page_openai", fake_read_page)
    app_module._analysis_worker("openai", "test-key", "test-model", .85, analysis_revision=10, gemini_batch_pages=1)

    assert storage.state.results == []
    assert app_module.runtime.job.running is False
    assert app_module.runtime.job.complete is False
    assert "stale" in (app_module.runtime.job.error or "").lower()



def test_gemini_batch_reader_enforces_page_and_point_provenance(tmp_path, monkeypatch):
    import json
    from PIL import Image
    import fieldbook_sync.ai_reader as ai_reader
    from fieldbook_sync.models import FieldBookPage

    p1 = tmp_path / "p1.jpg"
    p2 = tmp_path / "p2.jpg"
    Image.new("RGB", (120, 120), "white").save(p1)
    Image.new("RGB", (120, 120), "white").save(p2)
    pages = [
        FieldBookPage(page_id="p1", source_name="book.pdf", page_number=1, image_path=str(p1), mime_type="image/jpeg"),
        FieldBookPage(page_id="p2", source_name="book.pdf", page_number=2, image_path=str(p2), mime_type="image/jpeg"),
    ]
    payload = {
        "entries": [
            {
                "page_id": "p1", "point_id": "1000", "point_id_raw": "1000", "point_id_confidence": .99,
                "structure_label": "MH", "dipped": "NO", "basis": "AMBIGUOUS", "dipped_confidence": .98,
                "evidence": "No dip written", "pipes": [], "bbox": None, "notes": None,
            },
            {
                "page_id": "p2", "point_id": "9999", "point_id_raw": "9999", "point_id_confidence": 1,
                "structure_label": "MH", "dipped": "YES", "basis": "MEASUREMENT", "dipped_confidence": 1,
                "evidence": "Dip", "pipes": [], "bbox": None, "notes": None,
            },
            {
                "page_id": "invented", "point_id": "1000", "point_id_raw": "1000", "point_id_confidence": 1,
                "structure_label": "MH", "dipped": "YES", "basis": "MEASUREMENT", "dipped_confidence": 1,
                "evidence": "Must be discarded due to bad provenance", "pipes": [], "bbox": None, "notes": None,
            },
        ],
        "unmatched": [],
    }

    class FakeResponse:
        status_code = 200
        def json(self):
            return {
                "candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}],
                "usageMetadata": {"promptTokenCount": 123, "candidatesTokenCount": 45, "totalTokenCount": 168},
            }

    monkeypatch.setattr(ai_reader.requests, "post", lambda *a, **k: FakeResponse())
    evidence, unmatched, usage = ai_reader.read_pages_gemini(
        pages=pages, target_point_ids=["1000"], api_key="test", model="gemini-test"
    )
    assert len(evidence) == 1
    assert evidence[0].page_id == "p1"
    assert evidence[0].dipped == DipStatus.REVIEW  # NO without EXPLICIT_NO is blocked.
    assert len(unmatched) == 1
    assert unmatched[0].point_id_raw == "9999"
    assert unmatched[0].page_id == "p2"
    assert usage.requests == 1
    assert usage.total_tokens == 168


def test_manual_review_requires_no_api_key(tmp_path, monkeypatch):
    import importlib
    from fieldbook_sync.models import AppState, FieldBookPage
    from fieldbook_sync.storage import AppStorage

    app_module = importlib.import_module("fieldbook_sync.app")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    storage = AppStorage()
    storage.state = AppState(
        survey_points=[SurveyPoint(point_id="5000", northing=1, easting=2, elevation=3, code="MH", category="Manhole")],
        fieldbook_pages=[FieldBookPage(page_id="page", source_name="book.jpg", page_number=1, image_path="unused.jpg", mime_type="image/jpeg")],
    )
    monkeypatch.setattr(app_module.runtime, "storage", storage)
    monkeypatch.setattr(app_module.runtime, "provider", "manual")
    monkeypatch.setattr(app_module.runtime, "gemini_api_key", None)
    monkeypatch.setattr(app_module.runtime, "openai_api_key", None)
    monkeypatch.setattr(app_module.runtime, "job", app_module.AnalysisJob())

    job = app_module.api_analyze()
    assert job["complete"] is True
    assert job["api_requests"] == 0
    assert storage.state.results[0].status == DipStatus.REVIEW
    assert "Manual Review" in storage.state.results[0].notes


def test_gemini_request_estimate_batches_pages(tmp_path, monkeypatch):
    import importlib
    from fieldbook_sync.models import AppState, FieldBookPage
    from fieldbook_sync.storage import AppStorage

    app_module = importlib.import_module("fieldbook_sync.app")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    storage = AppStorage()
    storage.state = AppState(
        survey_points=[SurveyPoint(point_id=str(i), code="MH") for i in range(500)],
        fieldbook_pages=[FieldBookPage(page_id=f"p{i}", source_name="book.pdf", page_number=i+1, image_path="x", mime_type="image/jpeg") for i in range(10)],
    )
    monkeypatch.setattr(app_module.runtime, "storage", storage)
    monkeypatch.setattr(app_module.runtime, "provider", "gemini")
    monkeypatch.setattr(app_module.runtime, "gemini_batch_pages", 4)
    summary = app_module._summary()
    # 10 pages => 3 batches; 500 targets => 3 target chunks; 9 total requests.
    assert summary["settings"]["estimated_requests"] == 9


def test_qwen_ollama_structured_vision_and_page_guard(tmp_path, monkeypatch):
    import json
    from PIL import Image
    import fieldbook_sync.ai_reader as ai_reader
    from fieldbook_sync.models import FieldBookPage

    image_path = tmp_path / "page.jpg"
    Image.new("RGB", (160, 120), "white").save(image_path)
    page = FieldBookPage(
        page_id="page-1", source_name="book.jpg", page_number=1,
        image_path=str(image_path), mime_type="image/jpeg"
    )
    payload = {
        "entries": [
            {
                "page_id": "page-1",
                "point_id": "5000",
                "point_id_raw": "5000",
                "point_id_confidence": .99,
                "structure_label": "MH",
                "dipped": "YES",
                "basis": "MEASUREMENT",
                "dipped_confidence": .97,
                "evidence": "Dip 4.20 visible",
                "pipes": [{
                    "dip": 4.2, "dip_raw": "4.20", "diameter_in": 15,
                    "diameter_raw": '15"', "material": "RCP", "azimuth_deg": 90,
                    "azimuth_raw": "90", "notes": None,
                }],
                "bbox": [10, 20, 400, 300],
                "notes": None,
            },
            {
                # A correct PointID with invented page provenance must be discarded.
                "page_id": "invented-page",
                "point_id": "5000",
                "point_id_raw": "5000",
                "point_id_confidence": 1.0,
                "structure_label": "MH",
                "dipped": "YES",
                "basis": "MEASUREMENT",
                "dipped_confidence": 1.0,
                "evidence": "Should never attach",
                "pipes": [], "bbox": None, "notes": None,
            },
        ],
        "unmatched": [],
    }

    class FakeResponse:
        status_code = 200
        text = ""
        def json(self):
            return {
                "message": {"role": "assistant", "content": json.dumps(payload)},
                "prompt_eval_count": 120,
                "eval_count": 42,
            }

    monkeypatch.setattr(ai_reader.requests, "post", lambda *a, **k: FakeResponse())
    evidence, unmatched, usage = ai_reader.read_pages_ollama(
        pages=[page], target_point_ids=["5000"], model="qwen3.8:27b"
    )
    assert len(evidence) == 1
    assert evidence[0].matched_point_id == "5000"
    assert evidence[0].pipes[0].dip == 4.2
    assert not unmatched
    assert usage.requests == 1
    assert usage.total_tokens == 162


def test_qwen_ollama_blocks_non_target_id(tmp_path, monkeypatch):
    import json
    from PIL import Image
    import fieldbook_sync.ai_reader as ai_reader
    from fieldbook_sync.models import FieldBookPage

    image_path = tmp_path / "page.jpg"
    Image.new("RGB", (100, 100), "white").save(image_path)
    page = FieldBookPage(page_id="p", source_name="book.jpg", page_number=1, image_path=str(image_path), mime_type="image/jpeg")
    payload = {
        "entries": [{
            "page_id": "p", "point_id": "5999", "point_id_raw": "5999",
            "point_id_confidence": .94, "structure_label": "MH", "dipped": "YES",
            "basis": "MEASUREMENT", "dipped_confidence": .95, "evidence": "Dip visible",
            "pipes": [], "bbox": None, "notes": None,
        }],
        "unmatched": [],
    }

    class FakeResponse:
        status_code = 200
        text = ""
        def json(self):
            return {"message": {"content": json.dumps(payload)}}

    monkeypatch.setattr(ai_reader.requests, "post", lambda *a, **k: FakeResponse())
    evidence, unmatched, _ = ai_reader.read_pages_ollama(pages=[page], target_point_ids=["5000"], model="qwen3.8:27b")
    assert not evidence
    assert len(unmatched) == 1
    assert unmatched[0].point_id_raw == "5999"


def test_ollama_model_discovery(monkeypatch):
    import fieldbook_sync.ai_reader as ai_reader

    class FakeResponse:
        status_code = 200
        text = ""
        def json(self):
            return {"models": [{"name": "qwen3.8:27b"}, {"name": "llama3.2-vision:latest"}]}

    monkeypatch.setattr(ai_reader.requests, "get", lambda *a, **k: FakeResponse())
    models = ai_reader.list_ollama_models()
    assert "qwen3.8:27b" in models
    assert "llama3.2-vision:latest" in models


def test_point_id_found_default_produces_simple_yes_no_without_losing_detail_review():
    point_yes = SurveyPoint(point_id="5001", northing=1, easting=2, elevation=3, code="MH", category="Manhole")
    point_no = SurveyPoint(point_id="5002", northing=4, easting=5, elevation=6, code="MH", category="Manhole")
    ev = PageEvidence(
        matched_point_id="5001", source_name="book.pdf", page_number=1, page_id="p1",
        point_id_confidence=.99, dipped=DipStatus.REVIEW, dipped_confidence=.55,
        basis=EvidenceBasis.AMBIGUOUS, evidence="Exact PointID entry found; handwriting details unclear",
        model_agreement=False,
    )
    results = aggregate_results([point_yes, point_no], [ev], .85)
    assert results[0].status == DipStatus.YES
    assert results[0].dip_status == DipStatus.REVIEW
    assert results[0].qa_needs_review is True
    assert results[1].status == DipStatus.NO
    assert results[1].dip_status == DipStatus.NOT_FOUND
    assert results[1].qa_needs_review is False


def test_confirmed_dip_rule_preserves_legacy_review_not_found_states():
    p1 = SurveyPoint(point_id="6001", northing=1, easting=2, elevation=3, code="MH", category="Manhole")
    p2 = SurveyPoint(point_id="6002", northing=4, easting=5, elevation=6, code="MH", category="Manhole")
    ev = PageEvidence(
        matched_point_id="6001", source_name="book.pdf", page_number=1, page_id="p1",
        point_id_confidence=.99, dipped=DipStatus.REVIEW, dipped_confidence=.60,
        basis=EvidenceBasis.AMBIGUOUS, evidence="Point found but dip unclear",
    )
    results = aggregate_results([p1, p2], [ev], .85, status_rule=StatusRule.CONFIRMED_DIP)
    assert results[0].status == DipStatus.REVIEW
    assert results[1].status == DipStatus.NOT_FOUND


def test_status_rule_can_remap_existing_results_without_rerunning_ai():
    point = SurveyPoint(point_id="7001", northing=1, easting=2, elevation=3, code="MH", category="Manhole")
    ev = PageEvidence(
        matched_point_id="7001", source_name="book.pdf", page_number=1, page_id="p1",
        point_id_confidence=.99, dipped=DipStatus.REVIEW, dipped_confidence=.5,
        basis=EvidenceBasis.AMBIGUOUS, evidence="Exact PointID found; detail unclear",
    )
    r = aggregate_results([point], [ev], .85, status_rule=StatusRule.CONFIRMED_DIP)[0]
    assert r.status == DipStatus.REVIEW
    apply_status_rule_to_existing([r], StatusRule.POINT_ID_FOUND)
    assert r.status == DipStatus.YES
    assert r.dip_status == DipStatus.REVIEW
    assert r.qa_needs_review is True
    apply_status_rule_to_existing([r], StatusRule.CONFIRMED_DIP)
    assert r.status == DipStatus.REVIEW


def test_batch_group_key_page_suffixes():
    from fieldbook_sync.batch_pairing import batch_group_key

    expected = batch_group_key("JobA.jpg", "fieldbook")
    for name in (
        "JobA_p3.jpg",
        "JobA_page3.jpg",
        "JobA_pg003.jpg",
        "JobA_page_12.jpg",
        "JobA_p_12.jpg",
    ):
        assert batch_group_key(name, "fieldbook") == expected

    # Legitimate identifying job/date numbers must remain part of the key.
    assert batch_group_key("Project_2026_1047.pdf", "fieldbook") == "project 2026 1047"
