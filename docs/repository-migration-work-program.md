# Repository, release and Python retirement work program

This is the construction sequence for [ADR 0142](adr/0142-library-product-boundaries-and-independent-releases.md),
[ADR 0146](adr/0146-independent-agent-product-and-python-langgraph.md) and
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

## Product display migration

[ADR 0143](adr/0143-product-names-display-versions-and-historical-labels.md) records the accepted decision;
[Product display identity](product-display-identity.md) owns its terms, boundaries and rules. The following sequence refines
the Product capability phases above; it is not a completion ledger or a new acceptance Authority. It authorizes no code
changes by itself. Each implementation slice still freezes its own Task Contract under AGENTS.md.

| Stage | Deliverable and dependency | Acceptance at that boundary |
|---|---|---|
| D1 — Private Factor presentation | Audit the existing Rust writer, version-bound description and current consumers; implement owning current display metadata, meaningful defaults, API/DTOs and the existing Shipping editor together. Derive the display ordinal from verified history; preserve current content identity. | Normal UI creates an object with usable defaults, renames/edits its summary and retains changes after reload/restart. Object ID, existing Revision/source/API fingerprints and publication count stay unchanged. Stale concurrent rename fails explicitly; accepted Command replay does not apply another update. Two content publications keep stable ordinals after rename/filtering; incomplete/forked history is unavailable, not renumbered. Source/parameter-contract edits still follow content publication. No raw ID input is required. |
| D2 — Existing catalog and workspace surfaces | Start with the existing published private Factor directory/search/exact-detail consumers of D1: project current name/usage separately from unchanged registry/content identity, and retain the selected exact locator plus verified display ordinal across rename/new publication. Then reuse D1's presentation rules for installed Indicator/public Factor defaults, explicit Product type overrides and per-instance workspace labels. Touch only existing native catalog/workspace consumers and their actual owning stores. | Two instances of the same algorithm with different parameters remain distinguishable; a custom label survives restore without changing algorithm identity or numeric output. Plugin declarations/bytes remain unchanged. Reordering/filtering cannot change version labels. Technical IDs remain discoverable; missing/denied/loading states stay explicit. No new public calculation or execution capability is claimed. |
| D3 — Native task titles and submission snapshots | Include names/usage summaries and coherent exact-input name/version capture in each actual native Research or Backtest admission slice. D1/D2 establish label ownership; each task's existing semantic/admission prerequisites still govern execution. | Through normal Shipping UI submit with input name A, rename the object to B, then reopen/restart and view the result: A is primary, B is optional current context, and exact Revision/configuration/Dataset/result pins are unchanged. A concurrent rename cannot mix unbound snapshot fields. Rename the task title independently; accepted submission retry preserves the original snapshot. Unavailable current-name lookup does not substitute latest input or hide the recorded name. Published report bytes stay unchanged. Missing required new-model snapshots fail closed. |
| D4 — Direct-consumer closure and eligible Python deletion | At each earlier stage migrate its real callers and useful independent assertions, delete replaced Python business/import/export/packaging paths as soon as retirement conditions are met. After the last affected surface, review remaining raw-fingerprint-primary presentation and current description-as-name coupling. | No current caller/build/install/discovery path depends on a deleted implementation. Necessary algorithm SDK/AST/math helpers remain. No Python business proxy, duplicate name Authority, browser-generated ordinal, name-based execution lookup or speculative extension survives. The affected UI paths and direct consumers pass; this does not trigger a whole-repository cleanup or full test workflow. |

D1 is a complete small Product slice and need not wait for all D2/D3 work. Private Strategy display metadata and its authoring
Revision ordinals follow the same rules when the actual native Strategy authoring slice is delivered; D1 does not implement
Strategy authoring or assign publication ordinals to arbitrary frozen Strategy history. D3 is delivered with the real native task flow,
not with a mock task service or placeholder-page rewrite. Do not expand a task to all Research/Generation/Backtest lifecycles
solely to satisfy display planning. These stages add no services, crates, alias registry, second version ledger, dev runner,
release/cache framework or automatic deployment. They do not replace the existing Rust migration dependency order.

This active-development cutover excludes old-row/name initialization from current descriptions, historical name-snapshot
backfill, old-schema/DTO compatibility, legacy loaders, identity translation, old-version execution and rolling-upgrade matrix
work. Implement the chosen current model directly. Any necessary disposable dev rebuild is explicit and coordinated under
AGENTS.md; no test or normal startup silently resets, migrates or rebinds business data. This is not authority to rewrite
existing fingerprints, mutate retained immutable facts or weaken new-model history/recovery. No reset is performed by this
documentation task.

Verification follows actual impact: D1's metadata/identity/history/Command/API/editor checks; D2's affected plugin-description,
catalog and workspace consumers; D3's owning task admission, snapshot/recovery and result/report consumers. Run the nearest
affected canonical checks and real Shipping UI path through the single `onlyalpha-dev` entry. Keep hermetic error/concurrency
and current-model restart proofs, preserve guards and use bounded independent review where required. Do not run unrelated
Kernel/Research/Backtest suites, full-repo coverage or release matrices for a display-only slice. This document-only stage
requires link/reference, Constitution and bounded architecture review; it requires no business test run or code migration.

### Private Factor contract-form follow-up

[ADR 0144](adr/0144-private-factor-forms-and-lossless-contract-editing.md) refines the existing D1 authoring surface after its
name/usage/version boundary. [Structured contract editing](private-factor-authoring.md#structured-contract-editing-target)
owns the agreed fields, defaults, validation and lossless-round-trip acceptance cases. This sequence is a dependency plan,
not a completion claim or an authorization to change executable code in the documentation task. It does not replace D2/D3
or expand into their native execution capabilities.

| Step | Bounded deliverable | Proof before proceeding / closure |
|---|---|---|
| D1-F1 — Lossless editing boundary | Audit current three contract objects, ordinary representable subset and actual mapping consumers; specify the minimal per-section projection/patch behavior in the existing frontend. Keep Rust storage/API/identity unchanged. | Deterministic no-op/edit-revert vectors for omitted/explicit flags, nullable spellings, required/default combinations, unknown/nested content and exact numbers. Projection cannot drop fields or coerce values; unsupported sections retain advanced editing. No new generic schema engine, endpoints or tools. This technical prerequisite alone is not Product closure. |
| D1-F2 — Shipping forms | Integrate 所需数据 / 可调参数 / 计算结果, their documented new-object/new-row defaults, local errors and independent advanced controls into the current authoring dialog. Reuse Save/Publish and name/usage paths. | Through ordinary Web navigation create/edit/save/reload/publish without entering JSON for common structures. Exercise each complex section independently and show confirmed required/default companion edits. Existing content/display CAS, UNKNOWN recovery and unsaved text survive. Type/format checks are never presented as source/execution validation. |
| D1-F3 — Direct-consumer closure | Complete the owning architecture's acceptance cases with backend-observed identities and real UI/dogfooding; remove only superseded editor code whose consumers have moved. | No-op round trips and revert retain exact canonical content; true content edits use existing publication rules and leave old Revisions exact. Error/unknown-field/numeric and accessibility/narrow-viewport cases pass. No remaining direct consumer depends on removed UI code; Python algorithm/business code is not deleted merely because input widgets changed. |

Deliver these steps as one coherent bounded Product change; do not defer UI until an unrelated backend rewrite. Verification
covers the edited editor/client/projection tests and directly affected API/authoring consumers only. Preserve guards and
required identity/concurrency/recovery proof; run real Shipping UI through the sole dev environment. No full-repository suite,
new runner, compatibility framework, Kernel migration, automatic deployment or unrelated Python cleanup follows from this plan.
The present documentation change requires Constitution consistency, direct-reference review and bounded independent review,
not runtime tests, a dev refresh or code migration.

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

## Conversational Factor Research follow-up

[ADR 0145](adr/0145-conversational-factor-research-and-candidate-review.md) records the owner-selected next product direction:
[Conversational Factor Research](conversational-factor-research.md). Use the existing Private Factor authoring, forms and private
catalog/display consumers as foundations. Their actual current completion is established from source/tests/UI evidence, not this
work program. The ordering below refines phase 7's next Product slice and the Agent work program's earlier automatic-search-first
MVP. ADR 0146 now refines phases 1–6 with the Agent release unit and the extraction below; no implementation is authorized
through this documentation task.

### Stage one: human-led single Research

| Order | Bounded deliverable | Required acceptance before proceeding |
|---|---|---|
| C1. Trace and freeze the actual slice | Inspect existing Rust/Python Authoring, admission, Research, Dataset, provenance and Evidence consumers; map precise Product/API/Authority gaps and the smallest complete module delivery | Freeze Task Contract and real Shipping UI scenario, exact formula/implementation binding, source/code admission and input-preparation boundaries; distinguish implemented capabilities from target contracts; no alternate Authority or speculative platform |
| C2. Chat and confirmed Factor | Persistent chat/current-preview layout; clarify one hypothesis, generate readable Factor content, save/retrieve candidate through existing authoring; retain code/contracts in advanced details | Normal UI can inspect/confirm the exact Factor; no mandatory JSON/internal ID; stale or ambiguous confirmation cannot act; formula/code changes require renewed acceptance; refresh retains draft and confirmation context; this gate alone does not claim Research closure |
| C3. One-run Research vertical slice | Agent-recommended conditions, negotiated through chat, separately confirmed once; minimum native immutable-input/admission/Research/Evidence and provenance consumer closure; report actual scientific evidence | Real Shipping UI reaches canonical computation and report with pinned inputs; condition changes require reconfirmation; missing data/unsupported capability is actionable, not a fallback; acknowledgement loss/restart/cancel race preserves one Command/task; no mock chart result or LLM numeric substitute |
| C4. Review and improvement | Pending-review daily entry, full history, human collect/observe/archive; earlier names/versions and exact reports; one explained improvement draft | Same asset identities in all views; complete attempts retained; no scientific/runtime side effect from collection; improvement cannot run until both confirmations recur; no repeated resurfacing without new evidence; same-path usability/dogfooding and bounded review complete |

C2–C4 are construction steps of one user flow, not permission to mark the overall product complete while Research is missing.
Integrate ADR 0143's D3 task labels and historical-name snapshots when the real C3 consumers appear; do not build independent alias
infrastructure. Candidate disposition and screening views must not create a second progress, quality or certification ledger.

For every selected step, audit the Python counterpart and direct consumers under ADR 0139. Migrate the actual semantic boundary
and independent assertions to Rust, then remove eligible Product/Research/provenance implementation and its obsolete imports,
packaging and tests. Keep a still-required consumer explicit until migrated; neither a chat shell nor crate existence meets R8.
Legitimate independent Agent Python orchestration/model/tool code, Factor/Indicator algorithms and their minimum admitted SDK
are not automatically retired. Backend-owned facts remain Rust; extraction is not permission to relabel their old Python
implementation as Agent code. Do not implement
historical development-data compatibility, new legacy loaders or broad cleanup. No extra release/build/validation platform is
part of this Product priority.

### Stage two: bounded automatic mining

Begin only after the stage-one real path and the required formal Brief/Search/policy/budget/holdout capabilities support the
selected scope. It requires separate owner authorization; stage-one chat consent cannot be upgraded to blanket mining permission.

1. Bind a human-approved mandate to exact goals, sources, data/sample/evaluation rules, admitted tools/models, budgets, concurrency,
   expiry/cancel and stop conditions. Prove scope denial and recoverable consumed-budget/unknown-outcome handling.
2. Add the selected bounded search/refinement method through existing Research and provenance APIs; retain all attempts, rejected
   candidates and lineage. Literature/market reading is added only when that scope is authorized, with exact provenance and
   untrusted-content boundaries; no automatic public library changes.
3. Apply a frozen versioned screening policy to authoritative evidence: validity/sufficiency, predictive support/robustness and
   evidenced distinct contribution. Prove condition grouping, truthful missingness, evidence-tier membership, explicit deterministic
   ordering/ties and reasons, family grouping and no resurfacing without new evidence. Never optimize repeatedly against protected
   holdout while claiming independent confirmation.
4. Show a small pending-review shortlist with complete history available; human collection remains separate from scientific
   Qualification and Promotion. No cross-condition universal total score is required. Prove the full ordinary Shipping UI review,
   stop/cancel and restart path and the scoped budget/fault/adversarial cases before expanding autonomy.

Neither stage starts Backtest, SIM or LIVE. Their long-term direction and existing permission gates remain; they require future
bounded Product slices. All implementation verification remains impact-aware: modified modules and direct consumers, targeted
canonical lanes and real UI for the selected flow, with existing guard/determinism preserved. Do not run a full repository process
at each step, or broaden the work to unrelated tools. This plan records construction/acceptance requirements, not completion status.

## Independent Agent product migration

[ADR 0146](adr/0146-independent-agent-product-and-python-langgraph.md) and
[Agent service architecture](agent-service-architecture.md) refine C2 placement and the release-unit plan. The goal is a real
independent Agent, not a directory move or a second research engine. Phases are task-sized dependencies, not completion claims.
A1–A4 preserve/rehome the existing C2 user goal; A5 is C3, with exact execution prerequisites; C4 follows its existing scope.
No new code, package, database, dependency installation, data reset, deployment or publication is authorized by this plan.

| Phase | Minimum deliverable and dependency | Required acceptance / stopping boundary |
|---|---|---|
| A1 — Freeze actual closure and release boundary | Re-read current C2, Agent/Python callers, APIs/security, model credentials, release/build/lock consumers; freeze exact protocol/ownership/gap and independent Agent artifact selection. Add real manifest/build consumers only with a coherent runnable slice, never an empty package just to satisfy tooling. | One version metadata authority for Agent and `agent` selection in existing release consumers when implemented; no unrelated bump; exact frozen source/lock/environment inputs; deny missing/incompatible artifacts. Model/workflow configuration is separate from package/Factor identity. Classify current implementation vs target and eligible Python/Rust deletion; Constitution and bounded boundary review. No runtime migration is claimed from metadata alone. |
| A2 — Independent Agent C2 service | Python LangGraph service with its own identity/storage/migrations/model settings/secrets and API; immutable model/tool occurrences, Agent budget and checkpoint/session binding. Same authorized dev topology, separate installation closure. Keep the serving old path until an explicit coherent UI cutover; no active owner split. | Model setup, clarification and history are normal discoverable Shipping UI actions when exposed. Two-service subject/audience/ownership/origin checks; Agent cannot read backend tables/secrets or impersonate Human. Refresh/restart does not repeat calls/reset budget. Recorded-result reuse and unresolved UNKNOWN are distinct. Exact old workflow continues after upgrade; missing artifact/reader pauses without switching graph or backend fallback. Required independent review and targeted tests. No Research or Generation activation. |
| A3 — Backend proposal/acceptance seam | Reuse existing Authoring/global Command identity and retain the minimum validated immutable proposal snapshot with exact Agent origin. Scope Agent staging/query rights separately from Human confirm rights. No code/source admission is bypassed by registration. | Tampered/foreign/stale snapshots and code/formula mismatch rejected; concurrent manual edits protected; repeated registration/confirmation reconciles original identities. Lost acknowledgement/backend effect ahead of Agent checkpoint cannot produce a second effect. Backend displays/confirms staged input without Agent availability. No direct DB imports, distributed coordinator or parallel Factor store. |
| A4 — Atomic Shipping C2 cutover | Route chat/model settings/orchestration to Agent API and exact Factor confirmation directly to backend API. Both clients share a coherent user sign-in experience with separate intended audiences. Disable superseded C2 model/chat writer path at cutover; retain canonical backend authoring/validation. | Real Web: configure model → clarify → readable preview → direct backend Human confirmation → reload/restart. Verify independent outages, cross-user access denial, Agent attempt to confirm denied, stale tab, delayed response and UNKNOWN recovery. Formula/contracts/fingerprints/display labels unchanged; no mandatory raw JSON/IDs. Advanced forms remain usable. No Research/Generation; no dual active model configuration or legacy fallback. Normal UI can inspect exact pending/blocked state. |
| A5 — C3 one-run Research | Agent suggests real supported conditions; backend-registered proposal and separate direct Human Research authorization; complete only the necessary Rust admission/immutable-input/execution/statistics/report closure. | Real Shipping UI runs exactly one Research after both confirmations. Actual authoritative metrics and limitations, not chart/model results; edits invalidate appropriate approvals. Agent outage does not stop backend execution/observation/cancellation. Backend outage blocks formal progression; recovery reconciles original Command/task. Pin Dataset, Factor/source, model/workflow and relevant policies; retain failure/attempt/holdout/name facts. |
| A6 — Consumer and retirement closure | At each preceding phase remove already-eligible superseded code/imports/packaging/tests; this final step verifies no missed active consumers. Split old Python orchestration from backend-owned Search/Research/permission facts and migrate each at its actual owner. | Useful independent identity, fault, access and recovery assertions survive in the correct owner. No runtime/build/discovery consumer of removed Rust C2 hosting or old Python implementation; no permanent dual writer, proxy or compatibility shim. Retain legitimate Python Agent/algorithms/SDK and still-required callers until replacement gates pass. Removed routes/config readers cannot be reached through another entry. No speculative repository-wide cleanup. |

The prospective confirmation/staging and service-auth contracts are frozen in each owning implementation task before mutation;
this document selects no endpoint strings, token format, parser dependency, framework version or fake implementation. Use existing
public contract export/versioning and release/build/verification entry points; extend only necessary consumers, not a new tools
project, IAM platform or arbitrary historical version matrix. Backend Search/Research budgets and Agent call/tool budgets remain
separate, with consumption derived at their owning durable facts.

Selected default delivery verifies frontend/backend, frontend/agent and agent/backend combinations. Existing Agent sessions pin
workflow implementation/environment/checkpoint support; new releases change new-session defaults only. Prove active-session
ownership/fencing and that unavailable original versions cause visible pause with intact budget/outcomes. An explicit linked new
session with new confirmations/mandate is not silent migration of the old one.

Old disposable development C2 conversations/model settings are not a compatibility target. Reinitialize only explicitly confirmed
project-owned resources under AGENTS.md when an implementation requires it; never delete only one half of a coupled database/file/
key namespace or reset dev business state in tests/startup. New-model restart/integrity and retained exact facts still require proof.

After the single human-led C3/C4 path, stage two adds an explicit mandate and one justified search method at a time. RD-Agent-style
feedback and later QuantaAlpha trajectory methods are references, not installed execution authorities. AlphaGen RL and DEAP GP
are different methods; Optuna is not a drop-in replacement for ADR 0122's finite deterministic search. Any such integration must
freeze its actual algorithm/randomness/feedback/budget contract and use backend Research/Evidence, never a second PASS path.
Do not build all methods, broad literature infrastructure, Backtest or SIM before the selected product flow needs them.

Verification is strictly impact-aware: changed docs/contracts and direct references for A1 design; changed service/API/storage/
release consumers and real Shipping UI for executable slices. Preserve guards, determinism and bounded independent review.
Use the unique formal `onlyalpha-dev` entry and isolated test namespaces. No full-repository tests, extra tooling, automatic
publication/deployment or new business scope are implied by a phase number. Stop when that phase's required behavior and real
impact checks pass; do not silently proceed to the next phase without the corresponding authorized task.

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
