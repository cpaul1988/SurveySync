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

## Installed lifecycle follow-up

Resumed head `f9b21e1114b2f04ccdce2ef8866f5730ee524032` passed Quality, Native Security, UI Validation and Remaining Audit. Native Security and UI evidence explicitly show no threats in both rebuilt native files, and UI Validation also scanned its complete installer. Defender engine 1.1.26090.9 / definitions 1.461.64.0, all protection flags active, unchanged pre/post hashes. No Microsoft analyst verdict is claimed.

Installed Repair run **38995899435** passed installation, native controls, exports and shutdown/reopen, then failed **1 of 24** stress cycles (cycle 22). The other 23 passed. The child Python runtime exited with access violation `0xc0000005` during shutdown; the native launcher correctly displayed the unexpected-exit dialog. Evidence archive **12087506655** is retained. This failure is not an antivirus detection and is not counted as successful acceptance. The Windows full regression gate recorded **775 passed, 1 skipped, 1 warning**.

Inspection found an unsafe cleanup boundary: the HTTP service was a daemon thread, a timed join did not confirm it had stopped, and the session was marked clean before drainage. The follow-up uses a non-daemon server, always requests graceful stop on normal exit or WebView startup failure, joins the service before closing project storage, and writes the clean-session marker only after successful cleanup. It neither force-kills a process nor lengthens/removes the native acceptance deadlines. The exact cause of the native memory fault is not conclusively attributed from the available stack; the unsafe ordering is corrected and must pass another full installed run.

Focused local verification of this follow-up: **51 passed**, including five new shutdown-order contracts, existing exit/watch contracts, resource-conversion tests and security-evidence tests. Static and release-documentation gates also pass. Final Windows stress/upgrade acceptance of the follow-up is pending at this written checkpoint. Public Beta/Stable feeds remain held.
