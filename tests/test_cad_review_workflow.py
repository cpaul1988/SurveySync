import copy
import io
import json
from zipfile import ZipFile

import ezdxf
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from surveysync import cad_review as cad, cad_review_workflow as workflow
from surveysync.cad_geometry import read_drawing, analyze
from surveysync.project import SurveyProject


@pytest.fixture
def setup(tmp_path):
    project = SurveyProject.create(tmp_path/'projects', 'Revision test', crs='EPSG:2278', horizontal_units='us_survey_feet')
    doc = ezdxf.new(); m = doc.modelspace()
    line = m.add_line((2000000,1000000), (2000010,1000000))
    m.add_line((2000000,1000000), (2000010,1000000))
    block = doc.blocks.new('DETAIL'); block.add_line((0,0),(1,1));m.add_blockref('DETAIL',(2000005,1000005))
    def retain(name):
        path=tmp_path/name;doc.saveas(path)
        data=read_drawing(path,'us_survey_feet','us_survey_feet');data['qa']=analyze(data)
        return cad.retain(project,path.read_bytes(),name,data,cad.context(project))
    before=retain('before.dxf')
    line.dxf.end=(2000011,1000000,0)
    m.add_text('Revision',dxfattribs={'insert':(2000002,1000002)})
    after=retain('after.dxf')
    return project,before,after


def test_decisions_are_snapshot_bound_atomic_and_audited(setup):
    project,before,after=setup
    state=workflow.state(project,before);fid=state['finding_ids'][0]
    saved=workflow.decide(project,before,fid,'confirmed','Verified duplicate','CP',state['token'])
    assert saved['decisions'][fid]['status']=='confirmed'
    with pytest.raises(ValueError,match='Another decision'):
        workflow.decide(project,before,fid,'dismissed','Wrong drawing','CP',state['token'])
    with pytest.raises(ValueError,match='does not belong'):
        workflow.decide(project,after,fid,'dismissed','Wrong drawing','CP',workflow.state(project,after)['token'])
    reopened=workflow.decide(project,before,fid,'needs_review','Need source clarification','CP',saved['token'])
    assert len(reopened['history'])==2
    assert not workflow.state(project,after)['history']
    assert cad.read(project,before['review_id'])==before
    assert project.db.verify_audit_chain()['ok']


@pytest.mark.parametrize('status,note,reviewer', [('repaired','why','CP'),('dismissed',' ','CP'),('confirmed','why',' ')])
def test_invalid_decision_leaves_no_audit_event(setup,status,note,reviewer):
    project,before,_=setup;s=workflow.state(project,before)
    with pytest.raises(ValueError):workflow.decide(project,before,s['finding_ids'][0],status,note,reviewer,s['token'])
    assert workflow.state(project,before)==s


def test_comparison_handles_and_blocks_do_not_invent_identity(setup):
    _,before,after=setup
    result=workflow.compare(before,after)
    assert any(c['kind']=='changed_candidate' for c in result['changes'])
    assert any(c['kind']=='after_only' and c['after']['type']=='TEXT' for c in result['changes'])
    children=[c for c in result['changes'] if '/' in c['entity_id']]
    assert {c['kind'] for c in children}=={'before_only','after_only'}
    assert 'not proven identity' in result['scope']
    changed=copy.deepcopy(after);changed['point_snapshot']='other'
    with pytest.raises(ValueError,match='snapshots differ'):workflow.compare(before,changed)
    with pytest.raises(ValueError,match='different'):workflow.compare(before,before)


def test_export_contains_decisions_history_safe_text_and_comparison(setup):
    project,before,after=setup;s=workflow.state(project,before)
    saved=workflow.decide(project,before,s['finding_ids'][0],'dismissed','=HYPERLINK("bad") <script>','CP',s['token'])
    z=ZipFile(io.BytesIO(workflow.report(before,[],saved,workflow.compare(after,before))))
    assert b'&lt;script&gt;' in z.read('CAD_Review.html')
    assert b'<script>' not in z.read('CAD_Review.html')
    assert "'=HYPERLINK" in z.read('CAD_Decisions.csv').decode()
    data=json.loads(z.read('CAD_Workflow.json'))
    assert data['review_state']['history'][0]['status']=='dismissed'
    assert data['comparison']['before']['source_sha256']==after['source_sha256']


def test_routes_reject_stale_decisions_and_changed_source(setup,monkeypatch):
    project,before,after=setup
    from surveysync import router as context
    from surveysync.cad_review_routes import router
    monkeypatch.setattr(context,'current_project',project)
    app=FastAPI();app.include_router(router);client=TestClient(app)
    h={'X-SurveySync-Project':project.manifest['project_id']}
    payload={'review_id':before['review_id'],'snapshot':before['snapshot']}
    def post(path,p=payload):return client.post('/api/v9/cad/'+path,headers=h,json=p)
    s=post('state').json()
    decision=dict(payload,state_token=s['token'],finding_id=s['finding_ids'][0],status='confirmed',note='Source checked',reviewer='CP')
    assert post('decision',decision).status_code==200
    assert post('decision',decision).status_code==400
    assert post('report',dict(payload,state_token=s['token'])).status_code==400
    s=post('state').json();payload.update(state_token=s['token'],before_review_id=after['review_id'],before_snapshot=after['snapshot'])
    assert post('compare').status_code==200
    assert post('report').content[:2]==b'PK'
    (cad.folder(project)/after['review_id']/'original.dxf').write_bytes(b'tampered')
    assert post('compare').status_code==400
    assert post('report').status_code==400
    assert client.post('/api/v9/cad/state',json=payload).status_code==409
