# Publishing the approved SurveySync 9.4.0 Beta.4

Use the existing **SurveySync Release** workflow (`.github/workflows/release.yml`). Do not rerun an old build and do not use UI Validation to publish.

## Run settings

- Use workflow from: `v9.4.0-beta4-theme-branding`
- version: `9.4.0`
- action: `publish_beta`
- beta_suffix: `beta.4`

The selected job is **Publish approved Beta.4 (no rebuild)**. The legacy build and Stable promotion jobs are skipped for this selection. No local download, publisher script, compilation, or pre-created tag is required.

## Approved artifact and safeguards

The workflow downloads artifact `10923766429` from successful UI run `36294542913`, not the newest arbitrary artifact. The approved source is `1382bff0dc5b6bc452d7d64be5f6ac17cd2177a0`; successful Quality run `36294542902` is checked as well. The tag targets that source commit, not the later workflow-only commit.

Installer: `SurveySync_Setup_9.4.0.exe` (8,823,709 bytes).
SHA-256: `1660d9bdb329e61242c48b0dfe6d4a254d2d05220829a83cf54b901a10a5ae17`.

Artifact metadata/digest, executable, checksum file, and approved release notes are checked against pinned identities. A draft prerelease is uploaded and downloaded again for hash verification before publication. Existing tags are never moved; existing assets are never overwritten. A retry may complete missing uploads in the matching draft or finish the feed update for an already verified published prerelease.

Only the beta entry of `main/update.json` is updated. Stable and Developer entries are retained. Updates use the current file SHA so concurrent changes or branch rules cause a visible failure instead of a force push. Newer beta versions are not downgraded. No source merge or Stable promotion is performed.

## Validation and limitations

The publication helper passed nine local simulated-GitHub tests using the actual approved installer fixture: publication/idempotent retry, wrong branch, corrupted bytes, failed CI, conflicting tag, later beta suffix, newer version, feed conflict, and partial-draft recovery. These are tests, not evidence of live publication. A successful manual release run and its final feed verification are the publication evidence.

The approved CI artifact currently expires on 2026-10-11. Expired/missing artifacts fail closed. This does not change updater version-comparison behavior: earlier 9.4.0 betas may require a direct installer download.

This is a publication-only handoff following CP's approval. The approved Windows installer bytes and application source are unchanged. The local Publisher ZIP is superseded.
