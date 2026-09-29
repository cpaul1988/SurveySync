"""Connected review workflow contracts against a real project and API."""
import base64
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

from test_visual_qa import seed
from test_audit_reproductions import workspace

BASE = '/api/v9/review-workflow'


def test_revision_ambiguity_context_and_source_integrity(workspace,tmp_path):
    client,project,headers,source=seed(workspace,tmp_path)
    original=source.read_bytes(); data=client.get(BASE+'/state',headers=headers).json()
    context={k:data['project'][k] for k in ('crs','horizontal_units','vertical_units')}
    csv='PointID,Northing,Easting,Elevation,Description\n001A,105,201,12,ROAD\n001A,106,202,13,ROAD\n002,101,200,14,ROAD\n004,110,220,5,TREE\n'
    body={'snapshot':data['snapshot'],'csv_text':csv,**context}
    assert client.post(BASE+'/revision',headers=headers,json={**body,'horizontal_units':'meters'}).status_code==400
    with project.db.connect() as db:
        db.execute("UPDATE canonical_points SET point_id='001A' WHERE point_id='003'")
    data=client.get(BASE+'/state',headers=headers).json();body['snapshot']=data['snapshot']
    response=client.post(BASE+'/revision',headers=headers,json=body)
    assert response.status_code==200,response.text
    result=response.json()
    assert result['source_sha256']==hashlib.sha256(csv.encode()).hexdigest()
    assert len(result['ambiguous'])==1
    assert result['ambiguous'][0]['new_rows']==[2,3]
    assert not any(c['point_id']=='001A' for c in result['changes'])
    a,b=result['ambiguous'][0]['old_uuids']
    matched=client.post(BASE+'/revision',headers=headers,json={**body,'matches':[{'point_uuid':a,'row':2},{'point_uuid':b,'row':3}]}).json()
    assert len([c for c in matched['changes'] if c['point_id']=='001A'])==2
    assert all(c['distance'] is not None for c in matched['changes'] if c['point_id']=='001A' and c['old']['easting'] is not None)
    assert source.read_bytes()==original
    assert client.get(BASE+'/state').status_code==409


def test_recheck_reservation_evidence_report_and_delivery_gate(workspace,tmp_path):
    client,project,headers,_=seed(workspace,tmp_path)
    data=client.get(BASE+'/state',headers=headers).json();token=data['snapshot'];issue=data['issues'][0]['issue_id']
    reserve=client.post(BASE+'/reservations',headers=headers,json={'start':1000,'end':1099,'crew':'Crew A'}).json()
    assert reserve['status']=='active'
    assert client.post(BASE+'/reservations',headers=headers,json={'start':1050,'end':1100,'crew':'Crew B'}).status_code==400
    assert client.post(BASE+'/reservations',headers=headers,json={'start':2,'end':2,'crew':'Crew B'}).status_code==400
    req=client.post(BASE+'/rechecks',headers=headers,json={'snapshot':token,'issue_ids':[issue],'crew':'Crew A','instructions':'Check elevations'}).json()
    package=client.get(BASE+'/rechecks/'+req['id']+'/package',headers=headers)
    assert package.status_code==200
    with ZipFile(io.BytesIO(package.content)) as z:
        assert {'Field_Recheck.pdf','Field_Recheck.csv','Request.json'}==set(z.namelist())
    image=b'\x89PNG\r\n\x1a\n' + b'field sketch'
    e=client.post(BASE+'/evidence',headers=headers,json={'snapshot':token,'issue_id':issue,'filename':'sketch.png','media_type':'image/png','base64_content':base64.b64encode(image).decode()})
    assert e.status_code==200,e.text
    evidence=e.json();assert (project.paths.root/evidence['stored_path']).read_bytes()==image
    assert client.post(BASE+'/policy',headers=headers,json={'checks':{'enforce_delivery':True}}).status_code==200
    from surveysync.delivery import build_deliverable_package
    try: build_deliverable_package(project)
    except ValueError as exc: assert 'readiness' in str(exc)
    else: assert False,'delivery gate did not block'
    returned=client.post(BASE+'/rechecks/'+req['id']+'/return',headers=headers,json={'records':[{'point_uuid':req['points'][0]['point_uuid'],'northing':102,'easting':200,'elevation':11}],'note':'Reobserved'})
    assert returned.status_code==200,returned.text
    assert returned.json()['returns'][0]['records'][0]['delta']['northing'] is not None
    report=client.post(BASE+'/report',headers=headers,json={'snapshot':token,'evidence_ids':[evidence['id']]})
    assert report.status_code==200,report.text
    with ZipFile(report.json()['path']) as z:
        assert 'Review.pdf' in z.namelist()
        assert any(name.startswith('Attachments/') for name in z.namelist())
    assert client.post(BASE+'/acknowledge',headers=headers,json={'snapshot':token,'reviewer':'CP','note':'Reviewed source records'}).status_code==200
    assert client.post(BASE+'/reservations/'+reserve['id']+'/release',headers=headers,json={}).status_code==200
    assert project.db.verify_audit_chain()['ok']


def test_delivery_can_pass_once_required_checks_are_satisfied(workspace,tmp_path):
    client,project,headers,_=seed(workspace,tmp_path)
    data=client.get(BASE+'/state',headers=headers).json();token=data['snapshot']
    for issue in data['issues']:
        response=client.post('/api/v9/visual-qa/review',headers=headers,json={'snapshot':token,'jump':2,'distance':50,'reason':'Independent review','issue_id':issue['issue_id'],'decision':'dismissed'})
        assert response.status_code==200,response.text
    assert client.post(BASE+'/policy',headers=headers,json={'checks':{'enforce_delivery':True}}).status_code==200
    assert client.post(BASE+'/report',headers=headers,json={'snapshot':token}).status_code==200
    assert client.post(BASE+'/acknowledge',headers=headers,json={'snapshot':token,'reviewer':'CP','note':'Checked the current report'}).status_code==200
    ready=client.get(BASE+'/state',headers=headers).json()['readiness']
    assert ready['ready'],ready
    from surveysync.delivery import build_deliverable_package
    result=build_deliverable_package(project)
    assert Path(result['path']).is_file()
    with project.db.connect() as conn:
        conn.execute('UPDATE canonical_points SET elevation=11 WHERE point_id=?',('001A',))
    changed=client.get(BASE+'/state',headers=headers).json()['readiness']
    assert not changed['ready'] and not changed['checks']['reviewer_acknowledged']


def test_partial_crew_return_does_not_clear_readiness(workspace,tmp_path):
    client,project,headers,_=seed(workspace,tmp_path)
    data=client.get(BASE+'/state',headers=headers).json()
    issue=next(i for i in data['issues'] if len(i['point_uuids'])==2)
    req=client.post(BASE+'/rechecks',headers=headers,json={'snapshot':data['snapshot'],'issue_ids':[issue['issue_id']],'crew':'Crew A','instructions':'Check both elevations'}).json()
    first=client.post(BASE+'/rechecks/'+req['id']+'/return',headers=headers,json={'records':[{'point_uuid':req['points'][0]['point_uuid'],'elevation':10}],'note':'First shot'}).json()
    assert first['status']=='open'
    assert not client.get(BASE+'/state',headers=headers).json()['readiness']['checks']['rechecks_returned']
    second=client.post(BASE+'/rechecks/'+req['id']+'/return',headers=headers,json={'records':[{'point_uuid':req['points'][1]['point_uuid'],'elevation':14}],'note':'Second shot'}).json()
    assert second['status']=='returned'
    assert client.get(BASE+'/state',headers=headers).json()['readiness']['checks']['rechecks_returned']


def test_report_download_is_project_bound_and_hash_verified(workspace,tmp_path):
    client,project,headers,_=seed(workspace,tmp_path)
    data=client.get(BASE+'/state',headers=headers).json()
    created=client.post(BASE+'/report',headers=headers,json={'snapshot':data['snapshot']}).json()
    url=BASE+'/reports/'+created['id']+'/download'
    downloaded=client.get(url,headers=headers)
    assert downloaded.status_code==200
    assert downloaded.content==Path(created['path']).read_bytes()
    assert client.get(url).status_code==409
    assert client.get(url,headers={'X-SurveySync-Project':'other'}).status_code==409
    Path(created['path']).write_bytes(b'tampered')
    assert client.get(url,headers=headers).status_code==400


def test_revision_ambiguity_and_later_changes_invalidate_delivery_review(workspace,tmp_path):
    client,project,headers,_=seed(workspace,tmp_path)
    data=client.get(BASE+'/state',headers=headers).json(); token=data['snapshot']
    for issue in data['issues']:
        assert client.post('/api/v9/visual-qa/review',headers=headers,json={'snapshot':token,'jump':2,'distance':50,'reason':'Independent source check','issue_id':issue['issue_id'],'decision':'dismissed'}).status_code==200
    assert client.post(BASE+'/report',headers=headers,json={'snapshot':token}).status_code==200
    assert client.post(BASE+'/acknowledge',headers=headers,json={'snapshot':token,'reviewer':'CP','note':'Checked the report'}).status_code==200
    assert client.get(BASE+'/state',headers=headers).json()['readiness']['ready']
    context={k:data['project'][k] for k in ('crs','horizontal_units','vertical_units')}
    body={'snapshot':token,'csv_text':'PointID,Northing,Easting,Elevation,Description\n001A,100,200,10,ROAD\n001A,101,201,11,ROAD\n002,101,200,14,ROAD\n003,102,200,,TREE\n',**context}
    revision=client.post(BASE+'/revision',headers=headers,json=body).json()
    assert revision['ambiguous'][0]['new_rows']==[2,3]
    readiness=client.get(BASE+'/state',headers=headers).json()['readiness']
    assert not readiness['checks']['revision_matches_resolved']
    assert not readiness['checks']['report_present']
    assert not readiness['checks']['reviewer_acknowledged']
    assert not readiness['ready']
    uid=next(p['point_uuid'] for p in client.get('/api/v9/visual-qa/snapshot',headers=headers).json()['points'] if p['point_id']=='001A')
    assert client.post(BASE+'/revision',headers=headers,json={**body,'matches':[{'point_uuid':uid,'row':2}]}).status_code==200
    assert not client.get(BASE+'/state',headers=headers).json()['readiness']['checks']['revision_matches_resolved']


def test_legacy_partial_return_can_be_completed(workspace,tmp_path):
    from surveysync.review_workflow import state, save
    client,project,headers,_=seed(workspace,tmp_path)
    data=client.get(BASE+'/state',headers=headers).json();issue=next(i for i in data['issues'] if len(i['point_uuids'])==2)
    req=client.post(BASE+'/rechecks',headers=headers,json={'snapshot':data['snapshot'],'issue_ids':[issue['issue_id']],'crew':'Crew B','instructions':'Check both'}).json()
    s=state(project);s['rechecks'][0]['returns']=[{'received_utc':'old','note':'old','records':[{'point_uuid':req['points'][0]['point_uuid'],'observed':{'elevation':10},'delta':{'elevation':0}}]}];s['rechecks'][0]['status']='returned';save(project,s)
    assert not client.get(BASE+'/state',headers=headers).json()['readiness']['checks']['rechecks_returned']
    response=client.post(BASE+'/rechecks/'+req['id']+'/return',headers=headers,json={'records':[{'point_uuid':req['points'][1]['point_uuid'],'elevation':14}],'note':'Finished'})
    assert response.status_code==200,response.text
    assert response.json()['status']=='returned'
