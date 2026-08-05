# ADR 0057: Durable Runtime Transaction Kernel

Status: Accepted

## Decision

The immutable prepare/commit/project/recover kernel lives in `onlyalpha.transaction`. Its authority is
`operation_kind + operation_identity`; broker, update, order, and trade identities belong to execution facts and are
not required by the generic transaction envelope.

The supported operation kinds are `TRADE_FILL`, `ORDER_TERMINAL`, and `SETTLEMENT_MATURITY`. Every operation is one
immutable prepared transaction, one committed transaction, and one ordered projection sequence. The Runtime
transaction store is the durable authority; applied-projection state remains a rebuildable idempotency index.

Persistence schema 4 is intentionally incompatible with the former execution-specific schema. Older schema or
malformed legacy payloads are rejected rather than inferred or silently migrated.

## Consequences

Execution planners retain broker-specific validation and facts. Settlement maturity can use the same coordinator,
failure semantics, outbox, and forward recovery without inventing a broker update. New durable operations must define
stable identity, immutable facts, exact preconditions, and deterministic ordered projections.
