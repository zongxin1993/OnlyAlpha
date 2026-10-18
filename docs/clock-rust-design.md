# Rust Clock and Timer design

Status: OWNER-APPROVED DESIGN — selected through explicit review in the current engineering conversation. This is not a second semantic Contract, acceptance registry or Runtime
admission. PROJECT_CONSTITUTION.md, the owning Clock Contract (`clock.md`), ADR 0008 and ADR 0139 remain authoritative.

## Intent and selected boundary

Implement the complete Clock/Timer responsibility as a native Rust library. Audit Python behavior first, retain correct semantics,
and correct defects in Rust without requiring a structural Python rewrite. Python remains the admitted Runtime implementation until
explicit activation gates pass; its code is a comparison reference, never the source of expected correctness by itself.

Recommended organization under `crates/onlyalpha-kernel/`:

- `domain/`: immutable absolute time, UTC values and intervals; no mutable scheduling, OS clock, threads or Runtime.
- `clock/`: independent package `onlyalpha-clock`; pure scheduler state, virtual advancement and a separate Linux native driver.
- `core/`: retain existing Predicate responsibilities; do not hide the new independent Clock library inside the existing Predicate crate.

The independent crate is justified by a complete lifecycle/restore API and a smaller source/dependency closure than the broad
Kernel library. It is not a service, deployment unit, per-Timer crate or RPC boundary. Its allowed local edge is Clock -> Domain;
Domain and the existing Predicate library cannot reverse-import Clock. Runtime may consume Clock only in a later explicit slice.
Within Clock, place scheduler/value/error types, virtual execution and native driver in responsibility modules; do not mirror
Python's single large `core/clock.py`. No empty callback/plugin/framework counterpart tree is required.

## Alternatives

1. **Recommended:** independent Clock library with a deterministic scheduling core and separate native-time driver. It can be built,
   tested and reviewed without Runtime, and native effects cannot leak into virtual/replay execution.
2. Extend the existing Predicate crate with Clock. Fewer manifests, but unrelated responsibilities and build inputs become coupled.
3. Translate the Python package/file structure literally. Lower initial design effort, but preserves mixed responsibilities and
   restoration defects; it does not meet the owner-approved migration policy.

## Ownership and inputs

Clock owns mechanical scheduling state, reservation of Timer IDs for its lifetime, deterministic ordering, virtual advancement,
cancellation and callback-dispatch bookkeeping. Each owning Runtime creates and closes its Clock. A read-only Clock view cannot
advance, restore or close it. Scoped registration/cancellation capabilities must not grant Runtime-wide control.

Streaming Runtime's existing logical Timer registry, occurrence journal, committed trading effects and recovery/reconciliation
remain outside Clock. A scheduler notification is not an admitted/committed trading occurrence. Clock cannot publish formal
occurrences, execute orders, choose missed-occurrence policy or become a second durable Timer authority.

Pure scheduling inputs are explicit signed Unix-nanosecond instants, integer delays/positive intervals, Timer IDs, registration
order, explicit callback completion/failure and control operations. Use arbitrary-magnitude integers consistently with Domain and
Python; no platform-sized counters, implicit floating conversion or silent overflow. UTC microsecond projection reuses Domain.
All OS time/monotonic samples enter the native driver explicitly; monotonic readings are never persisted as business timestamps.

## Scheduling and callback behavior

- IDs are nonempty canonical validated strings and unique over the logical Clock lifetime, including completed, failed and
  cancelled Timers. Rejected registration cannot consume sequence or partially insert a Timer.
- One-shot deadlines cannot precede the relevant observed current time. Delays are nonnegative; fixed-rate intervals are strictly
  positive integers. Fixed-delay registration remains unavailable under ADR 0008; do not create an unused public mode/branch.
- Virtual dispatch order is `(deadline_ns, registration_sequence, timer_id)`. A callback observes its deadline; same-deadline
  registration/cancellation takes effect before the next dispatch. Fixed-rate recurrence advances from the previous deadline.
- Query, schedule and cancel are allowed through a private-field `VirtualClockContext`, never `&mut` to the owning Clock. It has
  no owner extraction, `DerefMut`, advance or restore methods; compile-fail tests enforce this control boundary. Recursive
  advance, set-time, snapshot restore or a second
  unresolved dispatch is rejected before mutation. The owning advancement cannot overwrite a time already advanced by recursion.
- Native callbacks execute outside the scheduler lock, serially. Represent completion/failure explicitly and stop a failed periodic
  Timer while retaining a structured failure; other Timers continue. Catch a Rust callback panic at the driver boundary according
  to the pinned unwind profile and report it distinctly from a successful callback. No panic is swallowed as successful work.
- A cancellation/close already observed by the owning dispatcher prevents subsequent dispatch/rearm. In-flight callback work cannot
  be undone; close must define a quiescence boundary and not claim rollback of prior effects.

Implement callback dispatch with one outstanding typed dispatch/completion token when needed by both drivers; a token binds the
actual Timer, sequence and fire count. It is local bookkeeping, not a new durable business identity or occurrence Authority. A
wrong/replayed completion must leave state unchanged. Do not turn the Kernel's direct calls into RPC or serialize callbacks.

## Virtual and Backtest control

Virtual advancement never reads system time, waits or creates threads. Reject backward targets. Fire all eligible deadlines,
including newly registered callbacks, in deterministic order before reaching the requested target. Callback failure is retained
in the advancement result. If a callback closes the Clock, abort remaining dispatch, preserve the final observed callback time,
and do not silently report that the unvisited target was reached. Closure and end-of-advance behavior must be covered directly.
Backtest uses this mechanism under its Runtime control capability; it does not need a duplicate timer implementation or wrapper
introduced only to copy Python class names.

## Snapshot and restore

A Clock checkpoint describes canonical scheduler state, not callback code. The complete restoration state includes current time,
registration sequence, all active and terminal Timer definitions, fire counts and the complete set of reserved lifetime IDs.
Terminal records themselves reserve IDs; do not maintain a competing independently writable used-ID authority. Validation must reject
negative counters, duplicate IDs/sequences, impossible mode/interval combinations, unsupported states, deadlines preceding current
time, fire-count inconsistencies and missing/noncanonical IDs. Reserved IDs cover every active ID. Sequence must dominate all
restored registrations. Snapshot contents must not expose mutable state aliases.

Restore is allowed only at a quiescent point, never inside a callback or unresolved dispatch. Validate the entire payload and
callback binding set, construct candidate state, then replace state once. Any rejection preserves current time, Timers, callbacks,
reserved IDs and ordering exactly. Restore into the same logical lifetime cannot release an already used ID; define explicit
fresh-instance recovery versus same-instance rollback rather than silently clearing identity authority.

A time-only restore cannot discard active work. Restoring active Timers requires exact explicit callback/handler rebinding from
the owning validated implementation; missing or extra active bindings fail closed. Callbacks, closures, native monotonic times,
threads and external effects are never serialized. The owning Runtime must preserve exact implementation/generation provenance.

The Rust snapshot shape is not claimed compatible with the current Python Runtime checkpoint, which omits retired IDs. No
historical migration by guesswork, empty-store replacement, old-reader fallback or Runtime switch is authorized. Later admission
must recover used identities from authoritative retained facts/definitions, or remain blocked if those inputs are insufficient.
Snapshot tests are in-memory/reader tests, not proof of a deployed restart or upgrade.

## Linux native driver and lifecycle

Use Rust std for SystemTime/Instant, synchronization, one scheduler thread and notifications. Keep OS operations in the native
module; pure/virtual modules cannot import SystemTime, Instant, thread or Condvar. No async runtime or third-party scheduler is needed.
Each native Timer binds its business deadline to a monotonic wait anchor at registration. Wall-clock adjustment cannot duplicate
an already dispatched Timer. A business-deadline heap must not block an independently monotonic-due Timer after a wall-time jump;
collect the due set from monotonic eligibility and dispatch it in explicit business-deadline/sequence order.

Same-time sampling, past-due observations, early notifications and new registrations have explicit inputs; no assumptions about
thread wake order define canonical dispatch. Positive intervals and arithmetic remain exact. Native wait conversion bounds are
transport mechanics only: reject unrepresentable operations explicitly or use a documented exact remaining-duration strategy;
never clamp a business deadline or silently shorten an interval.

Close is idempotent, prevents new registrations, cancels pending work and wakes the scheduler. A callback can request close without
joining itself. An external close waits for actual scheduler completion; it must not report Closed while a callback/worker remains
active. A stuck callback is a visible failure/unfinished lifecycle, never forcibly detached as a successful close. Deterministic
barrier/fault tests prove state transitions; no sleep-based correctness tests or retry-until-green.

## Dependency and build scope

Reuse the pinned std toolchain, Domain, and the already admitted arbitrary-integer registry closure. If a direct integer dependency
is required, admit its exact version/features and verify the existing registry closure before use; do not introduce a second
integer/decimal implementation. Canonical JSON support is added only if the selected snapshot reader requires it and reuses the
already admitted version. No network, SDK, database, Python bridge or native build script is part of this library.

Update the Cargo member/local-lock/version graph, exact edge/source-input guards and existing dev-environment inputs atomically.
Verify package-selected and isolated Clock + declared Domain/dependency closure tests without the application, Runtime or database.
A new Cargo manifest can require rebuilding the fixed dev validation image, but no parallel Compose topology or data reset.

## Required validation and acceptance boundary

Shared independent vectors cover UTC/nanosecond preservation, ordering, fixed-rate recurrence, cancellation, callback registration,
failures, close behavior and valid restore. Both languages exercise correct shared behavior. Correct-contract adversarial cases
cover recursive advancement, rejected-restore atomicity, lifetime-ID retention, malformed snapshots, replayed dispatch completion,
invalid inputs and native wall/monotonic jumps. Python defects stay explicitly diagnosed; no skip/xfail or weakened expected result
may make an incorrect Python behavior look equivalent to Rust. Do not call common-subset parity whole-module equivalence.

The complete selected Clock responsibility includes virtual control, Timer operations, restricted views/handles, snapshot recovery,
failure and close semantics, native Linux driver and its lifecycle. Unit completion requires all these paths, isolation, debug/release,
Clippy/format, targeted consumer/contract checks and bounded independent correctness/simplicity review. Pure queue primitives alone
are not the complete Clock module. Kernel-library tests do not replace formal Product UI, Backtest/SIM/LIVE admission or real upgrade
proof; those remain separate later slices. The present proposal does not modify the running Python application or business stores.
