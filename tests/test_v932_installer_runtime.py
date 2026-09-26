from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_landxml_startup_has_no_required_extra_runtime_dependency():
    requirements_in = (ROOT / "requirements.in").read_text(encoding="utf-8")
    requirements_lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    provisioner = (ROOT / "installer" / "provision_runtime.ps1").read_text(encoding="utf-8")
    landxml = (ROOT / "surveysync" / "landxml_io.py").read_text(encoding="utf-8")

    assert "try:" in landxml
    assert "from defusedxml import ElementTree as SafeET" in landxml
    assert "except ImportError" in landxml
    assert "defusedxml>=0.7,<1" not in requirements_in
    assert "defusedxml==0.7.1" not in requirements_lock
    assert "import surveysync.landxml_io,surveysync.router" in provisioner
    assert "fieldbook_sync.app" not in provisioner


def test_installer_uses_production_lock_not_dev_lock():
    provisioner = (ROOT / "installer" / "provision_runtime.ps1").read_text(encoding="utf-8")

    assert '$Req = Join-Path $InstallDir "requirements.lock"' in provisioner
    assert "requirements-dev.lock" not in provisioner
