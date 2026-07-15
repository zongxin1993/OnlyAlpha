# Strategy Ledger 组件差距分析

## 1. 当前策略资金与收益模型

| 模块 | 当前职责 | 当前问题 | 目标类型 |
|---|---|---|---|
| MyQuant `BrokerSim.account_data` | 保存初始资金、可用、冻结、市值和总资产 | 券商账户账与策略资金账混合；float；无法支持多个 Cluster 独立归因 | 后续 AccountManager；本阶段不修改 |
| MyQuant `BrokerSim.send_order/check_orders` | 买单冻结现金、成交扣款、卖出回款和费用 | Reservation、成交、Position、现金和手续费在 Broker 内耦合；费用有时进入持仓均价 | `OnlyStrategyCashReservationManager` + Ledger Trade Accounting |
| MyQuant `PositionManager` | 从账户 available/total 按比例计算买入预算 | 使用券商账户总资金，不能表达 Fixed Capital 或 Cluster 资金隔离 | `OnlyStrategyCapitalAllocation` + Ledger Risk View |
| MyQuant Order `pnl` | 保存卖出估算收益并扣除费用 | Fill、完整交易、费用和收益语义混合，无法稳定重放 | Allocation realized delta + Fee Ledger |
| MyQuant Engine 报表 | 从账户总资产、订单 PnL、成交额拼装日收益和 equity curve | 多个来源公式不一致；账户收益可能被当成策略收益；未实现盈亏与现金视图无法对账 | `OnlyStrategyEquitySnapshot` / Performance Snapshot |
| MyQuant Hyperopt | 从 float equity curve 计算最大回撤 | 与运行时资金状态分离，符号和精度不同 | Ledger High Water Mark / Drawdown |
| OnlyAlpha Position Allocation | Cluster 数量、独立均价、realized PnL、fee | 已是策略持仓成本权威，但没有虚拟现金、净值和绩效账 | Strategy Ledger 只消费 Allocation 结果 |
| OnlyAlpha Risk Reservation | 订单名义金额预占 | 不是 Cluster 虚拟现金账，不能替代 Cash Reservation | 保持分离并增加 Strategy Cash Reservation |

## 2. 当前资金更新链

```text
MyQuant:
Order
  -> BrokerSim 直接减少 Account.available、增加 Account.frozen
  -> Fill 同时修改 Account、PositionData、Order.pnl 和 Fee
  -> Engine 从 Account.total / Order.pnl / Trade amount 拼装 Equity 与 Daily PnL
  -> Hyperopt 再从导出曲线计算 Drawdown

OnlyAlpha 当前:
Order -> Risk Reservation -> Position Reservation
Trade -> Position -> Cluster Allocation
Cash / Fee / Strategy PnL / Equity / Performance：尚不存在
```

检查结论：账户资金与策略资金混用；多 Cluster 没有独立资金对象；订单提交没有策略现金预占；收益可能来自账户合并
资产或订单字段；手续费缺乏独立可重放归因账；回测与实盘统计来源不同；同一 Trade 没有 Strategy Ledger 幂等入口；
净值没有 Cash View/PnL View 双重校验；Context 尚未提供 Ledger，更没有只读 Scope。

## 3. 依赖与本次边界

| 依赖 | 当前状态 | 复用 / 新 Port |
|---|---|---|
| Order | Runtime Manager、cluster/account scope、标准回报已存在 | OrderService 通过窄 Cash Reservation Port 调用 Ledger |
| Trade | `OnlyPositionTrade` 强类型、带 Cluster/fee/sequence | 复用为 Accounting Input 的成交事实 |
| Position Allocation | 独立成本、数量、realized PnL、fee 已存在 | before/after Snapshot 是 position cost 和 realized delta 权威 |
| Position Valuation | 账户 Position Valuation 已存在 | 新 Strategy Valuation 只接受 Cluster Allocation |
| Market Data / Mark Price | 不可变 Snapshot 已存在 | 第一版测试/Execution 明确传入 mark price，不由 Ledger 自行查询 |
| Clock | 每 Runtime 独立 Clock | Manager 调用方传入 Runtime Clock 的 `OnlyTimestamp` |
| Risk | Runtime Risk Context 和只读 Port 已存在 | 新增 Strategy Ledger Risk View；异常状态 Fail Closed |
| Account | 只有纯 Domain Snapshot，无 AccountManager | 本阶段不读取或修改券商真实现金，不伪造权益 |
| Currency / Money | Decimal、强币种值对象已存在 | 第一版严格单 Base Currency，币种不一致明确拒绝 |
| Fee | Trade fee 已有 | 新增独立 Fee Entry/Ledger；不进入 Allocation 平均价 |
| Cash Flow | 尚不存在 | 支持 Initial Allocation 与 Runtime 管理的 Manual Adjustment |

## 4. 变更边界

本次建立每 Runtime 唯一 `OnlyStrategyLedgerManager`，按 Runtime/Account/Cluster/BaseCurrency 创建独立 Ledger。
第一版实现 Fixed Capital、单币种、Long-only 股票/ETF、买单现金预占、买卖成交现金流、Fee Ledger、Allocation 驱动的
Realized/Unrealized PnL、Cash/PnL Equity 双视图、Simple Return、High Water Mark、负号 Drawdown、基础交易累计、
不可变 Snapshot、Scope、幂等、严格乱序和 Replay。完整 AccountManager、FX、保证金、分红、自动资金转移、真实 Broker
现金同步、完整 ExecutionProcessor、Matching Engine 和 Web 均不在本阶段。
