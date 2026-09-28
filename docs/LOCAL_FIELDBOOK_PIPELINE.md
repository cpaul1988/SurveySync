# Private field-book candidate: 9.4.2-beta.2

## Processing and privacy

FieldBookSync now rejects cloud providers at settings, analysis startup, second-opinion and provider-call boundaries. Previously saved cloud selections start in Automatic local mode. Existing credentials are not deleted. Local requests use literal loopback endpoints, bypass environment proxies/netrc and reject redirects. Before Ollama receives document bytes, its model metadata must identify local weights; remote/cloud aliases and unverified metadata are blocked. This does not provide an operating-system firewall or attest a malicious local service. Disable Ollama Cloud in its own configuration (`OLLAMA_NO_CLOUD=1` and restart), as documented at https://docs.ollama.com/faq . Model/package installation is a separate, explicitly initiated operation requiring downloads; document inference does not silently download a model or fall back to cloud.

## Images and evidence

The original rendered page remains authoritative. A separate grid-cleaned view lightens long, light-colored ruled lines while retaining dark strokes. Paddle document orientation/unwarping is also disabled and its old cache schema invalidated. Neither perspective warping nor deskew moves pixels: OCR coordinates remain aligned with the original. Original and cleaned views run sequentially through one isolated Paddle worker with separate content-addressed cache entries; both observations are retained. A cleaned view never replaces the original OCR pass. Old derivatives are refreshed at analysis startup.

Semantic vision reads the original image. A small PointID locator expands to a bounded context region containing neighboring notes/sketches, rather than clipping to the ID's digits. That region is a context window, not an automatically proven structure boundary. Exact independent PointID evidence, disagreement gates and manual review still control acceptance. Wider context can contain adjacent structures; uncertain pipe-to-structure associations require review. This update does not claim automatic circle/leader segmentation or fully solved multi-directional handwriting.

Interpretation cache identity includes the current profile context and a new schema. Crops are regenerated from their current original image instead of trusting old crop filenames. Original images, survey coordinates and historical reports are not rewritten.

## Four-GB hardware and cancellation

For less than 6 GB dedicated VRAM, the performance plan keeps Paddle on CPU and reserves GPU memory for local vision. Existing Auto model selection prefers an installed 2B vision model for this hardware class; it does not install one. One-minute model retention limits idle residency without reloading for every crop. Actual fit, latency and accuracy on GTX 1650 Max-Q remain hardware acceptance items.

Ollama streams check cancellation between received chunks and before committing results, reject incomplete streams, close responses on failure, cap generated content and enforce a request deadline when chunks arrive. A blocked native/network read still has its configured timeout; this is not an immediate hard-cancel guarantee. Paddle retains its owned-process termination/checkpoint behavior.

## Verification and boundaries

Tests exercise real loopback HTTP with a deliberately unusable environment proxy, redirect rejection, cloud blocks before image reading, remote-model alias rejection, atomic settings rejection, preservation of dark strokes/source bytes/page dimensions, dual-view evidence and mixed-unit rod-height review. Historical cloud protocol/parser tests use entirely mocked transport to retain their provenance assertions; separate tests enforce production privacy.

A private BRT first-page visual check found six clearly readable structure IDs. Tesseract sparse-text baseline located 1/6 in the original and 0/6 in the cleaned view at the inspected resolution. This negative result motivated retaining both original and derivative passes; it is not evidence of Paddle/Qwen accuracy. Private pages and recognized contents are not committed to this public repository. No trained local vision runtime or GTX GPU is available in the development container, so real model accuracy, speed and cancellation remain unverified.

Rod-height summaries now normalize scatter to international feet and count the latest decision per run/candidate. Unknown units and nonfinite scatter are excluded; legacy records recover units from their original run when available. Confidence remains a heuristic evidence score, not a calibrated probability. Labeled real bust/non-bust examples are still required for field calibration.

The preceding beta.1 source passed all four Windows workflows, including 24 lifecycle cycles and three replacement fixtures. Beta.2 changes require fresh Windows acceptance; those earlier passes do not certify these new bytes. Official Trimble binary conversion also requires the actual vendor converter/runtime and representative .job files; JXL parsing or mocked conversion does not substitute for that acceptance.
