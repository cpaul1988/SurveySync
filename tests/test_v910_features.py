from pathlib import Path
import json

import pytest

from surveysync.project import SurveyProject
from surveysync.leveling import solve_level_run, import_run as import_level_run, solve_saved_run as solve_level_saved
from surveysync.traverse import solve_traverse
from surveysync.scale_factor import ScaleSample, fit_project_factor
from surveysync.field_to_finish import build_linework
from surveysync.spatial import typed_json_value, infer_schema
from surveysync.reporting import project_report
from surveysync.notifications import save_policy, load_policy


def make_project(tmp_path):
    return SurveyProject.create(tmp_path, 'V910 Test', crs='EPSG:26915', horizontal_units='meters', vertical_units='meters')


def test_level_closure_and_revision(tmp_path):
    p=make_project(tmp_path)
    obs=[{'point_id':'TP1','backsight':1.5,'foresight':1.0},{'point_id':'BM2','backsight':1.0,'foresight':1.4}]
    raw=solve_level_run(obs,start_elevation=100.0,known_end_elevation=100.05,adjustment_method='setups')
    assert raw['closure']==pytest.approx(0.05)
    rid=import_level_run(p.db,'Loop',obs,start_elevation=100.0,known_end_elevation=100.05)
    solved=solve_level_saved(p.db,rid)
    assert solved['revision']==1
    solved2=solve_level_saved(p.db,rid)
    assert solved2['revision']==2


def test_traverse_bowditch_closes_to_known_endpoint():
    courses=[
        {'from_point':'1','to_point':'2','azimuth_deg':90,'distance':100},
        {'from_point':'2','to_point':'3','azimuth_deg':180,'distance':100},
        {'from_point':'3','to_point':'4','azimuth_deg':270,'distance':100},
        {'from_point':'4','to_point':'1','azimuth_deg':0,'distance':99.9},
    ]
    d=solve_traverse(courses,start_n=0,start_e=0,known_end_n=0,known_end_e=0,adjustment_method='bowditch')
    assert d['linear_closure']==pytest.approx(0.1,abs=1e-8)
    assert d['adjusted_end_n']==pytest.approx(0,abs=1e-8)
    assert d['adjusted_end_e']==pytest.approx(0,abs=1e-8)


def test_project_factor_is_not_naive_average_and_reports_ppm():
    rows=[ScaleSample('MO East',1.0000878,2),ScaleSample('MO Central',1.0000712,1)]
    d=fit_project_factor(rows,max_distortion_ppm=20)
    assert 1.0000712 < d['project_factor'] < 1.0000878
    assert d['method']=='weighted_relative_least_squares'
    assert len(d['residuals'])==2
    assert d['review_required'] is True


def test_field_to_finish_concurrent_codes_and_curve_events():
    pts=[
        {'point_id':'1','northing':0,'easting':0,'elevation':0,'code':'500-BS'},
        {'point_id':'2','northing':0,'easting':1,'elevation':0,'code':'5001-BS'},
        {'point_id':'3','northing':1,'easting':0,'elevation':0,'code':'500-PC'},
        {'point_id':'4','northing':1,'easting':1,'elevation':0,'code':'5001-ES'},
        {'point_id':'5','northing':2,'easting':0,'elevation':0,'code':'500-PT'},
        {'point_id':'6','northing':3,'easting':0,'elevation':0,'code':'500-ES'},
    ]
    d=build_linework(pts)
    assert d['line_count']==2
    line500=next(x for x in d['lines'] if x['line_id']=='500')
    assert [v['event'] for v in line500['vertices']]==['BS','PC','PT','ES']


def test_typed_spatial_attribute_preservation():
    assert typed_json_value(b'abc')['__type__']=='binary'
    assert typed_json_value(7)==7
    schema=infer_schema([{'properties':{'A':1,'B':'x'}},{'properties':{'A':2.3,'B':None}}])
    assert 'A' in schema and 'B' in schema


def test_report_pdf_has_deliverable_and_notification_policy_is_secretless(tmp_path):
    p=make_project(tmp_path)
    save_policy(p,{'enabled':False,'recipients':['pm@example.com'],'smtp_host':'smtp.example.com','smtp_user':'u','from_address':'survey@example.com'})
    policy=load_policy(p)
    assert policy['recipients']==['pm@example.com']
    assert 'password' not in policy
    out=p.paths.reports/'report.pdf'
    d=project_report(p,out,prepared_by='Tester',project_number='123')
    assert out.is_file() and out.stat().st_size>1000
    assert d['deliverable_id']
    assert d['notification']['status']=='DISABLED'


def test_new_database_tables_exist(tmp_path):
    p=make_project(tmp_path)
    with p.db.connect() as conn:
        names={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for name in ['level_runs','level_solutions','traverse_runs','utility_structures','attachments','spatial_layers','scale_factor_solutions','deliverables','notification_events','cloud_sync_log']:
        assert name in names

from surveysync.spatial import import_dxf, import_spatial
from surveysync.reporting import control_report
from surveysync.notifications import send_deliverable_notification, list_notifications


def test_ascii_dxf_import_respects_project_crs(tmp_path):
    p=make_project(tmp_path / 'project')
    dxf=tmp_path/'lines.dxf'
    dxf.write_text('''0\nSECTION\n2\nENTITIES\n0\nPOINT\n8\nSHOT\n10\n500000\n20\n4200000\n0\nLINE\n8\nUTIL\n10\n500000\n20\n4200000\n11\n500010\n21\n4200010\n0\nLWPOLYLINE\n8\nEP\n70\n0\n10\n500000\n20\n4200000\n10\n500005\n20\n4200005\n0\nENDSEC\n0\nEOF\n''',encoding='utf-8')
    layers=import_dxf(dxf,p.manifest['crs'])
    assert len(layers)==1
    assert len(layers[0]['features'])==3
    assert {'Point','LineString'} <= set(layers[0]['geometry_types'])
    # Coordinates must have been transformed from EPSG:26915 to lon/lat,
    # rather than being mistaken for WGS84 degrees.
    pt=layers[0]['features'][0]['geometry']['coordinates']
    assert -100 < pt[0] < -80
    assert 30 < pt[1] < 50


def test_dxf_requires_explicit_crs(tmp_path):
    dxf=tmp_path/'one.dxf'
    dxf.write_text('0\nSECTION\n2\nENTITIES\n0\nPOINT\n10\n1\n20\n2\n0\nENDSEC\n0\nEOF\n',encoding='utf-8')
    with pytest.raises(ValueError,match='project CRS'):
        import_dxf(dxf,None)


def test_control_report_pdf_registers_deliverable(tmp_path):
    p=make_project(tmp_path)
    out=p.paths.reports/'control_report.pdf'
    d=control_report(p,out,prepared_by='QA')
    assert out.is_file() and out.stat().st_size > 1000
    assert d['kind']=='control_report_pdf'
    assert d['status']=='FINAL'
    assert d['notification']['status']=='DISABLED'


def test_notification_send_records_success_without_storing_password(tmp_path,monkeypatch):
    p=make_project(tmp_path)
    deliverable_path=p.paths.reports/'final.pdf'
    deliverable_path.parent.mkdir(parents=True,exist_ok=True)
    deliverable_path.write_bytes(b'%PDF-1.7\nfixture')
    deliverable={'deliverable_id':'d1','filename':'final.pdf','path':str(deliverable_path),'kind':'survey_report_pdf','sha256':'abc','status':'FINAL'}
    sent=[]
    class FakeSMTP:
        def __init__(self,*a,**kw): pass
        def __enter__(self): return self
        def __exit__(self,*a): return False
        def ehlo(self): pass
        def starttls(self,context=None): pass
        def login(self,user,password):
            assert user=='mailer@example.com'
            assert password=='session-secret'
        def send_message(self,msg): sent.append(msg)
    monkeypatch.setattr('surveysync.notifications.smtplib.SMTP',FakeSMTP)
    result=send_deliverable_notification(
        p,deliverable,recipients=['pm@example.com'],smtp_host='smtp.example.com',smtp_user='mailer@example.com',
        from_address='mailer@example.com',password='session-secret',use_tls=True,
    )
    assert result['status']=='SENT' and len(sent)==1
    rows=list_notifications(p)
    assert rows[0]['status']=='SENT'
    # Secret must never be written to notification details.
    raw=json.dumps(rows)
    assert 'session-secret' not in raw



def test_ron_three_point_workbook_profile_matches_authoritative_formula(tmp_path):
    from surveysync.control import import_observations, solve
    p=make_project(tmp_path)
    obs=[
        {'control_id':'CP1','northing':1000.00,'easting':2000.00,'elevation':100.00,'h_sigma':None,'v_sigma':None,'method':'GPS'},
        {'control_id':'CP1','northing':1000.06,'easting':1999.97,'elevation':100.03,'h_sigma':None,'v_sigma':None,'method':'GPS'},
        {'control_id':'CP1','northing':999.97,'easting':2000.03,'elevation':99.98,'h_sigma':None,'v_sigma':None,'method':'GPS'},
    ]
    import_observations(p.db,obs)
    d=solve(p.db,'CP1','ron_spreadsheet',horizontal_tolerance=0.10,vertical_tolerance=0.10)
    assert d['formula_status']=='VALIDATED_RON_WORKBOOK'
    assert d['count']==3
    assert d['northing']==pytest.approx(sum(x['northing'] for x in obs)/3)
    assert d['easting']==pytest.approx(sum(x['easting'] for x in obs)/3)
    assert d['elevation']==pytest.approx(sum(x['elevation'] for x in obs)/3)
    assert [r['spreadsheet_label'] for r in d['residuals']]==['A-Avg','B-Avg','C-Avg']
    # Workbook C-row VZ formula is Avg-Elev, opposite the conventional signed dz.
    assert d['residuals'][2]['spreadsheet_vz']==pytest.approx(-d['residuals'][2]['dz'])


def test_ron_three_point_profile_requires_exactly_three_shots(tmp_path):
    from surveysync.control import import_observations, solve
    p=make_project(tmp_path)
    import_observations(p.db,[
        {'control_id':'CP1','northing':1,'easting':2,'elevation':3,'h_sigma':None,'v_sigma':None,'method':'GPS'},
        {'control_id':'CP1','northing':2,'easting':3,'elevation':4,'h_sigma':None,'v_sigma':None,'method':'GPS'},
    ])
    with pytest.raises(ValueError,match='exactly three'):
        solve(p.db,'CP1','ron_spreadsheet')


def test_ron_three_wire_profile_uses_three_reading_average_and_stadia_formula():
    obs=[{
        'point_id':'TP1',
        'bs_upper':5.31,'bs_middle':5.20,'bs_lower':5.10,
        'fs_upper':4.50,'fs_middle':4.39,'fs_lower':4.30,
    }]
    bs_avg=(5.31+5.20+5.10)/3
    fs_avg=(4.50+4.39+4.30)/3
    known_end=100.0+bs_avg-fs_avg
    d=solve_level_run(obs,start_elevation=100.0,known_end_elevation=known_end,adjustment_method='none',calculation_profile='ron_workbook')
    assert d['formula_status']=='VALIDATED_RON_WORKBOOK'
    assert d['sum_bs']==pytest.approx(bs_avg)
    assert d['sum_fs']==pytest.approx(fs_avg)
    assert d['results'][0]['distance_bs']==pytest.approx((5.31-5.10)*100)
    assert d['results'][0]['distance_fs']==pytest.approx((4.50-4.30)*100)
    assert d['results'][0]['stadia_difference']==pytest.approx(1.0)
    assert d['raw_end_elevation']==pytest.approx(known_end)
    assert d['closure']==pytest.approx(0.0,abs=1e-12)


def test_source_windows_launcher_hides_bootstrap_console_by_default():
    root = Path(__file__).resolve().parents[1]
    bat = (root / 'run_windows.bat').read_text(encoding='utf-8', errors='ignore')
    vbs = (root / 'launch_hidden.vbs').read_text(encoding='utf-8', errors='ignore')
    bootstrap = (root / 'bootstrap_windows.py').read_text(encoding='utf-8', errors='ignore')
    assert 'launch_hidden.vbs' in bat
    assert '--hidden' in bat
    assert '--console' in bat
    assert 'wscript.exe' in bat.lower()
    assert 'shell.Run command, 0, False' in vbs
    assert 'bootstrap.log' in bootstrap
    assert 'MessageBoxW' in bootstrap
