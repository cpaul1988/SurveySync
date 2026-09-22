from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISS = (ROOT / "installer" / "SurveySync.iss").read_text(encoding="utf-8")


def test_v9_keeps_fieldbooksync_app_identity_for_in_place_upgrade():
    assert "AppId={{D7432040-46E5-4F2B-A9AC-97B2DB7BAF4B}" in ISS
    assert "DefaultDirName={localappdata}\\Programs\\SurveySync" in ISS
    assert "UsePreviousAppDir=yes" in ISS


def test_v9_migrates_fbs_association_to_surveysync():
    assert "ChangesAssociations=yes" in ISS
    assert 'ValueData: "SurveySync.Project"' in ISS
    assert '"{app}\\SurveySync.exe"" ""%1""' in ISS
    assert 'Subkey: "Software\\Classes\\FieldBookSync.Project"; Flags: deletekey' in ISS


def test_v9_removes_only_legacy_program_artifacts_not_user_data():
    assert '[InstallDelete]' in ISS
    assert 'Name: "{app}\\FieldBookSync.exe"' in ISS
    assert 'Name: "{autodesktop}\\FieldBook Sync.lnk"' in ISS
    # Never delete the legacy user data root during migration.
    install_delete = ISS.split('[InstallDelete]', 1)[1].split('[Registry]', 1)[0]
    actionable = "\n".join(line for line in install_delete.splitlines() if not line.lstrip().startswith(";"))
    assert "LOCALAPPDATA" not in actionable.upper()
    assert "project.json" not in install_delete
    assert "*.fbs" not in install_delete
