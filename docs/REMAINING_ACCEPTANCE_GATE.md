# Remaining-audit acceptance — unreleased

The 37-file source payload was imported after validating every before/after digest. Raw normalized payload SHA-256: `1696bb190b43ef74910e7431b59b19fc8f498c034fed16426d44af14b943e096`. The locked Ruff formatter then formatted changed governed files without changing the quality policy.

A fresh local Linux/Python 3.13 run of the release test selection recorded **563 passed, 1 skipped**. This includes 47 new remaining-audit/preservation cases. This is not a claim of Windows/browser acceptance. Local Chromium navigation is blocked by host policy; the test was not bypassed. Authorized repository Windows runners execute real panel controls and retain screenshots and traces.

The new acceptance workflow installs LAS/LAZ decoders only into the disposable QA environment, exercises real LAS and LAZ sampling, and runs actual QGIS and GRASS calculations on a separate Linux runner. Existing Quality, UI Validation and Repair Acceptance workflows remain unchanged and required. Missing runtime checks are not counted as external execution success.

All work is isolated on `fix-v9.4.1-remaining-audit`. The current internal version remains 9.4.1 solely for regression compatibility. Do not distribute its installer as the published 9.4.1; a separately identified candidate is required. No release tag, Stable feed, production signature policy or main merge is changed.

Signature support is preparation only: no production key, trusted signing identity or certificate is generated. The shipped dependency lock must include the Ed25519 verifier before requiring signed manifests. Real-world OCR/provider, Trimble and rod-height calibration still require data/runtime evidence; synthetic tests cannot establish field accuracy.
