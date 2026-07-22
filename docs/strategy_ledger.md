# Strategy Ledger：策略资金、收益与净值

## 1. 边界与所有权

每个 Runtime 独占一个 `OnlyStrategyLedgerManager`，每个 Cluster 按
`RuntimeId / AccountId / ClusterId / BaseCurrency` 拥有独立 Ledger。券商账户是真实现金和合并持仓的外部事实；Strategy
Ledger 是策略虚拟账，不修改券商现金，也不把账户合并均价或账户总收益按比例分摊给策略。

第一版只实现 Fixed Capital、单 Account、单币种、Long-only 股票/ETF、Average Cost Allocation 和 Linear PnL。它不实现
Shared Pool、动态资本再分配、多币种换汇、融资、分红、System Ledger 或策略间资金转移。

## 2. Capital、Cash 与 Fee Ledger

资本属于 Cluster 配置。单 Cluster 可省略 capital 并严格取 Account initial cash；多 Cluster 必须分别显式声明
`FIXED_CAPITAL`，币种与 Account Base Currency 相同、金额非负且总和严格等于 Account initial cash。不存在 Runtime 默认
Strategy capital、自动平均、剩余资金回退或旧字段双读。初始资金、外部现金流和交易现金流分开保存。Cash Entry 覆盖初始分配、预占/释放、买卖结算、费用和人工调整；
Fee Entry 按稳定 ID、类型、Trade/Order 和 UTC 时间独立记录，费用不混入持仓均价。

买单在送往 Execution Port 前建立 Strategy Cash Reservation。`cash_available = cash_balance - active_reserved`，连续订单同步
看到最新预占；重复预占幂等，成交按实际成交额与费用消费，拒单、失败、过期或取消后释放。超出预占只在剩余可用现金足够时
允许，底层永远拒绝负现金。卖单不预占现金，仓位预占仍由 Position 组件负责。

## 3. Trade Accounting 与 Position Allocation

成交更新顺序是 Execution 标准化 Trade → Account Position → Cluster Position Allocation → Strategy Ledger。Ledger 输入必须
携带 Allocation before/after、已实现收益增量、成本增量、Fee Entries 和买单 Cash Reservation。Manager 从 Allocation
边界重新验证收益及成本增量，不能接收账户平均成本或自行维护另一套持仓成本。

买入 `cash -= notional + fee`；卖出 `cash += notional - fee`。Realized PnL 是 Allocation realized 的前后差；Unrealized
PnL 和 Position Market Value 由 `OnlyStrategyValuationService` 使用该 Cluster 的 Allocation、Mark Price 和 Multiplier
生成。无法归因的 Position 仍属于 Position `Unallocated`，不会进入普通策略 Ledger。

## 4. Equity、Return 与 Drawdown

```text
Cash View = cash_balance + position_market_value
PnL View  = initial_capital + external_cash_flow + realized_pnl + unrealized_pnl - fees
Cash View == PnL View
```

不一致时 Ledger 进入 `RECONCILING` 并携带 `EQUITY_VIEW_MISMATCH`，Risk 默认禁止新订单；恢复一致后才回到 ACTIVE。
`net_pnl = realized + unrealized - fees`。没有外部现金流且初始资金大于零时提供 Simple Return；发生外部现金流后第一版返回
None，避免伪装成 TWR/MWR。High Water Mark 单调不降，Drawdown 与 Maximum Drawdown 均使用非正 Rate。

Trading Day 由 Runtime Calendar 提供；切换时锁定 day-start equity，用于 Daily PnL/Return，绝不以 UTC 日期猜测交易日。

## 5. Snapshot、Context、Risk 与 Scope

所有 Query 返回 frozen Snapshot。`ctx.ledger` 绑定当前 Runtime/Account/Cluster，只提供 snapshot、cash、PnL、equity、
return 和 drawdown 属性，没有 reserve/apply/deposit/reset 等修改入口。Risk Context 接入 `OnlyStrategyLedgerRiskView`，可读
资金、净值、日收益、回撤和状态；非 ACTIVE 状态 Fail Closed。

所有生产调用方通过 `OnlyStrategyLedgerLocator` 使用完整的
`RuntimeId / AccountId / ClusterId / BaseCurrency` scope 定位。Manager 创建时维护唯一 scope index；仅凭 Cluster ID 的
`get_by_cluster` / `by_cluster` 接口已删除。每次保存 Ledger Snapshot 同时追加不可变 Equity Point，显式 sequence 使同时间戳
变化仍可审计，并为 Cluster Return、Drawdown 和 valuation count 提供唯一证据。

## 6. 幂等、事件、Repository 与 Replay

Trade 按 trade/execution/venue trade ID 去重，Fee、Cash Flow、Reservation 和 Valuation 各自按稳定 ID/version 去重。稳定顺序
为 external sequence → event time → trade ID；迟到 Trade 进入 RECONCILING，第一版不静默重算历史。

Manager 先完成状态修改和持久化，再发布事实 Event。内存 Repository 保存 Snapshot、Cash/Fee Entry、Reservation 和 Event，
不暴露实体。Replay Entry 保存连续序号、操作类型和无损 JSON command；Replay Service 从初始资金重新执行命令，不恢复可变
实体。Money/Decimal 不转换为 float。第一版并发约束为 Runtime 单写入者；Gateway 线程和 Cluster 都不能直接修改 Ledger。

## 7. Demo 与限制

`examples/strategy_ledger_demo/` 包含九个示例。当前胜负统计按 realized delta 更新，尚未建立 Closed Position Result，因此不把
每个 Fill 宣称为完整交易；Backtest Runtime 已通过内存 ExecutionProcessor 完成标准化 Fill 到 Ledger 的同步纵切面编排，
但持久化事务、Recovery Orchestrator 和真实券商同步仍留给后续阶段。

Processor 调用 Trade Accounting 时延后 Strategy Cash Reservation 消费：Ledger 先验证 Reservation 身份并完成 Allocation-
authoritative accounting，Account 更新后再由 Processor 按实际 notional+fee 统一消费。Ledger 独立调用仍保持原有默认原子语义。
## 与 Account 的边界

Strategy Ledger 继续按 Cluster 记录固定初始资金、Allocation 成本、费用和 PnL；AccountManager 记录同一 Runtime 账户的合并
现金与权益。多个 Ledger 可以共享一个 Account，但不能读取或复用 Account/Virtual Broker 内部对象。Runtime 对同一 Fill
分别投递强类型 accounting input，账户合并成本不得反向污染 Cluster 归因。

回测结束时 `OnlyRuntimeLedgerReconciliationService` 验证初始资本、现金、持仓市值、已实现/未实现 PnL、费用和权益的
Account 值等于所有 Cluster Ledger 加总，并用 Committed Execution 核对逐 Trade fee 的 Cluster 归属。差异形成结构化结果，
Backtest 标记失败，服务不会修改 Account 或任一 Ledger。当前只正式执行最终 barrier 对账；逐估值 barrier 对账尚未实现。
