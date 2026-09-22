import os
from pathlib import Path
from fastapi.testclient import TestClient


def test_v9_api_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path/"config"))
    # Imports happen here so config location is test-local.
    from fieldbook_sync.app import app
    from surveysync import router as r
    r.config_store = r.ConfigStore(tmp_path/"config")
    r.current_project = None
    client=TestClient(app)
    root=client.get('/'); assert root.status_code==200 and 'SurveySync' in root.text
    res=client.post('/api/v9/project/create',json={"parent_folder":str(tmp_path),"name":"API Project","crs":"EPSG:2278","horizontal_units":"us_survey_feet","vertical_units":"us_survey_feet"})
    assert res.status_code==200, res.text
    st=client.get('/api/v9/status').json(); assert st['project']['name']=='API Project'
    inv=client.post('/api/v9/cogo/inverse',json={"n1":0,"e1":0,"n2":3,"e2":4}); assert inv.status_code==200 and inv.json()['distance']==5
    qa=client.post('/api/v9/qa/run'); assert qa.status_code==200
    fb=client.get('/fieldbook'); assert fb.status_code==200 and 'SurveySync' in fb.text

def test_project_switch_isolates_fieldbook_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path/"cfg_switch"))
    from fieldbook_sync import app as field_app
    from surveysync import router as r
    r.config_store = r.ConfigStore(tmp_path/"cfg_switch"); r.current_project=None
    client=TestClient(field_app.app)
    a=client.post('/api/v9/project/create',json={"parent_folder":str(tmp_path),"name":"A","crs":"","horizontal_units":"us_survey_feet","vertical_units":"us_survey_feet"}).json()
    field_app.runtime.storage.state.project_name='Only A'; field_app.runtime.storage.save()
    root_a=field_app.runtime.storage.root; db_a=field_app.runtime.job_store.path
    b=client.post('/api/v9/project/create',json={"parent_folder":str(tmp_path),"name":"B","crs":"","horizontal_units":"us_survey_feet","vertical_units":"us_survey_feet"}).json()
    assert field_app.runtime.storage.state.project_name != 'Only A'
    root_b=field_app.runtime.storage.root; db_b=field_app.runtime.job_store.path
    assert root_a != root_b and db_a != db_b
    client.post('/api/v9/project/open',json={"path":a['root']})
    assert field_app.runtime.storage.state.project_name=='Only A'
    assert field_app.runtime.storage.root==root_a

def test_v9_navigation_shell_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path/"cfg_ui"))
    from fieldbook_sync.app import app
    client=TestClient(app)
    root=client.get('/').text
    assert '<title>SurveySync v9.3.0</title>' in root
    assert 'data-menu="fileMenu">File</button>' in root
    assert 'data-menu="viewMenu">View</button>' in root
    assert 'class="module-tabs"' in root
    for module in ('FieldBookSync','ControlSync','UtilitySync','TopoSync','COGOSync','BoundarySync','GISSync','ReportSync'):
        assert f'data-module="{module}"' in root
    assert 'class="module-sidebar"' in root
    assert 'Survey Sync' not in root

    fieldbook=client.get('/fieldbook').text
    assert 'class="surveysync-module-tabs"' in fieldbook
    assert 'class="sidebar"' in fieldbook
    assert '<span>SurveySync</span>' in fieldbook

def test_global_theme_and_globe_branding(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path/"cfg_theme"))
    from fieldbook_sync.app import app
    client=TestClient(app)
    root=client.get('/').text
    fieldbook=client.get('/fieldbook').text
    assert 'surveysync_globe.svg' in root
    assert 'surveysync_globe.svg' in fieldbook
    assert 'data-global-appearance="system"' in root
    assert 'data-global-appearance="light"' in root
    assert 'data-global-appearance="dark"' in root
    assert "surveysync-appearance" in root
    assert "surveysync-product-theme" in root
    assert "surveysync-appearance" in fieldbook
    assert "surveysync-product-theme" in fieldbook
    assert 'data-appearance-command="system"' in fieldbook


def test_shared_ui_preferences_persist_across_shells(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path/"cfg_shared_ui"))
    from fieldbook_sync.app import app
    from surveysync import router as r
    r.config_store = r.ConfigStore(tmp_path/"cfg_shared_ui"); r.current_project=None
    client=TestClient(app)
    res=client.post('/api/v9/config/ui',json={"appearance":"dark","theme":"graphite","accent":"amber"})
    assert res.status_code==200, res.text
    assert res.json()=={"appearance":"dark","theme":"graphite","accent":"amber"}
    got=client.get('/api/v9/config/ui')
    assert got.status_code==200
    assert got.json()=={"appearance":"dark","theme":"graphite","accent":"amber"}
    cfg=client.get('/api/v9/config').json()
    assert cfg["ui_appearance"]=="dark"
    assert cfg["ui_theme"]=="graphite"
    assert cfg["ui_accent"]=="amber"


def test_single_survey_sync_updater_is_exposed_in_both_shells(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path/"cfg_update_shell"))
    from fieldbook_sync.app import app
    from surveysync import router as r
    r.config_store = r.ConfigStore(tmp_path/"cfg_update_shell")
    client=TestClient(app)
    main=client.get('/').text
    fieldbook=client.get('/fieldbook').text
    assert 'Check & Update' in main
    assert 'Stage Verified Update' not in main
    assert 'Check & Update' in fieldbook
    assert 'FieldBookSync/main/update.json' not in fieldbook
    assert 'FieldBookSync/releases' not in fieldbook
    source=client.get('/api/update/source')
    assert source.status_code==200
    assert source.json()['managed_by_surveysync'] is True
    assert 'cpaul1988/SurveySync/main/update.json' in source.json()['manifest_url']


def test_fieldbook_update_check_is_survey_sync_managed(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path/"cfg_update_check"))
    from fieldbook_sync.app import app
    from surveysync import router as r
    from fieldbook_sync import app as field_app
    r.config_store = r.ConfigStore(tmp_path/"cfg_update_check")
    # Avoid network: compatibility route delegates to shared updater helper.
    monkeypatch.setattr(field_app, 'surveysync_update_check', lambda store: {
        'version':'9.3.0','channel':'stable','update_available':False,'required':False,'release_notes':''
    })
    client=TestClient(app)
    res=client.get('/api/update/check')
    assert res.status_code==200
    body=res.json()
    assert body['mode']=='managed_by_surveysync'
    assert body['current_version']=='9.3.0'
    assert body['available'] is False


def test_one_button_update_route_reports_up_to_date(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path/"cfg_one_button"))
    from fieldbook_sync.app import app
    from surveysync import router as r
    r.config_store = r.ConfigStore(tmp_path/"cfg_one_button")
    monkeypatch.setattr(r, 'update_check', lambda store: {
        'version':'9.3.0','channel':'stable','update_available':False,'required':False,'release_notes':''
    })
    client=TestClient(app)
    res=client.post('/api/v9/update/check-and-install')
    assert res.status_code==200, res.text
    body=res.json()
    assert body['action']=='up_to_date'
    assert 'up to date' in body['message'].lower()


def test_project_manager_recent_switch_forget_and_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path/"cfg_projects"))
    from fieldbook_sync import app as field_app
    from surveysync import router as r
    r.config_store = r.ConfigStore(tmp_path/"cfg_projects")
    r.current_project = None
    client = TestClient(field_app.app)

    a = client.post('/api/v9/project/create', json={
        "parent_folder": str(tmp_path), "name": "Project A", "crs": "EPSG:2278",
        "horizontal_units": "us_survey_feet", "vertical_units": "us_survey_feet"
    }).json()
    b = client.post('/api/v9/project/create', json={
        "parent_folder": str(tmp_path), "name": "Project B", "crs": "EPSG:2278",
        "horizontal_units": "us_survey_feet", "vertical_units": "us_survey_feet"
    }).json()

    recent = client.get('/api/v9/projects/recent')
    assert recent.status_code == 200, recent.text
    rows = recent.json()['projects']
    assert [x['name'] for x in rows[:2]] == ['Project B', 'Project A']
    assert rows[0]['active'] is True

    switched = client.post('/api/v9/project/open', json={"path": a['root']})
    assert switched.status_code == 200, switched.text
    rows = client.get('/api/v9/projects/recent').json()['projects']
    assert [x['name'] for x in rows[:2]] == ['Project A', 'Project B']
    assert rows[0]['active'] is True

    forgotten = client.post('/api/v9/project/forget', json={"path": b['root']})
    assert forgotten.status_code == 200, forgotten.text
    assert Path(b['root']).exists()
    assert [x['name'] for x in client.get('/api/v9/projects/recent').json()['projects']] == ['Project A']

    bad_delete = client.post('/api/v9/project/delete', json={"path": a['root'], "confirm_name": "wrong"})
    assert bad_delete.status_code == 400
    assert Path(a['root']).exists()

    deleted = client.post('/api/v9/project/delete', json={"path": a['root'], "confirm_name": "Project A"})
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()['was_active'] is True
    assert not Path(a['root']).exists()
    assert client.get('/api/v9/status').json()['project'] is None
    assert client.get('/api/v9/projects/recent').json()['projects'] == []


def test_project_manager_controls_are_in_shell(tmp_path, monkeypatch):
    monkeypatch.setenv("SURVEYSYNC_CONFIG_ROOT", str(tmp_path/"cfg_project_shell"))
    from fieldbook_sync.app import app
    client = TestClient(app)
    root = client.get('/').text
    assert 'data-command="manage-projects"' in root
    assert 'id="projectsBtn"' in root
    assert 'Switch / Manage Projects' in root
    fieldbook = client.get('/fieldbook').text
    assert 'data-command="surveysync-projects"' in fieldbook
    assert 'Switch SurveySync Project' in fieldbook
