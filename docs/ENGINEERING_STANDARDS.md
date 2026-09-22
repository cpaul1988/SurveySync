# SurveySync 9.3.0 engineering standards

## Release contract

`python scripts/release_gate.py` is the single release-quality entry point. It runs documentation and static safety checks, whole-application undefined-name linting, formatting on extracted/new modules, gradual type checks, compileall, every bundled JavaScript syntax check, regressions with a 54% whole-application line-coverage floor, and all-platform vulnerability audits. Missing tools, unavailable vulnerability services and failed checks block completion. GitHub release and quality workflows use this same gate. Local release flags cannot bypass it or reuse old launchers.

The 54% floor reflects the measured baseline, not production-quality completeness. Coverage measures both application packages; it is not inflated by limiting measurement to small new files. Real Windows/WebView, OCR models, hardware and survey acceptance remain separate requirements. Formatting/type adoption is gradual; unconverted legacy code is not described as fully linted or typed.

## Dependencies

Requirements `.in` files describe intended dependencies. Committed `.lock` files specify exact transitive versions, platform markers and SHA-256 hashes. Requirements `.txt` wrappers require hashes. Windows setup and bootstrap install the core lock; optional Windows-AI integration uses its own constrained lock and remains best effort.

Regenerate intentionally with the pinned uv tool, then run the shared gate:

```
uv pip compile requirements.in --universal --python-version 3.12 --generate-hashes -o requirements.lock
uv pip compile requirements-dev.in -c requirements.lock --universal --python-version 3.12 --generate-hashes -o requirements-dev.lock
uv pip compile requirements-windows-ai.in -c requirements.lock --universal --python-version 3.12 --generate-hashes -o requirements-windows-ai.lock
```

Do not silently refresh locks during installer execution. Optional PaddleOCR/GPU environments are separate and are not yet covered by these core/Windows-AI locks. Build backend/toolchain acquisition and optional OCR model downloads are not a fully hermetic build; Python locking does not make that claim.

`audit_locks.py` audits the union of all exact package/version pins without evaluating away Windows markers. It never installs platform packages to audit them. Hash verification happens during package installation. A clean audit means no known advisory was found at the time, not proof of absence of vulnerabilities.

## Architecture and data integrity

API input models live separately from process state. Control math and report writers are separated from database orchestration. Domain routers retain URL contracts and are composed once. FieldBookSync vision/live/batch processing is separated from route orchestration. During this transition, explicit per-request imports of the application context preserve the active runtime; capturing an old runtime during project switching is prohibited.

Compatibility reexports are intentional. New modules should depend on narrow services; the remaining application-context dependencies should be replaced incrementally with explicit interfaces. The remaining root modules still warrant further reduction, but may not grow beyond their new ceilings. This release does not claim to have eliminated all legacy coupling.

No survey schema migration or automatic elevation correction is introduced. Preserve source evidence, coordinate pairs, PointIDs and analysis revision checks. Unexpected failures must retain a diagnostic trail. Boundary record geometry remains unadjusted.

## Distribution

Authenticode signing and cryptographically signed update manifests are not configured. Do not call a download signed merely because SHA-256 matches. A future signing rollout needs an approved certificate/service, protected credentials, timestamping and publisher verification; private keys must never enter source control. Stable promotion preserves the exact tested Beta installer hash and still requires human acceptance testing.
