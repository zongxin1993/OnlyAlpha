# MarketData organization and Rust delivery planning

Constitution impact NO. The business module is `crates/onlyalpha-kernel/market_data/`; state, construction and delivery are
necessary independently buildable subcrates. Preserve existing package names/records, move physical paths and update all direct
consumers atomically. No umbrella facade, workspace-in-workspace, legacy path aliases or extra deployment unit is needed.

## Responsibility and reference audit

The owning MarketData Contract, ADR0009/0020/0139/0140 define the boundary. Python subscriptions.py supplies immutable single-
instrument requirements and primary selection; dispatcher.py supplies stable Cluster ordering and PRIMARY_ONLY routing.
Pipeline composes calculation/readiness/execution, which remains outside this unit. Audit findings to classify separately:
Python allocates subscription UUIDs implicitly; Dispatcher retains every historical `(cluster,event)` until unregister;
result readers coerce booleans and reconstruct readiness from decoded data; unregister removes its local plan before calling
another mutable owner. Rust does not copy these defects or refactor Python production merely for structural symmetry.

## Inputs and outputs

New package `onlyalpha-market-data-delivery` under `market_data/delivery/`. Local edges only Delivery -> Domain, State and
Construction; State/Construction -> Domain. Reuse num-bigint and serde_json with already admitted versions/features; no new
registry nodes. Std synchronous pure library, no Clock/Event/Cluster/Strategy/Indicator/Runtime imports, callbacks, I/O, implicit
random IDs or readiness/activation authority. Caller supplies typed subscription ID explicitly as a canonical Domain identifier.
The new Rust subscription component schema1 is not Python subscription schema3 wire admission. Common UUID examples compare
semantic behavior through real APIs, not a compatibility layer.

`OnlyBarSubscription::new(id,bar_types,graph,primary:Option<BarType>,freshness)` validates nonempty unique canonical BarTypes,
one instrument and exact equality to all Bar nodes in its graph; Trade provider nodes must have that same instrument. Default
primary is minimum fixed-duration stride, then canonical BarType record order; any non-time Bar requires explicit primary.
Only PRIMARY_ONLY delivery is implemented. BarTypes are set-like and normalized. LatestClosed allows an unmaterialized secondary
view; SameEventTime requires every requested Bar to exist and end at the selected primary boundary. No readiness follows.
Strict record readers reject missing/unknown/wrong-type fields, canonical identifier aliases, duplicates and nested mismatches.

## Owner, planning and failure semantics

Non-Clone `OnlyMarketDataDelivery` binds one exact State Engine/Runtime scope. register(cluster,subscription) rejects duplicate
active Cluster or subscription identity; unregister absent rejects without mutation. No registration mutates Construction or
State: the future coordinator owns multi-owner composition. `route(&RuntimeSnapshot)` accepts only an unscoped Runtime view
with the exact owner. For each active registration in canonical Cluster ID order, primary must be updated to produce a plan;
other periods never trigger it. Restrict the immutable view to that Cluster/subscription and enforce freshness before commit.
Each `OnlyBarDeliveryPlan` contains the explicit subscription identity and immutable Cluster Snapshot; it is NOT dispatch-ready
or permission to call Strategy. No Boolean ready field and no deserializer mints an execution capability.

Keep at most one last-planned event boundary per active registration. A triggered primary must advance strictly; equality or
older time rejects, including after restore. Different Clusters may plan at the same timestamp in separate valid input snapshots.
Do not introduce a global timestamp cursor that would reject these cases. Build and validate the full result before updating
any watermark; invalid later registration cannot consume an earlier registration's boundary. No external effects or mutable
plugin calls occur, so validation failure leaves a healthy unchanged owner rather than pretending a partial execution happened.
Actual Cluster execution and per-Cluster callback failure isolation remain future coordinator responsibilities.

At-most-once is scoped to a continuously active registration. Unregister ends that registration and removes its cursor; a new
registration is a new planning lifetime. This component does not certify global historical ID uniqueness, durable exactly-once
strategy execution or reject replay across outer Generation changes; those remain Runtime admission/owning durable authority.

## Recovery

Checkpoint component schema1 has exact owner strings and registration rows containing Cluster ID, subscription record and
nullable last-planned Unix nanoseconds. Counts derive from registration membership; there is no parallel mutable counter/set
of all historical slices. Watermarks must be exactly representable Domain Bar timestamps. Restore requires preconfigured exact
Cluster/subscription membership and exact owner; no automatic configuration adoption. Parse all identities, duplicates, scope,
subscription/graph relations and timestamps into temporary state before one replacement. Idempotent restore and uninterrupted/
restored planning must agree. Decoded watermarks express component state, not proof a Strategy executed. Outer causal binding,
durable publication, real stop/start/upgrade and official Runtime activation are outside this unit.

## Validation and publication

TDD relocation and nested Cargo environment-input regression first; fixed dev image rebuild once when final manifests/lock are
known. Keep current registry digest and package versions0.10.10. Both existing libraries retain all tests and independent builds
from the deeper directory; fixture include paths and isolation extraction retain correct named corpora. Delivery tests cover
identity/graph/primary/freshness, registration order, scope narrowing, duplicate/late input, whole-batch failure atomicity,
exact-context recovery and bounded long-run state. Hand-specified vectors compare common Python behavior; malformed-reader and
watermark improvements remain classified Rust corrections. Linux unique-dev frozen-source validation, affected Python/static/
version/environment tests, Rust fmt/Clippy/debug/release and canonical lane; bounded simplicity and one independent final review.
Then normal fast-forward master publication with tested-tree/source equivalence and fetch verification. No Release by default.
