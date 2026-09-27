"""Independent regressions for audit repairs. Uses only disposable local data."""
import json
import math
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_audit_reproductions import workspace
from surveysync import control
from surveysync.manual_control import from_project_points
from surveysync.leveling import solve_level_run, parse_level_csv
from surveysync.utility import pipe_grades
from surveysync.survey_validation import finite_number, unit_factor

POINTS = {
    '100A': (1000., 2000., 10., 'CP-A'),
    '100B': (1000.03, 2000.01, 10.02, 'CP-B'),
    '100C': (999.99, 1999.98, 9.99, 'CP-C'),
}


def load_points(workspace, tmp_path):
    client, context, _ = workspace
    path = tmp_path / 'control.csv'
    path.write_text('point_id,northing,easting,elevation,code\n' + '\n'.join(
        f'{pid},{n},{e},{z},{code}' for pid, (n,e,z,code) in POINTS.items()), encoding="utf-8")
    original = path.read_bytes()
    reply = client.post('/api/v9/points/import', json={'file_path': str(path)})
    assert reply.status_code == 200, reply.text
    return context.current_project, path, original


def payload(ids=None):
    return SimpleNamespace(control_id='200', point_ids=ids or list(POINTS), horizontal_tolerance=.1, vertical_tolerance=.1)


def snapshot(db):
    with db.connect() as conn:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {name: [tuple(r) for r in conn.execute(f'SELECT * FROM "{name}" ORDER BY rowid')] for name in names}


@pytest.mark.parametrize('ids', [list(POINTS), ['100C','100A','100B'], ['100B','100C','100A']])
def test_control_repeat_preserves_source_identity_code_and_revisions(workspace, tmp_path, ids):
    project, path, original = load_points(workspace, tmp_path)
    saved_files = {}
    for revision in range(1, 6):
        result = from_project_points(project, payload(ids))
        assert result['revision'] == revision
        assert result['source_point_ids'] == ids
        assert result['code'] == POINTS[ids[0]][3]
        avg = [sum(p[k] for p in POINTS.values())/3 for k in range(3)]
        assert [result[k] for k in ('northing','easting','elevation')] == pytest.approx(avg)
        for i, residual in enumerate(result['residuals']):
            assert residual['point_id'] == ids[i]
            expected = [POINTS[ids[i]][k] - avg[k] for k in range(3)]
            assert residual['dn'] == pytest.approx(expected[0])
            assert residual['de'] == pytest.approx(expected[1])
            assert residual['dz'] == pytest.approx(expected[2])
            assert residual['spreadsheet_vz'] == pytest.approx(expected[2] * (1 if i < 2 else -1))
        text = Path(result['deliverables']['final_control_txt']).read_text(encoding="utf-8")
        assert 'Code: ' + POINTS[ids[0]][3] in text
        saved_files.update({p:Path(p).read_bytes() for p in result['deliverables'].values()})
        with project.db.connect() as conn:
            assert conn.execute('SELECT COUNT(*) FROM control_observations WHERE include=1').fetchone()[0] == 3
            assert conn.execute('SELECT COUNT(*) FROM control_observations').fetchone()[0] == revision*3
        assert project.db.verify_audit_chain()['ok']
    assert all(Path(p).read_bytes() == content for p,content in saved_files.items())
    assert path.read_bytes() == original
    from surveysync.project import SurveyProject
    reopened = SurveyProject(project.paths.root)
    assert reopened.db.verify_audit_chain()['ok']
    assert from_project_points(reopened, payload(ids))['revision'] == 6


@pytest.mark.parametrize('stage', ['solve','export','audit'])
def test_failed_recalculation_retains_last_valid_set_and_reports(workspace, tmp_path, monkeypatch, stage):
    project, _, _ = load_points(workspace, tmp_path)
    first = from_project_points(project, payload())
    before = snapshot(project.db)
    files_before = {p: p.read_bytes() for p in project.paths.reports.rglob('*') if p.is_file()}
    if stage == 'solve':
        def bad(*a, **kw): raise ValueError('Injected solver failure')
        monkeypatch.setattr(control, 'solve', bad)
    elif stage == 'export':
        def bad(result, ids, folder):
            (folder/'partial.txt').write_text('incomplete', encoding="utf-8")
            raise OSError('Injected disk failure')
        monkeypatch.setattr(control, 'write_ron_control_deliverables', bad)
    else:
        original_audit = project.db.audit
        def bad(module, action, **kw):
            if action == 'RON_3_POINT_FROM_PROJECT_POINTS': raise ValueError('Injected audit failure')
            return original_audit(module, action, **kw)
        monkeypatch.setattr(project.db, 'audit', bad)
    with pytest.raises((ValueError,OSError)):
        from_project_points(project, payload())
    assert snapshot(project.db) == before
    assert {p:p.read_bytes() for p in project.paths.reports.rglob('*') if p.is_file()} == files_before
    assert project.db.verify_audit_chain()['ok']


def test_concurrent_manual_requests_serialize(workspace,tmp_path):
    project, _, _ = load_points(workspace,tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: from_project_points(project,payload()), range(2)))
    assert sorted(r['revision'] for r in results) == [1,2]
    assert len({r['solution_id'] for r in results}) == 2
    assert project.db.verify_audit_chain()['ok']


@pytest.mark.parametrize('ids',[['100A','100A','100B'],['100A','100B','missing'],['100A']])
def test_invalid_selection_no_mutation(workspace,tmp_path,ids):
    project, _, _ = load_points(workspace,tmp_path)
    before=snapshot(project.db)
    with pytest.raises(ValueError): from_project_points(project,payload(ids))
    assert snapshot(project.db) == before


def test_export_uses_residual_identity_not_list_position(workspace,tmp_path):
    project, _, _=load_points(workspace,tmp_path)
    result=from_project_points(project,payload())
    result['residuals']=list(reversed(result['residuals']))
    paths=control.write_ron_control_deliverables(result,list(POINTS),tmp_path/'shuffled')
    text=Path(paths['qc_txt']).read_text(encoding="utf-8")
    for residual in result['residuals']:
        assert f"{residual['point_id']}\t{residual['horizontal']:.4f}\t{residual['dz']:.4f}" in text
    result['residuals'][0]['point_id']='wrong'
    with pytest.raises(ValueError): control.write_ron_control_deliverables(result,list(POINTS),tmp_path/'bad')


def test_swallowed_database_error_rolls_back_outer_transaction(workspace):
    _, context, _ = workspace
    db=context.current_project.db
    before=snapshot(db)
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.audit('ControlSync','SHOULD_ROLL_BACK')
            try:
                with db.connect() as conn: conn.execute('INSERT INTO missing_table VALUES(1)')
            except sqlite3.Error: pass
    assert snapshot(db)==before


@pytest.mark.parametrize('value',[float('nan'),float('inf'),float('-inf'),'nan','inf',True,None])
def test_finite_contract(value):
    with pytest.raises(ValueError): finite_number(value)


@pytest.mark.parametrize('header',['PointID','Point ID','point_id','POINT-ID','\ufeffPointID'])
def test_exact_pointid_header_alias(tmp_path,header):
    p=tmp_path/'input.csv';p.write_text(f'{header},BS,FS\n001A,1.5,1.0\n', encoding="utf-8")
    assert parse_level_csv(p)[0]['point_id']=='001A'


@pytest.mark.parametrize('bad',[float('nan'),float('inf'),float('-inf')])
def test_direct_level_solver_rejects_nonfinite(bad):
    with pytest.raises(ValueError): solve_level_run([{'point_id':'1','backsight':bad,'foresight':1}],start_elevation=100.)
    with pytest.raises(ValueError): solve_level_run([{'point_id':'1','backsight':1.5,'foresight':1}],start_elevation=bad)


@pytest.mark.parametrize('method',['none','setups','distance'])
def test_explicit_station_layout_and_fixed_benchmark(method):
    rows=[{'point_id':'BM','backsight':1.5,'distance_bs':30}, {'point_id':'TP','foresight':1,'backsight':2,'distance_bs':30,'distance_fs':30}, {'point_id':'BM2','foresight':1.2,'distance_fs':30}]
    with pytest.raises(ValueError,match='layout'): solve_level_run(rows,start_elevation=100)
    r=solve_level_run(rows,start_elevation=100,known_end_elevation=101.31,adjustment_method=method,row_layout='station_rows')
    assert [x['raw_elevation'] for x in r['results']]==pytest.approx([100,100.5,101.3])
    assert r['results'][0]['adjusted_elevation']==100
    assert r['setup_count']==2
    assert r['adjusted_end_elevation']==pytest.approx(101.3 if method=='none' else 101.31)
    assert all(x['row_role']=='POINT' for x in r['results'])


def test_separate_sights_distinguish_instrument_height():
    r=solve_level_run([{'point_id':'HI','backsight':1.5},{'point_id':'TP','foresight':1}], start_elevation=100)
    assert r['row_layout']=='separate_sights'
    assert r['results'][0]['raw_elevation']==101.5
    assert r['results'][0]['point_elevation'] is None
    assert r['results'][0]['row_role']=='HEIGHT_OF_INSTRUMENT'
    assert r['results'][1]['point_elevation']==100.5
    assert r['setup_count']==1


@pytest.mark.parametrize('h',['meters','international_feet','us_survey_feet'])
@pytest.mark.parametrize('v',['meters','international_feet','us_survey_feet'])
def test_all_unit_pairs(h,v):
    s=[{'point_id':'A','northing':0,'easting':0,'pipes':[{'invert_elevation':10}]}, {'point_id':'B','northing':100,'easting':0,'pipes':[{'invert_elevation':9}]}]
    e=[{'from_point':'A','to_point':'B','from_pipe_index':1,'to_pipe_index':1,'distance':100}]
    r=pipe_grades(s,e,horizontal_units=h,vertical_units=v)[0]
    assert r['grade_percent']==pytest.approx(unit_factor(v)/unit_factor(h))
    assert r['from_invert']==10 and r['distance']==100
    s[0]['pipes'][0]['invert_elevation']=8
    assert pipe_grades(s,e,horizontal_units=h,vertical_units=v)[0]['qc_flag']=='ADVERSE_GRADE'


@pytest.mark.parametrize('unit',['','feet','unknown'])
def test_unknown_units_fail(unit):
    with pytest.raises(ValueError): pipe_grades([],[],horizontal_units=unit)


@pytest.mark.parametrize('size',[(.1,.2),(100.1,200.2),(1.,1.)])
@pytest.mark.parametrize('reverse',[True,False])
def test_translated_polygon_is_stable(size,reverse):
    from surveysync.cogo_extended import polygon_area_perimeter
    w,h=size;n,e=1e7,3e6
    points=[{'northing':n+dn,'easting':e+de} for dn,de in [(0,0),(0,w),(h,w),(h,0)]]
    if reverse: points.reverse()
    original=json.dumps(points)
    r=polygon_area_perimeter(points=points)
    assert r['centroid_northing']==pytest.approx(n+h/2,abs=1e-7)
    assert r['centroid_easting']==pytest.approx(e+w/2,abs=1e-7)
    assert r['area']==pytest.approx(w*h,rel=2e-8)
    assert json.dumps(points)==original


def test_corrupt_ledger_recovery_preserves_original(tmp_path):
    from fieldbook_sync.job_engine import AnalysisJobStore
    p=tmp_path/'ledger.sqlite';data=b'not a database';p.write_bytes(data)
    store=AnalysisJobStore(p)
    try:
        assert list(tmp_path.glob('ledger.corrupt_*.sqlite'))[0].read_bytes()==data
        assert store._open_connection().execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    finally: store.close()


def test_quarantine_failure_does_not_overwrite_original(tmp_path,monkeypatch):
    from fieldbook_sync.job_engine import AnalysisJobStore
    p=tmp_path/'ledger.sqlite';data=b'broken';p.write_bytes(data)
    original=Path.replace
    def deny(self,target):
        if self==p: raise PermissionError('blocked')
        return original(self,target)
    monkeypatch.setattr(Path,'replace',deny)
    with pytest.raises(PermissionError): AnalysisJobStore(p)
    assert p.read_bytes()==data


def test_partial_connection_closed_before_quarantine(tmp_path,monkeypatch):
    import fieldbook_sync.job_engine as jobs
    p=tmp_path/'ledger.sqlite';p.write_bytes(b'broken')
    closed=[]
    real_connect=jobs.sqlite3.connect
    class Spy:
        def __init__(self,c): self.c=c
        def __setattr__(self,k,v):
            if k=='c': object.__setattr__(self,k,v)
            else: setattr(self.c,k,v)
        def __getattr__(self,k): return getattr(self.c,k)
        def close(self): self.c.close();closed.append(True)
    monkeypatch.setattr(jobs.sqlite3,'connect',lambda *a,**k:Spy(real_connect(*a,**k)))
    original=Path.replace
    def checked(self,target):
        assert closed
        return original(self,target)
    monkeypatch.setattr(Path,'replace',checked)
    store=jobs.AnalysisJobStore(p);store.close()
