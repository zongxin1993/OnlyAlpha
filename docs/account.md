# Account 组件

`OnlyAccountManager` 是每个 Trading Runtime 的本地账户单写入者，第一版支持 CNY 现金账户、Long-only 股票/ETF、现金、冻结、
待结算现金、费用、账户级盈亏、持仓市值、权益和 Reservation。内部状态受控可变，所有 Query、Context、Risk 和 Report
边界只读取 frozen `OnlyAccountSnapshot`。

Account 与 Strategy Ledger 是两本独立账：Account 表示 Trading Runtime 账户合并真值；每个 Strategy Ledger 只表示一个 Cluster
的虚拟资金与归因。Account 也不引用 Broker Store；Broker Snapshot 只能经 Runtime inbound queue 到达字段级 reconciliation，
冲突不能静默覆盖本地历史。

Research Runtime 不拥有 formal trading Account 或 Strategy Ledger；研究资金曲线只能是 Research Result，不得冒充交易账务真值。

现金账户不变量为：

```text
cash_balance >= 0
frozen_cash >= 0
unsettled_cash >= 0
trade_available_cash = cash_balance - frozen_cash
withdrawable_cash = trade_available_cash - unsettled_cash
equity = cash_balance + position_market_value
```

Order 创建后，Trading Runtime 同时协调 Risk Reservation、Account Cash Reservation 与 Strategy Cash Reservation。它们各有独立
状态和生命周期，不共享内部对象。成交后 Account 从标准化 Trade Cash Flow 更新，估值使用账户 Position 与已关闭行情。
Trade Cash Flow 的 fee 必须来自 Runtime 订单累计权威生成的 `OnlyFeeApplicationInstruction`；AccountManager 不读取
Market Profile、Broker Schedule 或外部费用证据，也不计算佣金。Strategy Ledger 与 Fee Application Ledger 应用同一指令投影。

受支持的 multi-fill Long Close 每笔使用 `gross_cash_inflow = sale notional`、`net_cash_inflow = sale notional -
incremental authoritative fee`。Account 不建立或消费现金 Reservation，frozen cash 保持不变；它只消费 Position 给出的
realized-PnL delta，并与 Strategy Ledger 的 cash、fee、realized PnL 和 valuation authority 在 Prepared Transaction 不变量中
交叉校验。Terminal Cancel/Reject/Expire 不产生现金流、Fee、realized PnL 或 Account Projection。

第一版不支持多币种换汇、保证金、融资融券、负债、期货/期权账户和 corporate action 现金流。

所有 Broker Account Update 由 ExecutionProcessor 分派到 `OnlyAccountReconciliationService`；Trade cash flow 位于 Ledger 后、
Reservation 前。Account Manager 事实经 Processor 缓冲，不会在后续 Reservation/Risk/Invariant 失败时形成完整成功事件。
# Close PnL 输入

Account 不计算平仓 PnL。它只消费 Planner 已由 Cluster Allocation 成本归因得到的 `realized_pnl_delta`；Runtime 对账比较 Account 与所有 Strategy Ledger 的聚合值。

## Rust component ownership and recovery boundary

`crates/onlyalpha-kernel/account/` is an isolated Domain-dependent CASH account component. It consumes normalized fee instruction totals and Position-attributed PnL; it never recomputes fee schedules, position costs or realized PnL. Account, Strategy Ledger and external Broker facts keep distinct Authorities. Cash-backed BUY consumes gross notional plus charges from its exact Reservation; rebates credit cash separately. SELL never consumes a buy Reservation. An explicit Order terminal_fill controls release of excess authority. Uncertain submit/cancel preserves holds, and reconciliation blocks new reserves/withdrawals while valid fills and observations continue.

The actual cash identities are `trade_available = ledger_cash - order_reserved_cash`, `withdrawable = trade_available - unsettled_receivable_cash`, `equity = ledger_cash + position_market_value`. This distinguishes the two availability views rather than using ambiguous available_cash shorthand. This component conservatively reserves and withdraws against withdrawable cash; market-specific settlement reuse is not inferred. Explicit source-bound settlement instructions consume recorded receivables. No hardcoded currency, venue, trading day or settlement date occurs.

Config/commands/checkpoints are closed schema1 records. Exact scope, currency precision, full-payload receipt conflicts, signed times, ordered trade/Broker sequences, valuation economic basis and bounded resources are checked before candidate commit. Broker snapshots only compare; unverified or stale proof cannot overwrite economics or clear stale-trade blocks. Canonical checkpoints bind the complete journal/state and replay into a fresh owner before atomic replacement. See the [component design](superpowers/specs/2026-10-19-rust-account-design.md) for input limits and errors.

Python direct Manager and the formal Execution reducer are separate reference paths. Direct Manager's ID-only dedup, incomplete receipt restoration and mutation-before-validation are audited deviations, not expected Rust behavior. Literal cash vectors compare actual Python common economics and the formal reducer with native Rust in both profiles. Rust does not introduce a second official writer, Runtime admission, durable cross-authority transaction, business history migration, Shipping UI acceptance or deployment certification. Margin/futures/FX/fee accrual/funding-policy derivation and reporting orchestration retain their owning boundaries and future admission tests.

Signed net Trade effects are accepted when the final cash invariants hold: charge/rebate components remain nonnegative, but fees can exceed sale proceeds and rebates can exceed purchase cost. A nonpositive sale net creates no positive unsettled receivable. A Fill proves submission even without an earlier send callback and can never permit NOT_SENT release of remaining authority. The input coefficient bound applies after canonical currency-precision padding, so every admitted config is readable by its checkpoint reader.

Reference distinction: the Python formal reducer adds a signed cash delta to unsettled receivables when a SELL is not withdrawable; a net-negative sale would violate its nonnegative receivable model. Rust instead records the real signed cash outflow without fabricating a negative settlement claim. This case has an independent Rust invariant test; it is not claimed as Python parity.

The Rust Execution composition evolves this isolated component's checkpoint body to schema2; it does not activate a writer or change official Python Runtime persistence. New semantic fields are mandatory and schema1 has no implicit fallback. New-risk admission budgets are distinct from complete safety history; existing observations/fills/releases and proved reduction retain complete replayable history beyond admission ceilings. See the [Execution boundary](execution.md#rust-component-execution-boundary) for cumulative Position PnL, explicit rounding residuals and exact Allocation cycle/identity inputs.
