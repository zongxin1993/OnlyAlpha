# Execution Authority

The durable Trade chain is `Broker Update → immutable Prepared Transaction → Runtime Persistence Store → ordered Projection →
Projection Ready → durable Outbox`. Each Fill is an independent transaction; the Order is the cumulative authority.

PR4.3.2 opens Generic T0 Cash LIMIT BUY OPEN partial-fill accounting. Order alone determines terminal Fill; Position/Allocation
retain exact cumulative cost; independent Order Fee Accrual converts cumulative fee targets into Fill deltas; cash and Risk
reservations consume incrementally; Account, Strategy Ledger and Risk receive explicit deltas. Each Fill remains one immutable,
Projection Ready transaction with a contiguous per-Order Fill index. Duplicate Fill identity is idempotent and conflicting payload
fails before authority mutation. See ADR 0049, ADR 0050 and `execution_trade_planning.md`.

SELL/CLOSE, Futures/Margin, Virtual Broker Partial Fill Schedule and complete Multi-Fill Recovery remain outside this product path.
