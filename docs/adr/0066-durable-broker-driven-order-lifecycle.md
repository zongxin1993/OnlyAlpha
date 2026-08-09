# ADR 0066: Durable Broker-Driven Order Lifecycle

- Status: Accepted
- Date: 2026-08-09
- Supersedes: ADR 0053 direct terminal fallback and ADR 0065 policy-v1 lifecycle admission

## Context

Trade fills and the exact SELL CLOSE terminal shape already use the Runtime durable transaction kernel, while Broker Accepted and
BUY OPEN terminal updates mutate multiple Runtime authorities directly. The SELL CLOSE terminal transaction also declares only a
Position Reservation projection even though its target invokes a command that mutates Position and Allocation. Declared durable
authority therefore differs from actual mutable authority.

Execution support policy/version naming also conflates the policy that admits an economic shape with serialized fact schema
versions.

## Decision

All Broker-driven economic lifecycle facts in the supported `CASH + LIMIT + LONG + NETTING + no Margin` BUY OPEN and SELL CLOSE
scope are durable. The operation kinds are `ORDER_ACCEPTED`, `TRADE_FILL`, and `ORDER_TERMINAL`; Accepted has its own stable
identity, normalized-payload fingerprint, fact, projection type, immutable planning context, and pure planner.

Execution Support Policy v2 admits:

- `ORDER_ACCEPTED`: BUY OPEN and SELL CLOSE;
- `TRADE_FILL`: BUY OPEN and SELL CLOSE;
- `ORDER_TERMINAL`: BUY OPEN and SELL CLOSE.

The capability resolver remains the sole admission authority and remains market-neutral. `policy_version` is the decision field;
`execution_support_policy_version` is persisted in committed facts. Fact `schema_version` remains independent. Old
`execution_support_policy_version` names are removed without aliases.

The following invariants are frozen:

1. Broker-driven economic lifecycle facts are durable.
2. One projection component mutates exactly one declared authority.
3. Projection targets validate and install absolute committed after-state; they do not orchestrate lifecycle commands.
4. Planners calculate the complete before-to-after economic transition and declare every changed authority and precondition.
5. Supported lifecycle shapes have no direct mutation fallback.
6. Unsupported economic shapes fail closed before mutation.
7. Recovery is forward-only and resumes unapplied committed projections.
8. Recovery does not re-authorize historical committed facts under the current policy.
9. Broker command durability is outside P4.2.

SELL CLOSE Accepted releases only the account-level duplicate Position freeze and advances Position Reservation stage. The
Cluster Allocation hold remains. SELL CLOSE terminal explicitly releases remaining Position hold only when ACK has not already
done so, always releases the exact remaining Allocation hold, and releases only the remaining Position/Risk Reservation. BUY OPEN
terminal explicitly projects Account, Strategy Ledger, both cash Reservations, Risk Reservation, and Risk; committed fills and
fees never roll back.

## Projection and recovery contract

Projection order is the Runtime canonical component order. Every actual change has one projection with matching expected/result
version and state hash. A target seeing the committed result state records recovery/idempotency without applying a relative
command. A crash after Store commit is resolved only by completing remaining projections and Outbox state.

Accepted and Terminal use `transaction_id == operation_identity`, so generic transaction-ID lookup is the deduplication authority;
no lifecycle-specific query proliferation is introduced.

## Consequences

`OnlyExecutionProcessor` routes supported Accepted, Trade, and Terminal updates through the same prepared-operation coordinator.
The direct `_accepted` and `_terminal_order` economic paths and cross-authority reservation coordination in
`OnlyOrderUpdateProcessor` are removed. Manager command APIs may remain for local command-side reservation/create cleanup, but
projection targets cannot call them.

Transaction/fact/persistence schema versions advance where their serialized unions change. Older unsupported schemas fail closed;
there is no silent migration or Memory fallback.

## Rejected alternatives

- Durable-then-direct fallback preserves two write authorities.
- A generic lifecycle operation/fact loses Accepted versus Terminal semantics.
- Relative `release/consume/acknowledged` calls in projection replay are not idempotent installation.
- Market-profile admission recreates identity-as-permission.
- Cross-Manager rollback contradicts the established forward-recovery model.
