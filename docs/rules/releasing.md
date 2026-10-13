# Release operation

For a new release, merge the intended changes into the default branch, then open
**Actions → Release → Run workflow**:

1. Select the default branch in the branch selector.
2. Leave `operation` as `new` and choose `bump`: `patch`, `minor`, or `major`.
3. Leave `release_tag` empty and run the workflow. README links update automatically.

No manual `git tag` or version-file edit is needed. The tag points to the default
branch commit captured at dispatch, even if the branch advances while the run waits.
The default bump is patch. The base is the numerically highest remote canonical
`vX.Y.Z` tag, including unpublished tags; prerelease and noncanonical tags are ignored.
For example, from `v2.1.2`, patch selects `v2.1.3`, minor selects `v2.2.0`, and major
selects `v3.0.0`. A repository without a stable tag fails rather than inventing a base.

You can still push an existing `vX.Y.Z` tag or dispatch with `operation: existing`
and `release_tag` to publish/resume it. The bump dropdown is ignored in that mode.
Only canonical stable tags are accepted; missing tags and prerelease tags fail.
This pipeline applies to new tags whose source includes the release helpers and GUI
diagnostic mode. It does not rebuild historical releases.

## Automated tagging and retries

Release runs share a repository-wide concurrency group with cancellation disabled.
GitHub concurrency allows one running and one pending run; a newer dispatch can
replace an older pending run. Runs are not a FIFO queue. Allocation happens only
when the preparation job executes, so a canceled pending run reserves no version.

Before creating a tag, the workflow saves `release-intent-RUN_ID` as a workflow
artifact retained for 90 days. It records the repository, original run ID, dispatch
commit, bump, and selected tag. Rerunning the same run downloads and validates that
intent instead of calculating another bump. If a rerun has no available original
intent (including a failure before saving it), it stops: start a new dispatch if no
tag exists, or use `operation: existing` to recover an existing tag.

The workflow creates an annotated Git tag through the GitHub API, recording its
intent and source in the annotation. A retry accepts a preexisting tag only if both
its annotation and commit match that original intent. Foreign/conflicting tags,
corrupt intent records, and expired/unavailable intent artifacts fail closed.
Downloads must match the original artifact archive's SHA-256 digest before their
JSON is used. Tags are never moved, overwritten, or deleted. A failure between creation of the tag
object and its reference can safely retry reference creation for the same version.

Tag creation uses `GITHUB_TOKEN`; that tag push does not trigger another workflow.
Checks, builds, and publication continue in the same run. See GitHub's
[Git tags API](https://docs.github.com/en/rest/git/tags) and
[workflow trigger behavior](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

If later checks fail, the tag remains reserved. Rerun the original run or dispatch
with `operation: existing` and that tag. A separate `new` dispatch selects the next
version, including tags left by failed releases. Use a new version for source fixes.
The job summary records the bump, version, source SHA, tag, and recovery instructions.

## Source and validation

Release resolves the remote tag, including annotated tags, to a commit SHA. Every
source-dependent job uses that SHA. Package builds fetch complete history and tags,
and use `setuptools_scm` without pretend-version overrides. Both distribution
metadata versions must exactly match the tag. Required checks are shared with CI;
Pyright remains informational.

Windows builds the executable with package metadata, wheel, and sdist. The bundle
contains exactly those three files, `LICENSE`, `THIRD_PARTY_NOTICES.md`,
`merge_states.json`, and `release-manifest.json`. The manifest records the repository,
tag, commit, version, producing run, and per-file SHA-256 digests. PR/manual CI builds
use an empty tag and their actual development version; they cannot publish.

The GUI executable must pass startup validation before uploading the bundle as a
workflow artifact retained for 90 days. Ubuntu and Windows then verify the bundle
and exercise the installed wheel in clean temporary environments. Windows also
rechecks executable startup. Publication requires all these checks to succeed.

## Draft publication and recovery

Publication creates a draft only after validation. Its release notes contain a
machine-readable marker linking the source, producing run, original artifact ID,
and manifest digest. Assets are uploaded to that draft, their exact file set and
digests are checked, and the remote tag is checked again immediately before publish.
Published assets are never overwritten or deleted by this workflow.

If publication fails, rerun the failed job or dispatch Release with
`operation: existing` and the same tag. A workflow-created draft for the same commit
resumes using its recorded bundle; it does not rebuild. Existing identical assets
are skipped and missing assets are
uploaded. Tests and artifact checks run again on a fresh dispatch. The API asset
digest is used when available; otherwise the asset is downloaded and hashed.

Unexpected files, differing bytes, incomplete uploads, a moved tag, a foreign draft,
or an expired/unavailable original artifact stop recovery and leave the draft
unpublished. Inspect the error and draft before any manual cleanup. The workflow does
not silently substitute a rebuilt bundle; after original-artifact expiry a matching
retry is unavailable. Use a new version for changed source or changed release bytes.

An already published tag is a successful no-op: no checks, rebuild, or asset updates
are performed. Repository-wide concurrency prevents simultaneous workflow publication.
`make_latest: legacy` prevents deliberately publishing an older version
from unconditionally marking it as the latest release.

## Automatic README links

New bump releases and tag pushes automatically update both language READMEs after
publication. Existing-tag dispatches preserve the opt-in `sync_readme` input,
including for published-tag no-ops.
The updater reads the latest published stable release and its actual wheel URL, not
the requested tag. It serializes README jobs and retries branch advancement three
times by refreshing the default branch and recomputing the latest links. It never
force pushes.

If branch protection or token permissions reject the push, the README job fails with
a separate message that publication succeeded. Resolve that issue and rerun the job;
the published release remains intact. The reset/retry helper refuses to run outside
a clean dedicated GitHub Actions checkout.

## Before the first release

Run required local checks from [testing.md](testing.md). Open a PR or manually dispatch
CI to exercise native Windows packaging and the Ubuntu/Windows installed-artifact
checks without publishing. Linux local tests do not establish Windows packaging
success. Interactive GUI merges, installed-game processing, and in-game playtesting
remain separate evidence. PyPI, code signing, and attestations are outside this
workflow.
