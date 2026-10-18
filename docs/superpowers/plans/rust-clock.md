# Rust Clock Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan inline. Use one bounded independent review of the complete module after initial validation; do not delegate each implementation task.

**Goal:** Implement the complete isolated Rust Clock/Timer responsibility, correcting audited Python defects without restructuring Python.

**Architecture:** One `clock/` library under the Kernel umbrella, depending only on Domain and explicitly admitted lower-layer dependencies. Pure scheduling and virtual control cannot read native time. A separate Linux driver owns one thread, native clock samples and callback dispatch.

**Tech Stack:** Pinned Rust 1.99.1, Rust std, Domain and reviewed existing arbitrary-integer registry closure; single dev Compose.

**Spec:** [Clock Rust design](../../clock-rust-design.md), owner-approved through the current conversation. Constitution, Clock Contract and ADRs remain normative.

## Global constraints

- Do not modify Python production code for structural symmetry or to make a wrong behavior the expected result.
- Complete Clock includes virtual control, scheduling/cancellation, restricted views/handles, snapshot/restore, failures, native Linux driver and lifecycle.
- No runtime activation, business-data mutation, Python retirement, automatic fallback, push or release.
- Exact integer nanoseconds/counters; no float or platform-sized integer defines canonical time/order.
- Deterministic barriers/channels/fake samples; no sleeps, retries, xfails or relaxed timeouts as correctness proof.
- No Criterion/Tokio/chrono/new scheduler dependency. Admit exact direct edges and features of reused registry packages before building.

## Review focus

- A callback recursively advances/restores the virtual Clock: reject before mutation while allowing query/register/cancel.
- Invalid restore has valid early fields: reject the complete candidate without changing a single existing state field.
- Restore follows completion/cancellation/failure: every used ID remains reserved in the same logical lifetime.
- Native wall time jumps while monotonic timers are pending: eligible work must not be blocked behind an ineligible business-time heap head.
- Close is requested inside a callback or while another thread waits: no self-join, premature Closed state, late rearm or detached worker.

## Scheduling core and isolated package

Files: create `crates/onlyalpha-kernel/clock/{Cargo.toml,src/lib.rs,src/model.rs,src/scheduler.rs,tests/scheduler.rs}`;
modify root Cargo workspace/lock and declared edge guards in `scripts/rust_kernel_check.py`.

Interfaces:
- Immutable Timer ID, mode (one-shot/fixed-rate), state, definition, event and structured failure types.
- `OnlyTimerScheduler::schedule_at`, `schedule_after`, `schedule_every`, `cancel`, `has_timer`, `timer_snapshot`.
- One outstanding dispatch token bound to Timer ID/sequence/fire-count; `complete_dispatch(token, result)` rejects stale/foreign tokens.
- Registration accepts explicit observed time and exact integer deadlines/intervals. The scheduler owns lifetime reserved IDs.

- [ ] Write tests for equal-deadline order, periodic recurrence, cancellation, failed callback continuation, duplicate IDs and exact huge/negative instants.
- [ ] Run the tests in the dev entry and retain the expected missing-library/function failure.
- [ ] Add the minimal deterministic state machine using std ordered collections and the admitted exact integers. No callback serialization or trading occurrence publication.
- [ ] Run scheduler tests and reverse-edge/dependency checks. Rejected operations must preserve state.

## Virtual control and atomic recovery

Files: create `clock/src/virtual_clock.rs`, `clock/src/snapshot.rs`, `clock/tests/virtual_clock.rs`, `clock/tests/restore.rs`.
Extend Domain pure time/identity operations only where a real Clock consumer requires a shared primitive; preserve Domain isolation.

Interfaces:
- `OnlyVirtualClock::new`, `timestamp_ns`, `now_utc`, `advance_to`, `advance_by`, `snapshot`, `restore`, `close`.
- `advance_to` dispatches serially through `VirtualClockContext`, which exposes scheduling/cancellation/read/request-close capabilities, never an owner reference; compile-fail tests forbid recursive control or owner replacement.
- Snapshot includes time, registration sequence, active definitions/fire counts and reserved IDs; exact handler rebinding is external to the snapshot.
- Restore validates a complete candidate then commits once; same-lifetime restore cannot release reservations. Fresh-instance recovery is explicit.

- [ ] Write regressions: callback cannot compile an owner advance/restore/replacement, while owner dispatch remains guarded against overlapping control; invalid active Timer state leaves the full old snapshot unchanged; completed/cancelled/failed IDs survive restore.
- [ ] Add malformed snapshot cases: duplicate identity/sequence, impossible interval/state, missing/extra binding, past deadline, negative counters, restore during dispatch and replayed completion.
- [ ] Run and observe failing regressions before implementing each behavior.
- [ ] Implement validation-before-commit, callback control guard, snapshot ownership and explicit close-during-advance result.
- [ ] Prove callback query/register/cancel/reentrant same-deadline dispatch, repeated replay and full restore continuation under debug/release.

## Linux native driver and capabilities

Files: create `clock/src/native.rs`, `clock/src/view.rs`, `clock/tests/native_clock.rs`, `clock/tests/capabilities.rs`.

Interfaces:
- `OnlyLiveClock` owns a single std scheduler thread and native SystemTime/Instant sampling.
- Read-only view exposes time; scoped Timer handles expose only inspection/cancellation. No virtual advance/restore/close capability leaks.
- Driver dispatches outside locks, reports callback error/panic distinctly and feeds explicit completion to the scheduler.
- `close` and callback-safe close request preserve actual worker completion semantics; no detached-success cleanup.

- [ ] Test sample-driven wall-clock jump ordering, early wake notifications, past-deadline rejection and exact interval arithmetic deterministically.
- [ ] Test single-worker registration/cancellation, callback scheduling/failure/panic, callback-close and external-close quiescence with channels/barriers.
- [ ] Prove pure modules have no native clock/thread imports and that views cannot gain controlling methods (compile-fail tests).
- [ ] Implement std-only OS driver and capability types; keep Runtime logical occurrence/recovery authority outside the library.
- [ ] Run the full native/virtual Clock tests, including faults, without sleep-based assertions.

## Cross-language reference, build closure and review

Files: add independent vectors under `test-data/clock/` with README; add Python reference consumers under `tests/clock/`;
update `scripts/rust_kernel_check.py`, `scripts/version_sync.py`, their affected tool tests, and owning Clock/development documentation.

- [ ] Define independent expected events/errors/state for common semantics. Rust must additionally satisfy correct adversarial cases for the three diagnosed Python defects.
- [ ] Run the existing Python Clock/checkpoint reference tests and common vectors. Preserve defect observations separately in ignored diagnostics; do not claim full parity or encode known bugs as passing expected behavior.
- [ ] Add exact Clock source/dependency closure extraction and guards rejecting reverse/undeclared edges; retain independent Domain isolation with Clock absent.
- [ ] Update local Cargo version/lock graph, source-input allowlists and dev-environment metadata. Rebuild the existing fixed dev validation image only if its input identity requires it.
- [ ] Run affected Ruff/format/mypy, version/build guards, Rust format/Clippy and complete debug/release tests, package-selected and isolated Domain/Clock builds through `scripts/dev_verification.py`.
- [ ] Complete one bounded independent correctness/simplicity review. Fix current-scope High/Critical with regressions, rerun affected checks, then stop. No runtime activation or release follows from library completion.
