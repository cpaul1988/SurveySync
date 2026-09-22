from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ISS = (ROOT / 'installer' / 'FieldBookSync.iss').read_text(encoding='utf-8')
PROVISION = (ROOT / 'installer' / 'provision_runtime.ps1').read_text(encoding='utf-8')
BUILD = (ROOT / 'Build_Setup_EXE.bat').read_text(encoding='utf-8')


def test_installer_identity_and_scope():
    assert (ROOT / 'VERSION.txt').read_text(encoding='utf-8').strip() == '8.1.21'
    assert '#define MyAppPublisher "Clever Bird Development"' in ISS
    assert 'AppPublisher={#MyAppPublisher}' in ISS
    assert 'DefaultDirName={localappdata}\\Programs\\FieldBookSync' in ISS
    assert 'PrivilegesRequired=lowest' in ISS
    assert 'OutputBaseFilename=FieldBookSync_Setup_8.1.21' in ISS
    assert 'SetupIconFile=..\\branding\\FieldBookSync.ico' in ISS


def test_installer_shortcuts_and_fbs_association():
    assert 'Name: "desktopicon"' in ISS
    assert 'Name: "fbsassoc"' in ISS
    assert 'Software\\Classes\\.fbs' in ISS
    assert 'FieldBookSync.Project' in ISS
    assert '.venv\\Scripts\\pythonw.exe' in ISS


def test_runtime_is_private_and_signature_checked():
    assert '$PythonVersion = "3.12.10"' in PROVISION
    assert 'Python Software Foundation' in PROVISION
    assert 'TargetDir=`"$RuntimeDir`"' in PROVISION
    assert 'InstallAllUsers=0' in PROVISION
    assert 'pip install --disable-pip-version-check -r $Req' in PROVISION
    assert 'setup_runtime.log' in PROVISION


def test_user_data_and_github_update_distribution_are_preserved():
    assert 'Join-Path $env:LOCALAPPDATA "FieldBookSync"' in PROVISION
    assert 'github_manifest' in PROVISION
    assert 'raw.githubusercontent.com/cpaul1988/FieldBookSync/main/update.json' in PROVISION
    # The Inno uninstaller cleans program-local runtimes only, not %LOCALAPPDATA%\\FieldBookSync.
    uninstall = ISS.split('[UninstallDelete]', 1)[1]
    assert '{localappdata}\\FieldBookSync' not in uninstall


def test_builder_outputs_hash_and_update_manifest():
    assert 'go build' in BUILD
    assert '-H=windowsgui' in BUILD
    assert 'FieldBookSync_Setup_8.1.21.exe' in BUILD
    assert 'Get-FileHash -Algorithm SHA256' in BUILD
    assert 'update.json' in BUILD


def test_local_ai_installers_prefer_bundled_runtime():
    cpu = (ROOT / 'install_paddleocr_local.bat').read_text(encoding='utf-8')
    auto = (ROOT / 'install_paddleocr_auto.bat').read_text(encoding='utf-8')
    gpu = (ROOT / 'Install_PaddleOCR_GPU_Optional.bat').read_text(encoding='utf-8')
    assert 'runtime\\python.exe' in cpu
    assert 'runtime\\python.exe' in auto
    assert 'runtime\\python.exe' in gpu
