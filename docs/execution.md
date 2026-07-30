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
checkpoint boundaries recover through the existing phases. Partial/Multi-Close and Futures/Margin remain outside this product
path.

PR4.4.1 migrates one deliberately narrow Close slice into that same chain: `GENERIC_T0_CASH + LIMIT + SELL + CLOSE + LONG +
NETTING`, cash account, one currency, Margin disabled, and a whole Fill that consumes an Order whose prior filled quantity and
fill count are both zero. The Position itself may remain open or reach zero. The Planner captures existing Position, Allocation,
Position Reservation, Risk Reservation, Account, Strategy Ledger, fee, settlement and valuation authority before producing one
immutable transaction. Its projection order is Order, Position, Allocation, Settlement, Order Fee Accrual, Fee, Account,
Strategy Ledger, Position Reservation, Risk Reservation, Risk and Valuation. SELL/CLOSE no longer enters `_unmigrated_trade()`.

Position is the single realized-PnL authority: `(fill price - average open price) × quantity × multiplier`. Allocation, Account,
Strategy Ledger and committed fact consume that exact delta. The exact released cost is `average open price × quantity`; a
remaining Long keeps its average, while a zero remainder clears average and cumulative cost. Gross cash inflow is sale notional,
net cash inflow is notional less the authoritative Fee instruction. Close carries no cash Reservation; its Position Reservation
is consumed inside the same ordered projection batch. Existing Fill identity/index, Coordinator, recovery phases, Event Gate and
at-least-once Outbox semantics are unchanged. Partial/Multi-Close, Short, Hedging, CloseToday/CloseYesterday, Futures/Margin and
Paper/Live remain outside PR4.4.1; PR4.4.2 owns incremental Partial/Multi-Close accounting. See ADR 0052.
