from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = (ROOT / 'installer' / 'app_launcher.go').read_text(encoding='utf-8')
HELPER = (ROOT / 'installer' / 'update_helper.go').read_text(encoding='utf-8')
SETUP = (ROOT / 'installer' / 'setup_ui.ps1').read_text(encoding='utf-8')
BUILD = (ROOT / 'Build_Setup_EXE.bat').read_text(encoding='utf-8')
PAYLOAD = (ROOT / 'installer' / 'build_payload.py').read_text(encoding='utf-8')
BOOTSTRAP = (ROOT / 'installer' / 'bootstrapper_main.go').read_text(encoding='utf-8')


def test_version_is_8121_everywhere_that_drives_runtime_identity():
    assert (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() == '8.1.21'
    assert 'const appVersion = "8.1.21"' in LAUNCHER
    assert 'const appVersion = "8.1.21"' in BOOTSTRAP
    assert "[string]$Version = '8.1.21'" in SETUP


def test_powershell_update_handoff_is_replaced_by_native_helper():
    assert 'FieldBookSyncUpdater.exe' in LAUNCHER
    assert 'launch_update.ps1' not in LAUNCHER
    assert 'powershell.exe' not in LAUNCHER
    assert '-o "..\\FieldBookSyncUpdater.exe" "update_helper.go"' in BUILD
    assert "Path('installer/update_helper.go')" in PAYLOAD


def test_launcher_requires_helper_heartbeat_before_exiting():
    assert 'update_helper_status.json' in LAUNCHER
    assert 'waitForHelperHeartbeat' in LAUNCHER
    assert '2500*time.Millisecond' in LAUNCHER
    assert 'state != "" && state != "started"' in LAUNCHER
    assert 'native updater helper did not report ready state' in LAUNCHER
    assert 'helperCmd.Process.Kill()' in LAUNCHER


def test_helper_logs_immediately_and_waits_for_exact_launcher_pid():
    assert 'update_helper.log' in HELPER
    assert 'FieldBook Sync Updater' in HELPER
    assert 'writeUpdaterStatus(*statusFile, status)' in HELPER
    assert 'waitForLauncherExit(*launcherPID, 45*time.Second)' in HELPER
    assert 'WaitForSingleObject' in HELPER
    assert 'waiting_for_launcher' in HELPER


def test_helper_reverifies_exe_and_only_clears_pending_after_setup_starts():
    assert 'sha256.Sum256(installerBytes)' in HELPER
    assert 'installer no longer has a Windows executable header' in HELPER
    assert 'cmd := exec.Command(installer)' in HELPER
    assert 'setupPID := cmd.Process.Pid' in HELPER
    assert 'status.State = "installer_started"' in HELPER
    start = HELPER.index('if err := cmd.Start(); err != nil')
    clear = HELPER.index('if err := os.Remove(*pendingFile)')
    assert clear > start


def test_stale_pending_updates_are_discarded_by_launcher_and_setup():
    assert 'discardStalePendingUpdate(logFile)' in LAUNCHER
    assert 'compareVersions(strings.TrimSpace(pending.Version), appVersion)' in LAUNCHER
    assert 'Discarded stale pending update' in LAUNCHER
    assert 'Clear-StalePendingUpdate' in SETUP
    assert '$pendingVersion -le $installedVersion' in SETUP
    assert "Remove-Item -LiteralPath $pendingPath -Force" in SETUP
    # setup also cleans the old v8.1.19/v8.1.20 PowerShell helper file if it exists.
    assert "updates\\launch_update.ps1" in SETUP


def test_bootstrapper_temp_folder_and_builder_use_8121():
    assert 'FieldBookSync_Setup_8_1_21_' in BOOTSTRAP
    assert 'FieldBookSync_Setup_8.1.21.exe' in BUILD
