import csv
import io
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from surveysync.topo.codes import CodeRule, classify, default_rules, parse_code
from surveysync.topo.detection import DetectionSettings, analyze, build_chains
from surveysync.topo.exports import reviewed_copy_csv
from surveysync.topo.imports import TopoPoint, parse_code_file, parse_points, survey_preview
from surveysync.topo.storage import load_record


def settings(**kwargs):
    return DetectionSettings(order_confirmed=True, units_confirmed=True, classifications_reviewed=True,
                             horizontal_units='international_feet', vertical_units='international_feet', **kwargs)


def fixture_points(shift=-1.83, count=5, recovery=True):
    codes=['671','694','871','872','604'][:count]
    points=[]
    for station in range(10 if recovery else 7):
        for lane,code in enumerate(codes):
            pid=str(36123+len(points))
            z=550-.3*station+.02*lane+(shift if 3<=station<=6 else 0)
            points.append(TopoPoint(pid,lane*3,station*10,z,code+('-BS' if station==0 else ''),len(points)+1))
    return points


def test_known_shift_sign_range_evidence_and_original_unchanged():
    points=fixture_points(); original=list(points)
    result=analyze(points,default_rules(),settings())
    assert len(result['candidates'])==1
    c=result['candidates'][0]
    assert (c['start_point'],c['end_point'])==('36138','36157')
    assert c['estimated_rod_bust']==pytest.approx(-1.83)
    assert c['recommended_correction']==pytest.approx(1.83)
    assert c['confidence']==85 and c['correction_ready']
    assert len(c['chain_evidence'])==5 and len(c['affected_point_ids'])==20
    assert c['score_breakdown']['setup_boundary']==0
    assert points==original


@pytest.mark.parametrize('shift',[0,.1])
def test_smooth_grade_and_below_threshold_are_not_flagged(shift):
    assert analyze(fixture_points(shift),default_rules(),settings())['candidates']==[]


@pytest.mark.parametrize('code',['296','294','633','634','363','877','364','600'])
def test_nearby_walls_ditches_creeks_structures_suppress_correction(code):
    points=fixture_points()+[TopoPoint('hazard',0,40,550,code,51)]
    candidates=analyze(points,default_rules(),settings())['candidates']
    assert candidates and all(c['status']=='SUPPRESSED' and not c['correction_ready'] for c in candidates)


def test_distant_wall_does_not_suppress_local_range():
    points=fixture_points()+[TopoPoint('wall',10000,10000,550,'296',51)]
    assert analyze(points,default_rules(),settings())['candidates'][0]['correction_ready']


def test_open_end_and_single_feature_require_review():
    for points in (fixture_points(recovery=False),fixture_points(count=1)):
        candidates=analyze(points,default_rules(),settings())['candidates']
        assert candidates and all(not c['correction_ready'] for c in candidates)


def test_unknown_code_inside_range_blocks_export():
    points=fixture_points();points.insert(19,TopoPoint('unknown',4,34,547,'999',99))
    c=analyze(points,default_rules(),settings())['candidates'][0]
    assert not c['correction_ready'] and c['unclassified_points']==['unknown']


def test_review_confirmations_are_enforced_on_server():
    for field in ('order_confirmed','units_confirmed','classifications_reviewed'):
        config=settings().model_copy(update={field:False})
        assert not analyze(fixture_points(),default_rules(),config)['candidates'][0]['correction_ready']


def test_explicit_codes_override_structure_range_and_markers_split_strings():
    rules={r.code:r for r in default_rules()}
    assert classify('604-BS',rules).role==classify('607',rules).role=='surface'
    assert classify('633',rules).role=='discontinuity'
    assert classify('600',rules).role=='structure'
    assert parse_code('226-A-PC')==('226','A',{'PC'})
    p=fixture_points(count=1)
    p[4]=replace(p[4],code='671-BS')
    assert len(build_chains(p,rules,settings()))==2


def test_numeric_order_and_exact_ids():
    points=fixture_points();points=[replace(p,point_id='0'+p.point_id) for p in points]
    ordered=analyze(list(reversed(points)),default_rules(),settings(order='point_id'))
    assert ordered['candidates'][0]['start_point']=='036138'
    points[0]=replace(points[0],point_id='A1')
    with pytest.raises(ValueError,match='all-numeric'):
        analyze(points,default_rules(),settings(order='point_id'))


def test_metric_threshold_conversion_matches_feet():
    points=[replace(p,northing=p.northing*.3048,easting=p.easting*.3048,elevation=p.elevation*.3048) for p in fixture_points()]
    config=settings().model_copy(update={'horizontal_units':'meters','vertical_units':'meters'})
    c=analyze(points,default_rules(),config)['candidates'][0]
    assert c['recommended_correction']==pytest.approx(1.83*.3048)
    assert c['confidence']==85


def test_constant_offset_scatter_and_projection_limits():
    points=fixture_points()
    for i in range(15,35): points[i]=replace(points[i],elevation=points[i].elevation+(i%3)*.6)
    assert not any(c['correction_ready'] for c in analyze(points,default_rules(),settings())['candidates'])
    assert analyze(fixture_points(),default_rules(),settings(max_projection_ft=5))['candidates']==[]


def test_setup_at_start_adds_evidence_but_setup_at_end_is_uncertain():
    points=fixture_points();points.insert(15,TopoPoint('setup',0,30,550,'800',99))
    assert analyze(points,default_rules(),settings())['candidates'][0]['confidence']==100
    points.insert(36,TopoPoint('setup2',0,70,550,'100',100))
    assert not analyze(points,default_rules(),settings())['candidates'][0]['correction_ready']


def test_import_preserves_ids_and_rejects_bad_rows():
    scan=survey_preview('0001,100,200,550,671\nA2,101,201,551,604',False)
    assert [p.point_id for p in parse_points(scan,scan['mapping'])]==['0001','A2']
    for text in ('1,100,200,nan,604','1,100,200,550,604\n1,101,201,551,604'):
        scan=survey_preview(text,False)
        with pytest.raises(ValueError): parse_points(scan,scan['mapping'])
    with pytest.raises(ValueError): survey_preview('PointID,PointID,Northing\n1,2,3',True)
    with pytest.raises(ValidationError): DetectionSettings(min_offset_ft=float('nan'))


def test_code_import_requires_review_and_accepts_roles(tmp_path):
    path=tmp_path/'codes.csv';path.write_text('code,description\n296,Retaining Wall\n604,Ground Shot\n999,Unknown thing')
    result=parse_code_file(path)
    assert [r.role for r in result]==['discontinuity','surface','unknown']
    path.write_text('code,description,role\n604,Ground,surface\n604,Duplicate,surface')
    with pytest.raises(ValueError):parse_code_file(path)


def test_corrected_copy_changes_only_selected_elevations_and_retains_provenance():
    points=fixture_points();report={'source_sha256':'abc','points':[p.to_dict() for p in points], 'result':analyze(points,default_rules(),settings())}
    original=repr(report)
    content,audit=reviewed_copy_csv(report,['RHB-0001'],'Rod height confirmed in field notes')
    rows=list(csv.DictReader(io.StringIO(content)))
    assert float(rows[15]['Elevation'])==pytest.approx(points[15].elevation+1.83)
    assert float(rows[0]['Elevation'])==points[0].elevation
    assert rows[15]['Code']==points[15].code and audit['source_modified'] is False
    assert repr(report)==original
    report['result']['candidates'][0]['correction_ready']=False
    with pytest.raises(ValueError):reviewed_copy_csv(report,['RHB-0001'],'reviewed')


def test_api_roundtrip_immutable_source_and_native_exports(tmp_path,monkeypatch):
    from surveysync.topo import routes
    monkeypatch.setattr(routes,'workspace',lambda:(tmp_path,None))
    app=FastAPI();app.include_router(routes.router);client=TestClient(app)
    text='\n'.join(f'{p.point_id},{p.northing},{p.easting},{p.elevation},{p.code}' for p in fixture_points())
    response=client.post('/api/v9/topo/survey/preview',files={'file':('survey.csv',text)},data={'header':'no'})
    assert response.status_code==200,response.text
    source=response.json();snapshot=(tmp_path/(source['source_id']+'.json')).read_bytes()
    response=client.post('/api/v9/topo/analyze',json={'source_id':source['source_id'],'mapping':source['mapping'],'rules':[r.model_dump() for r in default_rules()],'settings':settings().model_dump()})
    assert response.status_code==200,response.text
    run=response.json();prefix='/api/v9/topo/runs/'+run['run_id']
    assert client.get(prefix+'/export?format=csv').status_code==200
    assert client.get(prefix+'/export?format=json').json()['source_sha256']
    payload={'candidate_ids':['RHB-0001'],'review_reason':'field notes confirmed','confirmed':False}
    assert client.post(prefix+'/corrected-copy',json=payload).status_code==400
    payload['confirmed']=True
    assert client.post(prefix+'/corrected-copy',json=payload).status_code==200
    saved=client.post(prefix+'/save-export',json={**payload,'kind':'corrected'}).json()
    assert Path(saved['path']).is_file() and saved['source_modified'] is False
    assert (tmp_path/(source['source_id']+'.json')).read_bytes()==snapshot
    assert len(list(tmp_path.glob('*.json')))>=4
    assert client.post('/api/v9/topo/code-rules/save',json=[r.model_dump() for r in default_rules()]).status_code==200
    assert len(client.get('/api/v9/topo/code-rules').json()['rules'])==len(default_rules())
    assert client.post('/api/v9/topo/code-rules/import',files={'file':('bad.xlsx',b'not a zip')}).status_code==400
    with pytest.raises(ValueError):load_record(tmp_path,'../escape','source')


def test_bundled_headered_example_maps_all_five_fields():
    root = Path(__file__).resolve().parents[1]
    scan = survey_preview((root / 'examples/topo/rod_bust_demo.csv').read_text())
    points = parse_points(scan, scan['mapping'])
    assert len(points) == 50 and points[0].point_id == '36123'
    result = analyze(points, default_rules(), settings())
    assert result['candidates'][0]['recommended_correction'] == pytest.approx(1.83)
