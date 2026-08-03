# OnlyAlpha 当前组件完成状态

## 1. 审计基线

```text
Repository : zongxin1993/OnlyAlpha
Branch     : master
Commit     : 71892b10ff7748d097ef49cda1c06487f0b4bdb9
Version    : 0.3.2
Status     : Alpha
```

本报告中的“完成”只表示当前明确支持范围已经形成源码、测试和工程边界闭环，不代表已经达到生产级实盘标准。

状态定义：

| 状态     | 含义                     |
| ------ | ---------------------- |
| 稳定     | 核心边界已经明确，近期不应结构性重构     |
| 当前范围完成 | 明确支持范围已经形成产品纵切面        |
| 基础完成   | 核心接口和主要实现存在，但产品覆盖仍不完整  |
| 部分完成   | 已有实现，但缺正式纵切面、真实数据或完整验收 |
| 未完成    | 尚未形成可用产品循环             |
| 暂不支持   | 当前架构明确拒绝或 Fail Closed  |

---

## 2. 总体结论

OnlyAlpha 当前已经完成三个核心闭环：

```text
确定性 Backtest 产品链
+
Generic T0 Cash Long Durable Execution
+
Multi-Cluster 共享账户成本与收益归因
```

正式主链为：

```text
Cluster Config
→ OnlyEngine
→ Runtime Planner
→ Runtime Assembler
→ Backtest Runtime
→ Historical Replay
→ Indicator
→ Factor
→ Strategy
→ Risk
→ Order
→ Virtual Broker
→ ExecutionProcessor
→ Prepared Transaction
→ Durable Commit
→ Ordered Projection
→ Result / Analytics
→ Artifact / Report
→ Checkpoint / Recovery
```

当前最成熟的产品范围：

```text
Runtime         : BACKTEST
Market Profile  : GENERIC_T0_CASH
Account         : CASH
Order Type      : LIMIT
Position Side   : LONG
Position Mode   : NETTING
Open            : BUY OPEN
Close           : SELL CLOSE
Fill            : Whole / Partial / Multi-Fill
Terminal        : Cancel / Reject / Expire
Cluster         : Single / Multi-Cluster
Persistence     : Memory / SQLite
```

当前不应把以下能力描述成正式完成：

```text
Paper
Live
Shadow
Research Workflow
Web
Futures/Margin Durable Lifecycle
Short/Hedging Durable Lifecycle
Corporate Action
Multi-Currency/FX
OrderBook Matching
Distributed Backtest
```

---

## 3. 组件状态总表

| 组件                          | 当前状态      | 当前结论                                          | 主要缺口                            |
| --------------------------- | --------- | --------------------------------------------- | ------------------------------- |
| Domain Value Objects        | 稳定        | Money、Price、Quantity、Currency、Timestamp 等边界清晰 | 多币种和 FX 产品链                     |
| Instrument / Calendar       | 基础完成      | Instrument、Session、Calendar 可用于回测             | 公司行为、完整参考数据                     |
| OnlyEngine                  | 当前范围完成    | 唯一产品入口和生命周期已形成                                | 多进程和远程执行                        |
| Runtime Planner / Assembler | 稳定        | Runtime 分组、装配和兼容性判断清晰                         | 非 Backtest 产品装配                 |
| Backtest Runtime            | 当前范围完成    | 确定性回放、交易和恢复闭环                                 | 大规模性能基线                         |
| Paper Runtime               | 部分完成      | 任意时间装配、订阅/Bootstrap/Catch-up、Shadow Execution、Observation | 真实 Warmup 兼容性、Gap Recovery、恢复和完整产品验收 |
| Live Runtime                | 未完成       | 类型和接口基础存在                                     | Gateway、重连、同步、对账                |
| Shadow Runtime              | 未完成       | 仅有概念边界                                        | 完整产品循环                          |
| Research Runtime            | 部分完成      | Factor/Indicator 基础可复用                        | 实验、统计、批量任务、绘图                   |
| Cluster                     | 当前范围完成    | Strategy、Factor、Ledger Scope 隔离               | 动态资本分配                          |
| Multi-Cluster               | 当前范围完成    | 共享 Runtime/Account 和成本归因已闭环                   | Unallocated、Cross-Cluster Close |
| Clock                       | 稳定        | Backtest 时间推进和确定性调度完成                         | Live Clock 产品验证                 |
| Event Bus                   | 基础完成      | Runtime 内事件路由和恢复门禁完成                          | ACK、Watermark、Exactly-once      |
| MarketData Pipeline         | 基础完成      | Bar Replay、Cache、Aggregation 可用               | Tick、OrderBook、大规模读取            |
| Synthetic DataSource        | 当前范围完成    | 可用于确定性产品测试                                    | 不承担真实市场验证                       |
| Tushare DataSource          | 部分完成      | 日线读取、校验和缓存基础存在                                | 复权、公司行为、Golden Dataset          |
| MiniQMT DataSource          | 部分完成      | 实时 Adapter 与进程隔离 Historical Worker 已实现          | 本地 SDK Profile 兼容性、正式产品验收和恢复       |
| Market Profile              | 基础完成      | Registry、Compiler、Rule Engine 已建立             | 完整市场 Conformance Pack           |
| Generic T0 Cash             | 当前范围完成    | Durable Long 生命周期闭环                           | 非 Long、非 Cash 场景                |
| CN A-share Cash             | 部分完成      | T+1、涨跌幅、整手、费用基础存在                             | 正式 Runtime 纵切面                  |
| Futures / Margin            | 部分完成      | 领域模型和部分旧路径存在                                  | 统一 Durable Transaction          |
| Strategy API                | 基础完成      | 受限 Context 和订单接口可用                            | 生命周期和 Live 场景扩展                 |
| Factor                      | 基础完成      | Time-Series 基础链路可用                            | IC、分组、横截面研究产品                   |
| Indicator                   | 基础完成      | Registry、依赖和 Warmup 可用                        | 大规模向量化和研究缓存                     |
| Risk                        | 基础完成      | Pre-Trade、Reservation、Active Count 可用         | Portfolio Risk、强平、动态限额          |
| Order                       | 当前范围完成    | 状态机、Partial Fill、Terminal 完成                  | Replace、复杂 TIF                  |
| ExecutionProcessor          | 当前范围完成    | Broker Update 到 Durable Transaction 完成        | 非当前 Capability 范围               |
| Trade Planner               | 当前范围完成    | 纯规划和经济不变量完成                                   | 更多市场产品规则                        |
| Durable Transaction         | 当前范围完成    | Fill 与 Terminal 独立持久化                         | 通用 Non-Trade Operation          |
| Position                    | 当前范围完成    | 精确成本、增减仓、恢复完成                                 | Short、Hedging、Lot Selection     |
| Allocation                  | 当前范围完成    | Cluster 归属和精确成本完成                             | Cross-Cluster 和 Unallocated     |
| Close Cost Authority        | 当前范围完成    | Allocation 是归因权威，Position 是聚合权威               | 当前明确不支持无归属平仓                    |
| Account                     | 当前范围完成    | Cash、Fee、PnL、Equity 可用                        | Margin、多币种、Broker 对账            |
| Strategy Ledger             | 当前范围完成    | Cluster 级现金和收益归因可用                            | 动态资本池                           |
| Fee                         | 基础完成      | FILL 和 ORDER_CUMULATIVE 支持                    | 完整 A 股费用版本治理                    |
| Settlement                  | 基础完成      | Cash Settlement Instruction 可用                | 真实市场完整结算链                       |
| Virtual Broker              | 当前范围完成    | Next-Bar、Fill Plan、Checkpoint 完成              | 订单簿和流动性模型                       |
| Broker SPI                  | 稳定        | Core 与具体插件分离                                  | 更多正式 Adapter                    |
| Persistence                 | 当前范围完成    | Memory、SQLite、Schema 3 可用                     | Schema Migration、远程 Store       |
| Checkpoint                  | 当前范围完成    | Runtime Participant Checkpoint 可用             | Paper/Live Checkpoint           |
| Recovery                    | 当前范围完成    | Commit、Projection、Outbox、Restart 覆盖           | 生产环境恢复和远程基础设施                   |
| Scenario Framework          | 基础完成      | Parser、Runner、Assertion、Artifact 可用           | 完整市场 Pack                       |
| Result Collector            | 基础完成      | Projection Ready Fact 为结果权威                   | 大规模结果压缩                         |
| Analytics                   | 基础完成      | 收益、回撤、交易和 Exposure 基础统计                       | 高级风险和归因                         |
| Artifact                    | 基础完成      | JSON、Parquet、Manifest 和 Fingerprint           | 大规模数据输出优化                       |
| Report                      | 基础完成      | Console、JSON、Markdown 可用                      | 图表和交互报告                         |
| CLI                         | 基础完成      | Engine 产品入口可调用                                | 应用服务和任务管理                       |
| Web / API                   | 未完成       | 尚未形成产品                                        | REST、SSE、权限、控制台                 |
| Test Suite                  | 覆盖强、性能待治理 | 单元、集成、恢复和架构测试较完整                              | 分层、Fixture 复用、执行速度              |
| CI                          | 状态未确认     | 当前最新提交未发现关联 Workflow Run                      | 建立可验证的分层 CI                     |

---

## 4. 核心架构状态

### 4.1 Engine

`OnlyEngine` 已经是唯一产品级入口，负责：

```text
Cluster 注册
配置校验
Runtime 分组
Runtime 装配
生命周期管理
运行结果汇总
Artifact 和 Report
失败回滚
```

当前结论：

```text
状态：稳定
建议：不再创建第二套 Engine 或 Market 专用入口
```

---

### 4.2 Runtime

Runtime 是全部可变交易状态的所有者，包括：

```text
Clock
Event Bus
MarketData
Order
Position
Allocation
Account
Strategy Ledger
Risk
ExecutionProcessor
Settlement
Persistence
Checkpoint
Recovery
```

当前只有 Backtest Runtime 完成产品闭环。

```text
BACKTEST  : 当前范围完成
PAPER     : 部分完成（产品验收仍未通过）
LIVE      : 未完成
SHADOW    : 未完成
RESEARCH  : 部分完成
```

---

### 4.3 Cluster

Cluster 已实现：

```text
一个 Cluster 一个 Strategy
独立 Factor/Indicator Scope
独立 Ledger Scope
受限 Runtime Context
多 Cluster 确定性调度
```

Cluster 不持有 Runtime Manager，不直接访问 Broker、EventBus 或其他 Cluster 私有状态。

---

## 5. Durable Execution 状态

当前正式支持：

```text
GENERIC_T0_CASH
LIMIT
LONG
NETTING
BUY OPEN
SELL CLOSE
```

已经完成：

```text
Partial Fill
Multi-Fill
Same-Bar Multi-Fill
Cross-Bar Multi-Fill
Durable Fill Identity
Per-Order Fill Index
Prepared Transaction
Committed Transaction
Ordered Projection
Projection Ready
Durable Outbox
Cancel / Reject / Expire Terminal Transaction
Duplicate Idempotency
Conflict Fail Closed
Checkpoint / Restart
```

不可破坏的合同：

```text
一个 Fill
=
一个不可变 Prepared Transaction
=
一个 Committed Transaction
```

Terminal Operation：

```text
ORDER_TERMINAL
```

不伪造 Trade ID，也不计入 Trade Result。

---

## 6. Multi-Cluster Close Cost Authority

当前正式模型：

```text
Allocation
=
某个 Cluster 对仓位数量和成本的归属权威

Position
=
Account 对所有 Allocation 的聚合权威
```

某个 Cluster 平仓时：

```text
Order Cluster
→ 定位 Allocation
→ Allocation 计算唯一 released cost
→ Position 消费相同 released cost
→ 只计算一次 realized PnL
→ Account、Ledger、Fact 消费同一结果
```

必须成立：

```text
Position Quantity
=
sum(Allocation Quantity)

Position Cumulative Cost
=
sum(Allocation Cumulative Cost)

Position Released Cost
=
Allocation Released Cost
=
Fact Released Cost

Position PnL Delta
=
Allocation PnL Delta
=
Account PnL Delta
=
Ledger PnL Delta
=
Fact PnL Delta
```

当前明确不支持：

```text
Unallocated Position Close
Cross-Cluster Close
FIFO/LIFO Lot Selection
Short/Hedging Cost Attribution
Multi-Currency Cost Attribution
```

---

## 7. 数据和市场规则状态

### 数据

当前已完成：

```text
Synthetic Historical Data
Bar Replay
Exact Cursor
基础 Cache
Tushare 日线基础接入
```

当前未闭环：

```text
复权
公司行为
停牌数据
历史证券状态
参考数据版本
大规模回放验收
```

### A 股规则

当前已有基础：

```text
CN_A_SHARE_CASH@2025.1
T+1 Instruction
Long-only
基础涨跌幅
ST/板块差异
整手
零股清仓
基础费用
```

仍需完成：

```text
Profile 正式驱动完整 Runtime
停牌
涨跌停订单与撮合差异
完整申报规则
跨 Fill 最低佣金
完整 effective reference、历史 ST 与停牌数据
Checkpoint/Restart 验收
```

---

## 8. 测试体系状态

统一测试入口为 `uv run python scripts/test_suite.py <lane>`，其中 lane 为 `fast`、`integration`、`ashare`、
`recovery`、`miniqmt-contract`、`miniqmt-local`、`full` 或 `release`。默认离线通道不会访问网络、本地 MiniQMT 或真实账户；
具体 Marker、前置条件和性能报告见 [测试规范](docs/testing.md)。

测试已形成 Fast、Integration、A-share、Recovery、MiniQMT Contract、Full 和 Release 分层，并建立固定 Result Fixture、
只读 Recovery SQLite Baseline 与真实 MiniQMT 冻结 Bar。默认离线通道不依赖 Windows、`xtquant` 或 QMT 客户端。

当前边界：

```text
下游纯组件优先复用不可变 Result Fixture
Recovery 故障用例复制独立只读模板，不共享可写 SQLite
MiniQMT Golden v1 只包含未复权历史 Bar
历史 ST、停牌与 effective reference 尚未形成正式 Authority
MiniQMT 真实查询与真实订单分别由本地串行 Gate 和手动 Order Gate 管理
```

当前正式分层：

```text
Fast
Integration Smoke
Full Offline
Recovery / Exhaustive
External
```

测试优化必须遵守：

```text
不删除业务覆盖
不放宽经济不变量
不添加生产 test_mode
不隐藏 Close Execution
不以 skip/xfail 代替修复
```

---

## 9. 下一步推荐

### P0：Test Suite Performance and Layering

已完成：

```text
统一 Runner、Metrics 与 CI Lane
不可变 Result Fixture 与 Recovery Baseline 复用
MiniQMT Golden Dataset 离线纵切面
Worker Matrix 与性能软回归比较
```

### P1：PR4.5 CN A-share Cash Product Closure

目标：

```text
T+1
涨跌停
停牌
整手和零股
A 股费用
真实离线样本
完整 Scenario Pack
Checkpoint/Restart
```

### P2：真实数据与公司行为

目标：

```text
Raw / Adjusted Price 分离
分红
送股
拆并股
证券状态
参考数据版本
大规模历史回放
```

### P3：Research Workflow

目标：

```text
因子实验
IC
分组分析
批量参数
结果比较
绘图
```

### P4：Paper / Live

只有在以下条件满足后进入：

```text
A 股 Cash 产品闭环
真实数据闭环
测试执行时间可控
订单同步和对账模型冻结
```

---

## 10. 最终判断

当前 OnlyAlpha 可以准确描述为：

```text
一个以 OnlyEngine 为唯一入口、
具备确定性 Backtest、
Durable Cash Long Execution、
Multi-Fill Recovery、
Multi-Cluster 成本归因、
标准结果和制品输出能力的 Alpha 阶段量化交易系统。
```

不能描述为：

```text
生产级实盘平台
完整多市场交易平台
完整中国期货平台
完整研究平台
完整 Web 交易系统
```
