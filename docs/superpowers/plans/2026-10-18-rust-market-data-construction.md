# Rust Market Data Construction Implementation Plan

> Execute inline using superpowers:executing-plans and TDD; one bounded independent final review. The Owner explicitly
> delegates design decisions and authorizes implementation/publication without further approval handoffs. Checkboxes are
> planned actions, not repository progress; execution/evidence notes stay in ignored test-results.

**Goal:** Complete deterministic Construction library with audited identities, graph execution, TIME_BAR@1 and atomic recovery.
**Architecture:** Construction -> Domain only; immutable graph/plan, registered pure algorithm factories, one non-Clone owner.
**Tech Stack:** Rust1.99.1, std, exact admitted num-bigint/serde_json/sha2, sole Linux dev verification environment.
**Spec:** ../specs/2026-10-18-rust-market-data-construction-design.md

## Global constraints

Constitution impact NO. Version0.10.10. No Python production restructure, State/Runtime activation, history migration/deletion,
new registry nodes, UI, order effects or deployment. Current public schemas retain canonical meanings; manager Rust schema4
is unadmitted and has no Python schema3 fallback. All formal verification uses scripts/dev_verification.py with frozen source.

## Review focus

- Unregister an absent ID or create a cyclic/conflicting registration: owner and shared executor state unchanged.
- A valid first executor followed by invalid output/restore: no accepted prefix; process fail-stops, restore preserves prior state.
- Duplicate/late source input after a completed/reset window: reject rather than construct a second fact.
- Wrong calendar, whole owner, recipe, source or missing lane: no substitution; record decode grants no readiness/absence.
- Preview, optional amounts/precisions and historical acquisition init: preserve immutable facts and explicit logical timing.

## Task1: Model, recipe/graph identity and package admission

Files: new module Cargo.toml, src/{lib,model,record,compiler}.rs; tests/{model,graph}.rs and support/mod.rs; root Cargo manifests/
lock, scripts/rust_kernel_check.py and version_sync.py, affected tool graph fixtures. Package onlyalpha-market-data-construction.
Interfaces: OnlyConstructionInput::{Bar(OnlyBarType),Trade(OnlyTradeInputType)}, OnlyConstructionRecipe native/derived typed
constructors/current records/fingerprint, OnlyConstructionEdge::new(source,target,recipe), OnlyConstructionGraph::new(providers,
edges)/record/fingerprint, OnlyConstructionPlan::compile(graph,source)/ordered lanes and IDs. Fields private/read-only.
- [ ] Tests first: graph order independent; duplicate input/target, dangling/cycle, wrong instrument/semantic and known algorithm
input/output formation reject; exact current recipe/lane/graph JSON and fingerprints match independent literals.
- [ ] Observe RED through dev; implement strict validation and iterative topology, no recursive unbounded compiler.
- [ ] Admit sixth package with Domain + reviewed num-bigint/serde_json/sha2 exact features; update fake graph/version tests;
rebuild fixed dev image once after all planned manifest inputs are final. Run model/graph + manifest/version tests; local commit.

## Task2: Resolution and construction lineage

Files: src/resolution.rs, tests/resolution.rs. Typed OnlyConstructionCapability, Requirement::{PreferExactNative,Exact(recipe)},
OnlyConstructionResolutionContext(source/instrument/integration/calendar), OnlyConstructionResolutionPlan::resolve(...),
OnlyConstructionIdentity::new(plan,data_version,provider_semantic,optional derived base triple,adjustment evidence).
- [ ] RED tests: exact Native wins; unavailable/ambiguous/mismatched exact recipe refuses fallback; derived1m selection;
calendar/grant metadata remains explicit; RAW/LAST fixed<=240 interactive policy; negative-grid modulo and expected ends exact.
- [ ] Implement current plan3/identity2 strict readers and fingerprints; prove nested target/requirement/recipe/source relations,
mandatory base revision/seal and no false durability claim; roundtrip/mutation/independent vector tests GREEN; local commit.

## Task3: Pure executor SPI and TIME_BAR@1

Files: src/{executor,time_bar}.rs; tests/{time_bar,preview}.rs. OnlyConstructionFact typed Bar/Trade; executor process(fact,init)
->Result<Vec<Arc<OnlyBar>>>; target/checkpoint/restore. Registry exactID/version -> pure factory; default TIME_BAR1 only.
- [ ] RED tests: 3 x1m ->exactOHLC/volume300/count3; session/lunch/crossday/DST; divisible-aligned validation, no hidden clock;
missing REJECT/SKIP_WINDOW; tail DROP/REJECT; wrong precision/amount currency; duplicate after reset rejects; immutable preview.
- [ ] Implement using Domain calendar and decimal helpers, exact explicit init; state validates/reconstructs from bound schema1
records; late invalid restore leaves original untouched. Unknown executors unavailable; debug/release GREEN; local commit.

## Task4: Owner registrations, propagation and atomic recovery

Files: src/manager.rs, tests/{manager,recovery}.rs. OnlyConstructionScope(engine,runtime,source), manager new(scope,calendar,
registry), register(explicitID,graph), unregister(ID), process(source,fact,init), checkpoint/restore; immutable compiled queries.
- [ ] RED tests: registration-order-independent 1m->5m->15m fixpoint, shared refcounts/retained state; absent-ID unregister,
conflict/cycle/factory failure leaves state unchanged. Trade fake routes through exact Lane; wrong/duplicate/future/open output
fail-stops without committing or delivering prefix; wrong source rejected. Require explicit recovery before more processing.
- [ ] Implement fresh staged executors from pure factories + validated captured state. Restore full schema4 into temporaries,
check all owner/graph/calendar/registration/lane/count relations then one swap. Test duplicate rows, late malformed executor,
foreign complete context, huge exact creation count, idempotence and restored/uninterrupted equality; local commit.

## Task5: Independent vectors, enforced isolation, review and mainline

Files: test-data/market-data-construction/{README.md,models-v1.jsonl,operations-v1.jsonl}; module/tests/conformance.rs;
tests/market_data/test_rust_construction_vectors.py, tests/tools/test_rust_construction_boundary.py; owning MarketData Contract
and Rust responsibility map/work-program navigation; rust_kernel_check source guard + isolated extraction/main lane.
- [ ] Tests first for source/manifest reverse edges, hidden build/include/env, native effects and isolated Domain+Construction
closure. Extend existing guard with named fixture paths; no parallel store/env or calculation imports. Observe RED then GREEN.
- [ ] Hand-specify expected records/hashes/session outputs; both languages consume real common APIs, no generated oracle or
production compatibility layer. Preserve corrected Rust adversarial assertions separately from known Python deviations.
- [ ] Run affected Python resolution/aggregation/construction tests, vectors/tools, Ruff check/format, mypy scripts; all Rust tests,
fmt/Clippy and profiles; bounded simplicity review; one fresh independent review re-derives state space/relation closure/
negative invariants and mutations. Fix blocking findings with deterministic regression tests.
- [ ] Stable-source full canonical rust-kernel lane, exact receipts and Constitution consistency; no remaining scopedHigh/Critical.
Fetch master, fast-forward or integrate bounded concurrent changes with affected verification, prove tested-tree equivalence,
normal push, fetch and verify alignment. Publish no new Release/version by default; stop at authorized mainline publication.
