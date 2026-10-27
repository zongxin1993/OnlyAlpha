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

Before directory relocation, backend authority is `packages/backend/Cargo.toml`, frontend authority is
`packages/frontend/package.json`; the transport-neutral Product component derives the backend version. Move these
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

The native builder also accepts a minimal, explicit input selection. In the frozen dev tool environment, generate a candidate
with `python scripts/release_inputs.py candidate /workspace/test-results/selected-inputs.json`. It exclusively creates that
file and prints its SHA-256. Review/select the digest separately, then check with
`python scripts/release_inputs.py check /workspace/test-results/selected-inputs.json --sha256 SELECTED_SHA256`, or pass the same
file and digest to `scripts/native_workstation_build.py --release-inputs PATH --release-inputs-sha256 SELECTED_SHA256`.
All commands run through `scripts/dev_verification.py run -- ...`; use test-results for generated inputs so they never enter
their own source inventory. A changed working tree requires a newly reviewed selection; the builder does not refresh it.

This preflight binds the complete non-secret frozen source inventory, discovered independent versions, Cargo/uv/npm locks,
pinned Rust toolchain, native target, release profile, default feature selection and explicit Web build environment. Missing,
changed, extra or unsupported selected inputs fail before creating the artifact directory; inputs are checked again after
construction. The existing artifact manifest stores the selected digest, versions and build recipe, reusing its source inventory
instead of adding a second source or version ledger. Ordinary dev builds omit the selection and make no release-input claim.

### Per-unit immutable source inputs

`release_sources.py UNIT EXACT_COMMIT OUTPUT.zip [--tag UNIT-vX.Y.Z]` creates a source artifact from that exact committed
tree, never the current uncommitted files. Raw Git tree/blob reads bypass archive export attributes and disable object
replacements; blob object identities are verified. UNIT uses the existing manifest-derived release-unit names. Named tags are optional;
when supplied, the tag must already exist, match the unit/version and resolve to the exact commit. The tool never creates tags,
fetches, publishes or overwrites artifacts. A commit-only source artifact is a candidate, not proof of a published Release.

The ZIP uses sorted entries, fixed metadata/timestamps and no compression. Its canonical manifest records the unit/version,
commit/tag, file hashes and exact execution bits. Same inputs yield identical bytes. Consumption verifies the selected SHA-256,
canonical archive, complete payload and actual frozen unit source; it never extracts archive paths into the working tree.
Links, duplicate/escaping paths, missing/extra payload and same-version source drift fail closed.

Unit content follows actual workspace members: libraries include their crate trees, literal compile-time resources/vectors,
Gateway source protocols and the existing Gateway/timezone generator tools; a plugin includes its own distribution tree;
frontend includes its own package tree. Backend includes its Rust/Python constituent tree, the SDK files declared by the actual
SDK builder, schema/contract inputs and the build tools it uses. Root LICENSE is shared. Rust units bind inherited workspace
semantics, excluding the workspace member list and, outside libs, the library version. Pure Python plugins/frontend do not
inherit Rust semantics. Dynamic Rust includes are refused pending explicit closure design; existing Rust source guards remain.

Root manifests, Cargo/uv/npm locks and pinned toolchain are retained as original-build context in each source artifact.
The current composition independently binds its actual locks, profiles and environment through the full frozen build-input
selection. Reusing library source does not silently replace current locks with an old bundle's locks. Backend-only changes
can generate a new build selection while retaining the exact same library/plugin artifacts; version equality never substitutes
for content equality. Source identity includes the canonical unit inventory; the ZIP digest also binds original context/origin.

For a dependency-locked native build, provide an operational JSON file to `--source-bundles` in candidate, check and builder:

```json
{
  "libs": {"path": "libs.zip", "sha256": "SELECTED_SHA256"},
  "plugin-binance": {"path": "binance.zip", "sha256": "SELECTED_SHA256"},
  "plugin-tushare": {"path": "tushare.zip", "sha256": "SELECTED_SHA256"},
  "plugin-indicators": {"path": "indicators.zip", "sha256": "SELECTED_SHA256"}
}
```

Paths are locators, relative to that JSON file or absolute; they are not semantic identity and are not copied into the artifact
receipt. Required units derive from backend's declared Rust normal/build dependency closure and the internal Python executor's
plugin requirements; undeclared local Rust dependencies, omitted or extra units are rejected. No per-worker package/registry
is introduced. Keep generated ZIP/selection files under `test-results` when using the frozen dev environment.

The native builder requires this complete source selection whenever `--release-inputs` is used. Preliminary candidate/check
without source bundles remains only a whole-tree input preflight; ordinary dev builds omit both options. Before artifact
creation and after building, the selected source bytes/origin and the whole frozen build inputs must agree. Existing artifact
manifests retain each selected ZIP/content digest, unit version and commit/tag alongside the build receipt and artifact hashes.

These tools do not certify published provenance, a frontend/backend API pair, install/start/activation or supported history.
Those phase-6 proofs and authorized executable publication remain separate. No ordinary build activates a Generation or LIVE.

### Runtime assembly and selected-artifact acceptance

Native workstation and Docker runtime construction share `runtime_artifacts.py` schema 2. Each manifest requires an exact
bundled pair: backend/frontend versions from their own metadata, the backend executable digest, the Web file-inventory digest,
and Product API v2 OpenAPI/stream contract digests. The built executable's pure contract exports must equal the selected source
contracts before sealing. Version-number equality is neither required nor a compatibility test. The declared default is the
exact bundled pair; no arbitrary mixed-version matrix or rolling-upgrade promise is created. Missing/changed pair metadata,
contracts or payload fail with an explicit artifact error before acceptance starts. Earlier dev manifest schemas are not loaded.

Docker's `runtime-inputs` checks the same exact selection before runtime compilation/installation; the assembly checks it again
and writes the same manifest. Original fixed-path Python identity is retained: installation is created directly under
`/opt/onlyalpha/algorithms`. The runtime executable is `/opt/onlyalpha/bin/onlyalpha-backend`, inside the hashed artifact tree.
The final image verifies that tree as its non-root runtime user, without starting a Product service, database or deployment.
The default CI runtime smoke remains an explicitly unselected development build; it makes no release-input claim.

Local selected image construction uses the existing lifecycle/frozen-source entry and only the fixed `onlyalpha-runtime:dev`
tag, without creating or starting a new service/project:

```text
python scripts/dev_verification.py runtime-build -- --release-inputs INPUTS.json --release-inputs-sha256 SELECTED_SHA256 --source-bundles SOURCES.json
```

It validates/copies only the explicit non-secret selection into a managed frozen-context capsule, preserves original image
identity/consumer observations and build logs under `test-results/runtime-image`, and refuses source/selection drift.
Docker build inputs `ONLYALPHA_RELEASE_INPUTS_DIR` and `ONLYALPHA_RELEASE_INPUTS_SHA256` must be supplied together for a selected
build. No automatic publication or deployment follows. Changes to Docker/tool dependencies require the ordinary explicit
fixed dev-tool image preparation before affected formal checks; source-only edits do not.

Browser acceptance can consume the original selected workstation artifact without compiling or reinstalling it:

```text
python scripts/dev_verification.py run -- python scripts/native_web_e2e.py --artifact /workspace/test-results/native-workstation/OPERATION --artifact-sha256 SELECTED_MANIFEST_SHA256 --grep "native watchlist" e2e/product-package-migration.spec.ts
```

Both selection arguments are required together. The manifest digest, original installation path, source/payload and default
pair are admitted before touching test databases, checked before launch and again after owned process draining. The existing
single-dev test namespaces, test-DB guards and ordinary Shipping UI flows remain mandatory. This technical receipt records
the exact artifact used; it does not confer Generation or trading authority. A normal dev run may still build its own artifact.

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
