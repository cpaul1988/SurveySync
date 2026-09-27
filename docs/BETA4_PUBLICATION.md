# Publishing the approved SurveySync 9.4.0 Beta.4

Use the existing **SurveySync Release** workflow (`.github/workflows/release.yml`). Do not rerun an old build and do not use UI Validation to publish.

## Run settings

- Use workflow from: `v9.4.0-beta4-theme-branding`
- version: `9.4.0`
- action: `publish_beta`
- beta_suffix: `beta.4`

The selected job is **Publish approved Beta.4 (no rebuild)**. The legacy build and Stable promotion jobs are skipped for this selection. No local download, publisher script, compilation, or pre-created tag is required.

## Release #23 draft lookup repair

Run `36296242884` downloaded the approved installer archive and verified its digest, created the correct tag and draft release, then failed with HTTP 404. The helper requested `/releases/tags/v9.4.0-beta.4` immediately after creating a draft; GitHub documents this endpoint for published releases only. Draft ID `397517207` was present with zero assets when inspected. The Node.js deprecation warning and Ubuntu migration notice did not cause this failure.

The repair discovers existing drafts through authenticated, paginated release listings. New drafts use the numeric ID returned by the creation API; publication and verification use that ID. This resumes the existing draft without moving tags, duplicating the release, overwriting assets, or rebuilding the approved installer. Markdown body comparisons normalize CRLF/LF only; the downloadable notes file remains byte-for-byte hash checked.

**Start a new Run workflow on the same branch after the fix. Do not use Re-run jobs on #23:** that reuses its original commit and therefore the old helper. Do not manually publish or delete the empty draft; the corrected workflow completes it only after uploading and verifying the approved assets.

Twenty offline regression tests passed locally using the actual approved installer, checksum file and release-notes bytes with an intercepted GitHub CLI boundary. The tests explicitly reproduce draft-by-tag 404 behavior and cover existing empty/partial drafts, CRLF notes, pagination, idempotent publication, corruption, conflicting tags, failed CI, expired artifacts, permission errors, newer versions, and optimistic feed conflicts. The same tests now run inside the approved-artifact release job before any publication writes. These simulations are not evidence of a successful live publish.

## Approved artifact and safeguards

The workflow downloads artifact `10923766429` from successful UI run `36294542913`, not the newest arbitrary artifact. The approved source is `1382bff0dc5b6bc452d7d64be5f6ac17cd2177a0`; successful Quality run `36294542902` is checked as well. The tag targets that source commit, not the later workflow-only commit.

Installer: `SurveySync_Setup_9.4.0.exe` (8,823,709 bytes).
SHA-256: `1660d9bdb329e61242c48b0dfe6d4a254d2d05220829a83cf54b901a10a5ae17`.

Artifact metadata/digest, executable, checksum file, and approved release notes are checked against pinned identities. A draft prerelease is uploaded and downloaded again for hash verification before publication. Existing tags are never moved; existing assets are never overwritten. A retry may complete missing uploads in the matching draft or finish the feed update for an already verified published prerelease.

Only the beta entry of `main/update.json` is updated. Stable and Developer entries are retained. Updates use the current file SHA so concurrent changes or branch rules cause a visible failure instead of a force push. Newer beta versions are not downgraded. No source merge or Stable promotion is performed.

## Limitations

The approved CI artifact currently expires on 2026-10-11. Expired/missing artifacts fail closed. This does not change updater version-comparison behavior: earlier 9.4.0 betas may require a direct installer download.

This is a publication-only handoff following CP's approval. The approved Windows installer bytes and application source are unchanged. The local Publisher ZIP is superseded.
