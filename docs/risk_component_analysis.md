# Risk 组件实现前差距分析

## 1. 扫描范围

实现前已检查 OnlyAlpha 的 Order Request/Service/Manager/Result/View、Runtime/Context、Clock、Instrument、
MarketRule、TradingCalendar、MarketData Snapshot、EventBus 和既有测试；并只读分析 MyQuant 的
`core/rick.py`、`risk/FixedPercentageRisk.py`、`risk/FixedPriceRisk.py`、`risk/MarketRisk.py`、
`risk/RiskDataProvider.py`、`factory/risk_factory.py` 及 PositionManager 的风控和下单段落。

## 2. 当前 Risk 实现

| 模块 | 当前职责 | 当前问题 | 目标实现 |
| --- | --- | --- | --- |
| OnlyAlpha `order.service` | 创建订单、调用 Placeholder Execution | 创建前没有 Risk；结果不能表达 Risk REJECT/ERROR；没有 Reservation | 在 create 前同步调用 Runtime RiskService，接受后立即预占 |
| OnlyAlpha Runtime | 独占 Clock、OrderManager、EventBus 和行情管线 | 没有 RiskService、Risk State/Profile；InstrumentView 当前为空 | 每 Runtime 独占 RiskService/State/Reservation/Registry View |
| OnlyAlpha Context | 暴露只读 Clock/Market/Order capability | 没有只读 Risk Snapshot；策略无法审阅风险状态 | 增加只读 `ctx.risk`，不暴露 evaluate/配置/释放能力 |
| OnlyAlpha Instrument/MarketRule | 提供 tick/step、数量、名义金额、日历、涨跌停等纯规则 | 尚未组合为订单 Risk Rule；缺 Runtime Registry 装配 | 由只读 View 驱动 Instrument/Market Rule，不硬编码市场 |
| OnlyAlpha Account/Position Domain | 存在不可变领域快照 | 没有 Runtime Manager/可靠同步状态 | 只定义 Risk Port 和明确 unavailable View，依赖规则缺数据即 ERROR |
| MyQuant `RiskManagerBase` | 持仓止盈止损、市场 risk-off、后台轮询和强制卖出 | 不是 Pre-Trade 审批；直接依赖 PositionManager/Broker；读系统时间；使用 float；可跳过；异常仅日志 | 不复制；拆成未来 Position Risk Rule/Port，当前建立不可绕过 Pre-Trade Pipeline |
| MyQuant PositionManager | 买入冷却、总/单品种开仓次数、订单拆分 | 规则散落在下单循环，返回 skip/bool，无统一拒绝与错误类型；无 Reservation | 可迁移行为抽象为 Runtime/Cluster Rule 和结构化 Decision |

## 3. 当前订单风控链路

当前：

```text
Cluster → ctx.orders.submit → OnlyOrderService
→ OnlyOrderManager.create_order → Placeholder Execution → SUBMITTED
```

目标：

```text
Cluster → ctx.orders.submit → OnlyOrderService
→ request/scope context → OnlyRiskService.evaluate_order
  → REJECT/ERROR：审计 + Risk Event；不创建 Order、不调用 Execution
  → ACCEPT：create Order → 立即 Reservation → Execution
```

当前不存在可被策略调用或绕过的 Risk 对象，也没有通过 EventBus 执行 Risk；但同样没有任何最终审批。
OrderService 直接持有唯一创建入口，因此它是强制 Risk 的正确接入点。现有接口只有 Order mutation 结果，不能
区分正常 Risk REJECT 和 Rule ERROR；没有 on_bar 前状态、未完成订单额度、风险预占、Profile 或 Rule Scope。

MyQuant 的 Risk 由 PositionManager 注入并可按买入信号跳过；Live/Simulate 使用后台线程，Backtest 同步执行，
API 和顺序不同。Rule 直接读取/修改 PositionData 并调用 Broker，异常记录日志后继续循环；它不能作为
OnlyAlpha 强制系统风控或确定性回放的基础。

## 4. 当前风险数据来源

| 数据 | 状态 | 本阶段处理 |
| --- | --- | --- |
| Instrument | Domain 已实现，不可变 | Runtime 注册并通过只读 View 提供；Mandatory exists/tradable 与精度规则使用 |
| MarketRule | Domain 已实现，可组合 | Runtime 只读映射；tick ladder、lot、minimum notional、calendar、price limit 使用 |
| Clock | 每 Runtime 独立 | 所有 Decision/Snapshot/Reservation 时间来自 Clock |
| MarketData | Pipeline/Snapshot 已实现 | on_bar 前传入 Risk state update；MARKET 名义金额缺价格时不伪造 |
| Order | 每 Runtime OrderManager 已实现 | 只通过 Query/Risk View读取活跃订单，不暴露 Manager 给 Rule |
| Reservation | 未实现 | 新增 Runtime 私有 Manager，按 Runtime/Cluster/Account/Instrument 隔离 |
| Position | 只有 Domain 类型，无 Manager 真值 | 定义只读 Port 和 unavailable 占位；依赖规则缺数据时 ERROR |
| Account | 只有 Domain 类型，无 Manager 真值 | 定义只读 Port 和 unavailable 占位；不假设无限资金 |
| Cluster 配置 | `OnlyClusterConfig.values` 已实现 | 解析 `risk_profile`/profile config，Mandatory Rules 始终合并且不可删除 |
| Runtime 配置 | 已有 mode、Scope、默认账户 | 增加受控 Instrument/MarketRule/Profile 装配，不把 Risk 配置暴露给策略 |

## 5. 迁移边界

本阶段实现 Rule/Pipeline/Profile/Service/State/Snapshot/Reservation/Event/Audit、Account/Position 只读 Port，
并接入 Runtime、on_bar 前屏障和 OrderService。不会迁移 MyQuant 的后台线程、直接 Broker 下单、float 价格数量、
板块手数硬编码、Position 自动平仓或“买入信号跳过 Risk”。不实现真实 Account/Position Manager、策略
`on_risk_xxx` 回调、撮合、自动撤单/强平、真实 SDK 或 Web。
