# Verified audit repair continuation — Windows checkpoint

## Completed continuation

The saved 28-file patch was imported with every before/after SHA-256 verified; decompressed migration identity `bbe73d6b6f96ac61a7692a9d55f38bcc327e58220af87d41b27dad28823d61f0`. Four governed files were formatted with locked Ruff 0.16.8. Temporary import payload/workflow files were removed. All work remains in draft PR #12 on `fix-v9.4.0-verified-audit`.

Final tested application/test commit: `c79f37c1b6c9e4b342775a081b46315359457038`. Windows Quality run `36350961422`, UI Validation `36350961424`, and full installed Repair Acceptance `36350961418` succeeded. The last run archived merge checkout `94ea0e422f97cec8c3e77e7c263d126c63fb0637`.

## Problems caught during verification

1. The first Windows run caught five encoding problems in new test fixtures. Reads/writes/subprocess text now explicitly use UTF-8; no tests were disabled and no global encoding setting was used to hide the failure.
2. Review caught a real shutdown edge case: switching projects replaces Runtime and its Event. The initial watcher could wait on the old Event forever. Bounded waits now follow the current Runtime; a deterministic regression replaces it while the watcher is waiting.
3. The native UI harness initially failed before reaching a file picker. pywebview's documented debugging setting is now enabled only in the disposable child, and Playwright waits for navigation through its event loop rather than blocking on cached page.url values. These were harness failures, not evidence that the product's picker was broken.

## Final observed results

- Unchanged full release gate: **471 passed, 1 skipped**, including 78 audit/repair/bridge cases. Ruff, formatting, mypy, docs, static analysis, compilation, JavaScript and locked dependencies pass. Windows build separately verifies both native GUI launchers.
- Repaired real menu/toolbar commands and level-layout control pass.
- Existing 11-module/light-dark and 16-theme suites pass.
- Real Inno installation and private-runtime provisioning pass.
- Installed project creation/reopen, four manual control revisions, source code/PointID attribution, API exit and local-service termination pass in two sessions (6.312s and 5.891s exits).
- Real native Open dialog selection and cancellation pass; the actual report button generates CSV/TXT/XLSX, CSV parses and XLSX reopens, and input bytes are unchanged.
- Actual installed File -> Exit passes (7.125s; launcher code zero and API closed). No uncaught JavaScript errors in that native sequence.

See `docs/VERIFIED_AUDIT_REPAIRS.md` for exact artifact identities, detailed coverage and limits. The actual report screenshot is in `repair-evidence/native-point-ranges.png`; JSON and logs, not screenshots alone, establish successful execution. The early-painted dialog capture is not a completed visual-rendering signoff.

## Next gate, not a release approval

The full updater replacement cycle is still outstanding. G01–G05 and external/provider/field-calibration acceptance remain open. A separately numbered candidate must be built and accepted before distribution. Internal regression artifacts still say 9.4.0 and must not be confused with published Beta.4.

The current update documents this successful code/test checkpoint; later documentation-only changes do not retroactively alter which checkout and installer were tested. No release job, merge, tag mutation, provider call, feedback submission or Stable feed change was performed. Main remains `9965284c69e6a7cd95fe0750838130f4a39bd6e2` as last checked.
