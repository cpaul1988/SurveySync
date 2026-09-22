from pathlib import Path

import pytest
from fastapi import HTTPException

from fieldbook_sync.models import SurveyPoint, ResultRecord, DipStatus, PipeMeasurement, ReviewState, AnalysisJob
from fieldbook_sync.rod_height_qc import detect_rod_height_busts
import fieldbook_sync.app as appmod


def test_rod_height_detector_flags_round_increment_local_bust():
    pts = [
        SurveyPoint(point_id='100', easting=0, northing=0, elevation=100.00, code='RD'),
        SurveyPoint(point_id='101', easting=5, northing=0, elevation=100.02, code='RD'),
        SurveyPoint(point_id='102', easting=0, northing=5, elevation=99.98, code='RD'),
        SurveyPoint(point_id='103', easting=4, northing=4, elevation=101.00, code='RD'),
    ]
    items = detect_rod_height_busts(pts, search_radius=15, max_slope_percent=8, increment_tolerance=.08, min_neighbors=2)
    hit = next(x for x in items if x['point_id'] == '103')
    assert hit['matched_increment'] == 1.0
    assert hit['vertical_delta'] == pytest.approx(1.0, abs=.03)
    assert hit['confidence'] >= 50


def test_rod_height_detector_does_not_flag_gentle_nonround_grade():
    pts = [
        SurveyPoint(point_id=str(i), easting=i*5.0, northing=0, elevation=100+i*.10, code='RD')
        for i in range(5)
    ]
    assert detect_rod_height_busts(pts, search_radius=15, max_slope_percent=8, increment_tolerance=.08, min_neighbors=2) == []


def test_manual_review_rejects_measured_dip_with_not_found_detail(tmp_path, monkeypatch):
    # Reuse the app runtime but replace state narrowly and restore through monkeypatch.
    old_state = appmod.runtime.storage.state
    try:
        state = old_state.model_copy(deep=True)
        state.results = [ResultRecord(point_id='1', code='MH', status=DipStatus.YES, dip_status=DipStatus.NOT_FOUND)]
        appmod.runtime.storage.state = state
        appmod.runtime.job = AnalysisJob(running=False)
        payload = appmod.ResultEditIn(
            status=DipStatus.YES, dip_status=DipStatus.NOT_FOUND, review_state=ReviewState.EDITED,
            pipes=[PipeMeasurement(dip=3.25)]
        )
        with pytest.raises(HTTPException) as exc:
            appmod.api_edit_result('1', payload)
        assert exc.value.status_code == 400
        assert 'Dip detail cannot be NOT FOUND' in str(exc.value.detail)
    finally:
        appmod.runtime.storage.state = old_state


def test_pause_endpoints_and_ui_exist():
    root=Path(__file__).resolve().parents[1]
    app=(root/'fieldbook_sync/app.py').read_text(encoding='utf-8')
    js=(root/'fieldbook_sync/static/app.js').read_text(encoding='utf-8')
    html=(root/'fieldbook_sync/static/index.html').read_text(encoding='utf-8')
    assert '@app.post("/api/pause-analysis")' in app
    assert '@app.post("/api/resume-paused-analysis")' in app
    assert 'id="pauseBtn"' in html
    assert '/api/resume-paused-analysis' in js
    assert '_assert_analysis_idle_or_paused_locked()' in app


def test_launcher_reverifies_pending_installer_checksum():
    root=Path(__file__).resolve().parents[1]
    go=(root/'installer/app_launcher.go').read_text(encoding='utf-8')
    assert 'sha256.Sum256(installerBytes)' in go
    assert 'pending installer SHA-256 changed after verification' in go
    assert 'pending installer size changed after verification' in go
