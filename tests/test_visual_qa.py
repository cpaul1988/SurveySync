"""Visual review safety contracts using actual project databases and API routes."""
import io
import json
from zipfile import ZipFile

from test_audit_reproductions import workspace
from surveysync.topo.storage import save_record


def seed(workspace, tmp_path):
    client, context, _ = workspace
    path = tmp_path / 'qa.csv'
    path.write_text('PointID,Northing,Easting,Elevation,Description\n001A,100,200,10,ROAD\n002,101,200,14,ROAD\n003,102,200,,TREE\n')
    assert client.post('/api/v9/points/import', json={'file_path': str(path)}).status_code == 200
    project = context.current_project
    headers = {'X-SurveySync-Project': project.manifest['project_id']}
    return client, project, headers, path


def get(client, headers, **params):
    response = client.get('/api/v9/visual-qa/snapshot', headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def payload(data):
    return {'snapshot': data['snapshot'], **data['settings'], 'reason': 'Independent field book check'}


def test_linked_flags_review_and_copy_never_mutate_sources(workspace, tmp_path):
    client, project, headers, path = seed(workspace, tmp_path)
    original = path.read_bytes()
    d = get(client, headers)
    assert len(d['points']) == 3
    assert {i['kind'] for i in d['issues']} == {'elevation_jump', 'missing_z'}
    jump = next(i for i in d['issues'] if i['kind'] == 'elevation_jump')
    assert jump['evidence']['elevation_change'] == 4
    assert len(jump['point_uuids']) == 2
    assert client.post('/api/v9/visual-qa/review', headers=headers, json={**payload(d), 'issue_id': jump['issue_id'], 'decision': 'confirmed'}).status_code == 200
    reviewed = get(client, headers)
    assert reviewed['snapshot'] == d['snapshot']
    assert next(i for i in reviewed['issues'] if i['issue_id'] == jump['issue_id'])['review']['decision'] == 'confirmed'
    uid = d['points'][1]['point_uuid']
    correction = {**payload(d), 'changes': [{'point_uuid': uid, 'offset': -4}], 'confirmed': True}
    reply = client.post('/api/v9/visual-qa/export', headers=headers, json=correction)
    assert reply.status_code == 200, reply.text
    with ZipFile(io.BytesIO(reply.content)) as z:
        evidence = json.loads(z.read('review_evidence.json'))
        assert evidence['corrected_points'][1]['elevation'] == 10
        assert evidence['corrected_points'][0]['point_id'] == '001A'
        assert evidence['changes'][0]['original']['elevation'] == 14
    assert get(client, headers)['snapshot'] == d['snapshot']
    assert path.read_bytes() == original
    assert project.db.verify_audit_chain()['ok']


def test_confirmation_stale_revision_unknown_issue_and_wrong_project_rejected(workspace, tmp_path):
    client, project, headers, _ = seed(workspace, tmp_path)
    d = get(client, headers)
    body = {**payload(d), 'changes': [{'point_uuid': d['points'][0]['point_uuid'], 'offset': 1}]}
    assert client.post('/api/v9/visual-qa/export', headers=headers, json=body).status_code == 400
    assert client.get('/api/v9/visual-qa/snapshot').status_code == 409
    assert client.get('/api/v9/visual-qa/snapshot', headers={'X-SurveySync-Project': 'different'}).status_code == 409
    assert client.post('/api/v9/visual-qa/review', headers=headers, json={**payload(d), 'issue_id': 'f'*64, 'decision': 'dismissed'}).status_code == 400
    with project.db.connect() as conn:
        conn.execute('UPDATE canonical_points SET elevation=11 WHERE point_uuid=?', (d['points'][0]['point_uuid'],))
    assert client.post('/api/v9/visual-qa/export', headers=headers, json={**body, 'confirmed': True}).status_code == 409
    assert all(i['review'] is None for i in get(client, headers)['issues'])


def test_duplicate_records_missing_coordinates_and_mixed_units(workspace, tmp_path):
    client, project, headers, _ = seed(workspace, tmp_path)
    with project.db.connect() as conn:
        conn.execute("UPDATE canonical_points SET point_id='001A' WHERE point_id='002'")
        conn.execute("UPDATE canonical_points SET northing=NULL WHERE point_id='003'")
        conn.execute("UPDATE canonical_points SET horizontal_units='meters' WHERE elevation=14")
    d = get(client, headers)
    duplicate = next(i for i in d['issues'] if i['kind'] == 'duplicate_id')
    assert len(set(duplicate['point_uuids'])) == 2
    assert sum(p['mappable'] for p in d['points']) == 1
    assert {'missing_xy','coordinate_context'} <= {i['kind'] for i in d['issues']}
    assert not any(i['kind'] == 'elevation_jump' for i in d['issues'])


def test_thresholds_and_correction_validation(workspace, tmp_path):
    client, project, headers, _ = seed(workspace, tmp_path)
    d = get(client, headers, jump=5)
    assert not any(i['kind'] == 'elevation_jump' for i in d['issues'])
    for params in ({'jump': 0}, {'distance': -1}, {'jump': 'nan'}, {'jump': 'inf'}):
        assert client.get('/api/v9/visual-qa/snapshot', headers=headers, params=params).status_code in (400,422)
    change = {'point_uuid': d['points'][0]['point_uuid'], 'offset': 1}
    for changes in ([change,change], [{'point_uuid': 'absent', 'offset': 1}], [{'point_uuid': d['points'][2]['point_uuid'], 'offset': 1}]):
        assert client.post('/api/v9/visual-qa/export', headers=headers, json={**payload(d),'changes': changes,'confirmed': True}).status_code == 400
    assert client.post('/api/v9/visual-qa/export', headers=headers, json={**payload(d),'changes':[change],'confirmed':True,'reason':'   '}).status_code == 400


def test_rod_evidence_requires_exact_source_and_coordinates(workspace, tmp_path):
    client, project, headers, _ = seed(workspace, tmp_path)
    d = get(client, headers)
    p = d['points'][0]
    root = project.paths.module_root / 'TopoSync' / 'RodHeightQC'
    root.mkdir(parents=True)
    report = {'kind':'analysis','source_sha256':d['sources'][p['source_id']]['sha256'],
              'points':[p], 'result':{'settings':{k:d['project'][k] for k in ('horizontal_units','vertical_units')},
              'candidates':[{'status':'PROBABLE','affected_point_ids':[p['point_id']],'candidate_id':'RHB-1'}]}}
    save_record(root, report)
    d2 = get(client, headers)
    rod = next(i for i in d2['issues'] if i['kind']=='rod_candidate')
    assert rod['point_uuids'] == [p['point_uuid']]
    with project.db.connect() as conn:
        conn.execute("UPDATE canonical_points SET vertical_units='meters' WHERE point_uuid=?",(p['point_uuid'],))
    assert not any(i['kind']=='rod_candidate' for i in get(client, headers)['issues'])
    with project.db.connect() as conn:
        conn.execute("UPDATE canonical_points SET vertical_units=? WHERE point_uuid=?",(p['vertical_units'],p['point_uuid']))
    assert any(i['kind']=='rod_candidate' for i in get(client, headers)['issues'])
    with project.db.connect() as conn:
        conn.execute('UPDATE canonical_points SET elevation=11 WHERE point_uuid=?',(p['point_uuid'],))
    assert not any(i['kind']=='rod_candidate' for i in get(client, headers)['issues'])


def test_formula_text_is_safe_in_csv_but_exact_in_json(workspace, tmp_path):
    client, project, headers, _ = seed(workspace, tmp_path)
    with project.db.connect() as conn:
        conn.execute("UPDATE canonical_points SET point_id='=2+2' WHERE point_id='001A'")
    d=get(client,headers)
    r=client.post('/api/v9/visual-qa/export',headers=headers,json={**payload(d),'confirmed':True,'changes':[{'point_uuid':d['points'][0]['point_uuid'],'offset':1}]})
    assert r.status_code == 200
    with ZipFile(io.BytesIO(r.content)) as z:
        assert "'=2+2" in z.read('reviewed_points.csv').decode()
        assert json.loads(z.read('review_evidence.json'))['corrected_points'][0]['point_id']=='=2+2'


def test_original_observations_verified_and_source_tampering_refused(workspace, tmp_path):
    client, project, headers, _ = seed(workspace, tmp_path)
    d=get(client,headers)
    p=d['points'][0]
    route='/api/v9/visual-qa/source/'+p['point_uuid']
    r=client.get(route,headers=headers)
    assert r.status_code==200,r.text
    assert r.json()['observations'][0]['point_id']=='001A'
    assert r.json()['observations'][0]['elevation']==10
    with project.db.connect() as conn:
        conn.execute('UPDATE canonical_points SET elevation=99 WHERE point_uuid=?',(p['point_uuid'],))
    assert client.get(route,headers=headers).json()['observations'][0]['elevation']==10
    stored=project.paths.root/d['sources'][p['source_id']]['stored_path']
    stored.chmod(0o600)
    stored.write_text('tampered')
    assert client.get(route,headers=headers).status_code==400


def test_snapshot_cap_is_explicit_and_never_a_partial_success(workspace,tmp_path,monkeypatch):
    client,project,headers,_=seed(workspace,tmp_path)
    import surveysync.visual_qa as visual
    monkeypatch.setattr(visual,'MAX_POINTS',2)
    response=client.get('/api/v9/visual-qa/snapshot',headers=headers)
    assert response.status_code==400
    assert 'No partial review' in response.text
