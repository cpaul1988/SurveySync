from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "fieldbook_sync" / "app.py").read_text(encoding="utf-8")
JS = (ROOT / "fieldbook_sync" / "static" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "fieldbook_sync" / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "fieldbook_sync" / "static" / "styles.css").read_text(encoding="utf-8")
LAUNCHER = (ROOT / "installer" / "app_launcher.go").read_text(encoding="utf-8")
SETUP = (ROOT / "installer" / "setup_ui.ps1").read_text(encoding="utf-8")
UPDATER = (ROOT / "installer" / "update_helper.go").read_text(encoding="utf-8")


def test_available_point_ranges_matches_crew_example():
    from fieldbook_sync.survey import available_point_ranges

    used = list(range(1000, 4001)) + list(range(10000, 14001))
    assert available_point_ranges(used) == [(4001, 9999), (14001, None)]


def test_point_range_extractor_uses_all_numeric_ids_not_code_profile():
    from fieldbook_sync.survey import extract_numeric_point_ids

    raw = StringIO(
        "PointID,Northing,Easting,Elevation,Code\n"
        "1000,1,2,3,CONTROL\n"
        "1001,1,2,3,NOT-A-STRUCTURE\n"
        "10000.0,1,2,3,OTHER\n"
        "A10002,1,2,3,ALPHA\n"
    )
    ids, skipped = extract_numeric_point_ids(raw)
    assert ids == [1000, 1001, 10000]
    assert skipped == 1


def test_point_range_csv_api_and_ui_are_exposed():
    assert '@app.post("/api/survey/available-ranges")' in APP
    assert 'AvailableStart' in APP and 'AvailableEnd' in APP and 'AvailableRange' in APP
    assert 'INFINITY' in APP and '-infinity' in APP
    assert 'data-command="available-point-ranges"' in INDEX
    assert 'id="pointRangesBtn"' in INDEX
    assert 'downloadAvailablePointRanges' in JS


def test_help_update_dot_checks_silently_at_startup():
    assert 'id="helpMenuTrigger"' in INDEX
    assert '.menu-trigger.has-update::after' in CSS
    assert 'refreshUpdateNotification' in JS
    assert "setTimeout(refreshUpdateNotification,1500)" in JS
    assert "setInterval(refreshUpdateNotification,6*60*60*1000)" in JS


def test_update_handoff_waits_until_launcher_has_exited():
    assert 'pending_update.json' in APP
    assert '"handoff": "launcher"' in APP
    assert 'launchPendingUpdate' in LAUNCHER
    assert 'FieldBookSyncUpdater.exe' in LAUNCHER
    assert '--launcher-pid' in LAUNCHER
    assert 'waitForLauncherExit(*launcherPID, 45*time.Second)' in UPDATER
    assert 'WaitForSingleObject' in UPDATER
    assert 'cmd := exec.Command(installer)' in UPDATER
    assert "Wait-ForFieldBookSyncExit" in SETUP
