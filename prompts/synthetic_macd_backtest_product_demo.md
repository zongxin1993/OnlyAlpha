# OnlyAlpha 合成数据源与 MACD 完整回测成品 Demo 任务

## 1. 任务定位

本任务不是新增独立领域组件，也不是编写一次性测试脚本。

本任务目标是：

> 使用当前 OnlyAlpha 已实现的正式接口，构建一个接近实际项目成品使用方式的完整 MACD 回测 Demo，并通过该 Demo 验证当前所有已实现组件能否形成稳定、确定、可复用的回测闭环。

本任务必须以“最终用户如何实际使用 OnlyAlpha”作为设计标准。

Demo 不得通过手工创建和逐个调用 Manager 来模拟流程。

最终使用方式应接近：

```python
config = OnlyBacktestConfig.load("config.yaml")

runtime = OnlyBacktestRuntime.from_config(config)
result = runtime.run()

result.save("output/")
```

或符合当前工程已有正式 API 的等价形式。

---

# 2. 项目身份

OnlyAlpha 是完全独立、从零设计的量化交易系统。

本任务只依据：

```text
AGENTS.md
docs/
docs/adr/
当前 OnlyAlpha 代码
当前已批准架构
```

禁止：

* 参考其他工程；
* 引入历史兼容逻辑；
* 为 Demo 建立与正式工程不同的接口；
* 复制一套测试专用运行架构；
* 绕过现有 Runtime、Context、DataSource、Broker 或 Processor。

---

# 3. 核心目标

本任务必须完成以下完整流程：

```text
合成历史数据源
→ 历史数据回放
→ Backtest Clock
→ MarketData Processor
→ MarketData Pipeline
→ Bar Cache / Aggregation
→ MACD Indicator
→ Immutable Snapshot
→ MACD Strategy Cluster
→ ctx.orders.submit()
→ Risk
→ Order
→ ExecutionService
→ VirtualBroker
→ MatchingEngine
→ Broker Update Queue
→ ExecutionProcessor
→ Position
→ Position Allocation
→ Strategy Ledger
→ Account
→ Final Backtest Result
```

所有组件必须通过正式固定接口连接。

---

# 4. Demo-First 长期规则

从本任务开始，OnlyAlpha 的整体 Demo 应采用接近实际成品工程的书写方式。

以后 Demo 必须遵守：

```text
配置驱动
正式 Runtime 入口
正式 DataSource Port
正式 Context API
正式 Broker Port
正式 ExecutionProcessor
正式 Snapshot 和 Result
明确输出目录
可重复运行
可自动测试
```

禁止：

```text
Demo 中直接 new 十几个 Manager
Demo 中直接修改 Manager 内部状态
Demo 中手工按顺序调用 Position/Ledger/Account
Demo 中绕过 Runtime Queue
Demo 中绕过 Risk
Demo 中直接构造最终 Snapshot
Demo 中使用与生产 API 不同的便捷旁路
Demo 中使用无法固定的随机行为
```

测试可以注入配置和 Fixture，但不能建立第二套架构。

---

# 5. 执行前必须阅读

开始前必须阅读：

```text
AGENTS.md

docs/architecture.md
docs/architecture_principles.md
docs/integration_vertical_slice.md
docs/testing.md

docs/domain_model.md
docs/instrument_model.md
docs/time_model.md
docs/clock.md

docs/market_data_source.md
docs/historical_data_source.md
docs/historical_replay.md
docs/market_data_pipeline.md

docs/runtime.md
docs/runtime_context.md
docs/cluster.md

docs/order.md
docs/risk.md
docs/position.md
docs/strategy_ledger.md
docs/account.md

docs/broker_gateway.md
docs/virtual_broker.md
docs/execution_processor.md

docs/adr/
```

检查当前是否已经存在：

```text
OnlyBacktestRuntime
OnlyBacktestConfig
OnlyBacktestResult
OnlyHistoricalDataSource
OnlyHistoricalReplayService
OnlyMarketDataProcessor
OnlyMacdIndicator
OnlyVirtualBrokerGateway
OnlyExecutionProcessor
```

如果已有同语义类型，必须复用，不得重复定义。

---

# 6. 先进行回测能力差距分析

创建：

```text
docs/reports/synthetic_macd_backtest_gap_analysis.md
```

至少分析：

## 6.1 正式回测入口

检查当前是否可以通过一个正式入口运行：

```python
runtime = OnlyBacktestRuntime.from_config(config)
result = runtime.run()
```

如果当前只能通过：

```text
OnlyIntegrationEnvironment
手工装配
测试 Fixture
直接调用多个 Manager
```

则必须列出缺口。

## 6.2 当前数据链

检查是否为：

```text
HistoricalDataSource
→ HistoricalReplayService
→ BacktestClock
→ MarketDataProcessor
→ MarketDataPipeline
```

不得存在：

```text
Runtime 直接读取 DataFrame
Demo 直接调用 Pipeline
测试直接调用 Cluster
```

## 6.3 当前成交链

检查是否为：

```text
Order
→ Risk
→ VirtualBroker
→ Broker Update Queue
→ ExecutionProcessor
```

不得手工调用：

```text
OrderManager.apply_fill()
PositionManager.apply_trade()
LedgerManager.apply_trade()
```

## 6.4 当前结果输出

检查是否已有统一：

```text
OnlyBacktestResult
OnlyBacktestReport
```

并列出缺失字段。

完成差距分析后再开始实现。

---

# 7. 合成历史数据源

实现或完善：

```text
OnlySyntheticHistoricalDataSource
```

它必须实现当前正式：

```text
OnlyHistoricalDataSource
```

接口。

不得设计成测试专用 Helper。

## 7.1 配置类型

建议：

```text
OnlySyntheticHistoricalDataSourceConfig
OnlySyntheticInstrumentDataConfig
OnlySyntheticPriceScenario
OnlySyntheticPriceSegment
OnlySyntheticVolumeModel
OnlySyntheticNoiseModel
```

所有公开类型使用 `Only` 前缀。

## 7.2 注册信息

数据源根据注册信息生成数据：

```text
source_id
data_version
instrument
trading_calendar
trading_sessions
bar_type
start_time
end_time
initial_price
price_tick
quantity_increment
volume_model
price_segments
random_seed
```

时间必须为 UTC。

交易时段必须来自：

```text
OnlyTradingCalendar
OnlyTradingSession
```

午间休市、非交易日和节假日不得生成 Bar。

## 7.3 输出类型

必须输出正式：

```text
OnlyBarUpdate
```

并保留：

```text
source_id
source_sequence
data_version
ts_event
ts_init
quality_flags
```

不得直接输出普通字典或 DataFrame 作为核心接口。

---

# 8. 合成价格模型

第一版不要仅实现随机游走。

必须支持可配置的确定性分段行情：

```text
FLAT
UPTREND
DOWNTREND
OSCILLATION
GAP_UP
GAP_DOWN
VOLATILITY_EXPANSION
VOLATILITY_CONTRACTION
```

建议每个 Segment 包含：

```text
segment_type
duration_bars
start_price
end_price
amplitude
cycle_length
volatility
volume_multiplier
```

允许附加固定随机种子噪声，但：

* 同一配置和 Seed 必须完全一致；
* 噪声不得破坏主要预期信号；
* 主验收场景应允许关闭噪声；
* 不得根据策略状态修改未来行情。

---

# 9. OHLCV 生成规则

生成的 Bar 必须满足：

```text
high >= open
high >= close
low <= open
low <= close
high >= low
volume >= 0
```

并满足 Instrument：

```text
price_increment
quantity_increment
lot_size
```

所有价格和数量使用正式强类型，不使用裸 float。

同一配置重复生成时，以下内容必须一致：

```text
OHLCV
source_sequence
update_id
data_version
时间戳
质量标记
```

---

# 10. MACD 指标

优先复用当前 Indicator Pipeline。

如果尚未实现 MACD，则实现：

```text
OnlyMacdIndicator
OnlyMacdIndicatorConfig
OnlyMacdSnapshot
```

参数：

```text
fast_period
slow_period
signal_period
price_field
warmup_bars
```

MACD 应由 MarketData/Indicator Pipeline 在策略回调前完成更新。

策略读取：

```python
macd = ctx.market_data.indicator(
    instrument_id=instrument_id,
    indicator_id=macd_indicator_id,
)
```

或当前工程已批准的等价正式接口。

禁止策略内部建立另一套通用指标引擎。

必须保证：

* 只使用已经闭合的 Bar；
* 不读取未来数据；
* Warmup 未完成时状态明确；
* 同一输入结果确定；
* Decimal/强类型语义正确。

---

# 11. MACD 示例策略

实现：

```text
OnlyMacdExampleCluster
OnlyMacdExampleConfig
OnlyMacdSignalState
```

该策略必须是完整、可复用、符合正式 Cluster 接口的示例策略。

不得只是测试函数。

## 11.1 策略配置

至少包括：

```text
cluster_id
account_id
instrument_id
primary_bar_type
macd_indicator_id
trade_quantity
warmup_bars
allow_reentry
exit_mode
```

## 11.2 交易逻辑

推荐：

```text
上一周期 DIF <= DEA
当前周期 DIF > DEA
且自身无仓位
→ 提交买单
```

```text
上一周期 DIF >= DEA
当前周期 DIF < DEA
且自身存在可卖仓位
→ 提交卖单
```

卖出数量：

```text
min(
    configured_exit_quantity,
    ctx.positions.cluster.available_quantity
)
```

不得使用账户总仓位代替 Cluster Allocation。

## 11.3 策略只能使用 ctx

允许：

```python
ctx.clock
ctx.market_data
ctx.instruments
ctx.orders
ctx.risk
ctx.positions
ctx.ledger
ctx.accounts
ctx.logger
```

禁止：

```python
ctx.order_manager
ctx.position_manager
ctx.strategy_ledger_manager
ctx.account_manager
ctx.event_bus
ctx.broker_gateway
ctx.execution_processor
```

## 11.4 策略不能假设立即成交

提交订单后：

* 不直接修改内部持仓标记为已成交；
* 通过 Snapshot 获取真实状态；
* 防止订单未完成时重复下单；
* 可以查询自己的 Open Order；
* 订单状态以 OrderManager Snapshot 为准。

---

# 12. T+1 行为

主回测场景使用 A 股或 ETF 的正式市场规则。

不得在策略中写：

```python
if is_t1:
    ...
```

策略只查询：

```text
Cluster Available Quantity
```

T+1 由：

```text
SettlementRule
Position Bucket
Position Reservation
Risk
SettlementService
```

共同实现。

至少增加一个专门场景：

```text
第一交易日买入
→ 当日出现死叉
→ Cluster Available Quantity = 0
→ 不允许卖出

下一交易日完成 Settlement
→ 可卖数量恢复
→ 满足退出条件后卖出
```

---

# 13. 正式 Demo 目录

创建：

```text
examples/backtest_macd/
├── README.md
├── config.yaml
├── run.py
├── strategy.py
├── synthetic_market.yaml
├── expected_result.json
└── output/
    └── .gitkeep
```

如果策略示例应放入正式示例包，可调整为：

```text
src/onlyalpha/examples/strategies/macd.py
```

但 `run.py` 必须只负责：

* 读取配置；
* 创建或调用正式 Runtime；
* 执行回测；
* 输出 Result。

不得在 `run.py` 中手工装配业务链。

---

# 14. 配置示例

配置至少包括：

```yaml
runtime:
  runtime_id: macd_backtest_demo
  runtime_type: BACKTEST
  start_time: ...
  end_time: ...
  base_currency: CNY

data_source:
  type: SYNTHETIC
  source_id: synthetic_cn_equity
  data_version: macd-demo-v1
  random_seed: 20260715

instrument:
  instrument_id: TEST.ETF.XSHG
  venue: XSHG
  asset_class: ETF
  timezone: Asia/Shanghai
  trading_calendar: CN_XSHG
  settlement_rule: CN_EQUITY_T_PLUS_1

bars:
  primary: 1m

strategy:
  type: OnlyMacdExampleCluster
  fast_period: 12
  slow_period: 26
  signal_period: 9
  trade_quantity: "1000"

account:
  initial_cash:
    value: "1000000"
    currency: CNY

broker:
  type: OnlyVirtualBrokerGateway

matching:
  type: NEXT_BAR

commission:
  type: CN_EQUITY

slippage:
  type: NONE
```

字段名称按当前项目配置模型调整。

---

# 15. 正式回测入口

Demo 应优先使用：

```python
config = OnlyBacktestConfig.load(config_path)
runtime = OnlyBacktestRuntime.from_config(config)
result = runtime.run()
```

如果项目当前采用 Assembler：

```python
assembler = OnlyBacktestRuntimeAssembler(...)
runtime = assembler.build(config)
result = runtime.run()
```

也可以接受。

但最终必须形成一个稳定、少量代码的用户入口。

如果当前没有正式 `OnlyBacktestRuntime`，本任务允许补齐最小正式入口，但不得重新实现现有组件。

正式 Runtime 应负责：

```text
配置解析
组件装配
生命周期
Replay 启动
运行结束
最终 Snapshot
结果构建
资源关闭
```

---

# 16. OnlyBacktestResult

如果当前缺少统一结果类型，补充：

```text
OnlyBacktestResult
OnlyBacktestRunSummary
OnlyBacktestDataSummary
OnlyBacktestExecutionSummary
OnlyBacktestPerformanceSummary
```

至少包含：

```text
runtime_id
status
start_time
end_time

data_source_id
data_version
generated_bar_count
processed_bar_count
duplicate_count
gap_count

cluster_ids
order_count
rejected_order_count
trade_count

final_positions
final_allocations
final_ledgers
final_accounts

initial_equity
final_equity
realized_pnl
unrealized_pnl
fees
return_since_start
maximum_drawdown

invariant_results
determinism_fingerprint
failure
quality_flags
```

不要在本任务中实现完整研究分析平台。

---

# 17. Result 输出

Demo 至少输出：

```text
output/result.json
output/orders.json
output/trades.json
output/positions.json
output/allocations.json
output/ledgers.json
output/accounts.json
output/equity.csv
output/run_report.md
```

输出通过正式 Result/Exporter 接口完成。

不得在 Demo 中直接读取 Manager 私有字典后自行拼接。

---

# 18. 主验收行情设计

合成行情必须明确设计出可预测的 MACD 信号。

建议至少覆盖三个交易日：

```text
Day 1:
    初始横盘
    逐步上涨
    形成金叉
    策略买入

Day 2:
    继续上涨后转弱
    形成死叉
    卖出或等待可卖条件

Day 3:
    再次形成明确退出机会
    完成平仓
```

主场景关闭随机噪声，确保：

* 信号数量固定；
* 订单数量固定；
* 成交数量固定；
* 最终仓位固定；
* 最终结果可精确断言。

另建固定 Seed 噪声场景做鲁棒性测试。

---

# 19. 完整链路约束

正常场景必须经过：

```text
SyntheticHistoricalDataSource
→ HistoricalReplayService
→ BacktestClock
→ MarketDataProcessor
→ MarketDataPipeline
→ IndicatorPipeline
→ Cluster
→ OrderService
→ RiskService
→ OrderManager
→ ExecutionService
→ VirtualBroker
→ MatchingEngine
→ BrokerInboundQueue
→ ExecutionProcessor
→ PositionManager
→ PositionAllocationManager
→ StrategyLedgerManager
→ AccountManager
→ Final Result
```

禁止在正常场景中：

* 手工构造成交；
* 手工调用各 Manager；
* 直接修改 Reservation；
* 直接修改 Clock；
* 直接构造最终 Result；
* 从合成数据源直接调用 Pipeline；
* 从策略直接调用 Broker。

---

# 20. 自动化测试

建议创建：

```text
tests/examples/test_synthetic_data_source.py
tests/examples/test_macd_indicator.py
tests/examples/test_macd_example_cluster.py
tests/integration/test_synthetic_macd_backtest.py
tests/integration/test_synthetic_macd_t1.py
tests/integration/test_synthetic_macd_replay.py
tests/integration/test_synthetic_macd_product_api.py
```

---

# 21. 合成数据源测试

至少验证：

```text
按交易日历生成
午间休市不生成
非交易日不生成
UTC 时间正确
OHLCV 合法
价格增量合法
数量增量合法
相同 Seed 完全一致
不同 Seed 数据不同
数据版本一致
Sequence 稳定
支持流式读取
```

---

# 22. MACD 测试

至少验证：

```text
Warmup 状态正确
MACD 数值正确
金叉检测正确
死叉检测正确
不使用未来 Bar
重复 Bar 不重复更新
相同输入结果一致
```

MACD 数值应使用独立、小规模、固定输入做精确测试。

---

# 23. 策略测试

至少验证：

```text
Warmup 前不交易
金叉提交买单
死叉提交卖单
无仓位不卖
存在未完成买单时不重复买
存在未完成卖单时不重复卖
只读取自身 Allocation
使用 ctx.orders
不访问 Manager
不假设立即成交
```

---

# 24. 完整回测测试

必须验证：

```text
Runtime 正常启动和完成
数据源通过 ReplayService
Clock 只由 ReplayService 推进
MarketData 全部经过 Processor
MACD 在回调前完成
策略回调次数正确
订单经过 Risk
成交来自 VirtualBroker
Broker Update 经过 ExecutionProcessor
Position 正确
Allocation 正确
Ledger 正确
Account 正确
T+1 正确
Fee 正确
最终 Result 正确
```

---

# 25. 关键不变量

最终至少检查：

```text
Account Position
=
Allocation Sum
+
Unallocated Position

Cluster 不能使用其他 Cluster Allocation

Strategy Ledger 使用自身 Allocation 成本

Strategy Cash View
=
Strategy PnL View

Account Equity
=
Account Cash
+
Account Position Market Value
-
Liabilities

订单成交数量不超过订单数量

Reservation 不为负

Reservation 不重复消费或释放

重复数据不重复触发策略

重复 Broker Update 不重复记账

Snapshot 不包含未来数据

所有时间为 UTC

相同输入得到相同结果
```

---

# 26. 确定性重放

相同：

```text
config.yaml
synthetic_market.yaml
random_seed
Instrument
Calendar
Strategy Config
Risk Config
Broker Config
Matching Config
```

至少重复运行 100 次。

比较：

```text
生成 Bar
MarketData Audit
Clock 序列
MACD 序列
策略信号
OrderId
TradeId
订单状态
Position
Allocation
Ledger
Account
Event Sequence
Final Result
Determinism Fingerprint
```

必须完全一致。

---

# 27. Product-Style Demo 验收

必须新增一个测试验证最终用户 API：

```python
def test_macd_backtest_product_api() -> None:
    config = OnlyBacktestConfig.load(CONFIG_PATH)
    runtime = OnlyBacktestRuntime.from_config(config)
    result = runtime.run()

    assert result.status is OnlyBacktestStatus.COMPLETED
```

测试中不得手工访问 Manager 完成正常流程。

可以通过 Result 的公开 API 验证最终状态。

---

# 28. README 要求

`examples/backtest_macd/README.md` 至少说明：

1. Demo 目标；
2. 运行环境；
3. 配置文件；
4. 合成行情结构；
5. MACD 策略规则；
6. 正式运行命令；
7. 输出文件；
8. 预期订单和成交；
9. T+1 行为；
10. 确定性说明；
11. 如何替换为 Parquet 数据源；
12. 如何替换策略；
13. 如何替换 Virtual Broker 配置；
14. 已知限制。

README 面向实际使用者，不要写成测试内部说明。

---

# 29. 运行命令

必须提供单一入口：

```bash
python examples/backtest_macd/run.py \
    --config examples/backtest_macd/config.yaml \
    --output examples/backtest_macd/output
```

或当前项目正式 CLI 的等价形式：

```bash
onlyalpha backtest run --config ...
```

优先复用已有 CLI。

---

# 30. 完整历史回归

本任务必须运行所有现有：

```text
Domain
Clock
Runtime
Context
MarketData Source
Historical Replay
MarketData Pipeline
Order
Risk
Virtual Broker
Execution Processor
Position
Allocation
Strategy Ledger
Account
Integration Vertical Slice
```

不得：

* 删除测试；
* Skip 测试；
* 放宽断言；
* 建立 Demo 专用旁路；
* 修改原业务预期掩盖问题。

---

# 31. 文档输出

创建或更新：

```text
docs/examples/synthetic_macd_backtest.md
docs/backtest.md
docs/historical_data_source.md
docs/historical_replay.md
docs/market_data_pipeline.md
docs/cluster.md
docs/runtime.md
docs/testing.md
docs/integration_vertical_slice.md
docs/architecture_principles.md
```

如果当前 `docs/backtest.md` 不存在，则创建。

---

# 32. Architecture Principles 新增规则

加入：

```text
Rule: OnlyAlpha 的正式 Demo 必须使用与实际产品相同的固定接口。

Rule: Demo 不得通过手工装配多个 Manager 模拟产品运行。

Rule: Demo 必须使用正式 Runtime、配置、DataSource、Context、Broker 和 Result API。

Rule: 合成数据源必须实现正式 HistoricalDataSource Port。

Rule: 示例策略必须实现正式 Cluster 接口。

Rule: 完整回测 Demo 必须覆盖数据、策略、订单、风控、执行、仓位、账本和账户全链路。

Rule: 每个关键系统能力应优先通过可运行的 Product-Style Demo 验证。

Rule: Demo 的预期结果必须自动化测试和确定性重放。
```

---

# 33. ADR

创建：

```text
docs/adr/0018-product-style-demo-and-synthetic-backtest.md
```

至少记录：

## 背景

组件单元测试和手工 Integration Fixture 无法完全代表实际用户使用 OnlyAlpha 的方式，需要通过正式接口构建可运行的成品式 Demo。

## 决策

* Demo 使用正式 Runtime API；
* Demo 配置驱动；
* 合成数据源实现正式 HistoricalDataSource；
* 示例策略实现正式 Cluster；
* 完整成交经过 VirtualBroker 和 ExecutionProcessor；
* Demo 输出正式 Backtest Result；
* Demo 同时作为文档、示例和集成验收；
* 后续优先使用实际业务场景 Demo 验证新能力。

## 拒绝方案

* Demo 手工调用多个 Manager；
* Demo 直接构造成交；
* Demo 使用测试专用 Strategy API；
* Demo 绕过 Runtime；
* Demo 与真实项目使用方式不同；
* 只做组件级示例，不验证完整闭环。

---

# 34. 实现顺序

严格按以下顺序：

1. 阅读当前架构和接口；
2. 创建回测能力差距分析；
3. 确认正式 Backtest Runtime 入口；
4. 确认正式 Backtest Result；
5. 设计 Synthetic Source 配置；
6. 实现确定性价格分段模型；
7. 实现 OHLCV 生成；
8. 接入 TradingCalendar；
9. 实现正式 HistoricalDataSource 接口；
10. 补齐或复用 MACD Indicator；
11. 实现正式 MACD Cluster；
12. 创建配置文件；
13. 创建 Product-Style Demo；
14. 运行主确定性场景；
15. 验证完整交易闭环；
16. 增加 T+1 场景；
17. 增加噪声鲁棒性场景；
18. 增加产品 API 测试；
19. 运行所有历史测试；
20. 运行 100 次确定性重放；
21. 输出 Result 和报告；
22. 更新文档；
23. 创建 ADR；
24. 生成最终验收报告。

---

# 35. 最终验收报告

生成：

```text
docs/reports/synthetic_macd_backtest_report.md
```

至少包含：

```text
新增文件
修改文件
正式 Backtest API
Runtime 装配方式
Synthetic DataSource 接口
合成行情配置
交易日历行为
生成 Bar 数量
MACD Indicator
MACD Strategy
Warmup 行为
金叉次数
死叉次数
订单数量
拒单数量
成交数量
T+1 行为
Position 结果
Allocation 结果
Strategy Ledger 结果
Account 结果
费用
最终现金
最终权益
收益
回撤
完整 Vertical Slice
历史测试结果
产品 API 测试
100 次确定性重放
Determinism Fingerprint
已知限制
一票否决项
是否确认具备完整回测核心闭环
```

最终结论只能是：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```

---

# 36. 一票否决项

存在以下任一项，任务必须为 `REJECTED`：

```text
Synthetic Source 未实现正式 HistoricalDataSource

Demo 直接调用 MarketDataPipeline

Demo 直接调用 Cluster

Demo 手工调用多个 Manager

Demo 手工构造成交

成交未经过 VirtualBroker

Broker Update 未经过 ExecutionProcessor

策略直接访问 Manager

策略读取未来数据

MACD 在 Warmup 前交易

T+1 由策略硬编码

使用系统时间

使用未固定 Seed 的随机数据

相同输入结果不同

Demo 无正式配置入口

Demo 无正式 Backtest Result

产品 API 测试无法运行

历史集成场景失败

删除、Skip 或放宽旧测试

引入测试专用旁路
```
