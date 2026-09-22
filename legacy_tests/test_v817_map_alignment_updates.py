from pathlib import Path

from fieldbook_sync.map_gis import (
    apply_similarity_alignment,
    invert_similarity_alignment,
    solve_similarity_alignment,
    crs_details,
    search_coordinate_systems,
)
from fieldbook_sync.models import AppState

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'fieldbook_sync/static/app.js').read_text(encoding='utf-8')
HTML = (ROOT / 'fieldbook_sync/static/index.html').read_text(encoding='utf-8')
APP = (ROOT / 'fieldbook_sync/app.py').read_text(encoding='utf-8')


def test_similarity_alignment_round_trip():
    args = dict(scale_factor=0.99987342, rotation_deg=1.25, offset_x=125.5, offset_y=-88.25, origin_x=5000, origin_y=10000)
    gx, gy = apply_similarity_alignment(6123.456, 9876.543, **args)
    x, y = invert_similarity_alignment(gx, gy, **args)
    assert abs(x - 6123.456) < 1e-8
    assert abs(y - 9876.543) < 1e-8


def test_control_point_similarity_solver_recovers_known_transform():
    args = dict(scale_factor=1.00012, rotation_deg=-0.75, offset_x=250.0, offset_y=500.0, origin_x=0.0, origin_y=0.0)
    pairs=[]
    for name,x,y in [('A',1000,1000),('B',3000,1000),('C',1500,3500)]:
        gx,gy=apply_similarity_alignment(x,y,**args)
        pairs.append({'name':name,'local_x':x,'local_y':y,'grid_x':gx,'grid_y':gy})
    sol=solve_similarity_alignment(pairs)
    assert abs(sol['scale_factor']-args['scale_factor']) < 1e-10
    assert abs(sol['rotation_deg']-args['rotation_deg']) < 1e-10
    assert abs(sol['offset_x']-args['offset_x']) < 1e-8
    assert abs(sol['offset_y']-args['offset_y']) < 1e-8
    assert sol['residual_rms'] < 1e-8


def test_crs_catalog_includes_missouri_east():
    d=crs_details('ESRI:102696')
    assert 'Missouri East' in d['name'].replace('_',' ')
    hits=search_coordinate_systems('Missouri East', limit=15)
    assert any('Missouri East' in h['name'] for h in hits)


def test_map_state_has_alignment_defaults():
    s=AppState()
    assert s.map_alignment.enabled is False
    assert s.map_alignment.scale_factor == 1.0
    assert s.custom_coordinate_systems == []


def test_ui_has_box_zoom_cursor_zoom_and_coordinate_manager():
    assert 'mapZoomBoxIn' in HTML and 'mapZoomBoxOut' in HTML
    assert "zoomMapAt(e.deltaY<0?1:-1,p.sx,p.sy,true)" in JS
    assert "zoomToScreenRect" in JS
    assert 'Coordinate System & Alignment Manager' in JS
    assert 'CONTROL POINT CALIBRATION' in JS
    assert '/api/map/crs/search' in APP
    assert '/api/map/crs/import' in APP
    assert '/api/map/alignment/solve' in APP


def test_update_source_can_be_configured_and_uses_stable_github_channel():
    assert '@app.get("/api/update/source")' in APP
    assert '@app.post("/api/update/source")' in APP
    assert 'raw.githubusercontent.com/cpaul1988/FieldBookSync/main/update.json' in APP
    assert 'github.com/cpaul1988/FieldBookSync/releases' in APP
    assert 'Update manifest URL' in JS
    assert "sourceLabel=(u.provider||'github')==='github'?'GitHub':'Custom HTTPS'" in JS
