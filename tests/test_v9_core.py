from pathlib import Path
import json
import tempfile

from surveysync.project import SurveyProject
from surveysync.cogo import inverse, bearing_distance
from surveysync.reports import available_ranges
from surveysync.control import import_observations, solve
from surveysync.qa import run_project_qa


def test_project_create_and_open(tmp_path):
    p=SurveyProject.create(tmp_path,"Test Project",crs="EPSG:2278")
    assert p.paths.manifest.exists()
    assert p.paths.fieldbook_root.exists()
    assert p.manifest["name"]=="Test Project"
    assert SurveyProject(p.paths.root).manifest["project_id"]==p.manifest["project_id"]


def test_source_immutable_registry(tmp_path):
    p=SurveyProject.create(tmp_path,"P")
    source=tmp_path/"obs.csv";source.write_text("x\n1\n")
    info=p.import_source(source,"ControlSync")
    stored=Path(info["stored_path"])
    assert stored.exists()
    assert p.sources()[0]["sha256"]==info["sha256"]


def test_cogo_inverse_and_forward():
    r=inverse(1000,1000,1100,1200)
    assert round(r["distance"],9)==round((100**2+200**2)**0.5,9)
    f=bearing_distance(1000,1000,r["azimuth_deg"],r["distance"])
    assert abs(f["northing"]-1100)<1e-9 and abs(f["easting"]-1200)<1e-9


def test_ranges():
    assert available_ranges([1,2,5,8],1,10)==[
        {"start":3,"end":4,"count":2},{"start":6,"end":7,"count":2},{"start":9,"end":10,"count":2}
    ]


def test_control_average_and_qc(tmp_path):
    p=SurveyProject.create(tmp_path,"P")
    import_observations(p.db,[
        {"control_id":"CP1","northing":100.00,"easting":200.00,"elevation":10.0,"h_sigma":.02,"v_sigma":.03},
        {"control_id":"CP1","northing":100.04,"easting":200.00,"elevation":10.04,"h_sigma":.02,"v_sigma":.03},
        {"control_id":"CP1","northing":100.02,"easting":200.02,"elevation":10.02,"h_sigma":.02,"v_sigma":.03},
    ])
    r=solve(p.db,"CP1","arithmetic",.05,.05)
    assert r["count"]==3 and r["pass"] is True
    assert abs(r["northing"]-100.02)<1e-10


def test_ron_profile_is_enabled_from_authoritative_workbook(tmp_path):
    p=SurveyProject.create(tmp_path,"P")
    import_observations(p.db,[
        {"control_id":"CP1","northing":1,"easting":2,"elevation":3},
        {"control_id":"CP1","northing":2,"easting":3,"elevation":4},
        {"control_id":"CP1","northing":3,"easting":4,"elevation":5},
    ])
    r=solve(p.db,"CP1","ron_spreadsheet")
    assert r["formula_status"]=="VALIDATED_RON_WORKBOOK"
    assert r["northing"]==2 and r["easting"]==3 and r["elevation"]==4


def test_project_qa(tmp_path):
    p=SurveyProject.create(tmp_path,"P",crs="EPSG:2278")
    assert run_project_qa(p)["status"]=="PASS"

def test_environment_switch_clears_remote_resources(tmp_path):
    from surveysync.config import ConfigStore, AppConfig
    s=ConfigStore(tmp_path/'cfg'); c=AppConfig(environment='beta',resource_environment='beta',update_manifest_url='https://example.com/beta.json',feedback_endpoint='https://example.com/fb')
    s.save(c); c=s.load(); c.environment='production'; s.save(c); c=s.load()
    from surveysync.config import DEFAULT_UPDATE_MANIFEST_URL
    assert c.resource_environment=='production' and c.update_manifest_url==DEFAULT_UPDATE_MANIFEST_URL and c.feedback_endpoint==''


def test_crs_inspect_and_transform():
    from surveysync.crs import inspect_crs, transform_xy
    assert inspect_crs('EPSG:4326')['valid'] is True
    r=transform_xy(-95.0,29.0,'EPSG:4326','EPSG:3857')
    assert abs(r['x']) > 1_000_000 and abs(r['y']) > 1_000_000


def test_update_versions_are_normalized():
    from surveysync.updater import version_tuple
    assert version_tuple('9.1') == version_tuple('9.1.0') == version_tuple('9.1.0.0')
    assert version_tuple('9.1.3') > version_tuple('9.1')


def test_ranges_require_bounds_when_no_ids():
    import pytest
    with pytest.raises(ValueError, match='both a start and end'):
        available_ranges([], start=100, end=None)
    assert available_ranges([], start=100, end=105) == [{"start":100,"end":105,"count":6}]


def test_ranges_do_not_scan_large_empty_spaces():
    # Gap-walk result should depend on occupied IDs, not the width of the numeric domain.
    assert available_ranges([1, 10_000_000_000], 1, 10_000_000_000, min_run=1) == [
        {"start":2,"end":9_999_999_999,"count":9_999_999_998}
    ]


def test_control_alias_priority_is_deterministic(tmp_path):
    from surveysync.control import parse_control_csv
    p=tmp_path/'control.csv'
    p.write_text('point_id,point,northing,y,easting,x,height\nPRIMARY,SECOND,100,999,200,888,10\n', encoding='utf-8')
    rows=parse_control_csv(p)
    assert rows[0]['control_id']=='PRIMARY'
    assert rows[0]['northing']==100
    assert rows[0]['easting']==200
    assert rows[0]['elevation']==10


def test_fieldbook_height_header_and_shared_range_algorithm():
    from fieldbook_sync.survey import _find_header_mapping, available_point_ranges
    mapping=_find_header_mapping(['PointID','Northing','Easting','Height','Code'])
    assert mapping is not None and mapping['elevation']==3
    assert available_point_ranges([1000,1001,1005]) == [(1002,1004),(1006,None)]


def test_export_provenance_uses_current_surveysync_version():
    from fieldbook_sync.exporter import EXPORT_PROVENANCE
    assert 'SurveySync v9.3.0' in EXPORT_PROVENANCE
    assert 'v8.0.0' not in EXPORT_PROVENANCE


def test_crew_range_recommendations_rank_safe_and_useful_blocks():
    from surveysync.reports import crew_range_recommendations
    used=(list(range(4000,4435)) + list(range(5000,6091)) +
          list(range(6215,10665)) + list(range(11000,11501)))
    r=crew_range_recommendations(used,min_capacity=100)
    items=r['recommendations']
    assert [x['range'] for x in items] == ['4435 - 4999','6091 - 6214','10665 - 10999','12000 and above']
    assert items[-1]['capacity_label']=='Unlimited'
    assert [x['capacity'] for x in items[:3]] == [565,124,335]
    occupied=set(used)
    for item in items:
        if item['end'] is not None:
            assert not any(v in occupied for v in range(item['start'],item['end']+1))
    by_capacity=crew_range_recommendations(used,min_capacity=100,sort_order='capacity')['recommendations']
    assert [x['range'] for x in by_capacity[:4]] == ['12000 and above','4435 - 4999','10665 - 10999','6091 - 6214']
