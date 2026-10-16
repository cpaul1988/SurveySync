from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from scripts.validate_security_evidence import validate, validate_file

NOW = datetime(2026, 10, 16, 18, 40, tzinfo=timezone.utc)
SHA = 'a' * 64


def evidence():
    return {
        'schema_version': 1, 'result': 'passed', 'completed_utc': NOW.isoformat(),
        'defender': {'AMServiceEnabled': True, 'AntivirusEnabled': True,
                    'RealTimeProtectionEnabled': True, 'AMEngineVersion': 'test-engine',
                    'AntivirusSignatureVersion': 'test-signature',
                    'AntivirusSignatureLastUpdatedUtc': (NOW-timedelta(hours=1)).isoformat()},
        'scans': [{'name': 'SurveySync.exe', 'exit_code': 0, 'mode': 'custom-detection-only',
                   'threat_detected': False, 'sha256_before': SHA, 'sha256_after': SHA,
                   'exists_after': True, 'output_sha256': 'b'*64}],
    }


def test_exact_scan_passes():
    validate(evidence(), {'SurveySync.exe': SHA}, now=NOW)


@pytest.mark.parametrize('field,value', [
    ('exit_code', 2), ('exit_code', False), ('exit_code', '0'),
    ('threat_detected', True), ('threat_detected', None),
    ('mode', 'ordinary-remediating-scan'), ('exists_after', False),
    ('sha256_after', 'c'*64), ('sha256_before', 'bad'), ('output_sha256', None),
])
def test_rejects_detection_or_incomplete_evidence(field, value):
    r=evidence(); r['scans'][0][field]=value
    with pytest.raises(ValueError): validate(r, {'SurveySync.exe': SHA}, now=NOW)


@pytest.mark.parametrize('flag', ['AMServiceEnabled','AntivirusEnabled','RealTimeProtectionEnabled'])
def test_disabled_protection_is_not_a_clean_scan(flag):
    r=evidence(); r['defender'][flag]=False
    with pytest.raises(ValueError): validate(r, {'SurveySync.exe': SHA}, now=NOW)


def test_empty_duplicate_or_wrong_artifacts_fail():
    for scans in ([], evidence()['scans']*2):
        r=evidence(); r['scans']=scans
        with pytest.raises(ValueError): validate(r, {'SurveySync.exe': SHA}, now=NOW)
    with pytest.raises(ValueError): validate(evidence(), {'Other.exe': SHA}, now=NOW)


@pytest.mark.parametrize('hours', [-1, 49])
def test_stale_or_future_report_fails(hours):
    r=evidence(); r['completed_utc']=(NOW-timedelta(hours=hours)).isoformat()
    with pytest.raises(ValueError): validate(r, {'SurveySync.exe': SHA}, now=NOW)


def test_stale_signatures_and_unknown_result_fail():
    r=evidence(); r['defender']['AntivirusSignatureLastUpdatedUtc']=(NOW-timedelta(days=3)).isoformat()
    with pytest.raises(ValueError): validate(r, {'SurveySync.exe': SHA}, now=NOW)
    r=evidence(); r['result']='unavailable'
    with pytest.raises(ValueError): validate(r, {'SurveySync.exe': SHA}, now=NOW)


def test_actual_bytes_and_logs_are_verified(tmp_path):
    artifact=tmp_path/'SurveySync.exe'; artifact.write_bytes(b'MZtest-artifact')
    log=tmp_path/'scan.txt'; log.write_text('Scanning fixture found no threats.\n')
    r=evidence(); r['completed_utc']=datetime.now(timezone.utc).isoformat()
    r['defender']['AntivirusSignatureLastUpdatedUtc']=datetime.now(timezone.utc).isoformat()
    s=r['scans'][0]; s['sha256_before']=s['sha256_after']=hashlib.sha256(artifact.read_bytes()).hexdigest()
    s['output_file']=log.name; s['output_sha256']=hashlib.sha256(log.read_bytes()).hexdigest()
    report=tmp_path/'security-scan.json'; report.write_text(json.dumps(r))
    validate_file(report,[artifact])
    artifact.write_bytes(b'MZchanged')
    with pytest.raises(ValueError): validate_file(report,[artifact])
    artifact.write_bytes(b'MZtest-artifact'); log.write_text('changed log')
    with pytest.raises(ValueError): validate_file(report,[artifact])


def test_scan_gate_has_no_protection_bypass():
    source=(Path(__file__).resolve().parents[1]/'scripts/scan_windows_artifacts.ps1').read_text()
    for forbidden in ('Add-MpPreference', 'Set-MpPreference', '-ExclusionPath', '-Restore', 'Set-ExecutionPolicy'):
        assert forbidden not in source
    assert '-DisableRemediation' in source  # documented, detection-only custom scan


def test_updater_security_hold_is_fail_closed():
    from surveysync.updater import select_release
    with pytest.raises(ValueError, match='suspended for security'):
        select_release({'release_hold': {'active': True, 'channels': ['beta','stable']}, 'channels': {}}, 'stable')


def test_build_scans_both_native_and_packaged_bytes():
    root=Path(__file__).resolve().parents[1]
    source=(root/'Build_SurveySync.ps1').read_text()
    assert source.count("scripts\\scan_windows_artifacts.ps1") == 2
    assert source.index("security-evidence/native") < source.index('& $Iscc') < source.index("security-evidence/installer")
    assert (root/'GO_VERSION.txt').read_text().strip() == '1.27.2'
    assert 'security-evidence\\*' in (root/'installer/SurveySync.iss').read_text()
