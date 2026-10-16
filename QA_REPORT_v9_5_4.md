# SurveySync 9.5.4-beta.1 QA checkpoint

## Scope

Security-related build hardening after Defender detected Trojan:Win32/Bearfoos.A!ml in a user's 9.5.3 launcher. No antivirus bypass or project-data migration is part of the change. FBR-0018 remains implemented.

## Original 9.5.3 analysis, not candidate clearance

Exact installer extracted without execution; 207 comparable shipped source files matched the tested source snapshot. Extracted launchers identify Go 1.23.12. Updated Defender on an isolated Windows runner did not detect either original launcher; the recorded bytes survived unchanged. See original investigation run 38949172536 and docs/SECURITY_INCIDENT_953.md. Linux cross-compiler reproduction produced different hashes and is not treated as a source/binary identity proof; matching-host Windows reproduction is tracked separately.

## Candidate checks

The initial 20 local evidence-validator tests passed. Added integration cases also require security-hold errors and two build-time scan boundaries. All current regression counts, Windows SDK resource builds, native runtime behavior, Defender scans of the new executable/installer, installed lifecycle and update replacement must be obtained from this candidate's actual CI results. They are **pending at this written checkpoint**; no earlier run is substituted.

All scan results must identify engine/signature versions, real-time and antivirus state, exact pre/post file hashes and raw no-threat output. Missing, stale, modified, detected, or unknown-format scan results fail closed. Artifacts are not automatically published by these tests. The public update feeds remain held. Microsoft analyst clearance has not been obtained, and no guarantee is made about every workstation's cloud/reputation verdict.
