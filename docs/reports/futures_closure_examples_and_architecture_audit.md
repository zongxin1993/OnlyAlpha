# Futures Closure、Examples 与全局架构修改前审计

> 审计日期：2026-07-20（Asia/Shanghai）  
> 审计基线：Core `94dbdd3`、Examples `9dca95f`、Plugins `1a74f18`、Workspace `b3297c2`  
> 结论：本报告描述编码前事实，不代表任何门禁已经通过。

## 1. 审计范围与方法

本次从 Workspace 根目录核对四个仓库的生产源码、公开导出、配置模型、组合根、测试、版本约束和子模块状态。重点读取了
Core 的 Engine/Runtime、Order/Risk、Broker/Execution、Position/Allocation、Account、Settlement、Margin、Result、Scenario、
Market Profile/Rule Engine/Conformance，以及 Examples 和 Plugins 的全部生产目录。当前 Core 有 347 个 Python 生产文件；
Examples 有两个 Strategy family、两个 Factor family 和四组产品示例；Plugins 有 MiniQMT、Tushare 两个独立包。

## 2. Futures Order → Position → Margin → Account 当前链路

当前正式订单链为：

```text
Strategy Context orders.submit
→ OnlyOrderService
→ OnlyRiskService / OnlyMarketRuleEngine.evaluate_pre_trade
→ Risk Reservation + Cash/Position Reservation
→ OnlyBrokerExecutionService
→ OnlyVirtualBrokerGateway
→ Runtime Broker Inbound Queue
→ OnlyExecutionProcessor
→ Order / Position / Allocation / Strategy Ledger / Account
```

其中 Market Rule Engine 已能从 `GENERIC_MARGIN_FUTURES` Profile 编译 HEDGING、Short、10% 初始保证金、8% 维持保证金、
每手费用和合约乘数规则，也能产生 Position/Settlement/Margin/Fee/Cash Instruction。然而正式执行链仍把成交硬编码为：

```text
BUY  → LONG + OPEN
SELL → LONG + CLOSE
```

`OnlyPositionTrade` 明确拒绝 `SHORT`；Position 与 Allocation 实体把 BUY 固定为增加、SELL 固定为减少；Runtime 的成交校验也
只接受 LONG。因此 `SELL OPEN → SHORT` 和 `BUY CLOSE → SHORT 减少` 在修改前不能经过正式 Engine 完成。

`OnlyMarginManager` 和 `OnlySettlementManager` 已存在独立 Instruction 驱动实现，但未装配进 Runtime Services，也未被
ExecutionProcessor 调用。Account 仍以 Cash Account 为唯一生产实现，不维护 reserved/occupied/released margin。因此当前
Futures Position、Margin、Account 不是一个闭合事务链。

## 3. Risk Reservation 生命周期

当前存在四类独立状态：

- `OnlyRiskReservationManager`：Order exposure reservation；
- `OnlyAccountReservationManager`：BUY cash reservation；
- `OnlyPositionReservationManager`：SELL close position reservation；
- `OnlyMarginManager`：独立保证金状态，但尚未装配到订单/成交生命周期。

Order Service 在创建后依次建立 Risk、Position、Cash Reservation；ExecutionProcessor 在 Accepted、Rejected、Cancelled、Trade
更新上协调消费和释放。部分成交能消费 Risk/Cash/Position 的相应部分，终态会释放剩余量。Runtime 收口已有
`NO_ACTIVE_RISK_RESERVATION` 不变量，但没有覆盖 Margin Reservation，也没有一个统一的正常关闭策略证明所有活动订单及
四类 Reservation 都已解释。期货 SELL OPEN 还会错误进入 Position Reservation，而不是 Margin Reservation。

## 4. ExecutionProcessor 事务应用顺序与失败策略

修改前 Trade 路径实际顺序为：

```text
Validate / Deduplicate
→ Order.apply_fill
→ Position.apply_trade
→ Allocation.apply_trade
→ StrategyLedger.apply_trade_accounting
→ Account.apply_trade_cash_flow
→ Cash/Position/Risk Reservation consume/release
→ Invariant check
→ buffered facts commit
```

Position 与 Allocation 修改发生后若后续失败，不执行隐式补偿；Processor 丢弃成功事实、记录 Audit steps、将 Scope 标记为
RECONCILING，并写入 Reconciliation Queue。这是显式的失败一致性策略，但不是数据库原子事务。修改前缺少 Settlement、Margin、
Fee Manager 和 Account Margin 在上述固定顺序中的正式步骤，因此尚不能满足期货事务一致性门禁。

## 5. Settlement、Margin、Fee 标准事实来源

- Settlement：`OnlySettlementManager.records` 有 Instruction 驱动记录，但 Runtime 未装配；现有 Position T+1 使用另一条
  `OnlySettlementService` 路径，Collector 没有投影正式 Settlement Fact。
- Margin：`OnlyMarginManager.records` 有 reserve/occupy/release 状态记录，但未接入 Order/Execution/Account/Collector。
- Fee：Market Rule Engine 能产生 `OnlyFeeInstruction`；Broker Fill 也携带 fee，ExecutionProcessor 把 fee 写入 Position、Ledger、
  Account，但没有独立 Fee Manager/标准 Fee Fact。
- Collector：`OnlyBacktestResultCollector` 已收集 Order、Execution、Position、Account、Equity、Signal 等事实，但明确尚未收集
  profile timeline、compiled rules、market decision、settlement、margin、fee、scenario action。

因此修改前这三类事实均不能作为 Scenario Assertion 的正式来源；Assertion 若自行推导将违反边界。

## 6. 五个 Conformance Pack 当前运行状态

| Pack | 修改前状态 | 证据缺口 |
| --- | --- | --- |
| `CN_A_SHARE_CASH` | 未定义、未运行 | 无正式 Engine Scenario、Coverage、Pack Artifact |
| `GENERIC_T0_CASH` | 未定义、未运行 | 同上 |
| `GENERIC_MARGIN_FUTURES` | 未定义、未运行 | Futures 内核链未闭合 |
| `GENERIC_24X7_CRYPTO_SPOT` | 未定义、未运行 | 无正式 Engine Scenario |
| `CROSS_VERSION` | 未定义、未运行 | 无跨版本 Scenario/Timeline |

修改前 `onlyalpha.market.conformance` 只有 Pack/Scenario identity、内存 Registry 和基于“声明场景 capability”的静态检查。
它没有 Scenario Runner、Run Result、基于 PASSED evidence 的 Coverage、Pack fingerprint/artifact、Stability Evaluator、Release Gate、
Application Service、Repository、Query DTO 或 CLI。四个内建 Profile 全部为 `EXPERIMENTAL`。

## 7. 正式 Scenario 定义清单

修改前生产源码中没有任何注册的、可运行的 built-in Scenario Definition。`onlyalpha.scenario` 仅有：

- immutable Scenario document model；
- strict YAML/JSON parser；
- BACKTEST-only capability planner；
- runtime-neutral command projection；
- read-only assertion engine；
- input fingerprint。

尚不存在 Definition Repository、Exact DataSource、Action Strategy、OnlyEngine Runner、Standard Fact Projection、Scenario Artifact。
因此 `CN_A_SHARE_T1_ENGINE@1.0`、`GENERIC_T0_CASH_ENGINE@1.0`、`GENERIC_MARGIN_FUTURES_ENGINE@1.0`、
`GENERIC_CRYPTO_SPOT_ENGINE@1.0`、`CROSS_PROFILE_VERSION_ENGINE@1.0` 以及四个 Futures 边界场景修改前均不存在。

## 8. OnlyAlpha-examples 当前示例清单

修改前 Examples 没有根 README，也没有 `market_scenarios` 或 Conformance 示例。现有产品示例为：

- `examples/results_framework_demo`；
- `examples/tushare_daily_backtest`；
- `examples/miniqmt_real_history_backtest`；
- `examples/clusters/macd` 与 `examples/clusters/macd_fast` 配置。

生产扩展包括 MACD Strategy、Fixed Round Trip Strategy、MACD Signal Factor、Bar Count Factor。现有测试只覆盖 Results Framework
相关路径；没有 Definition coverage、逐 Scenario smoke、run-all、Pack、Artifact、Fingerprint、禁止私有导入或禁止网络测试。

## 9. Core、Examples 和 Plugins 版本约束

- Core package：`onlyalpha==0.2.4`；
- Examples package：`onlyalpha-examples==0.1.0`，依赖 `onlyalpha>=0.1,<0.2`，与当前 Core 不兼容；
- MiniQMT plugin：`0.1.0`，依赖 `onlyalpha>=0.1.0`，上界和当前公共 API 代际不明确；
- Tushare plugin：`0.1.0`，依赖 `onlyalpha>=0.1.0`，同样缺少准确上界；
- Workspace：`0.1.0`，以 uv workspace path 绑定 Core 和 MiniQMT，`uv.lock` 尚未对本任务后的版本重新生成。

修改前执行 `UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run pytest -q` 在 workspace dependency resolution 阶段失败：测试 fixture
包 `onlyalpha-test-plugin` 依赖名称与 workspace member `onlyalpha` 产生 shadow/cycle，尚未进入 pytest。这是 Workspace 门禁的
真实初始缺陷，不能记录为测试失败或通过。

## 10. Plugins 对 Core 公共接口的依赖

MiniQMT 与 Tushare 均通过 Core 的 `onlyalpha.plugin.api`、Plugin descriptor/lifecycle、DataSource/Broker SPI 以及公开 Domain DTO
接入。MiniQMT callback 负责标准化 Broker update 并入队；Tushare 只提供历史 DataSource。Core 不反向依赖 Plugins。

需在 Core 公共接口迁移后验证：

- 两个 package 的完整 pytest、Ruff、Mypy、format；
- 无 Runtime Manager/ExecutionProcessor/Position Manager 等 concrete private import；
- version constraint 与 Core 当前正式版本对齐；
- vendor SDK 继续 lazy import，测试不要求真实 SDK 或网络。

## 11. 全局生产组件清单（修改前分类）

| Repository | Component groups | State owner / entry |
| --- | --- | --- |
| Workspace | uv workspace、lock、submodule pin | `pyproject.toml` / `uv.lock` / `.gitmodules` |
| Core CLI/Application | CLI、Engine exporter、user-data layout | `onlyalpha` CLI / `OnlyEngine` |
| Core Config/Plugin | Cluster document、typed config、SPI、discovery/registry | Composition Root |
| Core Engine/Runtime | Engine、planner、assembler、Backtest/Paper/Live/Shadow/Research | Engine/Runtime session |
| Core Clock/Event | Backtest clock、clock view、timer、EventBus | Runtime |
| Core Data/Market Data | sources、queue、processor、replay、cache、pipeline、snapshot、dispatcher | Runtime |
| Core Cluster/Indicator/Factor/Strategy | cluster lifecycle、fixed pipeline、read-only contexts | Cluster / component registry |
| Core Market | profile、registry、compiler、rule engine、restricted ports | Registry / Rule Engine |
| Core Order/Risk | request/state/service、risk pipeline、reservation/audit | Runtime managers |
| Core Broker/Execution | Broker SPI、Virtual Broker、inbound update、ExecutionProcessor | Broker external state / Runtime local state |
| Core Position/Allocation/Ledger | account position、cluster allocation、strategy virtual ledger | dedicated managers |
| Core Account/Settlement/Margin | cash account、position settlement、instruction managers | dedicated managers, partly unassembled |
| Core Collector/Result/Analytics/Artifact/Report | standard facts、analytics、atomic writer、renderers | read-only completed-run facts |
| Core Scenario/Conformance | parser/planner/assertion skeleton、pack identity skeleton | no production runner yet |
| Examples | strategies、factors、product configs | public Core consumer |
| Plugins | MiniQMT DataSource/Broker、Tushare DataSource | Core SPI implementations |

完整逐模块 Inventory 将在阶段三基于源码生成，本节只记录修改前组件分组，不能替代最终 Inventory。

## 12. 需要删除或迁移的旧接口与重复实现

修改前审计发现以下当前源码兼容面与“只保留正式路径”冲突，需在实现过程中删除并迁移调用方：

- `OnlyBacktestRuntime` 的 legacy constructor 与 `process_bar` compatibility facade；
- `OnlyCancelRequest` 对 `OnlyCancelOrderRequest` 的重复别名；
- `OnlyMarginProcessor`、`OnlySettlementProcessor` 对 Manager 的重复别名；
- Domain enum、Clock、Calendar、Event 中仍标记为 Compatibility 的重复拼写/入口；
- 测试 fixture 目录名 `legacy_macd` 与当前正式 Config 语义不符，应迁移到当前产品 fixture 名；
- 文档中“Long-only first phase”“Futures 尚未接入”等完成后会过时的描述；
- 静态 Conformance `covered_capabilities` 不能继续作为正式 Coverage evidence，必须由 Scenario PASSED 结果取代。

历史 ADR 与审计报告保留；生产源码、当前测试、Examples 和现行文档不得继续依赖同义兼容路径。

## 13. 修改前门禁结论

本组合任务在修改前明确未完成。主要硬缺口为 Futures SHORT/Position/Margin/Account 事务链、标准 Settlement/Margin/Fee facts、
Cross-Version、五 Pack、Conformance 产品面、全量 Examples、版本/Workspace 对齐、三仓门禁以及全组件 Inventory/Mindmap/UML。
后续实现必须按阶段一、阶段二、阶段三顺序推进；任何部分结果都不能被描述为本组合任务完成。
