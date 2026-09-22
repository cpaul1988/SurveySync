from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
BOOT = (ROOT / 'installer' / 'bootstrapper_main.go').read_text(encoding='utf-8')
SETUP = (ROOT / 'installer' / 'setup_ui.ps1').read_text(encoding='utf-8')

def test_v812_powershell_runs_sta_and_is_not_hidden():
    assert '"-STA"' in BOOT
    assert 'HideWindow: true' not in BOOT

def test_v812_wizard_heartbeats_to_bootstrap_log():
    assert '"-BootstrapLog", logFile' in BOOT
    assert 'Write-BootstrapLog' in SETUP
    assert 'PowerShell setup script entered' in SETUP
    assert 'Setup window shown' in SETUP

def test_v812_wizard_forces_visible_front_window():
    assert '$form.ShowInTaskbar = $true' in SETUP
    assert '$form.BringToFront()' in SETUP
    assert '$form.Activate()' in SETUP

def test_v812_version():
    assert "[string]$Version = '8.1.21'" in SETUP
