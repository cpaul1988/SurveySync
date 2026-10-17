# SurveySync 9.5.4-beta.1 QA checkpoint

## Scope

Security-related build hardening after Defender detected Trojan:Win32/Bearfoos.A!ml in a user's 9.5.3 launcher. No antivirus bypass or project-data migration is part of the change. FBR-0018 remains implemented.

## Original 9.5.3 analysis, not candidate clearance

Exact installer extracted without execution; 207 comparable shipped source files matched the tested source snapshot. Extracted launchers identify Go 1.23.12. Updated Defender on an isolated Windows runner did not detect either original launcher; the recorded bytes survived unchanged. See original investigation run 38949172536 and docs/SECURITY_INCIDENT_953.md. Linux cross-compiler reproduction produced different hashes and is not treated as a source/binary identity proof; matching-host Windows reproduction is tracked separately.

## Candidate checks

The initial 20 local evidence-validator tests passed. Added integration cases also require security-hold errors and two build-time scan boundaries. All current regression counts, Windows SDK resource builds, native runtime behavior, Defender scans of the new executable/installer, installed lifecycle and update replacement must be obtained from this candidate's actual CI results. They are **pending at this written checkpoint**; no earlier run is substituted.

All scan results must identify engine/signature versions, real-time and antivirus state, exact pre/post file hashes and raw no-threat output. Missing, stale, modified, detected, or unknown-format scan results fail closed. Artifacts are not automatically published by these tests. The public update feeds remain held. Microsoft analyst clearance has not been obtained, and no guarantee is made about every workstation's cloud/reputation verdict.

## Resumed build correction

The interrupted candidate at `f7916ed18f49f195c44db31e6a19998794d43096` passed Quality and Remaining Audit checks but failed native compilation with `sectnum < 0!` before candidate scans could run (Native Security run 38953507213). Microsoft CVTRES emits absolute compiler metadata that Go's internal COFF linker rejects.

The correction retains Microsoft RC and copies its numeric icon/version/manifest payloads byte-for-byte into a minimal read-only AMD64 COFF resource object with positive section symbols. This replaces only the intermediate object wrapper, not executable instructions, and adds no external package. Go linker and PE-format requirements are documented in `scripts/res_to_coff.py`. Both actual product resource checks and all antivirus gates remain mandatory.

Local validation: **42 tests passed**, comprising 20 resource-conversion/real cross-link cases and 22 existing security-evidence cases. The cross-link test builds but never executes a PE and independently checks that its linked resource bytes match its input. Windows build, Defender, installer and lifecycle acceptance of this correction must be read from its new CI runs; they are not claimed complete in this checkpoint.
