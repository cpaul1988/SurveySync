# Repository tools review — October 19, 2026

## Decision and scope

The completed trials support keeping Ghidra as an optional tool for targeted inspection of compiled Windows artifacts and adopting the small local development handoff helper. An isolated `akitaonrails/ai-memory` pilot also demonstrated useful note persistence and retrieval. These are development tools. This change adds no application runtime dependency, survey calculation, document-inference provider, or UI rewrite.

Ghidra can help inspect the native Go launcher and updater. Most SurveySync behavior already has readable Python and JavaScript source, so decompilation is supplementary evidence. It cannot establish that a file is safe, explain the original Defender detection by itself, or automatically provide a Trimble `.job` importer. SurveySync currently uses the official Trimble converter for binary `.job` intake and parses JobXML directly.

The handoff helper records the actual branch, commit, tree, working-copy status and update hold, together with explicitly supplied work and evidence references. Previous-commit results remain separate from the current checkout. Inputs are deliberately selected repository material, with private fieldbooks, project databases, feedback contents and credentials excluded from the pilot. `longbridge/gpui-kit` offers UI ideas, but its Rust UI components are not a drop-in replacement for SurveySync's Python/FastAPI/pywebview interface. Revisit visual ideas in a separately scoped UI update after the repair's workstation acceptance.

## Completed development trials

- [Ghidra](ghidra_trial.md) analyzed the hash-identified original launcher and updater without executing either. It recovered 27 and 14 main-package functions, respectively, with all selected decompilations complete, no timeout and unchanged input hashes. The expected process supervision and staged-installer verification paths were recognizable. No new launcher defect or cause of the antivirus detection was demonstrated.
- [ai-memory and the handoff helper](handoff.md) were exercised separately. The pinned ai-memory binary retained two public-code notes and a pending handoff across a server restart. The helper produces local JSON and Markdown snapshots without installing agent hooks or reading chat history.
- Private `.dev-handoff/` output is ignored by Git and explicitly excluded from both installer and beta-fixture packaging. Git ignores alone do not govern Inno's recursive source rule.
- Focused Linux verification passed 31 tests, with the Windows junction regression explicitly skipped on Linux. Ruff name and formatting checks, release identity, release documentation and static quality checks passed. The new workflow runs the handoff and packaging regressions on Linux and Windows; repository CI provides commit-specific results. These checks do not constitute installed application acceptance.

## Verified repository state

The public default branch remains at `26edcf66a6c59ec39068c96dd02f50b35e41b1ad`. Its update manifest holds Beta and Stable distribution; 9.5.3 remains withdrawn. The existing repair is draft PR #25, branch `fix/defender-release-954`, head `1dbd79f9412cebcc0065c7d1ceb724c91e297f58`. Its tested PR merge is `d879f83000ff962b0f2b4e00470f81eea6d1438c`, with the same source tree as the repair head: `e5da65b79e2f3d42116ea032c30e7bcab4a863e1`.

PR #25 already adds pinned native builds, product resources, mandatory artifact scans, evidence validation, explicit update-hold messaging and safer desktop shutdown ordering. This review established no additional source defect requiring a duplicate repair. The development pilots preserve that work and the release hold.

## Independent acceptance evidence

The Actions API reports success for all five workflows at the repair head. The installed acceptance job logs independently record **780 passed, 1 skipped, 1 warning**, with **65.06% coverage** against the unchanged 54% threshold.

The final evidence ZIP was downloaded and its SHA-256 matched GitHub's artifact digest. Its tested-source record identifies the merge above. Both security reports and all three raw scanner logs were inspected; log hashes match their reports. On October 17, Defender reported no threats for the launcher, updater and final installer, with active antivirus/service/real-time protection and unchanged before/after hashes. Recorded engine: `1.1.26090.9`; intelligence: `1.461.64.0`, updated October 16 at 21:30:27 UTC.

All **24 lifecycle records** passed, preserving source points and recording clean shutdown and a closed API. All **three update replacement fixtures** passed, preserving source bytes, project data and settings; the 9.4.0 fixture records a manual close of the old window. These are historical results for the identified repair bytes. They do not certify a new development head, constitute a fresh scan, or establish a Microsoft false-positive determination. The existing validator limits scan freshness to 48 hours; any subsequent release decision must assess evidence accordingly. The accepted replacement remains unsigned, and workstation acceptance remains outstanding.

## Feedback checkpoint

The connected tracker was read on October 19, 2026. Intake contains **18 records**, with no item newer than **FBR-0018**, submitted `2026-10-16T16:44:16.847587Z`. The previous item is a wizard test. FBR-0018 concerns shared FieldBook navigation, theme and module-switch behavior, already addressed by the integration retained in PR #25. Both rows still show `New`, so tracker status lags implementation. Raw `Form Responses 1` contains no response rows. Metadata lists no `Errors` or `Retry Queue` tabs; those absent tabs were not treated as verified queues. No tracker data or statuses were modified, and no private feedback text is retained here.

## Source and artifact references

| Evidence | Verified reference |
| --- | --- |
| Held public feed | [update.json at main checkpoint](https://github.com/cpaul1988/SurveySync/blob/26edcf66a6c59ec39068c96dd02f50b35e41b1ad/update.json) |
| Existing repair | [PR #25](https://github.com/cpaul1988/SurveySync/pull/25) |
| Native Security | [Run 38997702454](https://github.com/cpaul1988/SurveySync/actions/runs/38997702454) |
| Quality | [Run 38997702423](https://github.com/cpaul1988/SurveySync/actions/runs/38997702423) |
| UI Validation | [Run 38997702413](https://github.com/cpaul1988/SurveySync/actions/runs/38997702413) |
| Remaining Audit Acceptance | [Run 38997702438](https://github.com/cpaul1988/SurveySync/actions/runs/38997702438) |
| Installed Windows Repair Acceptance | [Run 38997702407](https://github.com/cpaul1988/SurveySync/actions/runs/38997702407) |
| Accepted installer artifact | `12088745241`; ZIP SHA-256 `92f408ef107f8890b065caf20a2f7dcbe8b8594e1b7a6bf14f768c7a997de51f` |
| Accepted installer | `SurveySync_Setup_9.5.4-beta.1.exe`; 12,153,200 bytes; SHA-256 `17fb62ee40b9da9658dd8e24a7d935d91acc2f8dcb508e06067d2d63abb9493e` |
| Inspected acceptance evidence | `12088302822`; ZIP SHA-256 `d707a431f3e8d419b792f0efb404f30da61813163a9843a7733b36ae7e7455e0` |
| Original 9.5.3 installer evidence | [Run 38942210139](https://github.com/cpaul1988/SurveySync/actions/runs/38942210139), artifact `12064447178`; located for forensic extraction, not executed in this review |
| Feedback configuration | [feedback.json](https://github.com/cpaul1988/SurveySync/blob/26edcf66a6c59ec39068c96dd02f50b35e41b1ad/feedback.json); live tracker identified through that configuration |
| Binary import boundary | [trimble_job.py](https://github.com/cpaul1988/SurveySync/blob/26edcf66a6c59ec39068c96dd02f50b35e41b1ad/surveysync/trimble_job.py) |
