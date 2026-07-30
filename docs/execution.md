# Execution Authority

The durable Trade chain is `Broker Update → immutable Prepared Transaction → Runtime Persistence Store → ordered Projection →
Projection Ready → durable Outbox`. Each Fill is an independent transaction; the Order is the cumulative authority.

PR4.3.1 adds exact partial-fill Order reduction, canonical Fill identity/fingerprint, per-Order Fill index and durable queries.
Order authority tracks filled/remaining quantity, fill count, exact cumulative `price × quantity`, average price and last Trade ID.
Memory and SQLite Stores expose Fill-identity and Order-transaction queries with equivalent stable ordering.

The complete Runtime product path remains limited to Generic T0 Cash LIMIT BUY OPEN whole fills. Partial fills fail before commit
with `PARTIAL_FILL_ACCOUNTING_NOT_READY` until PR4.3.2 implements incremental Reservation, Risk, Fee, Account and Ledger accounting.
See ADR 0049 and `execution_trade_planning.md` for the detailed contract.
