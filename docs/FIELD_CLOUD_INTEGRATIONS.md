# SurveySync Field Cloud Integrations

## Trimble Connect
SurveySync's Trimble adapter is built around Trimble Connect's supported user-context API. Tokens are session-only and are not written to the SurveySync project. A production deployment should register a Trimble Connect application and use OAuth Authorization Code + PKCE with a localhost callback for the desktop application. The current integration can list accessible projects with a session access token and import an explicitly supplied authorized cloud file URL into SurveySync's immutable source registry.

## Leica ConX
Leica documents field/office transfer between Captivate/Infinity and ConX. A general public ConX developer REST contract was not located during implementation, so SurveySync does **not** hardcode guessed/private endpoints. The adapter accepts an official authenticated file/API URL when a Leica account/integration provides one. Until an official API contract is supplied, ConX exports can also be imported through the normal spatial/raw-data import pipeline.

## Security
- Cloud passwords/tokens are not stored in SurveySync project files.
- Survey source files are copied into the immutable source registry on import.
- Every cloud import creates an audit event and cloud-sync log entry.


## 9.3.0 engineering hardening

See `ENGINEERING_STANDARDS.md` and the root `RELEASE_NOTES_v9_3_0.md` for shared release gates, dependency locks, domain extraction, diagnostics and standalone TopoSync rod-height range QC. Windows acceptance and distribution signing remain outstanding.
