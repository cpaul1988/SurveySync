from __future__ import annotations

import re
import sqlite3
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

from fieldbook_sync.exporter import create_export_zip
from fieldbook_sync.image_processing import crop_normalized_bbox, enhance_fieldbook_image
from fieldbook_sync.intelligence import calculate_smart_confidence, infer_network, refresh_intelligence
from fieldbook_sync.models import (
    AppState, CodeProfile, DipStatus, EvidenceBasis, FieldBookPage, OcrCandidate,
    PageEvidence, PipeMeasurement, ResultRecord, ReviewState, SurveyPoint, VerifiedExample,
)
from fieldbook_sync.ocr_local import compare_ocr_to_evidence, locate_target_ids
from fieldbook_sync.project_files import create_project_bundle, load_project_bundle
from fieldbook_sync.search_index import search_project


def _result(point_id: str, e: float, n: float, az: float | None = None, dip: float | None = 4.2) -> ResultRecord:
    pipes = [PipeMeasurement(dip=dip, diameter_in=15, material="RCP", azimuth_deg=az)] if az is not None or dip is not None else []
    return ResultRecord(
        point_id=point_id, easting=e, northing=n, elevation=100.0, code="MH", category="Manhole",
        status=DipStatus.YES, confidence=.95, pipes=pipes,
    )



def _evidence_for_pipe(*, dip=None, diameter=None, material=None, azimuth=None, dipped=DipStatus.YES):
    return PageEvidence(
        matched_point_id="52004", source_name="book.pdf", page_number=1, page_id="p1",
        point_id_confidence=.99, dipped=dipped, basis=EvidenceBasis.MEASUREMENT,
        dipped_confidence=.99, evidence="test",
        pipes=[PipeMeasurement(dip=dip, diameter_in=diameter, material=material, azimuth_deg=azimuth)],
    )


def test_v6_1_cross_model_value_first_dip_does_not_collide_with_dip_material_token():
    ev = _evidence_for_pipe(dip=4.2, diameter=15, material="RCP", azimuth=90)
    agree, summary = compare_ocr_to_evidence("52004  4.20 DIP  15 RCP  AZ 90", ev)
    assert agree is True
    assert "dip=4.2" in summary
    assert "diameter=15" in summary
    assert "diameter=4.2" not in summary
    assert "dip=15" not in summary


def test_v6_1_cross_model_preserves_real_ductile_iron_pipe_material():
    ev = _evidence_for_pipe(dip=None, diameter=12, material="DIP", azimuth=90)
    agree, summary = compare_ocr_to_evidence("52004  12 DIP  AZ 90", ev)
    assert agree is True
    assert "diameter=12" in summary
    assert "dip=12" not in summary


def test_v6_1_cross_model_label_first_dip_still_works():
    ev = _evidence_for_pipe(dip=4.2, diameter=15, material="RCP", azimuth=90)
    agree, summary = compare_ocr_to_evidence("52004  DIP 4.20  15 RCP  AZ 90", ev)
    assert agree is True
    assert "dip=4.2" in summary
    assert "diameter=15" in summary


def test_v6_1_cross_model_ambiguous_material_context_prefers_no_false_disagreement():
    ev = _evidence_for_pipe(dip=None, diameter=12, material="DIP", azimuth=None)
    agree, summary = compare_ocr_to_evidence("52004  12 DIP  4.20", ev)
    assert agree is True
    assert "diameter=12" in summary
    assert "dip=4.2" not in summary

def test_v6_smart_confidence_cross_model_and_ocr():
    ev = PageEvidence(
        matched_point_id="52004", source_name="book.pdf", page_number=1, page_id="p1",
        point_id_confidence=.99, dipped=DipStatus.YES, basis=EvidenceBasis.MEASUREMENT,
        dipped_confidence=.95, evidence="4.20, 15 RCP AZ 90",
        pipes=[PipeMeasurement(dip=4.2, diameter_in=15, material="RCP", azimuth_deg=90)],
        primary_engine="Qwen3.8", secondary_engine="PaddleOCR-VL 1.6", model_agreement=True,
    )
    r = _result("52004", 0, 0, 90)
    r.evidence_records = [ev]
    ocr = [OcrCandidate(page_id="p1", source_name="book.pdf", page_number=1, point_id="52004", exact_match=True)]
    score, factors = calculate_smart_confidence(r, ocr)
    assert score == 100
    assert any("Exact PointID" in x for x in factors)
    assert any("agree" in x for x in factors)


def test_v6_smart_confidence_disagreement_forces_penalty():
    r = _result("52004", 0, 0, 90)
    r.status = DipStatus.REVIEW
    r.evidence_records = [PageEvidence(
        matched_point_id="52004", source_name="book", page_number=1, page_id="p",
        dipped=DipStatus.REVIEW, model_agreement=False,
    )]
    score, factors = calculate_smart_confidence(r, [])
    assert score <= 79
    assert any("disagree" in x for x in factors)


def test_v6_invert_and_qc_are_deterministic():
    r = _result("100", 0, 0, 90, dip=4.25)
    r.elevation = 542.18
    r.pipes[0].diameter_in = 150  # intentionally beyond QC threshold
    refresh_intelligence([r], [], elevation_is_rim=True)
    assert round(r.pipes[0].invert_elevation, 2) == 537.93
    assert any("diameter" in x.lower() for x in r.qc_flags)


def test_v6_network_reciprocal_azimuth_suggests_strong_connection():
    # From A to B is due east (90°); B points back west (270°).
    a = _result("A", 0, 0, 90)
    b = _result("B", 100, 0, 270)
    edges = infer_network([a, b], max_distance=500, max_bearing_error=20, reciprocal_tolerance=20)
    edge = next(e for e in edges if e.from_point == "A")
    assert edge.to_point == "B"
    assert edge.status == "STRONG"
    assert edge.bearing_error_deg == 0
    assert edge.reciprocal_error_deg == 0
    assert a.pipes[0].connected_point_id == "B"


def test_v6_paddle_index_exact_target_and_bbox(tmp_path):
    img = tmp_path / "page.jpg"
    Image.new("RGB", (1000, 2000), "white").save(img)
    page = FieldBookPage(page_id="p1", source_name="book.jpg", page_number=1, image_path=str(img), mime_type="image/jpeg")
    payload = {"res": {"parsing_res_list": [
        {"block_bbox": [100, 200, 600, 600], "block_label": "text", "block_content": "52004 15 RCP dip 4.20 AZ 287"},
        {"block_bbox": [0, 0, 100, 100], "block_label": "text", "block_content": "99999 irrelevant"},
    ]}}
    hits = locate_target_ids(page, payload, ["52004", "52005"])
    assert len(hits) == 1
    assert hits[0].point_id == "52004"
    assert hits[0].bbox == [100, 100, 600, 300]


def test_v6_image_enhancement_and_crop(tmp_path):
    src = tmp_path / "photo.jpg"
    im = Image.new("RGB", (900, 1200), "#ddd8cc")
    d = ImageDraw.Draw(im)
    d.rectangle((70, 60, 830, 1140), outline="black", width=5)
    d.text((170, 260), "52004  DIP 4.20  15 RCP", fill="black")
    im.save(src)
    enhanced = enhance_fieldbook_image(src, tmp_path / "enhanced.jpg")
    assert enhanced.exists() and enhanced.stat().st_size > 1000
    crop = crop_normalized_bbox(enhanced, [100, 100, 700, 500], tmp_path / "crop.jpg")
    assert crop and crop.exists()
    with Image.open(crop) as cim:
        assert cim.width > 100 and cim.height > 100


def test_v6_project_bundle_round_trip_pages_examples_and_profile(tmp_path):
    pages_dir = tmp_path / "pages"
    pages_dir.mkdir()
    original = pages_dir / "p1.png"
    enhanced = pages_dir / "p1_enhanced.jpg"
    Image.new("RGB", (40, 40), "white").save(original)
    Image.new("RGB", (40, 40), "white").save(enhanced)
    example = tmp_path / "verified.jpg"
    Image.new("RGB", (20, 20), "white").save(example)
    state = AppState(
        project_name="Johnson Creek",
        selected_profile="Client A",
        fieldbook_pages=[FieldBookPage(page_id="p1", source_name="book.pdf", page_number=1, image_path=str(original), mime_type="image/png", enhanced_image_path=str(enhanced))],
        verified_examples=[VerifiedExample(example_id="x", point_id="52004", page_id="p1", crop_path=str(example), accepted_result={"status":"YES"})],
    )
    bundle = create_project_bundle(state, pages_dir, tmp_path / "projects", CodeProfile(name="Client A"))
    restored, profile = load_project_bundle(bundle, tmp_path / "restored_pages", tmp_path / "restored_examples")
    assert restored.project_name == "Johnson Creek"
    assert Path(restored.fieldbook_pages[0].image_path).exists()
    assert Path(restored.fieldbook_pages[0].enhanced_image_path).exists()
    assert Path(restored.verified_examples[0].crop_path).exists()
    assert profile and profile.name == "Client A"


def test_v6_export_contains_modern_gis_outputs(tmp_path):
    a = _result("A", 1000, 2000, 90)
    b = _result("B", 1100, 2000, 270)
    state = AppState(project_name="GIS Test", results=[a, b])
    state.network_edges = infer_network(state.results, max_distance=500, max_bearing_error=20, reciprocal_tolerance=20)
    zpath = create_export_zip(state, tmp_path)
    with zipfile.ZipFile(zpath) as zf:
        names = set(zf.namelist())
        assert "fieldbook_sync.gpkg" in names
        assert "fieldbook_sync.geojson" in names
        assert "fieldbook_sync.kmz" in names
        assert "shapefile/structures.shp" in names
        assert "shapefile/structures.dbf" in names
        assert "shapefile/network_connections.shp" in names
        assert "create_arcgis_file_gdb.py" in names
        gpkg = tmp_path / "test.gpkg"
        gpkg.write_bytes(zf.read("fieldbook_sync.gpkg"))
    con = sqlite3.connect(gpkg)
    try:
        tables = {r[0] for r in con.execute("SELECT table_name FROM gpkg_contents")}
        assert {"structures", "pipes", "network_connections"}.issubset(tables)
        assert con.execute("SELECT COUNT(*) FROM structures").fetchone()[0] == 2
    finally:
        con.close()


def test_v6_global_search_hits_result_index_and_network():
    a = _result("52004", 0, 0, 90)
    b = _result("52017", 100, 0, 270)
    state = AppState(results=[a, b])
    state.ocr_candidates = [OcrCandidate(page_id="p7", source_name="book.pdf", page_number=7, point_id="52004", raw_text="52004 dip 4.20")]
    state.network_edges = infer_network(state.results, max_distance=500, max_bearing_error=20, reciprocal_tolerance=20)
    hits = search_project(state, "52004")
    kinds = {h["type"] for h in hits}
    assert "result" in kinds
    assert "fieldbook" in kinds
    assert "network" in kinds


def test_v6_ui_ids_referenced_by_js_exist():
    root = Path(__file__).resolve().parents[1]
    html = (root / "fieldbook_sync/static/index.html").read_text(encoding="utf-8")
    js = (root / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
    html_ids = set(re.findall(r'id=["\']([^"\']+)', html))
    # Static literal $('#id') / $$('.selector') references. Ignore selectors containing CSS syntax.
    refs = set(re.findall(r"\$\('#([A-Za-z][A-Za-z0-9_-]*)'\)", js))
    dynamic_ids = {"acceptResultBtn","addPipeBtn","editNotes","editStatus","editDipStatus","nextResultBtn","pipeEditors","prevResultBtn","reviewImage","saveResultBtn","secondOpinionBtn","arcAddBtn","arcAprx","arcAssignCrs","arcBackupAprx","arcBrowseAprxBtn","arcBrowseFolderBtn","arcProject","arcBackupProject","arcBrowseProjectBtn","arcDoneBtn","arcIncludeNetwork","arcLoadMapsBtn","arcMapInfo","arcMapSelect","arcOpenProject","arcOutputFolder","arcProjectSubfolder","arcReplaceExisting","arcRevealBtn","arcShpOnlyBtn","updateFolderBtn","updateInstallBtn","updateSourceBtn","installSurveySyncUpdateBtn","alignEnabled","alignOffsetX","alignOffsetY","alignOriginX","alignOriginY","alignRotation","alignScale","alignmentSolveResult","applyCrsManager","controlPairs","crsClearBtn","crsDirect","crsImportFile","crsSearch","crsSearchBtn","crsSearchResults","solveAlignmentBtn","clearFeedbackEndpointBtn","feedbackEndpointUrlInput","gmConvertBtn","gmConvertFile","gmConvertStatus","gmCustomFields","gmExportType","gmExtension","gmPreset","modalDiagnosticBundleBtn","openFeedbackTrackerBtn","saveFeedbackEndpointBtn","openFeedbackLogBtn","feedbackLogFolderBtn","feedbackLogSettingsBtn","feedbackReceiptFolderBtn","feedbackReceiptLogBtn","fwAttachments","fwBack","fwDiagnostics","fwNext","fwSubmit","fwSyncShared","manualAddPipeBtn","manualDipStatus","manualNotes","manualPipeEditors","manualPointId","manualSaveBtn","manualStatus","attachReviewPhotoBtn","teachProfileBox","teachProfileBtn","teachProfileSelect","previewTrainBookBtn"}
    missing = sorted(refs - html_ids - dynamic_ids)
    assert not missing, f"JS references missing HTML ids: {missing}"


def test_v6_ui_contains_theme_project_batch_map_and_engine_features():
    root = Path(__file__).resolve().parents[1]
    html = (root / "fieldbook_sync/static/index.html").read_text(encoding="utf-8")
    js = (root / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
    combined = (html + js).lower()
    for token in ["system", "light", "dark", "map & network", "batch queue", "field book index", "hybrid local", "paddleocr-vl 1.6", "gemini"]:
        assert token in combined
    assert "Ctrl" in html and "commandPalette" in html
    assert "/api/undo" in js and "/api/redo" in js
    assert "/api/project/download" in js


def test_v6_raw_batch_pairing_groups_page_images_and_exact_job_ids():
    from fieldbook_sync.batch_pairing import pair_batch_files
    paired = pair_batch_files(
        ["12345_survey.csv", "67890_raw_points.txt"],
        ["12345_fieldbook.pdf", "67890_fieldbook_page1.jpg", "67890_fieldbook_page2.jpg"],
    )
    assert len(paired.pairs) == 2
    by_key = {p.key: p for p in paired.pairs}
    assert by_key["12345"].fieldbook_files == ("12345_fieldbook.pdf",)
    assert len(by_key["67890"].fieldbook_files) == 2
    assert not paired.unmatched_surveys
    assert not paired.unmatched_fieldbooks


def test_v6_raw_batch_pairing_refuses_ambiguous_guess():
    from fieldbook_sync.batch_pairing import pair_batch_files
    paired = pair_batch_files(
        ["Johnson Creek survey.csv"],
        ["Johnson Creek east fieldbook.pdf", "Johnson Creek west fieldbook.pdf"],
        min_score=0.40,
        min_margin=0.20,
    )
    assert not paired.pairs
    assert "Johnson Creek survey.csv" in paired.ambiguous_surveys
    assert len(paired.unmatched_fieldbooks) == 2


def test_v6_batch_hybrid_uses_real_hybrid_pipeline(monkeypatch, tmp_path):
    import fieldbook_sync.app as appmod
    from fieldbook_sync.models import BatchJob, FieldBookPage, OcrCandidate, PageEvidence, EvidenceBasis

    state = AppState(
        survey_points=[SurveyPoint(point_id="52004", northing=10, easting=20, elevation=100, code="MH", category="Manhole")],
        fieldbook_pages=[FieldBookPage(page_id="p1", source_name="book.pdf", page_number=1, image_path=str(tmp_path/"missing.jpg"), mime_type="image/jpeg")],
    )
    candidate = OcrCandidate(page_id="p1", source_name="book.pdf", page_number=1, point_id="52004", raw_text="52004 dip 4.2")
    evidence = PageEvidence(
        matched_point_id="52004", source_name="book.pdf", page_number=1, page_id="p1",
        dipped=DipStatus.YES, basis=EvidenceBasis.MEASUREMENT, point_id_confidence=.99, dipped_confidence=.99,
        pipes=[PipeMeasurement(dip=4.2)],
    )
    called = {"hybrid": 0}
    from fieldbook_sync import batch_workers
    monkeypatch.setattr(batch_workers, "list_ollama_models", lambda base_url: [appmod.runtime.ollama_model])
    def fake_hybrid(job, state_arg, work_pages):
        called["hybrid"] += 1
        return [evidence], [], [candidate]
    monkeypatch.setattr(batch_workers, "_batch_hybrid_local", fake_hybrid)
    monkeypatch.setattr(batch_workers, "_set_batch_progress", lambda *a, **k: None)
    job = BatchJob(job_id="j1", name="test", provider="hybrid")
    appmod._batch_analyze_state(job, state, tmp_path)
    assert called["hybrid"] == 1
    assert state.ocr_candidates and state.ocr_candidates[0].point_id == "52004"
    assert state.results[0].status == DipStatus.YES


def test_v6_fbs_association_helper_and_desktop_accept_project_argument(tmp_path):
    from file_association import _open_command
    root = tmp_path / "FieldBook Sync"
    root.mkdir()
    (root / "run_windows.bat").write_text("@echo off", encoding="utf-8")
    command = _open_command(root)
    assert "run_windows.bat" in command and '"%1"' in command
    (root / "FieldBookSync.exe").write_bytes(b"MZ")
    exe_command = _open_command(root)
    assert "FieldBookSync.exe" in exe_command and '"%1"' in exe_command
    source = (Path(__file__).resolve().parents[1] / "desktop.py").read_text(encoding="utf-8")
    launcher = (Path(__file__).resolve().parents[1] / "run_windows.bat").read_text(encoding="utf-8")
    assert "load_project_path_into_runtime" in source
    assert "sys.argv[1:]" in source
    assert "--register-fbs" in source and "--unregister-fbs" in source
    assert "bootstrap_windows.py %*" in launcher
    bootstrap = (Path(__file__).resolve().parents[1] / "bootstrap_windows.py").read_text(encoding="utf-8")
    assert "desktop.py" in bootstrap and "forwarded" in bootstrap


def test_v6_2_delimiter_detection_prefers_consistent_semicolon_and_tab():
    from fieldbook_sync.survey import detect_delimiter
    semicolon = "PointID;Northing;Easting;Elevation;Code\n1001;10;20;30;STM,MH\n1002;11;21;31;GI\n"
    tabbed = "PointID\tNorthing\tEasting\tElevation\tCode\n1001\t10\t20\t30\tMH\n1002\t11\t21\t31\tGI\n"
    assert detect_delimiter(semicolon)[0] == ";"
    assert detect_delimiter(tabbed)[0] == "\t"


def test_v6_2_parse_survey_file_streams_large_file(tmp_path):
    from fieldbook_sync.survey import parse_survey_file
    from fieldbook_sync.models import CodeProfile, CodeRule, MatchMode
    profile = CodeProfile(name="X", codes=[CodeRule(code="MH", category="Manhole", match=MatchMode.EXACT)])
    path = tmp_path / "large.tsv"
    with path.open("w", encoding="utf-8") as f:
        f.write("PointID\tNorthing\tEasting\tElevation\tCode\n")
        for i in range(5000):
            f.write(f"{10000+i}\t{i}.0\t{i+1}.0\t100.0\tMH\n")
    points, issues = parse_survey_file(path, path.name, profile)
    assert len(points) == 5000
    assert not [i for i in issues if "delimiter" in i.message.lower() and "uncertain" in i.message.lower()]


def test_v6_2_fieldbook_path_ingestion_avoids_byte_buffer(tmp_path):
    from fieldbook_sync.fieldbook import ingest_fieldbook_path
    source = tmp_path / "book.jpg"
    Image.new("RGB", (120, 160), "white").save(source)
    pages = ingest_fieldbook_path(source, "book.jpg", tmp_path / "pages")
    assert len(pages) == 1
    assert Path(pages[0].image_path).exists()


def test_v6_2_export_contains_dxf_and_direct_dxf_geometry(tmp_path):
    from fieldbook_sync.exporter import direct_export_text
    a = _result("A", 1000, 2000, 90)
    b = _result("B", 1100, 2000, 270)
    state = AppState(project_name="DXF Test", results=[a, b])
    state.network_edges = infer_network(state.results, max_distance=500, max_bearing_error=20, reciprocal_tolerance=20)
    zpath = create_export_zip(state, tmp_path)
    with zipfile.ZipFile(zpath) as zf:
        assert "fieldbook_sync.dxf" in zf.namelist()
        dxf = zf.read("fieldbook_sync.dxf").decode("utf-8")
    assert "POINT_LABELS" in dxf and "NET_STRONG" in dxf
    filename, media, direct = direct_export_text(state, "dxf")
    assert filename.endswith(".dxf") and "dxf" in media and direct.endswith("EOF\n")


def test_v6_2_large_upload_routes_only_use_bounded_reads():
    root = Path(__file__).resolve().parents[1]
    src = (root / "fieldbook_sync/app.py").read_text(encoding="utf-8")
    # No endpoint should call UploadFile.read() without a bounded chunk size.
    assert "await upload.read()" not in src
    assert "await file.read()" not in src
    assert "await u.read()" not in src
    assert "await upload.read(UPLOAD_CHUNK_BYTES)" in src


def test_v6_2_ui_has_virtual_results_and_confidence_heatmap():
    root = Path(__file__).resolve().parents[1]
    html = (root / "fieldbook_sync/static/index.html").read_text(encoding="utf-8")
    js = (root / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
    css = (root / "fieldbook_sync/static/styles.css").read_text(encoding="utf-8")
    assert "resultsTableWrap" in html and "virtual-table-wrap" in html
    assert "renderResultWindow" in js and "resultVirtual" in js
    assert 'value="heat"' in html and "heat-spot" in js and "heat-spot" in css


def test_v6_2_logging_is_daily_rotating_and_background_failures_log_tracebacks():
    root = Path(__file__).resolve().parents[1]
    logging_src = (root / "fieldbook_sync/logging_config.py").read_text(encoding="utf-8")
    app_src = (root / "fieldbook_sync/app.py").read_text(encoding="utf-8")
    assert "TimedRotatingFileHandler" in logging_src and 'when="midnight"' in logging_src
    batch_src = (root / "fieldbook_sync/batch_workers.py").read_text(encoding="utf-8")
    assert "logger.exception(" in batch_src and "Batch job" in batch_src
    assert "logger.exception(\"Analysis failed" in app_src
    assert "/api/diagnostics/log" in app_src


def test_v63_structures_export_separates_primary_status_and_qa():
    from fieldbook_sync.exporter import _structures_csv
    r = _result("8001", 100, 200, None)
    r.status = DipStatus.YES
    r.dip_status = DipStatus.REVIEW
    r.qa_needs_review = True
    text = _structures_csv([r])
    assert "Status,DipDetailStatus,QAReview" in text
    assert "8001" in text and ",YES,REVIEW,YES," in text


def test_v6_5_direct_shapefile_export_to_selected_folder(tmp_path):
    from fieldbook_sync.exporter import export_shapefiles_to_folder
    a = _result("A", 1000, 2000, 90)
    b = _result("B", 1100, 2000, 270)
    state = AppState(project_name="Selected Folder", results=[a, b])
    state.network_edges = infer_network(state.results, max_distance=500, max_bearing_error=20, reciprocal_tolerance=20)
    out = tmp_path / "chosen"
    written = export_shapefiles_to_folder(state, out)
    assert Path(written["structures"]).exists()
    assert Path(written["network"]).exists()
    for stem in ("structures", "network_connections"):
        assert (out / f"{stem}.shp").exists()
        assert (out / f"{stem}.shx").exists()
        assert (out / f"{stem}.dbf").exists()
        assert (out / f"{stem}.cpg").exists()
    assert not (out / "structures.prj").exists()


def test_v6_5_arcgis_export_backs_up_project_and_calls_bridge(monkeypatch, tmp_path):
    import fieldbook_sync.arcgis_integration as ag
    state = AppState(project_name="Johnson Creek", results=[_result("52004", 100, 200, 90)])
    out = tmp_path / "exports"
    aprx = tmp_path / "Survey.aprx"
    aprx.write_bytes(b"fake-aprx")
    calls = []
    def fake_run(app_root, args, timeout=120):
        calls.append(args)
        return {"ok": True, "map": {"name": "Landbase", "spatial_reference": "State Plane", "wkid": 9999}, "added": []}
    monkeypatch.setattr(ag, "_run_propy", fake_run)
    result = ag.export_to_arcgis(
        state, tmp_path, str(out), aprx_path=str(aprx), map_name="Landbase",
        include_network=False, assign_map_crs=True, backup_aprx=True,
    )
    assert result["added_to_arcgis"] is True
    assert Path(result["shapefiles"]["structures"]).exists()
    assert result["shapefiles"]["network"] is None
    assert Path(result["backup_project"]).exists()
    assert calls and calls[0][0] == "add-layers"
    assert "--assign-map-crs" in calls[0]
    assert "--network" not in calls[0]


def test_v6_5_arcgis_map_listing_validates_aprx_and_uses_bridge(monkeypatch, tmp_path):
    import fieldbook_sync.arcgis_integration as ag
    aprx = tmp_path / "My Project.aprx"
    aprx.write_bytes(b"fake")
    monkeypatch.setattr(ag, "_run_propy", lambda app_root, args, timeout=120: {"ok": True, "maps": [{"name": "Map", "spatial_reference": "NAD83", "wkid": 1234}]})
    payload = ag.list_project_maps(tmp_path, str(aprx))
    assert payload["maps"][0]["name"] == "Map"
    try:
        ag.list_project_maps(tmp_path, str(tmp_path / "missing.aprx"))
        assert False, "Expected missing APRX validation"
    except ValueError:
        pass


def test_v6_5_ui_and_desktop_include_native_arcgis_export_workflow():
    root = Path(__file__).resolve().parents[1]
    html = (root / "fieldbook_sync/static/index.html").read_text(encoding="utf-8")
    js = (root / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
    desktop = (root / "desktop.py").read_text(encoding="utf-8")
    app_src = (root / "fieldbook_sync/app.py").read_text(encoding="utf-8")
    assert 'id="arcgisExportBtn"' in html
    assert "/api/arcgis/export" in js and "/api/arcgis/maps" in js
    assert "choose_folder" in desktop and "choose_arcgis_project" in desktop and "choose_aprx" in desktop and "window.expose(" in desktop and "js_api=bridge" not in desktop
    assert "/api/arcgis/status" in app_src and "/api/arcgis/export" in app_src


def test_v6_5_dashboard_drag_drop_targets_and_global_overlay_exist():
    root = Path(__file__).resolve().parents[1]
    html = (root / "fieldbook_sync/static/index.html").read_text(encoding="utf-8")
    assert 'id="surveyDropzone"' in html
    assert 'id="fieldbookDropzone"' in html
    assert 'id="globalDropOverlay"' in html
    assert 'id="globalDropTitle"' in html
    assert '.tsv' in html


def test_v6_5_drag_drop_classifies_supported_files_and_prevents_navigation():
    root = Path(__file__).resolve().parents[1]
    js = (root / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
    assert "SURVEY_EXTS=new Set(['.csv','.txt','.tsv'])" in js
    assert "FIELD_EXTS=new Set(['.pdf','.png','.jpg','.jpeg','.webp'])" in js
    assert "else if(x==='.fbs')out.project.push(f)" in js
    assert "document.addEventListener('dragover'" in js
    assert "e.preventDefault()" in js
    assert "handleDashboardDrop" in js
    assert "await importFileArray(g.survey" in js
    assert "await importFileArray(g.fieldbook" in js


def test_v6_5_batch_drag_drop_accumulates_files_until_pairing():
    root = Path(__file__).resolve().parents[1]
    html = (root / "fieldbook_sync/static/index.html").read_text(encoding="utf-8")
    js = (root / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
    assert 'id="batchSurveyDropzone"' in html
    assert 'id="batchFieldbookDropzone"' in html
    assert "batchRawSurveys=mergeFileLists(batchRawSurveys,g.survey)" in js
    assert "batchRawFieldbooks=mergeFileLists(batchRawFieldbooks,g.fieldbook)" in js
    assert "queueDroppedProjects" in js


def test_v7_arcmap_mxd_listing_dispatches_to_desktop_bridge(monkeypatch, tmp_path):
    import fieldbook_sync.arcgis_integration as ag
    mxd = tmp_path / "Legacy Map.mxd"
    mxd.write_bytes(b"fake-mxd")
    calls = []
    def fake_run(app_root, args, timeout=120):
        calls.append(args)
        return {"ok": True, "project_type": "arcmap", "maps": [{"name": "Layers", "spatial_reference": "NAD83", "wkid": 4269}]}
    monkeypatch.setattr(ag, "_run_arcmap_python", fake_run)
    payload = ag.list_project_maps(tmp_path, str(mxd))
    assert payload["project_type"] == "arcmap"
    assert payload["maps"][0]["name"] == "Layers"
    assert calls == [["list-maps", str(mxd)]]


def test_v7_arcmap_export_backs_up_mxd_and_calls_desktop_bridge(monkeypatch, tmp_path):
    import fieldbook_sync.arcgis_integration as ag
    state = AppState(project_name="Legacy Job", results=[_result("52004", 100, 200, 90)])
    out = tmp_path / "exports"
    mxd = tmp_path / "Legacy.mxd"
    mxd.write_bytes(b"fake-mxd")
    calls = []
    def fake_run(app_root, args, timeout=120):
        calls.append(args)
        return {"ok": True, "project_type": "arcmap", "map": {"name": "Layers", "spatial_reference": "State Plane", "wkid": 2278}, "added": []}
    monkeypatch.setattr(ag, "_run_arcmap_python", fake_run)
    monkeypatch.setattr(ag, "find_arcgis_desktop", lambda: {"installed": True, "python": "python.exe", "exe": None})
    result = ag.export_to_arcgis(
        state, tmp_path, str(out), project_path=str(mxd), map_name="Layers",
        include_network=False, assign_map_crs=True, backup_project=True,
    )
    assert result["added_to_arcgis"] is True
    assert result["project_type"] == "arcmap"
    assert Path(result["backup_project"]).suffix.lower() == ".mxd"
    assert Path(result["backup_project"]).exists()
    assert calls and calls[0][0] == "add-layers"
    assert "--mxd" in calls[0]
    assert "--assign-map-crs" in calls[0]
    assert "--aprx" not in calls[0]


def test_v7_arcgis_project_extension_dispatch_validation(tmp_path):
    import fieldbook_sync.arcgis_integration as ag
    bad = tmp_path / "map.qgz"
    bad.write_bytes(b"fake")
    try:
        ag.list_project_maps(tmp_path, str(bad))
        assert False, "Expected unsupported project extension"
    except ValueError as exc:
        assert ".aprx" in str(exc) and ".mxd" in str(exc)


def test_v7_arcmap_bridge_is_legacy_python_compatible_source():
    root = Path(__file__).resolve().parents[1]
    src = (root / "arcgis_desktop_bridge.py").read_text(encoding="utf-8")
    assert "arcpy.mapping.MapDocument" in src
    assert "arcpy.mapping.ListDataFrames" in src
    assert "arcpy.mapping.AddLayer" in src
    assert "from pathlib" not in src
    assert "def emit(payload: " not in src
    assert "f\"" not in src and "f'" not in src
    compile(src, "arcgis_desktop_bridge.py", "exec")


def test_v7_ui_supports_aprx_and_mxd_projects():
    root = Path(__file__).resolve().parents[1]
    html = (root / "fieldbook_sync/static/index.html").read_text(encoding="utf-8")
    js = (root / "fieldbook_sync/static/app.js").read_text(encoding="utf-8")
    desktop = (root / "desktop.py").read_text(encoding="utf-8")
    assert "ArcMap 10.x" in html or "ArcMap 10.x" in js
    assert ".aprx" in js and ".mxd" in js
    assert "project_path" in js
    assert "choose_arcgis_project" in desktop
    assert "ArcMap Document (*.mxd)" in desktop


def test_v7_0_2_paddle_quick_status_does_not_spawn_import_probe(tmp_path, monkeypatch):
    import fieldbook_sync.ocr_local as ocr_local

    py = ocr_local.paddle_python_path(tmp_path)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("stub", encoding="utf-8")

    def should_not_run(*args, **kwargs):
        raise AssertionError("quick Paddle status must not spawn the heavy import probe")

    monkeypatch.setattr(ocr_local.subprocess, "run", should_not_run)
    status = ocr_local.paddle_status(tmp_path, verify_import=False)
    assert status.installed is True
    assert status.verified is False
    assert "environment found" in status.message.lower()


def test_v7_0_2_paddle_successful_probe_is_cached(tmp_path, monkeypatch):
    import subprocess
    import fieldbook_sync.ocr_local as ocr_local

    py = ocr_local.paddle_python_path(tmp_path)
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(ocr_local, "_PADDLE_STATUS_CACHE", None)
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(ocr_local.subprocess, "run", fake_run)
    first = ocr_local.paddle_status(tmp_path, verify_import=True, force=True)
    second = ocr_local.paddle_status(tmp_path, verify_import=True, force=False)
    assert first.installed and first.verified
    assert second.installed and second.verified
    assert len(calls) == 1
    assert calls[0][1].get("stdin") is subprocess.DEVNULL


def test_v7_0_2_startup_does_not_wait_for_full_results_payload():
    from pathlib import Path
    js = Path(__file__).parents[1] / "fieldbook_sync" / "static" / "app.js"
    text = js.read_text(encoding="utf-8")
    init = text[text.index("async function init()") : text.index("init();", text.index("async function init()"))]
    assert "await refreshResults()" not in init
    assert "hideStartupSplash()" in init
    assert "watchdog" in init


def test_v7_0_2_paddle_button_requests_explicit_verified_probe():
    from pathlib import Path
    js = Path(__file__).parents[1] / "fieldbook_sync" / "static" / "app.js"
    text = js.read_text(encoding="utf-8")
    assert "/api/paddle/status?verify=true&refresh=true" in text
    assert "/api/paddle/status?verify=false" in text
