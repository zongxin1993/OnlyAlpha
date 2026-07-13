# MyQuant 现状分析

## 1. 范围与方法

分析日期：2026-07-13。来源为 `/home/zongxin/workspace/MyQuant` 的只读代码审查；未修改文件、未连接 QMT、未启动实盘、未执行含账户配置的示例。

重点入口为 `examples/demo.py`、`examples/demo_live.py`、`MyQuant/core/engine.py`、Strategy/Datachef/Broker/Datafeed 抽象及其 sim、XT、SQLite、Mongo 实现。

## 2. 当前执行模型

```text
EngineSetupConfig
  -> Engine(mode)
  -> Factory 创建一个 Strategy 及其 Context
  -> Datachef.on_bar() 拉取/整理数据
  -> Strategy.run_once(metadata)
  -> PositionManager/Broker.send_order()
  -> BrokerSim.check_orders() 或 XT SDK 回调
  -> Broker 内部订单、持仓、账户集合
```

`Engine.run()` 是同步主循环。`EngineRunMode` 在一个 Engine 内选择 BACKTEST、LIVE、HYPEROPT 或 ML 路径；没有多 Runtime 或多 Cluster 的顶层模型。回测与实盘共享部分 Strategy/Datachef 接口，但由模式分支和具体类实现差异。

## 3. 入口与生命周期

- 回测入口：`examples/demo.py` 将模式设为 BACKTEST，选择 `BrokerSim`，Datachef 逐步返回历史 bar，策略运行后记录结果并由 Engine 导出统计和图表。
- 实盘入口：`examples/demo_live.py` 将模式设为 LIVE，选择 XT Broker/Datafeed。该文件含具体账户路径、账户 ID 和 webhook，属于必须清理并改为外部安全配置的风险，不得迁移原值。
- ML/Hyperopt：也由同一 Engine 的模式分支承担，使 Engine 同时包含训练、优化、报表、通知和交易协调职责。
- Strategy 生命周期主要隐含在构造、`is_running`、`run_once` 和组件初始化中，缺少独立的 load/initialize/start/stop/fail 状态机。

## 4. 数据、订单与状态流

### 4.1 行情

Datafeed 抽象提供历史 bar/tick、交易日历、板块、财务数据和盘口查询。XT Datafeed 还负责订阅和最新 bar；DatachefLive 的 SDK 推送回调写入内部缓存，主循环轮询完整 bar。DatachefBacktest 预加载历史数据并以确定顺序推进。

问题：行情访问、特征准备、缓存、调度和策略上下文边界较混杂；事件没有统一 envelope、序号与 runtime/cluster 隔离字段。

### 4.2 下单和回报

策略经 PositionManager 调用 Broker。BrokerSim 在 `send_order` 中冻结资金/可卖量，在 `check_orders` 中根据 bar 高低价撮合并直接更新订单、持仓、账户和费用。BrokerXT 继承 XT 回调接口，维护本地与远端委托映射并处理订单、成交、资产和持仓推送。

问题：Broker 同时是外部适配器、撮合器和状态真值；查询与推送、去重、乱序及恢复缺少独立可验证边界。OnlyAlpha 应先标准化为领域事件，再由执行域唯一更新真值。

### 4.3 账户和持仓

`PositionData`、`OrderData`、`TradeData`、`AccountData` 是可变数据类。模拟 Broker 持有活动/历史订单字典、持仓字典和账户对象；实盘 Broker 从 SDK 查询和回调更新状态。核心价格、数量、金额、手续费和盈亏广泛使用 `float`。

OnlyAlpha 不直接复用这些模型；后续迁移必须先建立定点值对象、状态机、幂等事件和账户对账测试。

## 5. Cache、Storage、配置与可观测性

- Datachef 内有多种 DataFrame 内存缓存，但没有包含 engine/runtime/cluster/version 的统一 Cache 接口。
- DatafeedSQLite 提供 bar 的查询和 upsert；DatafeedMongo 查询历史数据。数据源访问与可靠业务状态 Storage 尚未分离。
- 配置使用 dataclass 与开放 `params` 字典，灵活但缺少强 Schema、秘密分离和版本迁移。
- 使用标准 logging，并含耗时统计、回测图表和实盘产物；这些是可保留的行为需求，不能整体复制实现。

## 6. 并发与时间

Engine 主循环同步运行；XT SDK 自有回调线程进入 Broker/Datachef；风险模块可启动后台线程并通过 `time.time()` 做冷却。部分逻辑直接使用 `datetime.now()`。共享状态的所有者和线程边界不统一。

OnlyAlpha 第一阶段采用单 Cluster 串行处理、有界队列、注入 Clock；任何 SDK 回调只做标准化和投递，不在回调线程执行业务或持锁调用外部接口。

## 7. 模块映射

| MyQuant 模块 | 当前职责 | 主要问题 | OnlyAlpha 边界 | 状态 |
|---|---|---|---|---|
| `core/engine.py` | 模式选择、循环、ML/优化、报表 | 单实例多职责、模式分支 | `engine` + 多 `runtime` + application | 仅建骨架 |
| `core/strategy.py` | 策略和上下文协调 | 生命周期与依赖隐式 | `cluster` | 仅建骨架 |
| `datachef/*` | 历史/实时数据整理、缓存、特征 | 数据、缓存、调度耦合 | `backtest/live/research` 服务 | 未迁移 |
| `broker/broker_sim.py` | 模拟撮合、订单、持仓、账户 | 多个状态真值、float | `execution/backtest` | 未迁移 |
| `broker/broker_xt.py` | XT 连接、交易、回调和映射 | SDK 与领域状态耦合 | `gateway` 适配器 | 未迁移 |
| `datafeed/*` | XT/SQLite/Mongo 数据访问 | 接口过宽、Cache/Storage 模糊 | market gateway/cache/storage | 未迁移 |
| `core/object.py` | 配置和交易数据类 | 可变、float、弱 ID | `domain/config` | 重新实现最小值对象 |
| `core/position.py` | 持仓和下单协调 | 直接依赖 Broker | execution/application | 未迁移 |
| `core/rick.py` | 风险线程和止盈止损 | 直接时钟、共享状态、直接下单 | risk service + command | 未迁移 |
| `tool/plotting.py` | 统计产物和绘图 | 与 Engine 导出流程耦合 | analytics/visualization | 未迁移 |

## 8. 可复用行为与不迁移实现

可作为回归需求：Datachef 的预热与闭合 bar 语义、模拟盘 T+0/T+1 可用量变化、订单/成交映射、SQLite bar upsert、固定输入的回测指标、日志和耗时观测。

不直接迁移：单 Engine 模式分支、Broker 内部多状态真值、开放参数字典、核心 `float`、真实账户示例值、回调线程直接更新业务对象、Engine 内绘图/通知/训练逻辑。

## 9. 后续回归基线

真实功能迁移前，另选脱敏的固定历史数据和无账户策略夹具，对比 bar 时点、信号、订单、成交、持仓、费用、收益和回撤。当前初始化阶段不复制策略、不运行该回归，也不宣称交易行为兼容。
