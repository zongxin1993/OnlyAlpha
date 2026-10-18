# Rust Market Data Construction design

The Owner selected Construction after State and explicitly authorized autonomous design, implementation, validation and
mainline publication without intermediate approval questions. Constitution impact NO. This is a library construction,
not Runtime admission, production migration, performance certification or retirement of Python.

## Owning constraints and reference audit

PROJECT_CONSTITUTION.md, MarketData Pipeline Contract, ADR0006/0009/0020/0139/0140 govern this unit. Domain owns canonical
Bar/Trade/calendar values. Construction owns recipes, exact construction lineage, dependency graphs and deterministic
stateful transformations. State, Event, Clock, Pipeline/Dispatcher, calculation workers, providers and durable history
remain separate. Construction must finish before State/Indicator/Snapshot/Strategy updates. A filled local cache does not
prove Source continuity, Generation admission, historical absence or trading readiness.

The Python correspondence is resolution.py (recipe/requirement/capability/plan/identity/graph), aggregation/compiler.py
(stable lane compilation), aggregation/manager.py (shared execution), aggregation/time_bar.py (TIME_BAR@1 and read-only
preview). Subscription delivery/primary selection belongs to future dispatch; this library consumes explicit graphs and
registration IDs rather than translating the whole subscriptions package. completed_boundary.py owns product session
querying and is outside this execution unit. Existing provider resolution policy restrictions remain explicit.

Audit targets include unregister mutation before graph recompilation, duplicate checkpoint lane collapse, sequential
executor restore, permissive record types, per-window sequence forgetting and arbitrary factory state. These are tested
against independent required semantics; no Python production cleanup or false whole-module parity is authorized. Current
Python official execution is unchanged. Relevant failure lessons: authoritative history must not mutate through shared
references (FP-DATA-002); restored projection is not Runtime readiness (FP-RUNTIME-002/FP-STORAGE-001).

## Module and dependency boundary

Create crates/onlyalpha-kernel/market_data/construction, package onlyalpha-market-data-construction. Private modules:
model (typed recipe/input/edge/graph), resolution (capability/requirement/plan/identity), compiler (immutable lane plan),
executor (pure extension contracts/registry), time_bar (TIME_BAR@1), manager (owner/checkpoint), record (strict helpers).
Only local edge: Construction -> Domain. Reuse admitted exact num-bigint 0.4.8 std, serde_json 1.0.154 std/arbitrary_precision,
sha2 0.11.1 without defaults; no registry nodes added. Domain supplies exact decimal arithmetic and calendar interval
resolution. No direct Jiff, OS clock/random/thread/I/O, Event/State/Clock/Runtime dependency, FFI or new worker framework.

Reuse existing Domain/schema representations and recipe1/graph1/plan3/identity2/lane1 fingerprints. JSON objects sort by
canonical key and preserve exact integers/Unicode; reader equality never uses floating point or coercion. Map-like graph
arrays normalize order and reject duplicate identities; histories never sort to hide invalid order. Exact recipes never
silently fall back to Native or another algorithm. Native is selected only by the explicit existing policy and exact
capabilities. Provider capability discovery remains an external adapter responsibility. Identity objects express lineage;
they do not certify referenced durable artifacts exist. Missing mandatory derived base revision/seal evidence rejects.

## Pure execution and state ownership

Facts are typed Bar or Trade. The graph supports Bar->Bar and Trade->Bar edges with matching instrument and semantic;
known algorithm IDs also constrain their input/output formation. Compile iteratively into stable topological level then
lane-ID order; reject duplicate/unknown sources, native/derived target conflicts and cycles. Provider Lane IDs include the
explicit source binding; derived Lane IDs include output, recipe fingerprint and source binding. A lane is the routing key,
not merely its output BarType. No wall time or implicit primary is chosen.

A non-Clone mutable manager binds Engine/Runtime/source and an immutable Domain calendar. register(id,graph) rejects an
existing ID; unregister(id) rejects an absent ID without mutation. Registration membership is authoritative; lane/provider
reference counts derive from it, avoiding parallel mutable truth. Shared lanes retain executor state until their final
registration disappears. Prepare graph/plan/executors fully before replacing a registration. Algorithm factories and
executors are in-process, deterministic, side-effect-free extension contracts, keyed by exact ID/version. TIME_BAR@1 is the
only built-in; absent rolling/tick/volume/value executors fail closed. Registered test executors prove Trade lane routing.

process receives source binding, typed fact and explicit logical initialization time. Wrong source rejects without rebinding.
For a routed fact, create temporary executor instances through registered factories and restore their validated checkpoints;
execute the entire lane propagation against that temporary state. Validate each output's exact target, closed/revision0,
end-time event, event horizon, uniqueness and init; deliver no prefix. Processing failure marks recovery-required while
preserving last committed executor state. Mark failed before executing extension code so unwinding cannot leave a healthy
owner after a partial attempt. Success swaps staged state and returns immutable closed Bars. Unmatched inputs yield no output;
this is not a durable absence or Source-continuity conclusion. No cross-module transaction/rollback claim is made.

## TIME_BAR@1 and preview

Consume closed unrevised fixed-duration Bars with exact source duration, compatible price/adjustment/alignment, increasing
end times and contiguous membership within a window. Reject source=end-event mismatch. Derive windows only from explicit
Domain calendar session intervals, never Unix modulo across sessions. Target duration must be larger and divisible by source,
and both source/target aligned tumbling semantics must match session alignment. Verify calendar session/day and homogeneous
OHLC/quantity precisions, adjustment, trading day/session; turnover currencies must match. Sum exact Domain decimals,
counts and optional quantities/money; any missing optional component makes that aggregate unavailable. Output uses first
open, max high, min low, last close/open-interest; init is explicit and must not precede close. Domain datetime conversion
must be exact; unsupported sub-microsecond init rejects rather than floors.

Missing policy REJECT or SKIP_WINDOW; session-tail incomplete policy DROP or REJECT. No gap fill, correction or partial
strategy fact. Persist the last accepted boundary even after window reset, so duplicates/late Bars cannot re-enter a fresh
window. Read-only preview may use a forming Bar, returns nonclosed projection, never mutates state or enters propagation.
It is separate from formal closed facts and cannot grant trading readiness.

## Recovery and records

Time executor schema1 binds exact edge and calendar fingerprint plus one validated state variant: EMPTY; PENDING with
chronological source Bars; or SETTLED with its last source Bar and optional skipped boundary. Latest acceptance derives from
that variant, without duplicate stored latest/window truth. Derive window metadata from canonical facts and Calendar; reject
inconsistent/missing/foreign/closed-window state.
Manager component schema4 binds exact Engine/Runtime/source/calendar, registrations, compiled graph identity, lane identities,
reference counts, executor records and exact lifetime creation count. Rust schema4 is unadmitted; existing Python Runtime
participant schema3 and stored artifacts remain unchanged. No fallback/converter/history deletion is introduced.

Restore validates the complete owner/context/graph/registration/lane set, rejects duplicate rows, validates every fresh
executor and creation-count relation, then replaces once and clears failed. Failure preserves prior values and failed state.
Recovery requires the receiver to have the exact registration configuration already supplied through typed register commands;
a fresh receiver registers its expected graph before restoring. It never imports registrations or silently adopts another
owner/configuration from a checkpoint. Repeated restore is deterministic. Factory implementation binding is
exact ID/version under the caller's artifact; changed external implementation requires its own canonical version/admission.
Capture while failed is prohibited; the owning outer coordinator must retain the last good checkpoint. This library cannot
certify real restart/upgrade, Source/Construction durable publication or Generation admission.

## Verification and publication

Freeze an in-context Task Contract (not a repository status artifact). Use TDD, independent expected operations/records and
Python common-reference consumers, classify deviations. Prove registration/unregistration and restore failure atomicity,
DAG level/lane ordering, per-session exact aggregation, missing/tail policies, unknown algorithms, malformed output, source/
owner/graph/recipe/calendar mismatch, huge counts, negative time, preview immutability and uninterrupted/restored replay.
Retain six-package guards, unchanged 40-node registry digest and independently extracted Domain+Construction builds in both
profiles. Formal checks only through unique onlyalpha-dev frozen-source service, serial workers and retained logs. Run
nearest Python resolution/aggregation/construction consumers, affected Ruff/mypy, Cargo fmt/Clippy, debug/release and canonical
Rust lane. One fresh bounded independent correctness/simplicity review; fix scoped High/Critical before publication.
Keep release0.10.10 unless a separate version decision is required. After acceptance, fetch current master, integrate only a
verified equivalent tree, push normally, fetch again to prove alignment. No force-push, deployment or business-data actions.
