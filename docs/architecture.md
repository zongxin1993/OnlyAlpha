# OnlyAlpha 总体架构

Risk 的 Runtime 所有权、固定 Pipeline、Profile 和 Reservation 决策见
[ADR-0012](adr/0012-risk-pipeline-profile-and-reservation.md) 与 [Risk 组件](risk.md)。Risk 位于 Runtime 与
OrderService 边界：Cluster 只能读取 Snapshot，所有订单在创建前强制审批。

## 1. 架构目标

OnlyAlpha 采用模块化单体作为初始形态，不在早期拆分微服务。

核心目标：

- 统一 Engine；
- 多 Runtime；
- 多 Cluster；
- 回测、模拟盘、实盘和投研共享核心模型；
- 市场、资产、Gateway 和策略解耦；
- 支持进程内运行，并为后续远程调用预留边界。

## 2. 顶层关系

```text
OnlyEngine
├── OnlyLiveRuntime
│   ├── OnlyCluster A
│   └── OnlyCluster B
├── OnlyPaperRuntime
│   └── OnlyCluster C
├── OnlyBacktestRuntime
│   └── OnlyCluster D
└── OnlyResearchRuntime
    └── OnlyFactorPipeline
```

## 3. 核心模块

```text
domain          强类型领域模型
core            通用基础能力
event           事件定义和 Event Bus
engine          顶层生命周期和组件协调
runtime         不同运行环境
cluster         策略运行单元和插件管理
gateway         行情与交易外部适配
execution       订单、成交、持仓和账户
risk            风控
cache           高速访问
storage         可靠持久化
backtest        历史数据驱动和撮合
live            实盘接入
research        因子和投研
analytics       统计
visualization   图表和报告
application     用例服务
api             Web/CLI 边界
```

## 4. 依赖方向

```text
domain
  ↑
core
  ↑
event / interfaces
  ↑
engine / runtime / cluster
  ↑
gateway / backtest / live / research
  ↑
application
  ↑
api / cli
```

内层不得反向依赖外层。

## 5. 状态真值

系统必须为以下状态定义唯一可信来源：

- 订单：`OnlyOrderManager`；
- 成交：`OnlyTradeRepository` 或执行域；
- 持仓：`OnlyPositionManager`；
- 账户：`OnlyAccountManager`；
- Instrument：`OnlyInstrumentRegistry`；
- Cluster 生命周期：`OnlyClusterManager`；
- Runtime 生命周期：`OnlyRuntimeManager`。

策略内部不得维护一份与系统真值脱离的完整账户副本。

## 6. 扩展方式

新增策略：增加 Cluster 类和配置。

新增市场：增加 Gateway、Market Rule 和 Instrument Provider，不修改 Engine 核心。

新增资产类别：增加 Instrument 类型、估值和风控规则，不修改策略框架。

新增存储：实现 Storage/Repository 接口。

新增 Web：调用 Application Service，不穿透到 Domain 内部。

## 7. 当前实现边界

`src/onlyalpha` 当前包含 Phase 1 骨架和 Phase 2 Pure Financial Domain：可组合多个 Runtime 和 Cluster，并提供基础金融值、ID、Instrument、订单/成交、持仓/账户、行情和日历模型。Live/Paper 类型仍只是运行环境标记，不连接行情或交易；Backtest 不含历史驱动和撮合；Research 不含因子管线。任何真实交易能力都必须在后续阶段通过独立 Gateway/Execution 边界和 ADR 引入。

Domain 仅依赖标准库和自身模块。`core` 及其上的所有模块可以依赖 Domain，Domain 不得依赖 core 或其他外层模块。

## 8. 时间依赖边界

Domain、Event、Storage 和 Runtime 的绝对时间统一为 UTC。市场解释由 Domain 的
Venue、IANA TimeZone、TradingCalendar、TradingDay 与 Session 完成；完整规则见
`docs/time_model.md` 和 ADR-0007。Application/API 可调用 Domain 外的
`OnlyTimeConversionService` 做 UTC/MARKET/USER_LOCAL 展示，但 Domain 不依赖显示层。
Backtest 与 Live 后续必须复用同一 Calendar 接口，不得各自维护时间规则。

## 9. Order 运行边界

Order 状态域属于 Runtime，而非 Engine 或 Cluster。Runtime 独占 `OnlyOrderManager` 和执行更新入口；Cluster
共享 Runtime 真值但只持有 Scope 受限的 `ctx.orders`。Domain 定义不可变请求、Fill 和 Snapshot，Order 层
定义受控实体与服务，Gateway 实现位于更外层。状态修改通过函数调用，成功后才发布事实 Event。

## 10. Position 运行边界

每个 Runtime 从构造起独占 `OnlyPositionManager`、`OnlyPositionAllocationManager` 和
`OnlyPositionReservationManager`。账户 Position 与 Cluster Allocation 是两层账；无法归因部分进入 Unallocated。
Cluster 只通过 `ctx.positions.account/cluster` 读取不可变 Snapshot。Broker Position Snapshot 只能进入字段级
AuthorityPolicy 和 ReconciliationService，不得覆盖本地历史。详见 [Position 组件](position.md) 与
[ADR-0013](adr/0013-position-allocation-settlement-and-reconciliation.md)。
