# Rust Strategy decision execution

## Purpose and authority

One independent `crates/onlyalpha-kernel/strategy/` library owns deterministic Revision/graph/input/decision semantics and exact
component recovery. Domain, Calculation and the existing MarketData Construction value model are its lower semantic dependencies. Infrastructure implements its calculation port
using the existing managed Python worker; algorithms remain registered Python TRADING plugins. MarketData supplies immutable
prepared observations; Strategy owns decision state. No order, Portfolio/Risk, Broker, formal Runtime activation or Web flow is added.
Constitution impact: NO. Current Python is the official Runtime owner throughout this construction unit.

## Explicit identity evolution

Strategy component schema2 uses the existing explicit Definition3 graph and a new schema-bound Strategy fingerprint. It is not
an official frozen StrategyRevision1 reader or writer. No persisted Definition2/Revision1 conversion, alias, fallback or fabricated
identity equality is added. Current Freeze-only creation, verified immutable readers, Research equivalence evidence and promotion
remain their owning authorities. New component values can be constructed for isolated technical comparison; their digest does not
confer formal admission. Future activation must explicitly evolve Freeze/consumers and prove retained exact artifacts/history.
Shared expected behavior compares common observation axes and decisions; Python Revision1 and component Revision2 identities are
classified as explicit schema evolution, not normalized into an equivalence claim. Trading resolution never requires Research.

## Revision and execution program

Revision2 binds a canonical sorted nonempty Universe, exact canonical RAW closed-Bar semantic and construction recipe, Definition3
DAG, exact node implementation descriptors and three Boolean role outputs: ELIGIBILITY, ENTRY_SIGNAL, EXIT_SIGNAL. Bindings cover
every node exactly, including native definition and actual TRADING implementation identities and explicit STATELESS or CHECKPOINTABLE
schema. Aliases are display-only. TARGET nodes cannot execute as trading signals. No silent parameter/semantic substitution.
An execution program additionally binds Runtime/Cluster scope, exact generation, Source and worker artifact, immutable revision and
per-instrument/node calculation bindings. Bounds: at most16 instruments,64 nodes,1MiB wire record; actual worker at most16 node
instances total per process. Unsupported type/version/shape/capability is rejected before execution. CROSS_SECTION has no admitted
shipped TRADING producer in this component; Research registration alone never grants Trading capability or changes the long-term goal.

## Deterministic decisions

Accept only Universe members with exact Bar semantic, closed/revision0/RAW/end-event input and explicit logical time. Observations
exclude transport/init metadata and include complete canonical financial facts. Repeating the same final observation returns its
previous outcome without invoking nodes again; corrected or older observations fail before mutation. Independent instruments have
isolated node instances; global logical time/order is explicit. Resolve external Bar fields to exact tagged scalar inputs. Walk the
existing stable DAG order, passing only current upstream outputs; validate exact names/types/nullability against each owning Definition.
Producer readiness is explicit; do not infer it from numeric values. Warmup or nonready dependencies yield an explicit blocked result,
not a StrategyDecision. Ready terminal nulls use the existing FALSE missing-decision policy. A decision binds revision, observation,
logical input identity and graph receipt trace. It is not an Order Intent or permission to trade.

Once processing can mutate a node, failure, panic, lost/malformed receipt or UNKNOWN leaves that Strategy owner recovery-required.
Never blind-retry earlier nodes, recreate workers, advance a last-decision watermark or advertise stale readiness. Previously completed
remote updates are not called rolled back. Other independently owned Strategy sessions can continue under their own bindings.

## Worker and integration

Extend the existing private Protobuf transport with a closed, schema-versioned node operation. Operations resolve one exact live
registered type, create an exact-bound isolated instance, update with a final Bar and tagged inputs, capture, fresh restore and close.
No dynamic module/class path, pickle, generic method invocation, network listener or Runtime command endpoint. Reuse declared
TRADING registrations from admitted indicator/operator/predicate sources and artifact-bind all used source closures. Unsupported
state/readiness/shape contracts fail closed. Decimal invocation retains the existing explicit numeric policy.

The first technical coordinator has one exact Cluster/primary instrument/source, while the pure executor supports isolated multi-instrument programs. A real technical coordinator feeds MarketData preparation (without a second copy of Strategy calculations) to Strategy and pairs both
checkpoints under one input cut. The existing pure preparation callback never owns hidden Strategy truth. Actual worker receipt and
independent expected decision values prove this handoff; planner callbacks alone do not. This is a non-publishing comparison component.

## Recovery

A bounded canonical checkpoint under a caller-retained expected digest binds exact program, node states/receipts, per-instrument
accepted observations/outcomes and complete input prefix. Every successful node acknowledgment carries the actual native plugin-state SHA-256, retained separately by Rust and bound in its receipt trace; capture/restore must reproduce it. A nested state transplant cannot manufacture a newer acknowledged commitment by rehashing only its envelope. Fresh restore reconstructs all candidates, validates bindings/cursors/
observations/output roles and current component relations, then installs all state at once. A failed candidate is discarded and
candidate processes reaped; the receiver remains unchanged, including its failed status. Coordinated MarketData/Strategy recovery
must reject cross-cut splices, including identical terminal Bars under different histories: Strategy parent must match the latest actual preparation receipt retained by Pipeline checkpoint schema2. The coordinator owns no independent delivery-prefix authority. No business store, history migration or service-upgrade certification is implied.

## Proof

Independent vectors cover identities, all scalar families, warmup, terminal nulls, multiple instruments and exact decisions.
Adversarial tests cover missing/extra/foreign bindings, cycles/types, duplicate/corrected/reordered inputs, known rejection/UNKNOWN,
later-node failure after earlier commit, stale outputs and nested/cross-prefix checkpoint mutation. Exercise actual registered SMA,
another indicator, operator and predicate; compare valid common Python behavior and classify audited reference defects. Require Linux
sole-dev frozen serial targeted/canonical lanes, affected static/protocol/package/version checks, offline debug/release plus isolated
source/dependency closure, bounded simplicity and one fresh independent correctness review. No Release in this unit.
