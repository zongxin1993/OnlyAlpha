# Rust Order lifecycle component

## Authority and boundaries

One pure independently buildable `crates/onlyalpha-kernel/order` owns isolated component Order state. It reuses Domain Request,
Fill, Snapshot and fee contract values; Domain remains lower and has no reverse dependency. No Broker calls, automatic Strategy-to-order
conversion, Risk approval, funds, position projection, official Runtime activation or business data migration. Constitution impact: NO.
Official Python Runtime and durable transaction ownership remain unchanged. Component mutation success grants no execution permission.

## Audited reference and corrections

Read Python `order/{entities,manager,id_generator}.py`, `execution/reducers/trade_state.py` and lifecycle reducers alongside ADR0011,
0049 and0066. Direct entity paths and durable reducers are distinct reference paths, never alternative Rust authorities.
Python create deduplicates only request ID, direct Fill loses PENDING_CANCEL, identity sets do not prove equal payload, and checkpoint
restore installs entries incrementally. Correct these in Rust; do not import Python legacy restoration or repair unrelated Python code.
Terminal fills are rejected in this component per ADR0049. Existing direct-Python cancelled-late-fill behavior is classified, not silently
called equivalent. Pending cancel partial Fill stays pending, final Fill becomes FILLED. Terminal state never regresses.

## Inputs, state space and determinism

One Manager binds exact engine/runtime/gateway/generation configuration. Create binds cluster/account plus canonical request; generated
Order and Client IDs use persisted Runtime-local counters independent of connection/session. An explicit opaque causal fingerprint
links the request to its caller-owned decision/policy facts; this component does not certify their admission. Duplicate request identity
requires exact request, scope and causal fingerprint. All local operations carry explicit business nanoseconds. External observations
carry exact runtime/gateway/generation/account/order, event identity, optional sequence and event/init times; Fill fields must agree with their envelope; event IDs must already use canonical spelling.
Only immutable Domain snapshots escape. Runtime/cluster checks guard all mutation and query operations. Venue ID mapping is unique
within the configured gateway/account. Financial values remain exact; weighted average rounds half-even once from integer ratio to
final price precision. Arithmetic/input/journal bounds fail before mutation. No wall clock, randomness or I/O enters semantics.

States: CREATED, SUBMITTED, ACCEPTED, PARTIALLY_FILLED, PENDING_CANCEL, FILLED, CANCELLED, REJECTED, EXPIRED, FAILED.
Independent submit outcomes: NOT_DISPATCHED, DISPATCHING, KNOWN_RESULT, UNKNOWN, RECONCILING, RESOLVED, SUPPRESSED.
BEGIN_SUBMIT records a local dispatch attempt as SUBMITTED plus DISPATCHING; SUBMITTED does not prove transport delivery or venue acceptance.
DISPATCHING precedes handing work to a transport; captured DISPATCHING restores as still non-dispatchable uncertainty, never NOT_DISPATCHED.
UNKNOWN/RECONCILING permit observations and cancellation but no repeated dispatch. Transport outcome is not Venue Accepted.
A committed venue observation resolves only an actually dispatched outcome; it cannot invent a dispatch from NOT_DISPATCHED.

APPLIED means a validated complete state transition. DUPLICATE requires matching retained payload; STALE requires lower external
sequence or local command time; CONFLICT means exact identity reuse with different payload/owner or equal sequence mismatch;
INVALID is a proved illegal transition. Missing order/config/proof and malformed input are errors, never absence or success.
Duplicates/stale/conflicts/invalid commands do not change versions, counters, retained receipt sets, checkpoint or event sequence.
Newly applied state returns a scoped immutable fact with explicit global sequence and snapshot. No EventBus mutation or publishing.
A second identical semantic Accepted/terminal outcome under a new event identity may be a no-op without advancing hidden watermarks.

## Identity and recovery proofs

Request -> runtime/cluster/account/causal fingerprint -> Order/Client -> gateway/account/Venue -> immutable update/Fill -> resulting
snapshot is the owned relation chain. Retain full fingerprints for event, local Trade and Venue Trade identities; equal ID alone cannot
prove duplicate. Absence of Venue ID, unresolved submit or cancel request cannot prove a rejected or cancelled order.
Domain Snapshot conserves requested = filled + unfilled quantity even for terminal states; a separate executable-remaining query is
zero for all terminal orders. Do not change Domain schema or call unfilled quantity executable.
New cancel identities during PENDING_CANCEL are INVALID, never proof of a duplicate occurrence.
Bound every nested fee Money amount before arithmetic-bearing Domain decoding. Caller-supplied complete fee tuple is installed atomically and validated by Domain before SUBMITTED; no invented zero fees or formulas.

Checkpoint schema1 is a bounded canonical record containing exact configuration, complete applied-command journal and independently
serialized resulting state, receipt payload commitments and identity indexes. Caller retains its expected SHA-256. Restore checks canonical encoding/digest, replays every command into
a fresh exact-config candidate, requires every recorded command APPLIED, verifies complete reconstructed state and only then replaces
the receiver. This restores counters, outcomes, receipt payloads, cancel identities and indexes together. No partial install, old reader,
latest substitution, union with current state, automatic dispatch or business store. Journal compaction is out of scope; at the explicit
bound new mutation is refused. Coherent rewrite plus attacker-chosen expected digest is not authentication.

## Evidence and limits

Curated FP-BROKER-001 (WonderTrader77/TqSdk71) motivates session-independent IDs and no submit replay; ADR0049 motivates exact
notional, fill identity and pending-cancel tests. Contracts take precedence over upstream behavior.
Independent shared vectors cover ordinary lifecycle and exact arithmetic. Compare valid common behavior with actual Python OrderManager;
explicitly test corrected cases against independent expectations. Structural mutations cover config, owner, input, nested snapshot,
identity collisions, counters, duplicate journal entries and complete-different history. Failed restore preserves its receiver.
Required Linux sole-dev frozen checks: targeted tests, affected Python static/tool/version checks, existing Order canonical lane,
Rust debug/release, extraction/independent build, source guards, one bounded independent review. No Web product behavior changed.
