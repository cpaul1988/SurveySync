import hashlib
import io
import json
from zipfile import ZipFile

import ezdxf
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from surveysync import cad_review as cad
from surveysync.cad_geometry import read_drawing, analyze, closure, METERS
from surveysync.project import SurveyProject


def drawing(tmp_path, build, units='international_feet', target='international_feet'):
    doc=ezdxf.new();build(doc,doc.modelspace());p=tmp_path/'sample.dxf';doc.saveas(p)
    return read_drawing(p,units,target),p


def test_entities_bulges_blocks_and_unsupported(tmp_path):
    def build(d,m):
        d.layers.new('BORDER');m.add_line((0,0),(10,0))
        m.add_lwpolyline([(0,0,1),(10,0,0)],format='xyb')
        m.add_polyline3d([(0,0,0),(1,2,0)])
        m.add_arc((10,10),5,0,90);m.add_circle((20,20),2)
        m.add_text('Survey <record>');m.add_mtext('Two\\P lines')
        b=d.blocks.new('B');b.add_line((0,0),(2,0));m.add_blockref('B',(100,100),dxfattribs={'rotation':90,'xscale':2,'yscale':2,'layer':'BORDER'})
        m.add_ray((0,0),(1,1))
    data,p=drawing(tmp_path,build);original=p.read_bytes()
    assert len(data['entities'])==8
    block=next(e for e in data['entities'] if e['block_path'])
    assert block['layer']=='BORDER';assert block['points'][1]==pytest.approx([100,104,0])
    assert data['unsupported'][0]['type']=='RAY'
    assert next(e for e in data['entities'] if e['type']=='LWPOLYLINE')['curved']
    assert p.read_bytes()==original


def test_exact_checks_and_curved_screening(tmp_path):
    def build(d,m):
        m.add_line((0,0),(1,0));m.add_line((1,0),(0,0));m.add_line((5,5),(5,5))
        m.add_lwpolyline([(0,0),(1,1),(0,1),(1,0)])
        m.add_line((1.05,0),(2,0));m.add_line((2.2,0),(3,0))
        m.add_polyline3d([(0,0,0),(1,1,4)])
    data,_=drawing(tmp_path,build);result=analyze(data)
    kinds={i['kind'] for i in result['issues']}
    assert {'duplicate_segment','zero_length','self_intersection','endpoint_gap','nonplanar'}<=kinds
    gaps=[i['value'] for i in result['issues'] if i['kind']=='endpoint_gap']
    assert any(x['gap_ft']==pytest.approx(.05) and not x['over_tolerance'] for x in gaps)
    assert any(x['gap_ft']==pytest.approx(.2) and x['over_tolerance'] for x in gaps)


@pytest.mark.parametrize('gap,status',[(.05,'WITHIN_TOLERANCE_REVIEW_REQUIRED'),(.10001,'INVESTIGATE')])
def test_closure_never_forces_gap(tmp_path,gap,status):
    data,p=drawing(tmp_path,lambda d,m:m.add_lwpolyline([(0,0),(10,0),(10,10),(0,gap)]))
    original=p.read_bytes();check=closure(data,[{'entity_id':data['entities'][0]['entity_id']}])
    assert check['status']==status
    assert check['closing_gap']['gap_ft']==pytest.approx(gap)
    assert p.read_bytes()==original
    assert data['entities'][0]['points'][-1]==[0,gap,0]


def test_order_direction_internal_gaps_and_declared_closed(tmp_path):
    def build(d,m):
        m.add_line((0,0),(1,0));m.add_line((0,0),(1.3,0));m.add_lwpolyline([(0,0),(1,0),(1,1)],close=True)
    data,_=drawing(tmp_path,build);a,b,c=data['entities']
    check=closure(data,[{'entity_id':a['entity_id']},{'entity_id':b['entity_id'],'reverse':True}])
    assert check['closing_gap']['gap_ft']==0
    assert check['status']=='INVESTIGATE';assert check['gaps'][0]['gap_ft']==pytest.approx(.3)
    with pytest.raises(ValueError,match='DXF-closed'):closure(data,[{'entity_id':c['entity_id']}])
    with pytest.raises(ValueError,match='duplicate'):closure(data,[{'entity_id':a['entity_id']}]*2)


def test_units_ocs_and_arc_endpoints(tmp_path):
    data,_=drawing(tmp_path,lambda d,m:m.add_arc((10,20,4),5,0,90,dxfattribs={'extrusion':(0,0,-1)}),'us_survey_feet','meters')
    e=data['entities'][0];factor=METERS['us_survey_feet']
    assert e['points'][0]==pytest.approx([-15*factor,20*factor,-4*factor])
    assert e['points'][-1]==pytest.approx([-10*factor,25*factor,-4*factor])
    assert data['scale_to_project']==factor


def test_recursive_and_nonuniform_block_are_reported(tmp_path):
    def build(d,m):
        b=d.blocks.new('recursive');b.add_blockref('recursive',(0,0));m.add_blockref('recursive',(0,0))
        b=d.blocks.new('C');b.add_circle((0,0),1);m.add_blockref('C',(10,10),dxfattribs={'xscale':2,'yscale':1})
    data,_=drawing(tmp_path,build)
    assert any('Recursive' in u['reason'] for u in data['unsupported'])
    assert data['entities'][0]['type']=='ELLIPSE'


def test_worker_failure_and_limits(tmp_path,monkeypatch):
    with pytest.raises(ValueError,match='DXF review failed'):cad.parse_bytes(b'not a DXF','meters','meters')
    with pytest.raises(ValueError,match='Explicit supported'):cad.parse_bytes(b'dxf','unknown','meters')
    monkeypatch.setattr(cad,'MAX_BYTES',3)
    with pytest.raises(ValueError,match='32 MiB'):cad.parse_bytes(b'four','meters','meters')


def test_budget_never_silently_truncates(tmp_path,monkeypatch):
    from surveysync import cad_geometry as g
    data,_=drawing(tmp_path,lambda d,m:[m.add_line((0,0),(1,0)) for _ in range(4)])
    monkeypatch.setattr(g,'MAX_FINDINGS',1)
    with pytest.raises(ValueError,match='No partial'):g.analyze(data)


@pytest.fixture
def project(tmp_path):
    return SurveyProject.create(tmp_path/'projects','CAD Test',crs='EPSG:2278',horizontal_units='us_survey_feet')


def retained(project,tmp_path):
    data,p=drawing(tmp_path,lambda d,m:m.add_line((0,0),(2,0)),target='us_survey_feet')
    data['qa']=analyze(data)
    return cad.retain(project,p.read_bytes(),p.name,data,cad.context(project)),p


def test_retained_integrity_and_reports(project,tmp_path):
    data,p=retained(project,tmp_path)
    assert cad.read(project,data['review_id'])==data
    assert cad.list_reviews(project)[0]['review_id']==data['review_id']
    z=ZipFile(io.BytesIO(cad.report(data,[{'entity_id':data['entities'][0]['entity_id']}])) )
    assert json.loads(z.read('CAD_Review.json'))['closure']['status']=='INVESTIGATE'
    assert b'INVESTIGATE' in z.read('CAD_Review.html')
    assert b'Foot definition' in z.read('CAD_Closure.csv')
    assert hashlib.sha256(p.read_bytes()).hexdigest()==data['source_sha256']
    (cad.folder(project)/data['review_id']/'original.dxf').write_bytes(b'changed')
    with pytest.raises(ValueError,match='DXF changed'):cad.read(project,data['review_id'])


def test_settings_and_snapshot_changes_refuse_stale_review(project,tmp_path):
    data,_=retained(project,tmp_path)
    project.manifest['horizontal_units']='meters'
    with pytest.raises(ValueError,match='context changed'):cad.read(project,data['review_id'])
    project.manifest['horizontal_units']='us_survey_feet'
    path=cad.folder(project)/data['review_id']/'review.json'
    payload=json.loads(path.read_text());payload['entities'][0]['points'][0][0]=999
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError,match='review changed'):cad.read(project,data['review_id'])


def test_route_upload_closure_stale_project_and_export(project,tmp_path,monkeypatch):
    from surveysync import router as context
    from surveysync.cad_review_routes import router
    monkeypatch.setattr(context,'current_project',project)
    app=FastAPI();app.include_router(router);client=TestClient(app)
    h={'X-SurveySync-Project':project.manifest['project_id']}
    _,p=drawing(tmp_path,lambda d,m:m.add_line((0,0),(1,0)))
    args={'files':{'file':('input.dxf',p.read_bytes(),'application/octet-stream')},'data':{'drawing_units':'international_feet','alignment_confirmed':'true'}}
    assert client.post('/api/v9/cad/import',**args).status_code==409
    r=client.post('/api/v9/cad/import',headers=h,**args);assert r.status_code==200,r.text
    data=r.json();payload={'review_id':data['review_id'],'snapshot':data['snapshot'],'selections':[{'entity_id':data['entities'][0]['entity_id']}]}
    assert client.post('/api/v9/cad/closure',headers=h,json=payload).json()['status']=='INVESTIGATE'
    payload['state_token']=client.post('/api/v9/cad/state',headers=h,json=payload).json()['token']
    assert client.post('/api/v9/cad/report',headers=h,json=payload).content[:2]==b'PK'
    assert client.post('/api/v9/cad/closure',headers={'X-SurveySync-Project':'other'},json=payload).status_code==409
    args['data']['alignment_confirmed']='false'
    assert client.post('/api/v9/cad/import',headers=h,**args).status_code==400


@pytest.mark.parametrize("units",["international_feet","us_survey_feet"])
def test_exact_tolerance_uses_project_foot_and_roundoff(units):
    a=[2000000.0,1000000.0,0];b=[2000000.1,1000000.0,0]
    d={"project_units":units,"entities":[{"entity_id":"A","points":[a,b],"endpoints":[a,b],"planar":True,"closed":False}]}
    c=closure(d,[{"entity_id":"A"}])
    assert c["status"]=="WITHIN_TOLERANCE_REVIEW_REQUIRED"
    assert c["foot_unit"]==units
    assert c["closing_gap"]["gap_ft"]==pytest.approx(.1,abs=1e-8)
