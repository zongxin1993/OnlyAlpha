# Rust MarketData Pipeline composition

## Ownership and scope

One independently buildable canonical library under `crates/onlyalpha-kernel/market_data/pipeline/` composes existing State,
Construction, Delivery and Calculation; it has no Infrastructure/plugin/process dependency. The existing managed-worker package
implements its calculation port and real process probe. No new registry dependency, official Runtime activation, historical
migration, Web flow or Release is introduced. Constitution impact: NO.

Audit Python Pipeline, Dispatcher and their direct consumers first. Sequential mutation is not an atomic multi-component
transaction; a delivery plan is not an actual callback. Construction providers, not visible subscriptions, define input roots.
Trade inputs never directly dispatch; no closed Bar means no state/calculation/delivery update. Source grant, gap/dedup admission
and historical evidence remain owning Processor/Runtime responsibilities, not new capabilities of this library.

## Program and deterministic input

An immutable program binds exact Engine/Runtime/Generation, Source fingerprints, graphs/calendars, subscriptions, calculation
bindings/dependencies and preparation-consumer implementation identity. Sources and registrations are bounded (16 Sources,
256 clusters, 256 calculation slots; worker adapter retains its existing 16-instance limit). Each visible or calculation BarType
must have one configured source/construction owner; conflicting native/derived/source lanes reject. Subscription graphs must
agree with configured source graphs. Market calendars and custom construction executors remain supplied through existing SPIs.

One synchronous input contains exact Source, positive provider sequence, typed provider Bar/Trade, logical init and quality.
Validate root/source/scope/time/order before processing. Provider sequence increases per exact Source/input stream; Bar event
increases strictly, Trade event may repeat with a later sequence. This is an ordering guard, not gap-free Source continuity proof.
Processing is stable by canonical source/BarType/scope/Cluster order, never registration order or EventBus priority. One immutable
closed-Bar batch updates State, then each matching scoped calculation. A cluster sees only subscribed MarketData and its own
calculation snapshots. Its primary updated at most once per input triggers evaluation; explicit timeframe expectations refer to
last submitted exact calculation positions. Not-yet-observed calculation context is explicit, never a fabricated timestamp.

Readiness uses existing pure Calculation policy. Unobserved optional instances degrade without blocking unrelated required
instances; required or transitive dependencies block. All-optional declarations are explicitly allowed (readiness has no required
obligations), whereas an empty calculation declaration is a distinct no-calculation program. Positive result expectations still
bind revision/samples/event/input digest. Concrete indicator algorithms remain Python-owned.

## Actual handoff and failure

The delivery port is an actual synchronous deterministic preparation consumer. It may inspect immutable scoped input and return
accepted/known-failed/UNKNOWN; it cannot submit orders, publish official trading facts or own economic state. Kernel-internal
composition remains direct typed calls. A receipt records actual invocation, stable delivery identity and outcome; a route plan,
warming state or missing primary never claims invocation/acceptance. This is not Factor/Strategy execution or Runtime admission.

Any shared construction/state/calculation/contract failure after processing starts leaves the owner recovery-required and blocks
new inputs/checkpoints. Remote UNKNOWN never auto-retries or silently restarts. Local preflight refusal leaves state unchanged.
Known optional calculation failure is visible and may degrade its cluster; required failure blocks that cluster. Consumer failure
or unwind quarantines only that cluster; other clusters continue in stable order. Previously committed data are not mislabeled
rolled back. Explicit recovery consumes a caller-retained complete checkpoint; delivery consumers must be non-effectful, so this
component replay cannot repeat an order or official publication.

## Checkpoint and recovery

Capture only quiescent healthy shared state. One canonical SHA-256-bound envelope (maximum 64 MiB) binds exact program record,
source managers, State, Delivery planning cursors, input frontiers, expected calculation positions, calculation port bundles and
cluster quarantine state. Each nested component keeps its own current record meaning. A caller-supplied expected digest is
mandatory; the record cannot authorize itself. No old record fallback or business format migration is added.

Restore validates exact fields/owners/program/referenced sets/frontiers/BarTypes and worker cursor/output relations, constructs
fresh managers, State, Delivery and worker instances, verifies current snapshots against exact stored expectations, then performs
one replacement. Partial candidate restoration kills candidate workers and preserves the receiver. No public hot rebind or new
Generation selection. Worker replay must use exact implementation artifacts. Component/process replay is not real service
stop/start/upgrade certification or proof of a durable business checkpoint participant.

The composed checkpoint includes a derived composition manifest binding each manager checkpoint SHA-256 to its exact root-frontier
projection and the global ordered input prefix. Neither older manager bytes nor an older manager-plus-binding can be transplanted
into a newer cutoff. The same manifest binds State, Delivery, calculation bundles and all other component fields to the same cutoff.
Healthy active calculations must match State latest Bar and version exactly; only failed/quarantined slots
may legitimately lag. The externally retained expected checkpoint digest is the trust root: this is integrity/provenance checking,
not authentication of a fully rewritten checkpoint accompanied by an attacker-chosen expected digest. It does not interpret or
redefine a custom Construction executor's opaque state.

## Proof and performance

Use independent controlled bar/trade vectors and Python common valid references; never make Python defects expected Rust
semantics. Test multicycle/multicluster/source isolation, duplicate/reordered facts, no-output Trade, timestamp lookahead, required
and optional calculations, real consumer outcomes, failures at stage boundaries, nested checkpoint mutation and deterministic
fresh restart continuation. Real worker probe runs SMA through actual processes and native callbacks, with exact output/receipt
checks. Timings are Infrastructure diagnostics: report whole-chain wall time, Python worker backend/exchange contribution and
startup separately; unmeasured internal phases are not fabricated. No workstation/UI latency or formal trading parity claim.
