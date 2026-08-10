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
available_cash = cash_balance - frozen_cash - unsettled_cash
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
