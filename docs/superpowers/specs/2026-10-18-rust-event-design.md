# Rust Event module design

Status: OWNER-APPROVED DESIGN — the owner confirmed this written design by requesting continuation after its review handoff.
This document specifies the construction, not module completion or Runtime admission. The Constitution,
`docs/event.md`, ADRs 0004, 0009, 0048 and 0139 remain authoritative.

## Goal and authority

Implement the complete Event responsibility as an independently buildable Rust library under
`crates/onlyalpha-kernel/event/` (package `onlyalpha-event`). Preserve the single-thread, synchronous, bounded observer plane.
Events describe completed facts; dispatch never owns order/account/risk transitions, pipeline scheduling, transaction commit,
recovery admission or durable publication. Python remains the admitted Runtime implementation during this work.

The delivery covers envelope/identity/scope/record semantics, queue and subscriptions, capability restrictions, errors,
backpressure, atomic batches, lifecycle and bounded operational diagnostics. Runtime publication interfaces are contracts only;
Router, Gate, Outbox, transaction event-identity generation and actual Runtime integration are outside this library.
No Python production restructuring, Runtime activation, business-data mutation, historical migration, push or release is included.
Constitution impact: NO — this design does not weaken or reinterpret the Constitution.

## Audited reference boundaries

Python `event/model.py` owns envelopes, IDs, scope and record conversion. `event/bus.py` owns queuing, subscriptions,
observation order, capacity policies and dispatch reports. `event/subscription_view.py` restricts public control.
`event/ports.py` declares low-level publication contracts implemented by the Runtime Router. The route names do not authorize
the bus to decide recovery phases or to assert durable commit/acknowledgment.

The following reference defects are diagnosed against the owning contracts, rather than adopted as Rust behavior:

- Frozen Python Event attributes retain mutable nested payload aliases; `to_dict` also retains nested mapping aliases.
- Recursive dispatch can start a second event before the first event's observer list completes.
- Python releases its queue lock before callbacks without excluding another dispatch; handlers can run concurrently.
- Failures, dispatch results and dropped-event histories grow without bound despite the long-running system requirement.
- Default random event/subscription IDs and callable `repr` are implementation conveniences, not deterministic Kernel inputs.
- The record reader coerces values, ignores redundant timestamp text and falls back to a legacy shape for unknown schema values.

Existing correct common behavior remains a comparison reference. Correct Rust adversarial cases stay separate where Python differs;
no skip, weakened expected result or fake whole-module parity may conceal a discrepancy. The first diagnostic probe itself needed
a detached pre-mutation baseline because its shallow `to_dict` baseline shared the same alias; retained diagnostic logs are not
a normative contract or repository status ledger.

## Organization and dependencies

One library, not a service or crate per source file:

- `model.rs`: validated identities, scope, priority, immutable envelope and payload.
- `record.rs`: strict current-record reader/writer and exact nanosecond validation.
- `bus.rs`: bounded FIFO, registry and serial dispatch/lifecycle.
- `capabilities.rs`: observer view, scoped callback context and cancellation handles.
- `diagnostics.rs`: structured dispatch/failure/replacement results and bounded retained samples/counters.
- `ports.rs`: direct/durable/lifecycle publication interfaces and validated result vocabulary; no Router/Gate implementation.
- `tests/`: independent corpus, adversarial, capability and lifecycle tests.

Reuse Domain and the exact already admitted `num-bigint = 0.4.8` and `serde_json = 1.0.154` packages with their existing
minimal `std`/`arbitrary_precision` features. There are no new registry nodes, UUID generator, async runtime, network or
scheduler dependencies. Standard Rust byte/string validation suffices for reading explicit canonical UUID identities.
Clock and Predicate are not dependencies: time is an explicit Domain value and dispatch is explicitly driven by its owner.
Domain/Clock/Predicate may not depend on Event. New local/version edges and isolated closures must be admitted explicitly.

The selected bus ownership model uses single-thread `Rc<RefCell<...>>` state, a non-cloneable owning bus and restricted views.
It deliberately cannot cross thread boundaries. This implements ADR 0004's existing single-thread dispatch contract and makes
concurrent dispatch impossible by construction; borrow conflicts return a structured Busy error instead of panicking.
An `Arc<Mutex<...>>` bus would add producer/dispatcher concurrency and lifecycle choices absent from this selected contract.
Async delivery would further change the accepted scheduling model. Neither alternative is required here.
Immutable Event values themselves may be transferred through an owning Runtime's existing inbound mechanisms later; the bus
adds no threaded ingress adapter, queue service, dispatcher thread or FFI boundary now.

## Explicit identity, values and payload

Event/correlation/causation/subscription UUID values are supplied explicitly by the caller; the library does not generate random
or time-derived IDs. Store validated UUID bytes and serialize canonical lowercase hyphenated text. Nil UUID remains a valid UUID;
creation policy belongs to the owning producer. Durable transaction UUID5 derivation remains in its existing transaction owner.
Subscription IDs are unique over one logical bus lifetime, including cancelled subscriptions; rejected registration consumes
neither the ID nor ordering sequence. Handler display names are explicit strings, never closure addresses or `repr`.

Registration/event sequences and diagnostic totals use exact nonnegative arbitrary integers. Queue/sample capacities are positive
resource bounds; converting them to allocation indexes is not a canonical counter or event identity. Priority is the existing
LOW/NORMAL/HIGH/CRITICAL vocabulary. Observer priority orders callbacks only, never trades, risk or pipeline steps.

The Event constructor requires a nonempty event type/source, strong Domain scope IDs, explicit event/init Unix nanoseconds,
producer sequence, event UUID, priority, payload and metadata. Event requires Engine+Runtime, with optional Cluster; a bus filter
may be Engine-wide, Runtime-wide or Cluster-specific. Cluster scope requires a Runtime. Initialization cannot precede event time.
UTC text is a derived microsecond floor projection, including negative sub-microsecond times, within Domain's supported civil range.
No OS time, lossy float conversion or hidden sequence allocation defines an Event.

Own all payload data; envelope fields are private and accessors provide immutable borrows or detached clones. Support the existing
record payload kinds: Domain `OnlyBar`, mapping, and scalar null/string/bool/exact integer. Mapping values may recursively contain
JSON objects/arrays/scalars, with string keys and finite JSON numeric tokens preserved exactly, without f64 evaluation. Financial
Domain records retain their existing string-based decimal contract. Arbitrary Python objects, invalid keys and unsupported
payload tags fail explicitly. Domain Bar parsing/validation reuses the owning Domain reader; Event does not reimplement it.
No handler may mutate a fact seen by a later handler, including through nested collections or returned record objects.

## Current record contract and history boundary

Read/write the current schema-2 field vocabulary: identity/type, exact event/init nanoseconds, matching UTC text, scope, source,
sequence, causal IDs, priority, tagged payload and metadata. Validate required fields and types before construction. Reject unknown
schema versions, invalid UUID/scope, negative sequence, conflicting timestamp fields and unsupported payload forms. Do not silently
coerce strings/bools into integer facts or guess an unknown kind. Numeric JSON tokens must preserve exact input magnitude.

The Rust reader does not include Python's old ISO-only reader or an unknown-schema fallback. This is an explicit development
reader/admission difference, not permission to delete old facts or change existing Python readers. Current Python record writers,
historical retained artifacts and Runtime persistence are not replaced. The typed Rust Event is not admitted as a historical
Runtime reader. Any later consumer migration must inventory exact stored schemas/references and preserve their owning reader or
explicit migration proof. No new schema/identity version or hash is invented merely to rename a Rust module.

Shared comparison checks semantic record fields and exact values. JSON object member order is not an event identity; do not
claim a Python dict's display order is canonical wire bytes. Existing causal IDs, priority, payload and scope may not be normalized
away to make comparison pass. Python-only constructor conveniences and unsupported legacy reader paths are classified deviations.

## Queue, observers and dispatch

Publication only enqueues. Preserve FIFO arrival order, including across different event priorities. A dispatch captures the
current observer list ordered by descending observer priority then ascending registration sequence. Subscribe/unsubscribe during
a callback affects subsequent events, not the captured current list. A callback may enqueue, subscribe, unsubscribe and request
close through a scoped context; it cannot extract/replace the owner or invoke dispatch/drain/close-owner operations.

Only one event can be in dispatch. An explicit guard rejects recursive dispatch before dequeue or sequence mutation, while compile-
fail tests protect owner/capability boundaries. Invoke callbacks and release callback captures outside active RefCell borrows.
Catch unwind panics at dispatch, distinguish them from returned callback errors, retain their subscription/event relation and
continue remaining observers. Do not retry a handler or convert failure into success. A later event cannot overtake an event
whose observer snapshot has not finished.

Single publish returns a structured enqueue/replacement receipt. REJECT and FAIL_RUNTIME reject a full queue without mutation;
FAIL_RUNTIME returns a distinct failure for the owning Runtime to handle and never directly changes Runtime state.
DROP_LOW_PRIORITY replaces the earliest queued item among the lowest eligible priorities, only when the arriving priority is
strictly higher. The receipt identifies both displaced and accepted facts; refusal leaves the queue unchanged.

Sequential `publish_many` keeps explicitly documented prefix acceptance and reports the accepted count on rejection.
`publish_many_atomic` validates all scope/capacity before mutation and either appends the complete batch or nothing. Preserve the
existing rejection of atomic batches under DROP_LOW_PRIORITY. Invalid scope or closed state cannot accept a prefix in the atomic API.
No duplicate-event suppression is added: the bus is delivery machinery, not semantic deduplication authority.

## Diagnostics and lifecycle

Dispatch returns a complete per-event report; replacement returns its full receipt to the caller. Separate bounded rings retain
recent dispatches, failures and replacements, each with an explicit positive configured capacity (default 1024). Exact lifetime
and evicted-sample counters make retention loss visible. These are operational samples, never durable evidence, subscriber ACKs
or a second formal fact store. The owner remains responsible for consuming returned reports at its existing audit boundary.
Bounds apply to retained item counts, not a claim that arbitrary payload sizes are byte-bounded. Do not add a speculative sink,
plugin, exporter, retry queue or remote telemetry API to solve this selected library concern.

Close moves Running -> Closing, rejects new publication/subscription, and drains accepted pending facts serially before Closed.
A callback requests close without recursive drain; the current observer snapshot completes and the owner's drain continues.
Cancelling existing subscriptions remains allowed. Closed is reported only with no outstanding dispatch and no queued events.
Explicit close is idempotent. An owner dropped before quiescence stops accepting and is observable as an unfinished/failed lifecycle,
not successful Closed or proof that pending observers ran. Drop performs no forced business publication or durable recovery.
Views expose subscribe/unsubscribe/pending/state/diagnostics only; no publish, dispatch, drain or close-owner authority leaks.

## Publication ports and Runtime separation

Provide the existing direct/durable/lifecycle interface vocabulary and publication-result value validation without implementing
routing. Attempted/published/staged/suppressed/rejected counts are nonnegative and add exactly. PUBLISHED remains the owning
Router's outcome, not a guarantee of subscriber processing or durable exactly-once delivery. The bus enqueue receipt is a different
mechanical result. Runtime phase transitions, bootstrap staging, history suppression, Outbox acknowledgment and formal identity
creation stay outside Event. Do not create an empty Rust Runtime crate solely to mirror Python names.

## Validation and delivery

Independent vectors under `test-data/event/` describe explicit inputs and expected record fields, observation order, capacity
outcomes, lifecycle, structured failures and port-result validation. Both languages exercise correct common cases. Tests may
control Python UUID allocation at its existing constructor boundary with recorded inputs; they may not strip formal identity
fields or redefine Python bugs as expected correctness. Rust-only regressions cover diagnosed deviations.

Required tests include nested payload mutation attempts; malformed/unknown/current records; exact negative/sub-microsecond times;
scope hierarchy; equal-priority registration ordering; callback registration/cancellation; recursive control and cross-thread
compile-fail; prefix vs atomic rejection; all capacity policies; error/panic continuation; callback close and owner quiescence;
invalid registration preserving sequence; bounded diagnostics with visible evictions; owner-drop unfinished lifecycle; and
read-only view authority restrictions. Use deterministic inputs/barriers, never sleep/retry/xfail as proof.

Extend exact dependency/source/native-effect guards, version metadata and isolated builds for Event+Domain with Clock/Predicate/
Runtime absent. Preserve isolated Domain/Clock checks. Admit this quality-infrastructure extension explicitly rather than relaxing
a generic allowlist. Formal verification uses the existing unique dev service, frozen source, offline Cargo and one worker.
Run affected Python Event/Router/Gate and architecture tests, static checks, Rust fmt/Clippy/debug/release and isolated closure,
package/version checks, plus bounded independent correctness and simplicity review. Fix scoped High/Critical and rerun affected
checks. Technical library evidence does not activate Rust, certify live trading or replace later product/recovery/upgrade gates.
