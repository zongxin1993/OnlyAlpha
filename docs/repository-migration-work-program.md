# Repository, release and Python retirement work program

This is the construction sequence for [ADR 0142](adr/0142-library-product-boundaries-and-independent-releases.md) and
[the owning architecture](repository-product-architecture.md), not an execution authorization, task checklist, progress ledger
or second acceptance Authority. Use AGENTS.md for each in-context Task Contract and risk/impact selection. This document-only
design does not move/delete code, release artifacts, reset data or activate execution. Constitution Impact: NO.

## Scope and order

First reorganize the engineering/product boundary while preserving admitted behavior. Then continue remaining native
capabilities in [Rust Product construction](rust-product-backend.md) and the [Kernel work program](rust-kernel-migration-work-program.md).
Do not require a whole-backend rewrite before repository organization; do not call repository organization complete Rust
Product migration. Phases below are dependencies, not claims that the initial checkout lacks or has passed any particular gate.

| Phase | Change surface and deliverable | Required proof before stopping the phase |
|---|---|---|
| 1. Normative alignment | Architecture/ADR, release rules and owning work programs; current paths explicitly distinguished from target | Constitution consistency, direct-link/reference review, no competing normative rule or code-completion claim; bounded independent review |
| 2. Release units | Root Cargo metadata; backend/frontend/plugin manifests and locks; `scripts/version_sync.py`, `scripts/github_release_plan.py`, `scripts/publish_github_release.cjs`, release workflows and their actual tests | Independent selected increments/tags; no unrelated bump; immutable publication/retry/conflict tests; existing publisher remains coherent until atomic cutover |
| 3. Libraries | Move shared libraries from `packages/` to `crates/`; rename `core`/`onlyalpha-kernel` to `predicates`/`onlyalpha-predicates`; change manifests/imports/build and fingerprint consumers together | Package-selected and isolated source/dependency builds; forbidden-edge checks; unchanged owning semantic vectors/errors/bytes; provenance changes recorded without changing old facts |
| 4. Product packages | Merge Product/HTTP modules into `packages/backend`; move Web to `packages/frontend`; consume separated library/SPI boundaries | Affected Application/API/security/persistence/renderer regressions and real Shipping UI paths; no direct transport-store shortcut or plugin-backend edge; actual build/install/deploy consumers updated |
| 5. Execution packaging | One backend program's serve/worker roles; extract native supervision from reusable algorithm bridge; reconcile minimal Python manifests, `scripts/build_algorithm_sdk.py`, Docker/build/install consumers | Actual child execution/checkpoint continuation; bounded failure/cancel/UNKNOWN tests, role/claim isolation, restart recovery; installed SDK closure matches metadata and runs without broad Python business services where replacement is admitted |
| 6. Formal release composition | Exact library/plugin source artifacts, backend/Python bundle and frontend artifacts, release provenance and declared API combinations | Clean locked build/install/start from selected immutable inputs; reject drift/missing artifacts/unsupported combination; tested default pair; exact Generation claim, draining/new-work rollback/history proofs |
| 7. Remaining native capabilities and retirement | Complete affected Rust owners in actual dependency order; delete each eligible Python implementation and its full consumer closure | Per-capability semantic, Product, fault/recovery and applicable compatibility/history gates; no current caller of removed code; final R8 aggregate retirement remains required |

Phase 2 establishes release selection/provenance rules using actual current paths: backend metadata starts at the current
HTTP product entry manifest, frontend at the current Web manifest, with internal transitional components derived from their
owning product unit rather than independently published. Phase 4 moves those authorities/path consumers atomically to
`packages/backend` and `packages/frontend`. Do not create empty target packages to satisfy phase 2. A buildable combined
release/package cutover is permitted where actual tooling dependencies require it; the same unit's tests stay together.
Phase 6 proves the assembled artifacts after relocation. Every intermediate
candidate must be buildable and honest about its scope. Do not disable old checks without replacing their required assertions;
do not publish an intermediate candidate with incoherent old/new release rules. Release numbers for the first new-line artifacts
are selected against actual published history at implementation time, not invented here. No automatic commit, merge, push or
publication is authorized by this plan.

The current workstation's release composition can be validated independently of not-yet-native Research/Generation roles.
Keep phase-5/6 claim/drain/new-work rollback obligations attached to the capabilities that consume them; a build or workstation
UI check does not discharge them. Private Factor authoring is constructed before its Research/Generation execution consumers,
following the Product dependency map and [Private Factor authoring](private-factor-authoring.md). This clarifies dependency order,
not completion or a waiver of any gate.

## Implementation procedure at each stable boundary

Read Constitution, owning contracts/ADRs and current checkout/callers first. Freeze Required Behavior and name the exact source,
test, packaging, fingerprint and deployment consumers in the in-context Task Contract. Add minimal regression/fault tests for
real behavior changes and new guards, prove their failure, implement the smallest correct change, then run impacted checks.
Pure relocation uses existing meaningful semantic tests plus stale-reference/build/provenance checks, not tests that merely
mirror names. Extend impact only to the nearest demonstrated stable boundary.

Retain independent lower-layer builds, explicit allowed dependency checks and internal-module ownership. Update directory
references, code generators, installed resources, license inputs, image inputs and source inventories atomically; do not leave
compatibility aliases to conceal missed consumers. Path movement changes executable provenance, not canonical semantic identity.
Do not create empty directories or future APIs to fill the target tree.

## Python cleanup is part of migration delivery

Start by auditing Python counterparts of already implemented Rust libraries during phase 3, not only newly implemented
capabilities in phase 7. Include eligible deletion in the earliest bounded phase whose consumer/admission dependencies permit
it. Phase 7 closes remaining dependencies; it is not a blanket deferral of all cleanup to the end.

Assess each selected migrated library's Python implementation and current consumers, including SDK build projections, tests,
algorithm execution, Product services, admission, persistence/recovery and cross-language comparison tools. Classify against
the owning Contract: migrate business/Kernel semantics to Rust; retain only necessary algorithm API/helpers and legitimate
language-specific plugins/tools. Rust crate existence, a module count or local vectors alone are never deletion proof.

An eligible module's retirement must remove its obsolete implementation, imports/re-exports, entry points, package metadata,
dependencies/locks, build/deployment references and obsolete implementation-only comparison tests in the same bounded delivery.
Keep or migrate independent golden/adversarial vectors, deterministic fault assertions, identity/serialization guards and replay
tests to their Rust/remaining legitimate consumers. Do not retain a live Python reference implementation just to run a retired
comparison, delete a valid assertion to make removal pass, or port Python defects as the Rust oracle.

If a still-admitted Python Runtime, algorithm resource or consumer requires the module, first migrate that consumer or extract
its minimum Contract-defined algorithm SDK. Keep the fact explicit in task context until resolved; do not mark cleanup complete
or delete early. Retire safely replaceable modules incrementally; R8 is the final aggregate gate, not a mandatory period of
unnecessary dual maintenance. Follow ADR 0139/0141 activation requirements for each affected official writer.

Prove no maintained runtime/public caller depends on removed paths and no hidden Python business fallback exists. Required
exact historical artifacts/readers for bound work remain addressable; retention is not permission for a new current legacy
loader or permanent dual Kernel. Demonstrate current-state stop/start/recovery and applicable supported upgrade/history behavior.
Disposable old local dev data can be rebuilt only under AGENTS.md resource/lifecycle rules; rebuilding does not prove historical
compatibility. Cleanup of source is not authority to erase immutable facts or artifacts.

## Acceptance by impact

| Area | Evidence and negative cases |
|---|---|
| Structure/dependency | Affected package and isolated-closure build/test; reject reverse, cyclic, undeclared or backend-from-plugin imports; all relevant generators/build/install consumers updated |
| Semantic preservation | Exact canonical values, bytes/identity, errors, permissions, state transitions and applicable restart/checkpoint results; no silent historical rebinding |
| Lifecycle | Controlled crash after claim and at durable boundaries; API restart, worker/child exit and cancellation; no duplicated effects, second order identity or discarded UNKNOWN |
| Generation/artifacts | Missing/corrupt/mismatched artifacts fail closed; simultaneous different Generations remain isolated; activation/rollback affects new work only; sole binding/ledger Authority preserved |
| Releases | Selected-unit increment only, unique tags and immutable bytes; idempotent exact retry, conflicting publication failure, source drift despite matching manifest version, lock/toolchain/features/target drift |
| Python installation | Actual built minimal installation executes admitted algorithm and continuation without ambient host packages; package metadata, builder and installed closure agree; no broad Core hidden in SDK |
| API combinations | Default pair passes real UI flow; explicitly claimed differing versions pass contract/behavior proof; incompatible use gives clear UI/startup feedback without fallback or auth weakening |
| Python deletion | No surviving current import/build/deploy/discovery reference; useful vectors/fault/history assertions survive; required historical artifact resolution and legitimate SDK remain |

Business acceptance starts at the normal Shipping Web UI and includes every business step in the selected User Goal, through
the real versioned Product API and canonical owning Authority. No direct API commands, DB fixtures performing the goal,
state injection, mock backend or special acceptance page may replace user operations. Existing UI gaps remain explicit Product
gaps; they do not justify bypasses. Infrastructure build/install/compatibility tests and library tests are separate technical
evidence. Browser checks cover loading/empty/invalid/denied/unavailable/degraded/success, discoverability and normal recovery,
relevant keyboard/focus/responsiveness and the owning interaction budgets. Scope product flows by actual affected behavior.

Local formal validation uses only `onlyalpha-dev` / `deploy/docker-compose.dev.yml`, fixed dev roles/images, frozen read-only
source/configuration views, isolated test namespaces, one worker by default and retained `test-results/`. Reuse current safe
formal entry points; if unavailable, report the gap instead of using a second Compose topology or a legacy destructive runner.
Use impacted module tests and the canonical execution definitions from `quality-policy.toml`, `scripts/test_suite.py` and
`scripts/verify.py`. A phase boundary does not authorize a complete local verification workflow: select only modified modules
and demonstrably affected consumers, reuse unaffected passing evidence, and keep full release/CI gates explicit. Library
relocation requires isolated closure proof for the relocated/renamed libraries, not repeated semantic suites for untouched
Kernel modules. Use affected Rust format,
Clippy/build/tests and Python Ruff/format/mypy where applicable. No unrelated full-suite requirement is added by this plan.

Each nontrivial executable change includes bounded Simplicity Review; each high-risk unit includes bounded Independent Review.
Governance/release changes are high risk. Stop when Required Behavior, selected acceptance/baseline/specialized checks,
Constitution consistency and required reviews pass with no current-scope High/Critical. Preserve unavailable evidence as
unavailable. Library, structure, local Linux, real DB, browser, CI and external-target evidence remain distinct. No phase
grants LIVE activation or waives R3–R8; no repository PASS/status ledger is created.
