from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_installed_runtime_declares_landxml_startup_dependency():
    requirements_in = (ROOT / "requirements.in").read_text(encoding="utf-8")
    requirements_lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    provisioner = (ROOT / "installer" / "provision_runtime.ps1").read_text(encoding="utf-8")
    landxml = (ROOT / "surveysync" / "landxml_io.py").read_text(encoding="utf-8")

    assert "from defusedxml import ElementTree as SafeET" in landxml
    assert "defusedxml>=0.7,<1" in requirements_in
    assert "defusedxml==0.7.1" in requirements_lock
    assert "openpyxl,defusedxml" in provisioner
    assert "import surveysync.router,fieldbook_sync.app" in provisioner


def test_installer_uses_production_lock_not_dev_lock():
    provisioner = (ROOT / "installer" / "provision_runtime.ps1").read_text(encoding="utf-8")

    assert '$Req = Join-Path $InstallDir "requirements.lock"' in provisioner
    assert "requirements-dev.lock" not in provisioner
