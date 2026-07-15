# Strategy Ledger 第一版验收报告

## 结论

`ACCEPTED`。建议 Strategy Ledger Domain 与 Runtime/Context/Risk/Order Reservation 集成进入当前主线；暂不进入完整
AccountManager、完整 ExecutionProcessor 或 ExecutionSimulator，后者应在独立任务中编排 Position Allocation → Ledger。

## 验收摘要

- 每个 Runtime 独立 Manager；每个 Cluster 独立 Ledger Key、资金、费用、PnL、Equity 和 Drawdown。
- Fixed Capital 可由 Runtime 配置并由 Cluster 覆盖；单币种且 Money/Currency 强类型。
- Cash Entry 覆盖初始、预占/释放、买卖、费用和调整；连续预占立即派生可用资金。
- 买卖现金、费用、Realized PnL 和成本增量均验证 Position Allocation，不使用账户合并均价。
- Cluster Allocation × Mark × Multiplier 产生 Cost、Market Value 与 Unrealized PnL。
- Cash View 与 PnL View 完全对账；不一致进入 RECONCILING，Risk Fail Closed。
- 提供 Net PnL、Simple Return、Daily PnL/Return、HWM、Drawdown、Maximum Drawdown。
- `ctx.ledger` 只读；Snapshot 不可变；Runtime 和 Cluster Scope 由 Key 与 Query 限制。
- Trade/Fee/Reservation/Cash Flow/Valuation 幂等；迟到 Trade 阻断；JSON 无损；Command Replay 确定。
- 状态先保存再发布事实 Event；内存 Repository 不暴露可变实体。

## 测试与 Demo

全量 `pytest -q` 结果为 **175 passed**；Ruff、Mypy 均通过，九个 Demo 均以退出码 0 运行。专项覆盖资金预占、买卖成交、费用、收益归因、多 Cluster、Runtime 隔离、Scope、
不可变性、双视图、Risk Fail Closed、幂等、序列化、Replay、HWM/Drawdown 和确定性。九个 Demo 位于
`examples/strategy_ledger_demo/`。

## 已知限制与一票否决检查

仅支持 Fixed Capital、单币种、Long-only 股票/ETF、线性 PnL。外部现金流后 Simple Return 返回 None；胜负统计尚无完整
Closed Position Result。未实现完整 AccountManager、真实券商 SDK/现金同步、多币种、保证金、自动强平或策略内部净额化。

一票否决项均未出现：无 Cluster 可变 Ledger、无账户平均价分摊、无静默双视图漂移、无 EventBus 状态机、无跨 Runtime 可变
共享、无 Decimal→float、无真实交易调用。
