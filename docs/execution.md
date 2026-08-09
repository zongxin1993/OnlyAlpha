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
checkpoint boundaries recover through the existing phases. The same Fill Plan is now also proven for Long Close.

PR4.4.2 completes the deliberately narrow Close slice in that same chain: `GENERIC_T0_CASH + LIMIT + SELL + CLOSE + LONG +
NETTING`, cash account, one currency and Margin disabled. Every partial or final Fill is an independent transaction. The Planner captures existing Position, Allocation,
Position Reservation, Risk Reservation, Account, Strategy Ledger, fee, settlement and valuation authority before producing one
immutable transaction. Its projection order is Order, Position, Allocation, Settlement, Order Fee Accrual, Fee, Account,
Strategy Ledger, Position Reservation, Risk Reservation, Risk and Valuation. Removed non-durable execution source is absent;
unsupported shapes fail closed.

Position is the single realized-PnL authority: `(fill price × fill quantity - exact released cost) × multiplier`. Position and
Allocation use one cumulative-cost reducer; partial fills release `cumulative cost × fill quantity / quantity before`, while the
final Fill releases every remaining cost unit and sets cumulative cost exactly to zero. Allocation, Account, Strategy Ledger and
committed fact consume that exact delta. Gross cash inflow is sale notional,
net cash inflow is notional less the authoritative Fee instruction. Close carries no cash Reservation; its Position Reservation
is consumed inside the same ordered projection batch. Existing Fill identity/index, Coordinator, recovery phases, Event Gate and
at-least-once Outbox semantics are unchanged. Partial Fill Cancel/Reject/Expire uses an `ORDER_TERMINAL` transaction with stable
`ETERM-...` identity, no Trade ID and four ordered projections. Same identity/same payload is idempotent; a conflicting payload
fails closed. Terminal Facts are excluded from Trade Results. Short, Hedging, CloseToday/CloseYesterday, Futures/Margin and
Paper/Live remain outside this scope. See ADR 0053.
# Attributed Close Cost

`OnlyTradeExecutionTransactionPlanner` 在 reducer 前创建 `OnlyAttributedCloseCostAuthority`。只有 builder 调用平均成本归约函数；Position 和 Allocation reducer 安装 Authority 给出的 after state，不再独立计算 released cost 或 PnL。缺失 Allocation、scope 冲突、数量不足或 Position 成本无法由 Allocation 聚合解释时，在 commit 前 fail closed。
