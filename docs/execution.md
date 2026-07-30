# Execution Authority

The durable Trade chain is `Broker Update → immutable Prepared Transaction → Runtime Persistence Store → ordered Projection →
Projection Ready → durable Outbox`. Each Fill is an independent transaction; the Order is the cumulative authority.

PR4.3.2 opens Generic T0 Cash LIMIT BUY OPEN partial-fill accounting. Order alone determines terminal Fill; Position/Allocation
retain exact cumulative cost; independent Order Fee Accrual converts cumulative fee targets into Fill deltas; cash and Risk
reservations consume incrementally; Account, Strategy Ledger and Risk receive explicit deltas. Each Fill remains one immutable,
Projection Ready transaction with a contiguous per-Order Fill index. Duplicate Fill identity is idempotent and conflicting payload
fails before authority mutation. See ADR 0049, ADR 0050 and `execution_trade_planning.md`.

PR4.3.3 adds the plugin-owned deterministic Virtual Broker Fill Plan and complete Generic T0 Cash LIMIT BUY OPEN Multi-Fill
Recovery. WHOLE, legacy MAX_PER_BAR and explicit SCHEDULE share one execution chain; ONE_PER_BAR and ALL_DUE produce one
independent immutable Runtime transaction per Step. Broker execute-before-publish, Commit, Projection, Outbox and partial-plan
checkpoint boundaries recover through the existing phases. SELL/CLOSE and Futures/Margin remain outside this product path.
