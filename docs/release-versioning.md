# Development release numbering and compatibility

`AGENTS.md` owns the engineering rule. The root `pyproject.toml` is the sole release-number
authority; `scripts/version_sync.py` maintains its existing complete workspace release graph.
This document explains that rule, not a release-status ledger or an additional acceptance gate.

## One main-branch PR, one increment

During `0.y.z` active development, every PR merged to `master` (including documentation,
dependency and revert PRs) carries exactly one increment relative to the **current** target:

| Selection | Increment | Example | Decision |
|---|---|---|---|
| Default | patch + 1 | `0.9.9` → `0.9.10` | Ordinary merged PR |
| `release:minor` | minor + 1, patch = 0 | `0.9.10` → `0.10.0` | Owner explicitly recognizes a bounded stage/product objective |
| `release:major` | major + 1, minor/patch = 0 | `0.10.3` → `1.0.0` | Separate Owner decision, including explicit support/compatibility scope |

Minor replaces, rather than follows, that PR's patch increment. PR creation, review,
additional commits, validation and closing without merge do not increment. A version
does not certify a stage, freeze a contract, authorize deployment or confer LIVE authority.
Major-zero numbering is an integration counter, **not** a claim that all patch changes
are compatible bug fixes. After an explicitly approved stable `1.0.0` release, standard
SemVer compatibility classification governs level selection in addition to one increment
per merged PR; breaking supported contracts require major, compatible public additions minor.

Choose the version **inside the PR**, not in an automatic post-merge commit. Refresh the
target before merging; if two PRs target the same number, the second must update its branch
and graph after the first merges. Require up-to-date branches and the `Release transition`
check in repository branch protection/merge controls. Workflow code alone cannot install
those remote settings or eliminate the last check-to-merge race. Do not infer they exist.

The release workflow defaults to patch, rejects conflicting labels, and requires an explicit
Owner action on the selected release label for minor/major. Generic code approval is not
a stage-recognition or major/support decision and grants no exceptional level. Its repository
Owner is the GitHub repository owner user; an organization-owned repository needs a separately
approved human-owner policy, not a guessed team/maintainer fallback. The merged notification
reports the actual merged commit versus its first parent (merge/squash), **before** validating
selection. It reconstructs label state from fully paginated GitHub events strictly preceding
the unique event for that exact merge, never from mutable current labels/reviews. Missing or
ambiguous historical proof is an explicit failure, while the actual old → new notice is retained.
It exposes invalid numbering instead of repairing history. For rebase merges the final commit must carry the complete version
increment; use squash/merge unless that condition is deliberately maintained.

The check and merged notification print old → new in Actions logs and job summaries. No bot
commit, automatic tag, package publication, deployment, PR comment or auto-merge is performed.
The workflow must be on the main branch before normal future merge notifications can run.

```bash
# Read-only suggestion. Run these through the canonical dev verification service locally.
python scripts/version_sync.py next
python scripts/version_sync.py next --level minor
python scripts/version_sync.py check-transition --base-ref origin/master

# Only when the PR's version change is authorized, synchronize all metadata + uv.lock:
python scripts/version_sync.py set 0.9.11
python scripts/version_sync.py check
uv lock --check
```

The number in the last command is an example, not authorization to change this tree.
Retain metadata/build checks and installed-distribution parity after a real bump.
Local verification captures the existing `origin/master` commit, tree and ref into
the frozen source inventory. `check-transition` reads that exact captured base;
it does not fetch or substitute a later target. Refresh the local target explicitly
before starting validation when a newer base is required.

## Component and compatibility domains

| Domain | Version/identity authority | Upgrade rule |
|---|---|---|
| Core, repository-owned Python components/plugins, Shipping Web | Root release number; existing workspace members and Web metadata are synchronized | Exact internal `==X.Y.Z` dependencies, Web lock root, Provider **distribution** provenance and `uv.lock` move together; coordinated build/rollout |
| External plugins and private assets | Their own distribution/provider/asset authorities | Declare exact admitted SPI/API and content bindings; not silently rewritten by a public release bump |
| Test distributions | Existing independent fixture versions | Formal workspace dependency references remain exact; fixture versions need not equal the release |
| Product API | Canonical OpenAPI, API major, exact contract fingerprint and compatibility policy | ADR 0103/0130 detection and generated-client parity remain mandatory; release number is not API major |
| Plugin SPI | Public Plugin API version and capability descriptors | Existing major/minor admission checks remain authoritative, not inferred from package release equality |
| Provider / Calculation | Exact Provider version + content fingerprint; Calculation semantic version/backend/implementation | Changed content needs new Provider version; changed semantics also needs semantic version. Byte-identical repackaging changes distribution provenance only (ADR 0112) |
| Private Factor / Strategy | Mutable Draft → immutable Revision; exact API/adapter, Provider, Catalog and StrategyRevision bindings | ADR 0115, 0129–0132; no Git/package requirement introduced by release numbering |
| Schema / durable facts / checkpoints | Owning schema, migration and replay contracts | Explicit preconditions, atomicity, integrity and restart semantics; no automatic migration inferred from release comparison |
| Runtime / deployment | Image content ID, source/build provenance, node/semantic-store identity, immutable generations | Fixed `:dev` tags are convenience only. Running work is never rebound by a release bump or Web HMR |

Before upgrade: classify every affected public/persistent contract, inspect actual consumers,
update current repository consumers atomically, and execute related contract/build/migration
tests. `DEVELOPMENT_UNFROZEN` allows explicitly classified breaking changes, not silent
identity drift, damaged durable facts, lost replay or weakened authentication. Frozen/supported
contracts retain their actual obligations regardless of `0.y.z` numbering. Do not invent legacy
loaders, mixed-version compatibility or rolling-upgrade guarantees without an accepted contract.

Rollback uses the exact old artifacts and only a demonstrated compatible persistence state.
Otherwise fail closed and retain facts/volumes for backup/forward-fix; a smaller version string
does not make a destructive downgrade safe. Reverts are new patch PRs, not reused release IDs.

## Engineering evidence

[SemVer 2.0.0](https://semver.org/) distinguishes initial-development numbering from stable
compatibility promises and forbids rewriting released content. OnlyAlpha retains exact
content identities; it rejects using release ordering as Provider admission or fail-forward.
[GitHub Actions security guidance](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions)
documents script-injection and privileged untrusted-checkout failure patterns. The release
workflow uses read-only permissions, no secrets and no `pull_request_target`; the latest base
is read via GitHub's authenticated branch API and its exact SHA is passed through an environment
variable, without persisted Git credentials. Regressions cover invalid increments, stale/duplicate
numbers, component drift and unknown release levels; branch protection remains an explicit
remote prerequisite, not a local PASS claim.
