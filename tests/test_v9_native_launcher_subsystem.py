from pathlib import Path
import struct
import pytest

ROOT = Path(__file__).resolve().parents[1]


def pe_subsystem(path: Path) -> int:
    data = path.read_bytes()
    assert data[:2] == b"MZ"
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[pe_offset:pe_offset + 4] == b"PE\0\0"
    optional_header = pe_offset + 4 + 20
    # IMAGE_OPTIONAL_HEADER{32,64}.Subsystem is at +68 bytes.
    return struct.unpack_from("<H", data, optional_header + 68)[0]


def test_shipped_native_launchers_use_windows_gui_subsystem():
    if not (ROOT / "SurveySync.exe").exists():
        pytest.skip("Source package: native binaries are verified after Go compilation by the Windows build.")
    assert pe_subsystem(ROOT / "SurveySync.exe") == 2
    assert pe_subsystem(ROOT / "SurveySyncUpdater.exe") == 2


def test_release_workflow_always_builds_gui_subsystem_launchers():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "./Build_SurveySync.ps1" in workflow
    build = (ROOT / "Build_SurveySync.ps1").read_text(encoding="utf-8")
    lines = [line.strip() for line in build.splitlines() if "& $go.Source build" in line]
    app = next(line for line in lines if "app_launcher.go" in line)
    updater = next(line for line in lines if "update_helper.go" in line)
    assert "-H=windowsgui" in app
    assert "-H=windowsgui" in updater
