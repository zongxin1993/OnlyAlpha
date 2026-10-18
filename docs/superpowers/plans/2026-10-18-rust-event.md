# Rust Event Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement the approved plan inline in this session. Use one bounded independent correctness/simplicity review after initial validation; do not delegate each implementation task. Checkboxes describe planned actions, not a repository completion ledger.

**Goal:** Implement the complete isolated Rust Event responsibility, correcting audited reference defects while preserving the admitted Python Runtime.

**Architecture:** An independent `onlyalpha-event` library under `crates/onlyalpha-kernel/event/` depends on Domain and the admitted exact integer/JSON packages. Private owned facts and a single-thread owner separate observation from business transitions; restricted views and callback contexts cannot drive dispatch. Runtime publication ports remain declarations.

**Tech Stack:** Official pinned Rust 1.99.1, Rust std, `onlyalpha-domain`, `num-bigint = 0.4.8`, `serde_json = 1.0.154`, the existing single Linux dev service.

**Spec:** [Owner-approved Event design](../specs/2026-10-18-rust-event-design.md); Constitution, the owning Event Contract and Accepted ADRs remain normative.

## Global constraints

- No Python production restructuring, Runtime activation, business-data mutation, historical migration, push or release.
- Keep release `0.10.9`; add the local Event package to the existing version/lock graph without incrementing the release.
- Event -> Domain is the only local edge. Clock/Predicate/Runtime/Application/Store/plugins are absent from Event's isolated source closure.
- Reuse exact direct features: num-bigint with `default-features=false, features=["std"]`; serde_json with `default-features=false, features=["std","arbitrary_precision"]`. Add no registry nodes, UUID generator or async dependency.
- Explicit UUID identities, exact nanosecond facts and arbitrary-integer sequences/counters; no OS time, random IDs or f64 evaluation.
- Shared vectors define independent expectations; Python deviations cannot be reported as parity. No compatibility fallback, old-schema reader or fact rewrite is introduced.
- All formal local checks run through `scripts/dev_verification.py` with frozen source and one worker. Rebuild only the existing fixed dev validation image when manifest/lock/environment identity requires it.
- Preserve full rejected-operation atomicity, exact IDs and caller-visible failure/replacement outcomes. Deterministic tests use explicit inputs or barriers, never sleeps/retries/xfails.

## Review focus

1. A later observer attempts to see a mutated nested payload or returned record: construction and record access must not retain writable aliases (Task 1).
2. A callback captures a subscription view, changes subscriptions and requests close: fixed current-observer membership, capture release and lifecycle must remain correct without RefCell borrow panics (Tasks 3/4).
3. A batch fails after a valid prefix, or DROP_LOW_PRIORITY displaces a queued fact: prefix/atomic behavior and precise replacement identities must remain distinguishable (Task 2).
4. Negative/sub-microsecond timestamps, oversized exact integers and conflicting ISO fields: preserve values and reject contradictory current records instead of falling back (Task 1).
5. Diagnostics overflow or an owner disappears with queued work: expose evictions/unfinished lifecycle; never imply durable audit, successful drain or subscriber ACK (Task 4).

## Task 1: Immutable event values, strict records and admitted package

**Files:** create `event/Cargo.toml`, `event/src/{lib,model,record}.rs`, `event/tests/model.rs`, `event/tests/records.rs`;
modify root `Cargo.toml`, `Cargo.lock`, `scripts/rust_kernel_check.py`, `scripts/version_sync.py` and affected tool fixtures.
All `event/` paths here are under `crates/onlyalpha-kernel/`.

**Interfaces:**
- `OnlyEventId`, `OnlyCorrelationId`, `OnlyCausationId`, `OnlySubscriptionId`: distinct validated UUID-byte newtypes with `parse(&str)` and canonical text output; no `new_random` method.
- `OnlyEventType`, `OnlyEventSource`, `OnlyEventScope` and `OnlyEventPriority`; scope validation/inclusion reuses Domain Engine/Runtime/Cluster ID types.
- `OnlyEventInput`: event/type/source/scope, explicit event/init `OnlyTimestamp`, `BigUint` producer sequence, causal IDs, priority, metadata and validated payload.
- `OnlyEvent::new(OnlyEventInput) -> Result<Self, OnlyEventError>`; private fields and immutable accessors.
- `OnlyEventPayload`: Bar, mapping or scalar; owned JSON data and Domain Bar validation; returned JSON values are detached clones.
- `OnlyEvent::{to_record,from_record}` use `serde_json::Value`, plus `to_json/from_json` for the same current schema-2 record; no legacy branch or semantic byte-identity promise.
- `OnlyEventError`: distinct Validation, Record, Scope, Capacity, RuntimeFailure, Closed, Busy, DuplicateSubscription and Callback error families. Diagnostic panic/error classification is separate from successful work.

- [ ] Write package/boundary tests that fail when Event is absent or has an undeclared/reverse edge. Observe the missing-package/interface failure through dev before implementing values.
- [ ] Write records with fixed UUIDs, event time `-1 ns`, initialization `0 ns`, sequence `18446744073709551616`, causal IDs and nested mapping data; assert exact values survive round-trip and detached output mutation cannot change the Event.
- [ ] Add rejection cases for missing/extra schema-2 fields, unknown version, invalid UUID, cluster without Runtime, negative/non-integer/bool sequence, init-before-event, mismatched ISO/nanosecond fields and unsupported payload kind. Reuse Domain Bar's own valid/invalid record expectations.
- [ ] Implement typed values and strict field reading using existing Domain readers and exact integers. Direct scalar payload admits null/string/bool/integer; nested JSON finite numbers remain exact tokens. Never use financial floating conversion.
- [ ] Admit Event's exact local/direct-feature graph, preserve the reviewed registry digest, and include the fourth local package in version checks/fixtures. Verify Cargo lock contains only the added local node and existing registry closure.
- [ ] Rebuild the one fixed dev validation image if required by those manifest inputs; then run the value/record tests, affected guards and version checks offline. Keep source stable during each frozen run.

## Task 2: Scoped FIFO and explicit backpressure

**Files:** create `event/src/bus.rs`, `event/tests/queue.rs`; extend model errors/receipt types only as consumed here.

**Interfaces:**
- `OnlyEventBusConfig { capacity, diagnostic_capacity, scope, queue_policy }`, both capacities positive, default 1024; policies REJECT, FAIL_RUNTIME, DROP_LOW_PRIORITY.
- `OnlyEventBus::new(config) -> Result<Self, OnlyEventError>`; non-cloneable owner of `Rc<RefCell<State>>`.
- `publish(Arc<OnlyEvent>) -> Result<OnlyEventEnqueueReceipt, OnlyEventError>`; receipt identifies accepted and optional replaced Event.
- `publish_many(&[Arc<OnlyEvent>]) -> Result<BigUint, OnlyEventBatchFailure>`; failure contains exact accepted-prefix count, rejected index and cause, while the caller retains all original values.
- `publish_many_atomic(&[Arc<OnlyEvent>]) -> Result<BigUint, OnlyEventError>`; full validation precedes mutation; DROP_LOW_PRIORITY rejects this API.
- `pending_count() -> Result<usize, OnlyEventError>` is a queue resource measurement, not an identity counter.

- [ ] Write failing tests: queue capacity 2; publish priorities HIGH then LOW and observe FIFO order, not priority delivery order. Cross-Runtime/Cluster scope failure leaves the queue unchanged.
- [ ] Pin REJECT and FAIL_RUNTIME errors at capacity; for replacement use priorities LOW/LOW/HIGH with capacity 2 and assert the first LOW is displaced and the second LOW remains before HIGH. Equal/lower arriving priority is rejected without mutation.
- [ ] Pin sequential prefix acceptance versus atomic rejection using one valid event followed by an invalid-scope event. Verify failed atomic batches preserve every preexisting queue item and all diagnostic totals; DROP_LOW_PRIORITY atomic rejection also preserves state.
- [ ] Implement std `VecDeque` queue mechanics and validated receipts. Do not add event-ID deduplication, delivery retries or a Runtime failure transition.
- [ ] Run queue tests and existing Python Event/Runtime Router atomic-batch tests through the dev entry.

## Task 3: Serial observers and restricted capabilities

**Files:** create `event/src/capabilities.rs`, `event/tests/dispatch.rs`, `event/tests/capabilities.rs`; extend `bus.rs`.

**Interfaces:**
- `OnlyEventHandler = Box<dyn for<'a> FnMut(&OnlyEvent, &mut OnlyEventCallbackContext<'a>) -> Result<(), OnlyEventError>>`.
- `subscribe(id, event_type, handler_name, priority, handler) -> Result<OnlySubscriptionHandle, OnlyEventError>`; ID/type/name/priority are explicit; rejected registration does not reserve ID or increment sequence.
- `OnlySubscriptionHandle`: immutable subscription metadata and `cancel()` only. Used IDs remain reserved for the bus lifetime, including cancelled entries; no second mutable identity authority.
- `OnlyEventBusSubscriptionView`: cloneable restricted subscribe/unsubscribe/read/diagnostics access; no publish, dispatch, drain, owner-close or owner extraction.
- `OnlyEventCallbackContext`: scoped publish/subscribe/unsubscribe/request-close and reads; no owning bus reference or recursive control.
- Owner-only `dispatch_one() -> Result<Option<OnlyEventDispatchReport>, OnlyEventError>` and `drain() -> Result<BigUint, OnlyEventError>`.

- [ ] Write failing order tests with two events: higher-priority observer first, equal-priority observers by registration sequence, and every observer of event 1 before event 2.
- [ ] Capture current subscription membership before callbacks: callback cancellation/registration affects event 2, while the captured event-1 list completes. Newly enqueued events run after existing FIFO items.
- [ ] Add compile-fail tests forbidding owner extraction/replacement/dispatch from callback context, publishing/closing from the subscription view, and moving the bus/view across threads. Add an internal rejected reentrant-control test proving no dequeue or state mutation.
- [ ] Implement registration and immutable per-event observer snapshots; callbacks and capture destructors run outside all active RefCell borrows. Catch callback unwind panics as explicit failures, retain event/subscription/handler links and continue remaining observers.
- [ ] Pin returned callback error versus panic and continued next-observer/next-event delivery; verify no retry. Reject duplicate lifetime subscription IDs without consuming sequence.
- [ ] Run dispatch/capability/queue regressions in both profiles; compiler rejection, not a timing stress test, proves cross-thread control restriction.

## Task 4: Quiescent lifecycle, bounded diagnostics and publication contracts

**Files:** create `event/src/{diagnostics,ports}.rs`, `event/tests/{lifecycle,diagnostics,ports}.rs`; extend owner/context/view control.

**Interfaces:**
- `OnlyEventBusState`: Running, Closing, Closed, Failed; view/context can read, callback context can `request_close`, owner `close()` drives drain and returns the actual state.
- Dispatch reports contain exact Event identity and every handler outcome; replacement receipts contain both Event identities.
- `OnlyEventDiagnostics`: bounded recent reports/failures/replacements, exact lifetime totals and evicted-sample counts. Reuse one small internal bounded-ring implementation for these three actual consumers.
- `OnlyRuntimeEventRoute`, `OnlyRuntimeEventDisposition`, `OnlyRuntimeEventPublicationResult` and direct/durable/lifecycle traits preserve the existing lower-layer interface vocabulary. Result counts are `BigUint` and add exactly; no bus implementation claims durable publication.

- [ ] Write failing close tests: callback requests close with another event queued; new publications/subscriptions reject, current observer snapshot completes, existing queue drains, and Closed appears only with zero queued/in-flight work. Repeated owner close is idempotent.
- [ ] Test callback captures of views/handles: cancellation/close/drop releases registry captures outside RefCell borrows, including cyclic captures broken by owner cleanup. Retain lifetime-ID reservation semantics.
- [ ] With diagnostic capacity 2, create 3 dispatch/failure/replacement samples; assert exactly 2 retained, total 3 and evicted 1 independently for each stream. Returned full reports remain available to callers despite sample eviction.
- [ ] Drop an owner with pending work while retaining a view; observe Failed/unfinished lifecycle and no callback execution or false Closed. Release pending registry/callback captures outside borrows; do not create recovery or durable history.
- [ ] Test publication-result count conservation for each route/disposition and oversized exact totals; traits must compile without a Rust Runtime and must not expose Gate/Outbox behavior.
- [ ] Implement minimal lifecycle/sample/port types and run these tests plus all prior Event tests in both profiles. Do not add monitoring exporters, persistence, worker threads or a new Runtime crate.

## Task 5: Shared conformance, isolated builds and bounded final review

**Files:** add `test-data/event/{records-v2.jsonl,delivery-v1.jsonl,README.md}`, `event/tests/conformance.rs`,
`tests/event/test_rust_event_vectors.py`, `tests/tools/test_rust_event_boundary.py`; modify `scripts/rust_kernel_check.py`,
`scripts/version_sync.py`, their affected tool tests, `docs/event.md`, `docs/rust-kernel-development.md`,
`docs/rust-kernel-migration-work-program.md` and `test-data/README.md` only for owning contracts/navigation/build rules.

- [ ] Hand-author independent records and operation sequences covering values/scope/causal IDs, FIFO/observer priority, cancellation, failures, prefix/atomic capacity outcomes, normal close and publication-result conservation. No implementation generates the other's expected outputs.
- [ ] In Python shared cases, supply fixed Event IDs and control subscription UUID allocation at the existing constructor seam with recorded inputs. Compare all causal/authority fields; classify deep-mutability/reentrant/concurrent/bounded-retention/strict-reader differences outside common parity.
- [ ] Add exact Event source/native-effect guards: reject OS time/random/thread use, hidden include/path/cfg_attr/build scripts, undeclared features/edges and Core/Clock/Runtime reverse imports. Allow only the two named Event corpus includes in test code; compile-fail snippets may mention forbidden APIs as negative evidence.
- [ ] Extend `_isolated_modules` through `isolated_event` for Event+Domain only; verify the extracted tree lacks Clock, Predicate, Runtime, application and production Python. Preserve independent Domain/Clock extraction and all existing registry/version protections.
- [ ] Run affected Event/Router/Gate/architecture/tool/vector tests, Ruff check/format and affected mypy; version graph, Cargo fmt/Clippy, workspace debug/release and isolated Domain/Clock/Event lanes run through the canonical dev entry. Logs stay under ignored `test-results/`; no tests use sleep/retry to prove correctness.
- [ ] Complete bounded independent correctness and simplicity review over actual changes and direct impact, fix scoped High/Critical with regressions, and rerun affected checks. Check Constitution fingerprint and source-cut agreement before claiming completion.
- [ ] Leave code local for owner review. Report actual verified boundaries separately from known Python deviations; do not activate Rust, delete Python, push, bump versions or publish a Release.
