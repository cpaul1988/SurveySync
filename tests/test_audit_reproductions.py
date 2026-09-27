"""Independent 9.4.0 audit assertions. Failures are evidence, not fixes.

These tests never contact feedback services, mutate a release, or install an update.
They use temporary projects. Expected results are independent numeric references
or the UI/API contracts printed by the released code.
"""
from pathlib import Path
import json
import math
import random
import re
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    from fieldbook_sync import app as f
    from surveysync import router as r
    monkeypatch.setenv('SURVEYSYNC_CONFIG_ROOT', str(tmp_path/'config'))
    monkeypatch.setattr(r, 'config_store', r.ConfigStore(tmp_path/'config'))
    monkeypatch.setattr(r, 'current_project', None)
    monkeypatch.setattr(f, 'runtime', f.Runtime(tmp_path/'field'))
    client=TestClient(f.app, raise_server_exceptions=False)
    created=client.post('/api/v9/project/create',json={
        'parent_folder':str(tmp_path/'projects'),'name':'Audit', 'crs':'EPSG:2278',
        'horizontal_units':'us_survey_feet','vertical_units':'us_survey_feet'})
    assert created.status_code==200, created.text
    yield client,r,f
    client.close()
    f.runtime.job_store.close()


def test_A01_repeat_landxml_import_is_idempotent(workspace,tmp_path):
    client,r,_=workspace
    file=tmp_path/'points.xml'
    from surveysync.landxml_io import export_landxml
    export_landxml(output_path=file,points=[{'point_id':'101','northing':1000.,'easting':2000.,'elevation':10.}],parcels=[],alignments=[])
    original=file.read_bytes()
    first=client.post('/api/v9/landxml/import',json={'file_path':str(file)})
    second=client.post('/api/v9/landxml/import',json={'file_path':str(file)})
    assert first.status_code==200, first.text
    assert file.read_bytes()==original
    assert second.status_code==200, f'reimport failed: {second.status_code} {second.text}'
    assert second.json()['source']['source_id']==first.json()['source']['source_id']


def test_A02_level_PointID_header_advertised_by_error_is_accepted(tmp_path):
    from surveysync.leveling import parse_level_csv
    p=tmp_path/'level.csv'; p.write_text('PointID,BS,FS\nTP1,1.5,1.0\n')
    assert parse_level_csv(p)[0]['point_id']=='TP1'


def test_A03_field_to_finish_PointID_header_is_accepted(tmp_path):
    from surveysync.field_to_finish import parse_coded_points
    p=tmp_path/'points.csv';p.write_text('PointID,Northing,Easting,Elevation,Code\n1,1000,2000,20,500-BS\n2,1010,2000,20,500-ES\n')
    assert len(parse_coded_points(p))==2


def test_A04_separate_fieldbook_BS_FS_rows_have_point_elevations():
    from surveysync.leveling import solve_level_run
    result=solve_level_run([
        {'point_id':'BM_START','backsight':1.5},
        {'point_id':'TP1','foresight':1.,'backsight':2.},
        {'point_id':'BM_END','foresight':1.2},
    ],start_elevation=100.,known_end_elevation=101.3,adjustment_method='none',row_layout='station_rows')
    assert result['results'][-1]['raw_elevation']==pytest.approx(101.3)
    actual=[row['raw_elevation'] for row in result['results']]
    assert actual==pytest.approx([100.,100.5,101.3]), f'Point elevations expected [100,100.5,101.3], got {actual}'


@pytest.mark.parametrize('bad',['nan','inf','-inf'])
def test_A05_level_nonfinite_readings_are_rejected(tmp_path,bad):
    from surveysync.leveling import parse_level_csv
    p=tmp_path/'bad.csv';p.write_text(f'Point,BS,FS\nTP1,{bad},1.0\n')
    with pytest.raises(ValueError):parse_level_csv(p)


@pytest.mark.parametrize('bad',['nan','inf'])
def test_A05_traverse_nonfinite_distance_is_rejected(tmp_path,bad):
    from surveysync.traverse import parse_traverse_csv
    p=tmp_path/'bad.csv';p.write_text(f'From,To,Azimuth,Distance\n1,2,0,{bad}\n')
    with pytest.raises(ValueError):parse_traverse_csv(p)


def test_A06_exact_closing_traverse_is_json_serializable(workspace,tmp_path):
    client,_,_=workspace
    p=tmp_path/'traverse.csv';p.write_text('From,To,Azimuth,Distance\n1,2,0,100\n')
    imported=client.post('/api/v9/traverse/import',json={
        'file_path':str(p),'start_n':0.,'start_e':0.,'end_n':100.,'end_e':0.,'adjustment_method':'none'})
    assert imported.status_code==200, imported.text
    solved=client.post('/api/v9/traverse/solve',json={'run_id':imported.json()['run_id'],'adjustment_method':'none'})
    assert solved.status_code==200, f'valid exactly-closing traverse: {solved.status_code} {solved.text}'
    assert solved.json()['linear_closure']==0


def test_A07_utility_grade_normalizes_vertical_and_horizontal_units(workspace):
    from fieldbook_sync.models import ResultRecord,PipeMeasurement,NetworkEdge
    client,r,f=workspace
    r.current_project.manifest['vertical_units']='meters'
    f.runtime.storage.state.results=[
        ResultRecord(point_id='1',code='351',northing=0,easting=0,elevation=12,pipes=[PipeMeasurement(invert_elevation=10.)]),
        ResultRecord(point_id='2',code='351',northing=100,easting=0,elevation=11,pipes=[PipeMeasurement(invert_elevation=9.)])]
    f.runtime.storage.state.network_edges=[NetworkEdge(from_point='1',to_point='2',from_pipe_index=1,to_pipe_index=1,distance=100)]
    result=client.post('/api/v9/utility/analyze',json={})
    assert result.status_code==200,result.text
    expected=100.*1./(100.*(1200./3937.))
    assert result.json()['grades'][0]['grade_percent']==pytest.approx(expected),result.json()


@pytest.mark.parametrize('cmd',['project-data','data-inspector','support-center'])
def test_A08_main_shell_command_uses_valid_dom_collection(cmd):
    """Execute the unchanged production function in Node with DOM contract stubs."""
    js=(Path(__file__).parents[1]/'surveysync/static/app.js').read_text()
    line=next(line for line in js.splitlines() if line.startswith('function runCommand(cmd)'))
    stub="""let activeModule='Home';let switched='';function closeMenus(){};
    function switchView(v){switched=v};function $(s){return {dataset:{module:'Home'},classList:{toggle(){}},focus(){},click(){}}};
    function $$(s){return [$(s)]};const document={}; const window={};\n"""
    run=subprocess.run(['node','-e',stub+line+f'\nrunCommand({json.dumps(cmd)});console.log(switched);'],text=True,capture_output=True)
    assert run.returncode==0,run.stderr
    assert run.stdout.strip()


def test_A09_exit_menu_calls_exposed_exit_app():
    js=(Path(__file__).parents[1]/'surveysync/static/app.js').read_text()
    line=next(line for line in js.splitlines() if line.startswith('function runCommand(cmd)'))
    stub="""let activeModule='Home';function closeMenus(){};let called=false;
    const window={pywebview:{api:{exit_app:()=>{called=true}}},close:()=>{}};
    const pywebview=window.pywebview;\n"""
    run=subprocess.run(['node','-e',stub+line+"\nrunCommand('exit-app');if(!called)throw Error('Native exit_app was not called');"],text=True,capture_output=True)
    assert run.returncode==0,run.stderr


def test_A10_polygon_small_parcel_at_state_plane_coordinates():
    from surveysync.cogo_extended import polygon_area_perimeter
    n,e=10_000_000.,3_000_000.
    width,height=.1,.2
    points=[{'northing':n+dn,'easting':e+de} for dn,de in [(0,0),(0,width),(height,width),(height,0)]]
    result=polygon_area_perimeter(points=points)
    # Account for binary representation of coordinates, not cancellation of products.
    area=(points[1]['easting']-points[0]['easting'])*(points[2]['northing']-points[1]['northing'])
    assert result['area']==pytest.approx(area,rel=1e-6),result
    assert result['centroid_northing']==pytest.approx(n+height/2,abs=1e-5),result
    assert result['centroid_easting']==pytest.approx(e+width/2,abs=1e-5),result


def test_P01_random_point_ranges_never_allocate_used_ids():
    from surveysync.reports import available_ranges
    rng=random.Random(940)
    for _ in range(500):
        used=rng.sample(range(1,1001),rng.randint(1,150))
        ranges=available_ranges(used,start=1,end=1000,min_run=1)
        emitted={i for r in ranges for i in range(r['start'],r['end']+1)}
        assert not (emitted & set(used))
        assert emitted|set(used)==set(range(1,1001))


def test_P02_random_forward_inverse_roundtrip():
    from surveysync.cogo import bearing_distance,inverse
    rng=random.Random(941)
    for _ in range(1000):
        n,e=rng.uniform(1e6,1e7),rng.uniform(1e6,3e6)
        az,d=rng.uniform(0,360),rng.uniform(.1,10000)
        p=bearing_distance(n,e,az,d);inv=inverse(n,e,p['northing'],p['easting'])
        assert inv['distance']==pytest.approx(d,abs=2e-8)
        assert abs((inv['azimuth_deg']-az+180)%360-180)<1e-6


def test_P03_Ron_differential_setup_rows_use_all_three_wires():
    from surveysync.leveling import solve_level_run
    o=[{'point_id':'TP1','bs_upper':2.01,'bs_middle':2.,'bs_lower':1.98,
         'fs_upper':1.03,'fs_middle':1.,'fs_lower':.99}]
    r=solve_level_run(o,start_elevation=100.,calculation_profile='ron_workbook')
    assert r['results'][0]['raw_elevation']==pytest.approx(100+(2.01+2+1.98-1.03-1-.99)/3)
    assert not r['adjusted']


def test_P04_field_to_finish_alternative_point_id_header_and_exact_chains(tmp_path):
    from surveysync.field_to_finish import parse_coded_points,build_linework,to_geojson
    p=tmp_path/'coded.csv';p.write_text('point_id,northing,easting,elevation,code\n1,0,0,10,500-BS\n2,0,1,10,5001-BS\n3,10,0,10,500-ES\n4,10,1,10,5001-ES\n')
    result=build_linework(parse_coded_points(p))
    assert result['line_count']==2
    assert {r['line_id'] for r in result['lines']}=={'500','5001'}
    assert len(to_geojson(result)['features'])==2


def test_P05_project_reopen_preserves_sources_and_audit(workspace,tmp_path):
    from surveysync.project import SurveyProject
    _,r,_=workspace
    p=tmp_path/'points.txt';p.write_text('1,100,200,10,CONTROL\n')
    evidence=r.current_project.import_source(p,'Audit','Independent audit fixture')
    root=r.current_project.paths.root
    reopened=SurveyProject(root)
    assert reopened.manifest['project_id']==r.current_project.manifest['project_id']
    assert Path(evidence['stored_path']).read_bytes()==p.read_bytes()
    assert reopened.db.recent_audit(100)


def test_P06_both_units_equal_preserves_utility_grade():
    from surveysync.utility import pipe_grades
    s=[{'point_id':'1','northing':0,'easting':0,'pipes':[{'invert_elevation':10.}]},
       {'point_id':'2','northing':100,'easting':0,'pipes':[{'invert_elevation':9.}]}]
    e=[{'from_point':'1','to_point':'2','from_pipe_index':1,'to_pipe_index':1}]
    assert pipe_grades(s,e)[0]['grade_percent']==pytest.approx(1.)
