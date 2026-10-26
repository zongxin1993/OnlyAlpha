# Release units and compatibility

[ADR 0142](adr/0142-library-product-boundaries-and-independent-releases.md) records the owner-selected release model;
[repository architecture](repository-product-architecture.md) defines ownership. AGENTS.md governs execution/validation.
This document explains release policy, not implementation status or a second version/acceptance ledger.

## Independent metadata authorities

Keep one repository and root Cargo workspace; independent versions do not require independent repositories or a lock per worker.

| Release unit | Single version metadata authority after cutover | Tag |
|---|---|---|
| Reusable Rust libraries | Root `Cargo.toml` workspace package version, inherited by the selected library set | `libs-vX.Y.Z` |
| Backend, all roles and bundled Python base resources | `packages/backend/Cargo.toml` package version, independent of workspace version | `backend-vX.Y.Z` |
| Frontend | `packages/frontend/package.json`; lock root must match | `frontend-vX.Y.Z` |
| Concrete plugin distribution | Its own package metadata; multi-language projections of one distribution derive from one selected authority | unambiguous `plugin-<name>-v<distribution-version>` |

The selected reusable library set comprises the twenty Kernel crates and the six non-Kernel libraries in the architecture.
Do not inherit the library version into backend or plugin manifests. Internal Python executor/SDK wheels derive their
constituent version/provenance from backend; they are not independent worker product release lines. Independently distributed
algorithm plugins retain their own distribution metadata. Fixtures keep their existing independent versions.

SemVer release lines use actual declared support/compatibility boundaries and ADR 0130 breaking-change classification. During
`0.y.z`, classify all changes explicitly and do not pretend initial development means permanent patch compatibility. Major-zero
breaking public changes advance minor rather than being hidden as patch; stable supported breaking changes require major,
compatible public additions minor, compatible fixes patch. First versions for the new lines require checking actual published
history; example version numbers in discussions do not assign them. Private asset/provider versions retain ADR 0115, including
positive-integer semantic/provider identities and existing private distribution rules rather than forced SemVer conversion.

Only selected changed release units advance. A source PR may change multiple units in one atomic commit; unrelated units and
pure documentation changes do not force a release. An actual release requires explicit selection and authorized publication,
not every mainline merge. Do not create a version registry duplicating package metadata or an automatic post-merge version commit.
Tags, versions and artifact identities are immutable. Exact reruns may finish/reuse the same matching publication; conflicting
content, tag targets, unknown boundaries or ambiguous existing publication fail closed without overwrite or tag movement.

## Source and dependency locking

Development uses local workspace paths and the committed Cargo/uv/npm locks. A matching path dependency version only checks
metadata; a lockfile does not freeze local source bytes. Formal release construction must:

1. Select exact released library/plugin source artifacts and their immutable content identity; verify all relevant source,
   manifests, generated inputs, resources and build configuration in their dependency closures, excluding credentials.
2. Verify the actual source used in the frozen build equals that selected content. Same version plus changed source is a failure.
   A new library change requires a new selected library release before backend can formally claim it.
3. Bind dependency locks/registry checksums, compiler/toolchain, target, profile, features and relevant non-secret configuration.
   Preserve isolated package/dependency proofs and reject undesired feature/registry changes; no automatic latest resolution.
4. Build/install from those exact inputs and record actual artifact bytes and provenance through existing artifact manifests.
   Source-only tags are not proof of a correctly built binary/Python environment.

Start with immutable source bundles and content verification, without a private Cargo registry. Source/build provenance extends
existing Distribution Artifact records where needed; it is not another work-binding or activation Authority. A path/registry URL
is an operational locator, never semantic identity. Artifact retention/availability is independently required by bound history.

Rust plugins initially compile into backend. Plugin publication alone changes no installed backend; adoption requires a rebuilt
backend release with exact selected plugin content. No Rust dynamic ABI or module hot reload is promised. Python algorithm
plugins/private executable Revisions may form new admitted environments without rebuilding an unchanged backend base. Changing
bundled executor/SDK/interpreter/default resources changes the backend artifact and requires its new version.

## Python base resources

Backend delivery includes the target-platform interpreter/environment, minimal algorithm executor/authoring SDK, generated
protocol bindings, exact dependency artifacts/hashes and licenses. Internal wheels are constituent artifacts. Package metadata,
`scripts/build_algorithm_sdk.py` and deployment installation must describe the same actual closure; do not retain broad Python
business/Core code merely to satisfy obsolete package declarations. Do not copy a host venv or resolve packages on startup.

Private Factor/Strategy Draft/Revision remains DB-native under ADR 0129. Exact algorithm plugins and materialized Revisions enter
isolated environments through existing artifact/Catalog/Generation admission. Keep base runtime and author code identities
separate; changing a Factor does not require a backend release. Retain the original exact environment for already-bound work.

## Compatibility and activation

| Domain | Governing rule |
|---|---|
| Frontend/backend | Default tested pair; different versions allowed only for explicitly verified Product API combinations. Clear unsupported UI/startup feedback, no guessing or fallback. No arbitrary mixed-version or rolling-upgrade promise. |
| Libraries/backend/plugins | Exact build selection plus public API/SPI/capability checks. Equal versions alone do not prove compatibility; independent versions alone do not prove incompatibility. |
| Provider/Calculation/private assets | Existing semantic version, Provider content, implementation fingerprint, Catalog and StrategyRevision authorities; software releases do not rewrite them. |
| Persistence/checkpoints | Owning schema, integrity and recovery contracts; apply supported history/upgrade gates. Disposable local dev data follows AGENTS.md, not a fabricated migration PASS. |
| Runtime/deployment | Actual artifact/image content, source provenance and immutable Generation/work binding. Fixed `:dev` tags are convenience, not execution identity. |

Release publication, deployment, Generation activation and LIVE authorization are separate. New-work activation/rollback uses
the sole existing Generation ledger; running work is never rebound to the current pointer. Preserve exact history/readers,
UNKNOWN and risk-reduction paths. A smaller version string does not prove a persistence downgrade safe. Do not introduce shims
for retired development versions or new legacy loaders; actual supported contract obligations still apply.

## Release tooling and current path mapping

`version_sync.py` validates the independent release graph. It requires `--unit` for version mutation/suggestions; the old
whole-repository `set` is removed. Units are `libs`, `backend`, `frontend` and `plugin-<name>`, discovered from actual workspace
manifests. Backend and Rust plugins have explicit versions; libraries inherit the workspace version. Python backend resources
are projections of backend, Python/Rust plugin metadata share that plugin's authority, and internal dependencies pin their
actual target distribution version. Fixture versions remain independent. No version is advanced merely by this cutover.

Before directory relocation, backend authority is `packages/onlyalpha-http-server/Cargo.toml`, frontend authority is
`packages/onlyalpha-web-console/package.json`; the transport-neutral Product component derives the backend version. Move these
paths and their consumers atomically in the Product-package phase, without empty packages or another version ledger.

PR selection uses explicit labels such as `release:frontend:patch` or `release:plugin-binance:minor`. No label means no release;
selected units must equal changed version units. Multiple units can select their own level. Minor/major retains explicit human
Owner label-action proof; generic approval or a later post-merge label does not authorize an earlier transition. Validate exact
current base/head and strictly ordered historical events before the exact merge. Actual transitions are reported even when
historical authorization proof is unavailable. Unknown/conflicting labels and stale/skipped/downgraded versions fail closed.

CLI interfaces (use the canonical dev verification entry for read-only formal checks):

```text
version_sync.py check
version_sync.py next --unit frontend --level patch
version_sync.py set --unit frontend X.Y.Z
version_sync.py release-selection --context-file release-context.json
version_sync.py check-transition --base-ref EXACT_BASE --context-file release-context.json
```

`set` edits the selected unit/projections and incoming dependency pins, then refreshes `uv.lock`; it is a source-edit operation,
not a command to run against the read-only formal source cut. PR checks separately validate locks and graph. The trusted mainline
publisher derives named source Releases from exact first-parent version changes; no change produces no Release. It preserves
existing legacy `vX.Y.Z` tags/artifacts, does not publish them again under new names, and retains immutable tags, exact retry and
partial-publication conflict protections. It does not upload executable artifacts, deploy or activate a Generation. Phase 6
must still prove immutable dependency content, actual installed artifacts and claimed frontend/backend combinations.

The minimal installation's base distribution version belongs to backend; Indicator Provider provenance must use the installed
plugin's separately sealed distribution metadata. Never copy backend version into plugin source identity. Missing, duplicate,
conflicting or changed installed metadata fails closed; startup still requires the base version to match the backend program.

Release-unit changes include manifests/locks, affected Provider distribution provenance, transition checks, release
selection/notes, planner/publisher, workflows and tests as one coherent change. Preserve read-only PR validation and authorized
mainline write access. Source changes and this documentation do not authorize a tag, merge, push or publication.

Validation covers selected-unit changes, untouched units, exact target pins and mixed-language projections, canonical version
transitions, historical label/merge proof, immutable tag conflicts, partial retries and installed plugin provenance. Formal
artifact/source-composition and API-pair proofs remain phase 6; source tags alone never establish them. Run relevant local checks
through the single dev environment and retain results. The [work program](repository-migration-work-program.md) supplies
sequence, not a second gate authority.
