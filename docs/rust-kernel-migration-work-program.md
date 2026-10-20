# Rust Kernel migration work program

This document decomposes the owner-approved target in [ADR 0139](adr/0139-linux-first-rust-trading-kernel-migration.md).
It specifies construction order, deliverables and the behavior each unit must prove; it is not a task authorization, progress
ledger, certification report or second acceptance Authority. Every implementation unit still needs its in-context Task Contract
and AGENTS.md impact-aware validation. No Rust implementation or QMT removal is claimed by publishing this program.

## Responsibility assessment and incremental alignment

Use all of `src/onlyalpha/` as the assessment boundary under ADR 0139 section 1.1. This broadens assessment, not the definition of
Trading Kernel or the authorization to rewrite the entire backend. For each selected slice:

1. Identify its canonical Contract and actual callers; separate stable semantics, Python algorithm authoring, plugin differences,
   application orchestration and Infrastructure. A Python package may contain more than one responsibility.
2. Record the Python/Rust module correspondence in its owning design/development document. Reuse existing semantic Contracts and
   `test-data/` vectors; do not create per-language specifications or a second progress/acceptance registry.
3. Keep `src/onlyalpha/` and `crates/onlyalpha-kernel/core/src/` as their respective source roots for the canonical library. Align names,
   responsibilities and dependency direction only where the module exists. Preserve component/plugin placement for other roles.
4. Reuse sound paths; restructure only for a demonstrated boundary need in the selected slice. If paths change, update direct
   consumers, exact implementation manifests/fingerprints, tests and build inputs together; preserve historical exact artifacts.
5. Prove the selected Contract with independent vectors in both implementations, then apply the existing comparison/admission
   gates. Directory correspondence alone cannot establish equivalence, replace R1-R8 dependencies or authorize Python retirement.

Correct Python code does not need structural relocation before Rust migration. Audit the selected Python slice, freeze its
semantic Contract, implement it at the appropriate Rust boundary, and compare both against independent expectations. Retain
Python paths while they are comparison implementations; change Python only for demonstrated correctness, safety or comparison
validity needs. Retirement still follows R8 and preserves required artifacts/history; this policy does not retire Python-authored
indicators/factors or language-appropriate plugins. See the [time responsibility map](rust-kernel-development.md#time-responsibility-map)
for a concrete cross-package correspondence.

Stable application/Infrastructure capabilities need their own bounded consumer and migration proof before Rust implementation;
this program does not schedule a backend-wide rewrite. Algorithm authoring and market/plugin boundaries remain as defined in
ADR 0139. Begin navigation from the [Predicate responsibility map](rust-kernel-development.md#predicate-responsibility-map), without
moving existing files solely to make the map visually symmetric.

## Complete Domain module construction

Begin the module-oriented migration with `src/onlyalpha/domain/` and `crates/onlyalpha-kernel/domain/` under ADR 0139 section 1.2.
The selected unit covers the complete Domain public surface, not only a convenient set of identifiers or scalar primitives.

1. Audit all Python Domain areas and nearest consumers against their owning Contracts. Enumerate base serialization/errors,
   identifiers/enums, financial values, time, instruments/catalogs, calendars/venues/rules, trading intent, market facts,
   accounts/positions/PnL, fee identities/assessments and execution requests/fills/snapshots. Resolve normative and implementation
   differences before declaring a stable comparison baseline; preserve historical identities and immutable artifacts.
2. Apply the owner-approved rules in [ADR 0140](adr/0140-domain-determinism-and-cross-language-contract.md): numerical precision/rounding/range rules, unambiguous identity encoding, strict subtype-aware serialization and explicit
   timezone-rule dependencies where needed. Existing Python behavior that violates higher-level invariants is not a Rust target.
3. Build the independent Rust Domain library in internal dependency order: foundational errors/enums/serialization, identity/value/time,
   then their model and operation consumers. Reuse maintainable admitted dependencies where std does not cover required behavior;
   do not invent decimal arithmetic, JSON or timezone infrastructure to satisfy a speculative zero-dependency goal.
4. Exercise both implementations against independent module-wide vectors and adversarial mutations, with exact canonical identity,
   numerical results, errors, subtype-preserving serialization and applicable replay/history checks. Internal steps do not replace
   whole-module coverage. Add direct consumer regression evidence required by actual Python corrections.
5. Prove declared package-selected and isolated source/dependency closure build/test, reject reverse/cyclic/undeclared imports,
   and complete bounded independent correctness and simplicity review before module acceptance. No Runtime activation, Python
   retirement or LIVE permission follows from a Domain library build or matching corpus.

These are future construction dependencies, not a completion ledger. The existing R0-R8 activation and retirement gates remain.

## Complete Clock module construction

Apply the owning [Clock Contract](clock.md), ADR 0008 and the [owner-approved Rust design](clock-rust-design.md).
Audit Python `core.clock` and its direct checkpoint/Timer-service consumers before implementation. Keep Python production paths
as reference implementations; classify defects against independent expectations, without requiring structural cleanup.

**Modification map:** independent `crates/onlyalpha-kernel/clock/` library, pure scheduler/model/snapshot and virtual/capability
modules, native sampled-time mechanics and one Linux OS driver. Update the exact Cargo/dependency/version graph, source guards,
shared Clock vectors and package-selected/isolated build closures atomically. No Runtime activation or history conversion follows.

**Deliverable:** complete registration/cancellation/query, ordering/fixed-rate/failure behavior, virtual control, restricted
callbacks/views/handles, atomic complete-ID recovery, native time/worker lifecycle and callback-safe close. Do not call a pure
queue or virtual-only subset the complete Clock module. Compare correct common Python behavior; never copy defects for parity.

**Proof:** exact independent vectors and adversarial capability/restore/sample/lifecycle tests, debug/release/Clippy/format,
Clock+Domain isolated closure and Domain-without-Clock isolation, affected guard/version/consumer checks and bounded independent
review. Current-scope unresolved High/Critical blocks module acceptance; library evidence is not Backtest/SIM/LIVE admission.

## Complete Event module construction

Use the [Event Contract](event.md), ADRs 0004/0009/0048 and the
[owner-approved Event design](superpowers/specs/2026-10-18-rust-event-design.md). Audit Python model/bus/ports/view and direct
Router/Gate consumers before implementation; known reference defects never define expected Rust results.

Construct one isolated Event library: explicit identities/time/scope, owned immutable payload/current records, scoped FIFO,
observer registration/cancellation, exact backpressure/prefix/atomic outcomes, restricted serial dispatch, failures, quiescent
close/drop, bounded visible diagnostics and interface-only publication ports. Router/Gate/Outbox and official Runtime remain
outside this unit. Preserve historical readers/artifacts and do not activate a new official writer.

Prove independent shared common vectors and corrected adversarial/capability/lifecycle semantics, exact edge/source admission,
Event+Domain isolated debug/release builds, affected Python consumer/static/version checks and bounded independent review.
A matching corpus does not certify all Python behavior, persistent recovery, cross-platform support or Runtime admission.

## Dependency order

```text
R0 Current MiniQMT retirement
→ R1 Python module stability and language-neutral equivalence vectors
→ R2 Linux toolchain and first canonical Rust module
→ R3 isolated comparison integration
→ R4 Python calculation/plugin worker boundary
→ R5 complete Rust Backtest slice
→ R6 Rust SIM continuity and recovery
→ R7 Rust LIVE readiness and explicitly human-authorized activation
→ R8 retire maintained Python Kernel
```

R0 and R1 may be reviewed independently, but R2 consumes a stable R1 semantic slice. R4 is required before R5 uses Python-backed
calculations; do not block a pure canonical R2 module on a speculative worker framework. Performance units P0–P2 below are separate
and may proceed where their real dependencies allow. Passing a unit never grants LIVE permission or waives another unit's gates.

## R0 — Retire the unavailable MiniQMT implementation

**Inputs:** ADR 0139 retirement boundary; current package/consumer inventory; existing independent CN A-share conformance Contract.

**Modification map:**

- Remove `plugs/onlyalpha-plugin-miniqmt/`, its three `scripts/*miniqmt*` tools and adapter-only runtime fixture/configuration.
- Update root `pyproject.toml`, `uv.lock`, `scripts/test_suite.py`, `scripts/verify.py`, affected pytest layering/metrics selectors,
  `.github/workflows/ci.yml`, `quality.yml`, `miniqmt-local.yml` and `miniqmt-order.yml`; remove adapter-only entries/jobs and their
  aggregate dependencies without disabling unrelated lanes or leaving dead wheel/entrypoint checks.
- Inspect `src/onlyalpha/runtime/streaming/config.py` and `runtime.py`; remove concrete `miniqmt-history-v2` defaults while preserving
  generic historical-worker, streaming and stop/recovery semantics. Any required replacement is an explicit neutral configuration,
  not a silent default/fallback into a different provider.
- Replace adapter imports used by `tests/integration/test_engine_sim_virtual_broker_execution.py` and
  `tests/integration/test_trading_authority_e2e.py` with a controlled neutral Source at the existing test seam. Inspect all remaining
  direct consumers, including `tests/support/golden_data.py` and `tests/conformance/cn_a_share_cash/test_miniqmt_golden.py`; preserve
  shared trading/reference/product assertions and historical golden data under the ADR's narrowed retention rule.
- Update current support/installation docs, including `docs/miniqmt_historical_isolation.md`, without rewriting historical design
  provenance as if the adapter had never existed. Do not delete `test-data/miniqmt/cn_a_share_v1/` frozen bytes/manifests or
  `onlyalpha-plugin-cn-ashare` reference provenance just to make a textual QMT search empty.

**Deliverable:** current supported packages/builds/tests do not require the unavailable SDK; generic runtime behavior remains.

**Proof:** first add/retain regression assertions for neutral SIM execution, durable transaction, restart and Authority ownership;
run them after replacement. Package discovery/build and canonical lane selectors must contain no removed entry points. Verify
historical Integration reads without the installed type and fail-closed admission of missing implementations, preserving IDs and
all existing business data. Run affected canonical lanes, static/type/build checks and bounded independent review. Do not claim
QMT removal from a grep count or by deleting failing shared tests.

## R1 — Freeze each canonical semantic slice and comparison inputs

**Modification map:** inspect `src/onlyalpha/runtime/trading/{kernel,builder,config,services,predicate}.py`, owning domain/value
Contracts and directly affected transaction/recovery owners; reuse their existing tests before adding new fixture infrastructure.

**Deliverable:** for the selected module, an explicit canonical input/state/output/error inventory and language-neutral recorded
vectors attached to its owning Contract/tests. This is semantic test data, not a second task-status document. Select the first
bounded module from real dependencies and stable behavior; do not port risk/order code from an unreviewed broad source snapshot.

**Proof:** no unresolved Critical/High defects in the selected canonical Contract or accepted Rust implementation. Cover exact IDs
and bytes, Decimal precision/rounding, boundary/overflow
values, ordered and duplicate facts, denied/incomplete/unavailable/UNKNOWN outcomes, authority mutations, and relevant crash/replay
cuts. Record semantic versions and immutable inputs; separately record each implementation artifact/generation identity. Any real
Python bug is diagnosed against the owning Contract and correct independent expected results. Fix Python under its own impact scope
when current official execution correctness/safety or trustworthy comparison requires it; otherwise retain it only as a classified
reference deviation. Incorrect Python outputs never become expected Rust results, and known mismatches cannot be reported as
full cross-language parity. A reference deviation does not waive Runtime admission, history integrity or the selected Rust
module's correctness/recovery gates.

## R2 — Linux toolchain plus the first canonical Rust module

**Modification map:** introduce a root `Cargo.toml` workspace, committed `Cargo.lock`, `rust-toolchain.toml` and a narrowly scoped
`crates/onlyalpha-kernel/core/` only with the selected real R1 consumer. Extend `deploy/Dockerfile.dev`,
`deploy/docker-compose.dev.yml`'s existing fixed dev services, and the canonical verification selectors as needed; do not add a
second Compose file/project or install dependencies from the network during a test.

**Deliverable:** the selected stable semantic module implemented in Rust, compiled and tested from frozen source inside Linux dev.
Choose and pin the exact stable official toolchain/target before writing module code, based on dependency and fixed-image support.
No async runtime, generic transport or crate is added merely for future modules. Apply ADR 0139 dependency review to each necessary
crate; establish locked build provenance, checked arithmetic, explicit rounding and debug/release parity.

**Proof:** R1 vectors pass in Python and Rust with exact Contract equality; malformed numeric/time/identity inputs fail correctly.
Run Rust format/lint/tests and both build profiles, package/build checks, affected Python regressions and independent review through
the one canonical dev entry. Host-only compilation is inner-loop evidence, not formal acceptance. Windows/macOS Rust remain deferred.

## R3 — Bounded side-effect-free comparison

**Modification map:** integrate at the real Runtime-neutral Kernel input/output boundary and reuse existing immutable generation,
work-binding and diagnostics Infrastructure. Keep comparison tooling outside trading Authority; add no alternate public mutation API.

**Deliverable:** both implementations consume identical explicit input sequences and isolated initial state; comparison reports bind
input, semantic version and both exact implementation identities. Only the selected Runtime implementation can publish official
facts or effects. Read-only diagnostics cannot become Research Evidence or certified execution equality merely by having a hash.

**Proof:** intentionally alter an identity, rounding result, ordering, rejection, nested owner relation and terminal outcome to prove
mismatches are detected. Inject comparison crash/timeout and prove no duplicate Broker submit or formal publication. Test generation
mixing, unavailable artifacts and restart binding; missing proof remains unavailable, never equality. No timing cache, latest fallback
or nondeterministic comparison suppression is allowed. Extend vectors per real module until the Backtest slice has complete coverage.

## R4 — Managed Python calculation/plugin boundary

**Modification map:** extend the single existing `contracts/gateway/v1/onlyalpha_gateway_protocol/v1/` protobuf authority and generated consumers only for the real first
calculation/plugin use; reuse gateway lifecycle/admission and the existing registered Calculation SPI. Inspect
`docs/gateway_protocol.md`, `src/onlyalpha/application/chart_study_numeric.py`, Research worker composition and owning numerical
Contracts. Do not treat gateway `TEST_UNARY`/`TEST_STREAM` as an already implemented calculation protocol.

**Deliverable:** bounded versioned batches with exact source/generation/input identity, Decimal/time representation, output
readiness/provenance and explicit ordering. Define maximum frame/batch/queue/work budgets, deadline/cancellation and termination
semantics in that consumer's canonical Contract before implementation. Managed worker reuse must respect generation and fault domains.

**Proof:** empty/malformed/oversized batches, partial frames, wrong generation, duplicate/out-of-order replies, disconnect, cancellation,
crash and exhausted capacity have explicit bounded outcomes. Stale results cannot cross contexts. Worker failures cannot mutate
Kernel state, create a second order or silently substitute values. Test exact indicator/factor results against existing registered
backends and preserve scientific versus DISPLAY_ONLY admission. Verify the real Shipping UI/API path for each affected product flow.

## R5 — Complete Rust-owned Backtest product slice

**Modification map:** current Backtest driver/facade, shared Trading Kernel and formal Product Runtime admission; owning persistence,
Result/Evidence and StrategyRevision consumers. Reuse shared Market Product, virtual Broker and existing Dataset materialization.

**Deliverable:** normal Web → versioned API → admitted Runtime executes a frozen Strategy Revision against immutable inputs with the
Rust Kernel. Python calculators remain behind R4 as needed. New-work activation selects one exact Rust generation; active Python
work drains under its original binding. No public Python-to-Core shortcut or test-only product page is introduced.

**Proof:** UI creation/configuration/submission/viewing/cancellation, exact semantic comparison and outcome/Evidence ownership;
crash before/after durable commits, deterministic restart, duplicate/reordered external facts, fee/risk/position/account boundaries,
old-history read and real stop/start/upgrade. A fresh empty database or matching final portfolio alone is insufficient. Retain all
affected canonical lanes, independent proof review, and fail closed on missing historical implementation/input closure.

## R6 — Rust SIM continuous lifecycle

**Deliverable:** the same Rust Kernel runs the ordinary SIM product flow with realtime input and virtual execution, preserving
subscribe/warmup/handoff, processed watermark, shutdown, durable transaction, reconciliation and restart semantics.

**Modification map:** shared Kernel plus existing streaming facade/driver, Source/plugin boundary, Product API/Web and their tests.

**Proof:** controlled disconnect/reconnect, duplicate and late observations, worker death, UNKNOWN outcomes, queue/resource exhaustion,
stop during processing, crash at every affected commit boundary and recovery without a second identity or lost official facts.
Validate via real Shipping UI with controlled external inputs and canonical stores; SIM does not certify LIVE venue behavior.

## R7 — LIVE readiness and explicit activation

**Deliverable:** the same Kernel passes the affected Broker/venue conformance, permissions, account/position reconciliation,
UNKNOWN-submit and risk-reduction paths. No new LIVE activation authority is granted to Agent, workers or deployment tooling.

**Proof:** venue-specific controlled lanes where required, crash/reconnect/reconciliation, observation and cancellation under
fail-closed execution, exact audit chain and normal operator UI. Missing real-target evidence remains unavailable, never a mock PASS.
LIVE activation, strategy changes and material risk require the existing explicit human operations even after all technical gates.

## R8 — Retire the maintained Python Kernel

**Inputs:** affected Rust semantic/product/recovery evidence, module coverage and owner-authorized release/activation decision.

**Deliverable:** new formal work uses the Rust Kernel only; current Python Kernel source and obsolete dual-comparison wiring leave
the maintained product after affected consumers migrate atomically. Python indicators/factors and appropriate plugins remain.
Permanent language-neutral vectors, Contracts and replay tests continue to protect Rust evolution.

**Proof:** no current public/runtime caller depends on removed Python Kernel paths; exact historical artifacts still resolve for
bound work according to ADR 0117. Prove restart and deployment upgrade with existing stored histories, references and keys. Remove
no facts, rewrite no historical execution identity, add no legacy loader and perform no automatic downgrade/fallback.

## Independent performance workstream

- **P0 — Measure the actual complete journey.** Use existing Shipping UI and formal API. Separate warm fixed-window, moving latest
  tail, a new instrument, large historical gaps, restart and two concurrent pages. Attribute session, external fetch, publication,
  proof/read, compute, queue, transport and render wall time; use CPU evidence before claiming a language benefit. Preserve errors
  and incomplete measurements. Monitoring overhead is measured separately, with deep profiling off for latency acceptance.
- **P1 — Incremental verified display.** Existing verified bars may paint while acquisition runs; for empty history, fetch a bounded
  recent batch before completing the required window. Define that batch and acquisition ordering in the existing Market Data
  Contract before changing behavior. Keep exact Source/Instrument/BarSemantic/window identity, independent proof, automatic fill,
  visible loading/error/retry, credential/context withdrawal and complete-input gating. Test new/partial/failed/denied/unprovable
  paths from the ordinary UI, with deterministic barriers and actual owning services/stores.
- **P2 — Optimize measured limiting phases.** Reuse safe existing paths before adding implementation; choose Rust only where CPU
  or boundary measurements justify it. Preserve exact identity, proof and recovery. Warm one-page P95 budgets remain 1s K-line and
  2s for the three default Bollinger/MACD/Wilder RSI studies; two pages remain 2s/4s per page. Full windows contain 2000 bars.
  First partial paint never substitutes for full readiness. Cold/restart goals need explicit measured baselines and owner agreement;
  return difficult goals and options to the owner rather than raising timeouts or weakening criteria.

## Execution and stopping rules

For each unit: read its owning Contract/Accepted ADR, freeze an in-context Task Contract, add the minimal regression/differential
or fault test, establish its failure, implement the smallest correct change, and run affected canonical dev validation and review.
Build tooling changes require environment/package checks; wire/persistence/authority changes require the actual affected high-risk
proof. Do not run unrelated full-repository gates automatically. No progress checkboxes or PASS/READY ledger belongs in this file.
The next unit starts only after its true prerequisites hold; publishing this work program is not permission to skip them.


### Market Data State source navigation

The audited bounded State responsibility uses `crates/onlyalpha-kernel/market_data/state/` (`onlyalpha-market-data-state`),
with a sole local Domain edge. It covers atomic closed-Bar updates, immutable Runtime/Cluster queries and strict component
checkpoint replacement. Construction, Pipeline/Dispatcher orchestration, calculation readiness and durable historical storage
remain separate. See the [owning Contract](market_data_pipeline.md#rust-state-library-boundary) and
[responsibility map](rust-kernel-development.md#market-data-state-responsibility-map). This library construction does not change
the official Python participant, authorize activation/migration or record module completion.

### Market Data Construction source navigation

The bounded Construction responsibility lives in `crates/onlyalpha-kernel/market_data/construction/`, with Domain as its
only local dependency. It includes exact construction values, graph compilation, pure executor SPI, TIME_BAR@1 and an atomic
Runtime-local owner. See the [owning Contract](market_data_pipeline.md#rust-construction-library-boundary) and
[responsibility map](rust-kernel-development.md#market-data-construction-responsibility-map). This library work does not
activate Rust in Runtime or remove Python; Source/Generation admission, durable migration and measured product performance
remain separately scoped integration work.

### MarketData organization and Delivery source navigation

One business directory `crates/onlyalpha-kernel/market_data/` contains the independently buildable State, Construction and
Delivery responsibilities. Delivery implements subscription identity/primary/freshness and deterministic scoped planning with
active-registration watermarks and component recovery. Python callback execution and calculation readiness are not moved into
this planner. See the [owning Contract](market_data_pipeline.md#rust-delivery-planning-boundary). Later Pipeline composition
must preserve ADR0009 actual execution guarantees and validate its real calculation/lifecycle dependencies before activation.


### Calculation source navigation

`crates/onlyalpha-kernel/calculation/` groups the pure Definition/parameter, DAG/compatibility and exact registry foundation in one
independently buildable library. It does not move concrete indicators/factors out of Python or replace Core Predicate arithmetic.
Its versioned Definition3 identity correction is not Python Definition2 wire/hash admission. The next integration dependencies
remain exact calculation/plugin execution, scoped state/readiness, then MarketData/Cluster composition. Consult the
[responsibility map](rust-kernel-development.md#calculation-responsibility-map) and existing R3-R8 migration gates.

The scoped execution cursor remains in Calculation; the actual Python plugin process and Rust client live in
`packages/onlyalpha-calculation-worker/`, with canonical Gateway messages. Refer to the
[execution boundary design](superpowers/specs/2026-10-18-rust-calculation-worker-design.md) for lifecycle, exact binding,
checkpoint admission and UNKNOWN behavior. This isolated comparison does not activate a Runtime participant or authorize
historic data conversion. Subsequent MarketData/Cluster composition must consume the same ordered facts, exact generation
and formally owned durable checkpoints; callback-to-RPC substitution by itself is not integration closure.

The Calculation scoped-state boundary is in `calculation/src/{state,readiness}.rs`, consumed by the managed worker Rust client.
It supplies explicit result/failure snapshots and a dependency barrier against caller-specified exact input positions; it does
not execute Factors/Strategies or compose a MarketData transaction. Subsequent Pipeline composition must own its transaction,
per-timeframe expectations, admitted input/generation and durable recovery obligations. See the
[state boundary](indicator_registry.md#rust-scoped-calculation-state-and-readiness-boundary).

### Strategy decision source navigation

`crates/onlyalpha-kernel/strategy/` owns the bounded pure decision component; the managed Python calculation worker supplies actual
registered algorithms and the technical MarketData coordinator. See the [owning boundary](strategy.md#rust-decision-component-boundary).
Revision2 component identity is explicitly separate from official Revision1/Freeze admission. Subsequent activation must evolve the
owning public contract and all consumers atomically, prove exact retained artifacts/history, and preserve R3-R8 gates. Order intent,
Risk/Portfolio, Broker effects and LIVE permissions are not inferred from a component decision or a passing technical probe.


### Order source navigation

`crates/onlyalpha-kernel/order/` groups component lifecycle, exact receipt/identity handling and fresh recovery in one independent
library. See the [owning boundary](order.md#rust-component-canonical-lifecycle-and-recovery) and
[design](superpowers/specs/2026-10-19-rust-order-design.md). Subsequent Position/Allocation, Account/Ledger, Risk and execution-transaction
work must preserve owning authorities and ordered economic effects. An isolated Order transition is not durable execution closure,
formal Runtime activation, successful submission or evidence of absent venue effects. R3-R8 gates continue to apply.

### Position source navigation

The isolated Position component resides in `crates/onlyalpha-kernel/position/`. Its one candidate commit covers account/attribution conservation and sell-hold ownership. See [Position](position.md#rust-component-ownership-and-recovery-boundary). Account cash, Strategy Ledger, Risk and durable execution/reconciliation orchestration remain separately owned; R3-R8 activation/history gates are unchanged.

### Account source navigation

The isolated Account component is `crates/onlyalpha-kernel/account/`; [Account](account.md#rust-component-ownership-and-recovery-boundary) owns its scope and reference deviations. Strategy Ledger, Risk, fee accrual and durable execution orchestration retain distinct owners. Later integration consumes typed immutable inputs rather than calling another Manager's internal state; R3–R8 activation/history gates remain unchanged.

### Strategy Ledger source navigation

The isolated virtual-account library resides in `crates/onlyalpha-kernel/strategy_ledger/`. Its [owning contract](strategy_ledger.md#rust-component-ownership-and-recovery-boundary) separates Cluster attribution from consolidated Account and Position cost authority. Risk and durable Execution transaction/reconciliation composition consume normalized immutable inputs in later admission work; R3–R8 activation/history gates remain unchanged.

### Risk source navigation

`crates/onlyalpha-kernel/risk/` owns bounded risk decisions, explicit profiles and scoped risk exposure lifecycle, depending only on Domain. See [Risk](risk.md#rust-component-ownership-and-recovery-boundary). Subsequent Execution composition must preserve exact Order/Request/Trade relationships, resolve net capacity versus same-owner holds explicitly, authenticate source admissions and commit Account/Position/Ledger/Risk effects atomically with durable replay/reconciliation. An ACCEPT or isolated checkpoint is not official Runtime, submission, upgrade or LIVE admission; existing R3-R8 gates remain unchanged.

### Execution source navigation

`crates/onlyalpha-kernel/execution/` owns bounded pure execution planning and ordered commit/recovery coordination using the isolated Order/Position/Account/Strategy Ledger/Risk libraries. Its [owning boundary](execution.md#rust-component-execution-boundary) retains one durable Store authority, exact frozen projections, admission-only resource budgets, mandatory economic evidence and at-least-once Events. Library construction does not activate a Runtime, certify a deployment upgrade or replace R3–R8 admission/history gates.


Broker common semantics are specified in `docs/superpowers/specs/2026-10-19-rust-broker-design.md`:
normalize provider observations, preserve Execution v2 business identity across sessions, gate
dispatch on exact durable Ready intent, and reconcile only through complete owning application
receipts plus current venue/local equality. Concrete Brokers, the official persistence writer,
Runtime activation and shipping Web behavior remain separate gates under the existing roadmap.


## Rust Fee component boundary

`crates/onlyalpha-kernel/fee/` is the Domain-only semantic library for exact scoped rule binding, assessment/estimation, per-component accrual/application, typed queries, external evidence lineage, forward adjustments and Fee risk blockers. Concrete schedules/basis translation remain plugin inputs. The schema1 component IR uses explicit day ordinals, UTC nanosecond instants, exact source snapshots and bounded Decimal inputs; it does not decode or replace the official Python Fee wire/history format. Fixed rules retain their exact binding when current schedules expire; effective families require one matching scoped version. Decimal spelling and registry order do not create new semantic identities.

Execution consumes Fee applications and freezes the Fee checkpoint in Execution metadata schema5 within the existing ordered commit. Its explicit admitted cumulative-target port remains subject to owning Runtime source authentication; an integrity digest does not prove producer authority. Aggregate targets do not manufacture detailed component evidence. Fee adjustment outputs are immutable instructions; they do not themselves write Account/Strategy Ledger state or authorize trading. Official full fee-reconciliation transaction admission remains an R3–R8 Runtime integration gate.

The Python formula/rounding/accrual/reconciliation responsibilities are audited references; concrete factory/provisioning, policy selection, storage and Runtime transaction orchestration keep their existing owners. Split estimates use a conservative full-basis upper bound and reserve gross charges; no rebate offsets funding. Explicit zero rules do not require a meaningless split assumption. These are scoped correctness decisions, not claimed whole Python implementation parity. See the [design](superpowers/specs/2026-10-19-rust-fee-design.md).

## Rust Settlement responsibility and admission boundary

`crates/onlyalpha-kernel/settlement/` is the Domain-only cash-security Settlement library. Python `settlement/{models,identity,authority,facts}.py` supplies the classified model/schedule/initial-owner/due reference; `settlement/planner.py` transaction composition stays in Execution. Source Calendar and compiled policy remain explicit Plugin/adapter inputs. Six distinct booking/availability/withdrawal/legal dates use the existing versioned Domain Calendar and exact trading-day advances, with bounded coverage/search and no UTC-midnight inference. Instruction identity binds full owner, economic, policy/calendar and Position/Allocation lifecycle inputs. Direct snapshots never grant authoring authority.

Resource admission reserves worst-case canonical Fill slots before submission from exact Order quantity and Instrument quantum. Existing records plus all remaining quanta cannot increase on a valid positive Fill. Orders are replayed by their immutable admission ordinal, installing preceding frozen instruction histories before later resource admissions. Capacity remains at most 512 instruction slots, with a 32 MiB checkpoint bound; individual inputs, records and receipts are bounded so all six pending transitions retain space. New-risk admission can fail closed without discarding observed in-budget facts or suppressing maturity.

Execution metadata schema5 freezes the Settlement owner in its existing six-group transaction, and `SETTLEMENT_MATURITY` updates exact Position/Allocation buckets, Account receivables and the Ledger's non-economic Allocation version/evidence witness atomically. Ledger refresh cannot alter quantity, identity/cycle, cost or PnL; no version/before-proof guard is relaxed. Supported cash execution requires immediate booking and cash trading availability, with explicit T+N asset availability, cash withdrawal and legal settlement. Other economic shapes are rejected explicitly.

The library represents all six axes, including delayed booking; it completes only when all six flags are effective. Strict ID/venue, duplicate/restore and complete-booking behavior are independently tested corrections/extensions, not asserted whole Python parity. Source digest is integrity rather than authenticated producer authority. Native codecs and comparison identities do not decode official Python history. Formal Runtime admission, durable storage drivers, deployment upgrade/old-history activation, futures daily MTM, LIVE and Shipping UI acceptance remain separate R3-R8 gates.


## Rust Margin responsibility boundary

See [Margin Contract](margin_model.md#rust-margin-responsibility-and-consumer-boundary) for complete reservation/quantity/recovery semantics and real Order/Execution/Account consumption. Construction of the isolated library does not admit an official Runtime or retire Python; R3–R8 remain unchanged.

### Valuation responsibility boundary

[Valuation](valuation.md) groups source-derived marking in the Position library with typed Account consumption and an independent Execution barrier. Runtime Ledger Reconciliation consumes those distinct Account and Cluster projections; it must preserve per-owner rounding and cannot silently repair discrepancies. Official Runtime composition and complete Backtest admission remain subject to R3–R8.
