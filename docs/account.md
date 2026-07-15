# Account 组件

`OnlyAccountManager` 是每个 Runtime 的本地账户单写入者，第一版支持 CNY 现金账户、Long-only 股票/ETF、现金、冻结、
待结算现金、费用、账户级盈亏、持仓市值、权益和 Reservation。内部状态受控可变，所有 Query、Context、Risk 和 Report
边界只读取 frozen `OnlyAccountSnapshot`。

Account 与 Strategy Ledger 是两本独立账：Account 表示 Runtime 账户合并真值；每个 Strategy Ledger 只表示一个 Cluster
的虚拟资金与归因。Account 也不引用 Broker Store；Broker Snapshot 只能经 Runtime inbound queue 到达字段级 reconciliation，
冲突不能静默覆盖本地历史。

现金账户不变量为：

```text
cash_balance >= 0
frozen_cash >= 0
unsettled_cash >= 0
available_cash = cash_balance - frozen_cash - unsettled_cash
equity = cash_balance + position_market_value
```

Order 创建后，Runtime 同时协调 Risk Reservation、Account Cash Reservation 与 Strategy Cash Reservation。它们各有独立
状态和生命周期，不共享内部对象。成交后 Account 从标准化 Trade Cash Flow 更新，估值使用账户 Position 与已关闭行情。

第一版不支持多币种换汇、保证金、融资融券、负债、期货/期权账户和 corporate action 现金流。

所有 Broker Account Update 由 ExecutionProcessor 分派到 `OnlyAccountReconciliationService`；Trade cash flow 位于 Ledger 后、
Reservation 前。Account Manager 事实经 Processor 缓冲，不会在后续 Reservation/Risk/Invariant 失败时形成完整成功事件。
