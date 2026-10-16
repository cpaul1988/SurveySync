# SurveySync 9.5.4-beta.1 — security build and artifact validation

This candidate retains the shared project, persistent FieldBookSync pane, common navigation and themes from FBR-0018 while hardening the Windows build and release checks after the 9.5.3 Defender report.

- Native builds require pinned Go 1.27.2 and include product/company/version/icon resources and an asInvoker manifest generated with Microsoft Windows SDK tools.
- Native symbols/debug metadata are retained for diagnosis. No obfuscation, antivirus exclusions, restoration, or protection-disable steps are introduced.
- The signed-or-explicitly-unsigned launchers are scanned before packaging, and the final installer is scanned after the signing step. Active Defender, fresh security intelligence, explicit no-threat output, and unchanged artifact hashes are required. Missing evidence fails closed.
- Scan logs, engine versions and exact file identities are validated and retained outside the installed application.
- New clients report an explicit security-review message when an update channel is on hold.

9.5.3 remains withdrawn. The exact original launcher/updater did not reproduce the detection on a fresh Windows Defender test runner, but Microsoft has not issued analyst clearance. Signing is not configured merely by adding product metadata. See `docs/SECURITY_INCIDENT_953.md` and the candidate Actions evidence for measured outcomes.

Do not restore the old blocked launcher, add exclusions, or disable Windows protection. Existing project folders and data are not removed or converted by this packaging change. Candidate availability depends on successful artifact scanning and Windows acceptance; these notes are written before that validation completes.
