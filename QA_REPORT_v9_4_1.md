# SurveySync 9.4.1 QA

Versioned validation is required: unchanged full release gate, new updater regressions, both native Go component test suites, 11-module light/dark and 16-theme browser checks, actual Inno installation, native file-picker/report/Exit and project reopening. The complete replacement test uses the actual new installer and verifies projects/settings/sources after reopening. Evidence distinguishes an internal version-only predecessor from the known old-release manual-close migration limitation.

At source preparation these checks are pending. The CI evidence JSON/logs identify the executed commit and exact executable checksum; no prospective test result is presented as completed. Publication is blocked on acceptance failures. No tests are skipped to permit distribution and the coverage floor stays 54%.
