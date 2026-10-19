# Rust Execution design draft

Design for the isolated Rust Execution component. Owning Contracts define authority; current source and tests establish implementation behavior. This document is not acceptance evidence.

## Goal and boundary

Implement one independently buildable `crates/onlyalpha-kernel/execution/` library for deterministic prepared execution, ordered projection and recoverable coordination. Keep market rules, provider protocols, fee schedules, storage drivers and Runtime activation outside canonical business semantics. Python remains the official Runtime implementation until existing migration gates are satisfied.

The first complete economic scope is single-currency Generic T0 cash LIMIT BUY OPEN and LIMIT SELL CLOSE LONG NETTING, including order acceptance, partial/full fills and cancellation/rejection/expiry after partial execution. Unsupported shapes fail closed explicitly. UNKNOWN submission never authorizes a second Order identity. This construction does not certify Futures, LIVE activation or a Rust-owned Backtest product.

## Owning authorities

Follow PROJECT_CONSTITUTION.md, ADR 0139, execution.md, execution_prepared_transaction.md, execution_projection_targets.md and the commit-before-mutation decision in ADR 0041. Earlier ADR 0016/0033 ordering must not override the later durable transaction authority.

The external venue owns external execution observations. The owning Runtime Persistence Store owns committed local execution transactions. Component projections and applied indices are rebuildable representations. Event publication is at least once with stable identity; do not claim exactly once.

## Execution decisions

Owner authorized inline implementation and publication without further confirmation. Constitution impact: NO. The public component checkpoint/restore boundary is reused for complete immutable projection payloads; exact before/result checkpoint digests lock the entire component including its version, receipts, indexes and config. Component restore validates a fresh candidate from the frozen journal; it does not rerun the Execution Planner, external fee schedule, market rules or mutable queries. This avoids an additional mutable-state installation API. Full component payloads are intentionally larger than per-entity deltas; optimize only with measured evidence and equivalent recovery proof.

Execution owns only its scoped immutable fee accrual/settlement records and transaction identity relations. Its Store port is the sole durable transaction authority; test storage adapters are outside the semantic crate source. This module does not replace the existing Runtime Store or introduce a second production store. Technical actual-file reopen evidence is distinguished from official Runtime/storage upgrade certification.

## Audit-derived dependencies

1. Existing Order, Position, Account, Strategy Ledger and Risk libraries expose command application and complete checkpoint replay. They do not currently supply the complete typed before/result authority installation boundary required for committed projection replay. Extend public component boundaries only where necessary; do not access private state or rerun planners during recovery.
2. Order, Position, Account and Strategy Ledger have unconditional journal/capacity guards, including 4096-command limits. Verify each affected safety path deterministically. Separate admission of new risk from continuation of existing observations, fills, cancellation, releases and risk reduction. Checkpoint/restart must preserve that distinction. Raising constants or dropping historical receipts is not a fix.
3. Fee assessment and settlement are explicit authoritative inputs. Generic order-level cumulative target-to-incremental fee accrual, identity and application belong to stable semantics; concrete rate/minimum-fee rules remain plugins. Missing fee or settlement proof is unavailable, never an assumed zero/default T0 instruction.
4. Preserve one Position close-cost authority shared with Allocation and consumed by Account/Ledger. Prove fractional partial closes and the final all-remainder rule against independent expectations.
5. Risk capacity input must explicitly reconcile Account net availability and this Risk owner's existing holds. Authenticate and validate evidence family, scope, generation and causal watermark at the integration boundary.

## Internal organization

One Execution crate with internal fact, identity, planning, economics, projection, coordination and recovery modules. Group related responsibilities without a crate per file. Local dependencies point only toward admitted lower-layer components. Storage implementations belong outside the semantic library. Introduce only the commit/query/projection contracts required by the real transaction consumer; do not invent general frameworks or new network protocols.

## Transaction lifecycle

Normalized external observation and exact immutable before-authority
-> pure plan with identity, complete economic facts, ordered projections and preconditions
-> durable Store commit of transaction and pending Outbox
-> exact predecessor-ready gate
-> ordered component authority installation
-> durable Projection Ready
-> business-query and Outbox visibility
-> at-least-once delivery with stable Event identity.

Each projection binds component/entity identity, expected version/hash, exact result version/hash and transaction/execution sequence. Result versions follow the owning component contract, not an assumed +1. Same identity/same full payload is idempotent; conflicting payload or owner relation fails closed.

Store failure must precede all component mutation. After a committed partial projection failure, retain the applied prefix, hide success visibility and resume forward. Recovery consumes committed payloads; it does not rerun fee rules, planning or current mutable lookups. Applied-index loss is recoverable only from exact installed result authority and the committed transaction. There is no cross-component compensating rollback or second durable journal authority.

## Required proof

Derive the authority state space and relation closure before implementation: Engine/Runtime/Generation/Account/Cluster/Strategy Revision/Request/Order/Trade/venue observation/transaction/projection/Event. Missing or malformed relevant proof is incomplete/unavailable, not certified absence or equality.

Cover accepted, rejected, failed, cancelled, expired, partial, full, duplicate, stale, out-of-order, incomplete and UNKNOWN cases. Mutate whole context, nested owner relation, source reference, leaf identities, evidence family and complete-but-different identities.

Independent vectors establish quantity, cash, cost, fee, reservation and attribution conservation. Compare the actual Python reference and Rust components against these expectations; classify reference defects rather than copying them. Recover at Store commit, every projection installation/index boundary, Ready marking and publication acknowledgement. Reopen the actual selected storage implementation where durable behavior is claimed; in-memory fakes alone cannot establish persistence.

## Verification and integration limits

Run targeted unit/contract/fault tests, affected Python/static/architecture checks, debug/release native equivalence and isolated dependency closure through the sole onlyalpha-dev verification entry. Preserve test-results and frozen source binding. Perform bounded simplicity review and one independent authority/recovery review. No source acceptance with unresolved High/Critical findings.

Library integration is not Shipping UI or deployment-upgrade certification. Any actual Runtime admission or existing-history format change must atomically update its owning consumers and satisfy the existing history/upgrade gates. No automatic cleanup, data reset, compatibility fallback or LIVE activation is authorized.

## Implementation sequence

1. Publish the already verified Risk prerequisite without modifying its verified source. Establish an isolated Execution branch from the resulting exact mainline.
2. Complete the Python/Rust public-contract audit and freeze explicit wire/identity/numerical boundaries in owning documentation.
3. Add independent negative and economic vectors; observe the missing behavior fail in the nearest affected boundary.
4. Implement the necessary component projection installation and safety-capacity corrections with regression tests.
5. Implement immutable Execution facts, canonical identities, fee accrual and pure OPEN/CLOSE/terminal planning.
6. Implement ordered projection and durable commit/recovery coordination using the owning Store boundary; demonstrate actual Rust component composition.
7. Prove partial-fill/cancellation, duplicates/conflicts, UNKNOWN safety, crash matrix, fresh replay and existing-history obligations that the actual persistence changes create.
8. Integrate canonical build/verification selectors and dependency guards, complete formal verification and independent review, then publish by auditable fast-forward with a post-push fetch.

Release cadence remains representative milestones rather than an automatic release for every crate. Do not change PROJECT_CONSTITUTION.md.

## Audited precision and representation decisions

Position emits cumulative currency-target differences from one exact Allocation-cycle realized accumulator; Account/Ledger consume its Money delta and explicit exact-minus-Money rounding residual. Mandatory Allocation identity/cycle/exact-realized fields prevent new-cycle version resets from erasing lifetime PnL. The isolated Position/Account/Ledger checkpoint body becomes schema2, without fallback; no official Rust writer/history is admitted here and Python Runtime persistence remains unchanged. Existing exact artifacts are not rebound.

The Rust Prepared1 comparison representation groups atomic component checkpoints in Order/Position/Account/Ledger/Risk/Execution order. It is not Python Prepared4 or an adapter of its public Projection union/order. Every committed group result is frozen and private prefixes stay hidden. Official Runtime admission still needs its own atomic contract/consumer/history proof under ADR0139; no compatibility claim follows from common economic output parity.

Curated FP-STORAGE-001 requires full committed causal history and corrupt/missing-record fail-closed tests, including real fresh-process file replay. FP-BROKER-001 supplies UNKNOWN/no-second-identity and partial-cancel tests. FP-BROKER-002 supplies nonzero/missing cost evidence tests; fixed haircuts, venue retry and local fee formulas are rejected. These are failure-pattern evidence, not authority or copied patches.

Generic T0 monetary inputs explicitly bind currency, resolved notional and HALF_EVEN settlement rounding. Position retains raw price-times-quantity cost. Ledger accumulates settlement-versus-cost/realized rounding residual from validated trade deltas; Account consumes the sum of those owning residuals. The residual is not inferred from the equity equation. Full Ready-prefix causal hashes must connect genesis to the current projection before query, admission or completed recovery.

Market and valuation source references identify immutable evidence occurrences within their respective family. Reuse for a new request, watermark or payload is rejected. Positive quantity/exact gross can resolve to zero currency settlement; this does not make the Fill absent or waive price/quantity/settlement proof.
