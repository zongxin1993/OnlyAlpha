你现在负责在 OnlyAlpha 三仓 Workspace 中设计并实现正式的：

# OnlyAlpha Results Framework

中文名称：

# OnlyAlpha 结果框架

本任务需要一次性建立以下五个相互解耦但完整贯通的模块：

```text
Result
Collector
Analytics
Artifact
Report
```

最终依赖关系必须为：

```text
Runtime / Cluster / Strategy / Broker
                 │
                 ▼
             Collector
                 │
                 ▼
        OnlyBacktestResult
                 │
       ┌─────────┼──────────┐
       ▼         ▼          ▼
   Analytics   Artifact    Report
                               │
                               ▼
                    CLI / Web / Notebook
```

核心原则：

> Runtime 只负责运行交易系统，不负责生成统计报告。
> Collector 只收集运行事实，不负责业务分析。
> Result 是统一、稳定、不可变的运行结果真值。
> Analytics 只消费 Result，不反向依赖 Runtime。
> Artifact 只负责持久化，不重新计算交易事实。
> Report 只负责面向用户展示，不建立新的数据真值。

---

# 一、Workspace 范围

Workspace 包含：

```text
OnlyAlpha/
OnlyAlpha-plugins/
OnlyAlpha-examples/
OnlyAlpha-workspace/
```

仓库职责：

```text
OnlyAlpha
    核心领域模型
    Engine / Runtime / Cluster
    Result Framework
    Analytics
    Artifact SPI
    Report SPI
    CLI 集成

OnlyAlpha-plugins
    DataSource
    Broker
    其他供应商适配
    不定义通用 Result 和 Analytics

OnlyAlpha-examples
    示例策略
    示例 Factor
    示例配置
    结果框架演示

OnlyAlpha-workspace
    子模块集成
    统一 uv 环境
    统一验收
```

所有公共类型继续遵守命名规则：

```text
Only*
```

不得创建没有 `Only` 前缀的公共类型。

---

# 二、当前系统背景

OnlyAlpha 当前已经具备完整的基础交易纵切面：

```text
OnlyEngine
    ↓
Runtime
    ↓
Cluster
    ↓
Historical DataSource
    ↓
Historical Cache
    ↓
Historical Replay
    ↓
Market Data Pipeline
    ↓
Indicator
    ↓
Factor
    ↓
Strategy
    ↓
Risk
    ↓
Order
    ↓
Virtual Broker
    ↓
Execution
    ↓
Position
    ↓
Strategy Ledger
    ↓
Account
```

目前已经支持：

```text
Synthetic Historical Data
Tushare 日线历史数据
MiniQMT 历史数据
Parquet Historical Cache
Manifest
Fingerprint
CACHE_ONLY
PREFER_CACHE
FORCE_REFRESH
Virtual Broker
基础 Next-Bar 撮合
基础 T+1 持仓语义
MACD 示例策略
单 Cluster
多 Cluster
共享 Runtime 分组
```

当前外部日线 Bar 已经可以正常通过 Market Data Pipeline。

此前存在的：

```text
base input must be 1m
```

限制已经修复。

本任务不得重新引入母线必须为 1 分钟的假设。

---

# 三、当前主要问题

当前一次回测运行结束后，CLI 主要只能看到：

```text
status
run_id
engine_id
cluster_count
failures
determinism_fingerprint
manifest_path
```

当前无法稳定回答：

```text
加载了多少根 Bar？
回放了多少根 Bar？
策略回调了多少次？
Factor 更新了多少次？
产生了多少标准信号？
提交了多少订单？
订单被接受、拒绝、取消和成交的数量是多少？
每笔成交的价格、数量、费用是多少？
最终现金是多少？
最终持仓是多少？
最终总资产是多少？
净值曲线是什么？
最大回撤是多少？
总收益是多少？
每笔完整交易的盈亏是多少？
回测失败时第一个底层异常是什么？
两个相同回测的交易结果是否完全一致？
```

当前部分失败只能显示为：

```text
historical replay failed=N rejected=M
```

底层异常可能被聚合错误遮蔽。

当前还缺少：

```text
统一结果模型
统一事实采集
统一绩效计算
统一结果文件
统一控制台报告
统一结果指纹
```

---

# 四、最终目标

实现以下完整产品链：

```text
Runtime
    ↓
Result Collector
    ├── Bar Facts
    ├── Signal Facts
    ├── Order Facts
    ├── Execution Facts
    ├── Position Facts
    ├── Account Facts
    ├── Equity Facts
    └── Failure Facts
    ↓
OnlyBacktestResult
    ├── Run Result
    ├── Cluster Results
    ├── Strategy Results
    ├── Account Results
    ├── Data Statistics
    ├── Diagnostics
    └── Fact Collections
    ↓
Analytics
    ├── Trade Reconstruction
    ├── Equity Analysis
    ├── Drawdown Analysis
    ├── Return Analysis
    ├── Trading Statistics
    └── Performance Summary
    ↓
Artifact
    ├── summary.json
    ├── diagnostics.json
    ├── data_manifest.json
    ├── orders.parquet
    ├── executions.parquet
    ├── trades.parquet
    ├── positions.parquet
    ├── accounts.parquet
    ├── equity.parquet
    ├── signals.parquet
    └── artifact_manifest.json
    ↓
Report
    ├── CLI JSON
    ├── Console Summary
    └── Markdown Summary
```

本任务完成后，任意回测必须具备：

```text
可观察
可解释
可诊断
可复现
可比较
可审计
```

---

# 五、模块边界

本任务必须实现五个清晰模块。

建议目录结构如下，但应优先遵循当前工程风格：

```text
src/onlyalpha/
├── result/
│   ├── __init__.py
│   ├── models.py
│   ├── identifiers.py
│   ├── enums.py
│   ├── records/
│   │   ├── bar.py
│   │   ├── signal.py
│   │   ├── order.py
│   │   ├── execution.py
│   │   ├── position.py
│   │   ├── account.py
│   │   ├── equity.py
│   │   └── failure.py
│   └── collector/
│       ├── base.py
│       ├── backtest.py
│       ├── state.py
│       └── builder.py
├── analytics/
│   ├── __init__.py
│   ├── trade_builder.py
│   ├── equity.py
│   ├── drawdown.py
│   ├── returns.py
│   ├── statistics.py
│   └── service.py
├── artifact/
│   ├── __init__.py
│   ├── models.py
│   ├── writer.py
│   ├── json_writer.py
│   ├── parquet_writer.py
│   ├── fingerprint.py
│   └── manifest.py
└── report/
    ├── __init__.py
    ├── models.py
    ├── console.py
    ├── json_report.py
    └── markdown.py
```

如果当前工程已有：

```text
storage
output
manifest
result
reporting
```

等类似模块，必须复用或重构，而不是建立重复体系。

---

# 六、开始前必须阅读

完整阅读：

```text
OnlyAlpha/AGENTS.md
OnlyAlpha/HANDOFF.md
OnlyAlpha/ROADMAP.md
OnlyAlpha/README.md
OnlyAlpha/pyproject.toml
```

完整阅读核心模块：

```text
OnlyAlpha/src/onlyalpha/engine/
OnlyAlpha/src/onlyalpha/runtime/
OnlyAlpha/src/onlyalpha/cluster/
OnlyAlpha/src/onlyalpha/event/
OnlyAlpha/src/onlyalpha/clock/
OnlyAlpha/src/onlyalpha/data/
OnlyAlpha/src/onlyalpha/market_data/
OnlyAlpha/src/onlyalpha/strategy/
OnlyAlpha/src/onlyalpha/factor/
OnlyAlpha/src/onlyalpha/indicator/
OnlyAlpha/src/onlyalpha/order/
OnlyAlpha/src/onlyalpha/risk/
OnlyAlpha/src/onlyalpha/broker/
OnlyAlpha/src/onlyalpha/execution/
OnlyAlpha/src/onlyalpha/position/
OnlyAlpha/src/onlyalpha/ledger/
OnlyAlpha/src/onlyalpha/account/
OnlyAlpha/src/onlyalpha/cache/
OnlyAlpha/src/onlyalpha/storage/
OnlyAlpha/src/onlyalpha/config/
OnlyAlpha/src/onlyalpha/plugins/
OnlyAlpha/src/onlyalpha/cli/
OnlyAlpha/tests/
```

阅读插件：

```text
OnlyAlpha-plugins/packages/onlyalpha-plugin-virtual/
OnlyAlpha-plugins/packages/onlyalpha-plugin-tushare/
OnlyAlpha-plugins/packages/onlyalpha-plugin-miniqmt/
```

阅读示例：

```text
OnlyAlpha-examples/examples/tushare_daily_backtest/
OnlyAlpha-examples/examples/
OnlyAlpha-examples/src/onlyalpha_examples/strategies/
OnlyAlpha-examples/src/onlyalpha_examples/factors/
```

重点搜索和确认现有类型：

```text
OnlyEngineRunResult
OnlyRuntimeResult
OnlyClusterResult
OnlyStrategyResult
OnlyRunManifest
OnlyOrderRequest
OnlyOrder
OnlyExecution
OnlyFill
OnlyPosition
OnlyPositionAllocation
OnlyStrategyLedger
OnlyAccount
OnlyCashBalance
OnlyBar
OnlyBarType
OnlyTradingDay
OnlyMoney
OnlyPrice
OnlyQuantity
OnlyRunId
OnlyEngineId
OnlyRuntimeId
OnlyClusterId
OnlyStrategyId
OnlyAccountId
OnlyOrderId
OnlyExecutionId
OnlyOrderRequestId
OnlyJsonValue
OnlyOutputFormat
```

实际代码名称如果不同，以代码为准。

禁止为了匹配本提示词而建立与现有类型重复的同义类型。

---

# 七、实现前分析要求

修改代码前，先输出一份简短但完整的中文分析，至少包括：

## 7.1 当前运行结果链

说明：

```text
CLI
→ OnlyEngine
→ Runtime
→ Cluster
→ Strategy
→ Broker
→ Engine Run Result
→ Manifest
→ CLI JSON
```

每层当前返回什么。

## 7.2 当前事实来源

分别说明以下事实当前存在哪里：

```text
Bar
Signal
Order Request
Order
Order Status
Execution
Position
Cash
Ledger
Account
Runtime Failure
```

## 7.3 当前事件能力

检查 Event Bus 中是否已经存在：

```text
Bar processed event
Strategy callback event
Order submitted event
Order accepted event
Order rejected event
Order cancelled event
Execution event
Position changed event
Cash changed event
Account snapshot event
Runtime failure event
```

## 7.4 当前结果扩展

确认 Strategy 当前如何：

```text
build_result_extension()
```

或者通过其他机制输出策略自定义结果。

## 7.5 当前持久化

说明当前：

```text
manifest.json
user_data
run directory
JSON output
Parquet
fingerprint
```

的实现位置。

## 7.6 当前确定性

说明：

```text
determinism_fingerprint
```

当前包含和排除什么。

## 7.7 当前多 Cluster

说明：

```text
多 Cluster
共享 Runtime
独立账户
共享账户
```

的运行和结果聚合方式。

分析完成后再实施。

---

# 八、通用设计原则

必须严格遵守以下原则：

```text
1. Result 是不可变的运行事实快照
2. Collector 只收集事实，不计算绩效
3. Analytics 只分析 Result
4. Artifact 只持久化已有结果
5. Report 只展示已有结果
6. Runtime 不依赖具体 Report
7. Strategy 不计算账户级收益
8. Broker 不生成最终回测报告
9. 插件不定义核心结果模型
10. 所有内部时间使用 UTC aware datetime
11. Money、Price、Quantity 不使用 float 作为真值
12. 所有输出顺序必须确定
13. 结果框架不得改变交易事件顺序
14. 结果框架不得影响交易行为
15. 失败运行也应尽量保留部分结果
```

禁止：

```text
Strategy 直接写 CSV
Broker 直接写 summary.json
Tushare 插件计算最大回撤
Collector 修改 Position
Analytics 调用 Broker
Report 读取 Runtime 内部私有状态
Artifact 重新计算交易盈亏
从日志文本反推订单和成交
```

---

# 九、Result 模块

Result 模块定义稳定、通用、不可变的结果对象。

Result 不得依赖：

```text
Tushare
MiniQMT
Virtual Broker 插件实现
具体 Strategy
pandas
pyarrow
matplotlib
CLI
```

Result 可以依赖核心 Domain Value Object。

---

## 9.1 OnlyBacktestResult

建议语义：

```python
@dataclass(frozen=True, slots=True)
class OnlyBacktestResult:
    schema_version: int
    run_id: OnlyRunId
    engine_id: OnlyEngineId
    status: OnlyRunStatus
    started_at: datetime
    finished_at: datetime
    runtime_results: tuple[OnlyRuntimeBacktestResult, ...]
    cluster_results: tuple[OnlyClusterBacktestResult, ...]
    account_results: tuple[OnlyAccountBacktestResult, ...]
    data_statistics: OnlyBacktestDataStatistics
    diagnostics: OnlyBacktestDiagnostics
    facts: OnlyBacktestFacts
    determinism_fingerprint: str
```

顶层 Result 不直接包含：

```text
文件路径
pyarrow.Table
pandas.DataFrame
开放文件对象
插件 Client
Runtime 实例
Broker 实例
```

---

## 9.2 OnlyBacktestFacts

统一保存原始事实集合：

```python
@dataclass(frozen=True, slots=True)
class OnlyBacktestFacts:
    bars: tuple[OnlyBarResultRecord, ...]
    signals: tuple[OnlySignalResultRecord, ...]
    order_requests: tuple[OnlyOrderRequestResultRecord, ...]
    orders: tuple[OnlyOrderResultRecord, ...]
    executions: tuple[OnlyExecutionResultRecord, ...]
    positions: tuple[OnlyPositionResultRecord, ...]
    accounts: tuple[OnlyAccountResultRecord, ...]
    equity: tuple[OnlyEquityResultRecord, ...]
```

如果 Bar 数量过大，不建议将所有 Bar 永久驻留顶层 Result。

可以采用：

```text
内存 Collector 中只保存统计和必要引用
Artifact Writer 从受控事实流写出
Result 中保存轻量引用或可选事实集合
```

但不得破坏 Analytics 的纯 Result 输入原则。

可选设计：

```text
OnlyBacktestFacts
    小规模事实内存化

OnlyResultDatasetRef
    大规模事实使用稳定数据集引用
```

如果使用引用，Analytics 必须通过核心定义的只读 Result Dataset 接口读取，而不是直接依赖具体文件路径。

第一阶段优先保证结构清晰和正确性，不需要提前做复杂流式存储。

---

## 9.3 Cluster Result

实现：

```text
OnlyClusterBacktestResult
```

至少包含：

```text
cluster_id
runtime_id
strategy_id
account_id
status
started_at
finished_at
callback_count
signal_count
order_request_count
order_count
execution_count
final_position_count
warnings
failures
strategy_extension
```

Strategy 自定义扩展必须保持兼容。

---

## 9.4 Account Result

实现：

```text
OnlyAccountBacktestResult
```

至少包含：

```text
account_id
currency
initial_cash
ending_cash
ending_market_value
ending_equity
realized_pnl
unrealized_pnl
commission
fees
final_positions
```

如果 Account 模型已有官方：

```text
equity
balance
net liquidation value
```

定义，严格复用，不得另建不一致语义。

---

## 9.5 数据统计

实现：

```text
OnlyBacktestDataStatistics
```

至少包含：

```text
data_source_ids
instrument_ids
bar_types
requested_ranges
resolved_ranges
observed_ranges
loaded_bar_count
replayed_bar_count
accepted_bar_count
rejected_bar_count
failed_bar_count
first_bar_time
last_bar_time
rows_fetched
rows_read
cache_hit
content_fingerprints
price_adjustments
```

无法精确获知的值允许为 `None`。

不得用推测值填充。

---

## 9.6 标准记录模型

### Bar Record

至少包含：

```text
sequence
runtime_id
cluster_ids
source_id
instrument_id
bar_type
bar_start
bar_end
ts_event
trading_day
open
high
low
close
volume
turnover
accepted
failure_id
```

第一阶段可以不把所有 Bar 写入标准 Artifact，避免体积膨胀。

但 Collector 至少应记录：

```text
数量
首尾时间
失败关联
```

### Signal Record

实现：

```text
OnlySignalResultRecord
```

至少包含：

```text
signal_id
cluster_id
strategy_id
factor_id
instrument_id
signal_type
ts_event
trading_day
score
confidence
related_order_request_id
payload
```

必须建立通用信号记录接口。

不能继续依赖解析某个 MACD Strategy 自定义：

```text
signals: list[dict]
```

Strategy 应通过受限 Context 调用类似：

```python
context.strategy.results.record_signal(...)
```

实际接口名根据现有 Context 设计决定。

### Order Request Record

至少包含：

```text
request_id
cluster_id
strategy_id
account_id
instrument_id
side
offset
order_type
quantity
limit_price
stop_price
submitted_at
tags
```

### Order Record

至少包含：

```text
order_id
request_id
cluster_id
strategy_id
account_id
instrument_id
side
offset
order_type
requested_quantity
filled_quantity
remaining_quantity
status
submitted_at
accepted_at
completed_at
rejection_code
rejection_message
tags
```

### Execution Record

至少包含：

```text
execution_id
order_id
request_id
cluster_id
strategy_id
account_id
instrument_id
side
offset
quantity
price
turnover
commission
fees
slippage
ts_event
trading_day
venue
```

### Position Record

至少包含：

```text
sequence
ts_event
trading_day
cluster_id
strategy_id
account_id
instrument_id
total_quantity
available_quantity
frozen_quantity
average_price
mark_price
market_value
realized_pnl
unrealized_pnl
```

### Account Record

至少包含：

```text
sequence
ts_event
trading_day
account_id
currency
cash
frozen_cash
market_value
equity
realized_pnl
unrealized_pnl
commission
fees
```

### Equity Record

至少包含：

```text
sequence
ts_event
trading_day
account_id
cluster_id
cash
market_value
equity
realized_pnl
unrealized_pnl
commission
fees
gross_exposure
net_exposure
position_count
complete
```

### Failure Record

至少包含：

```text
failure_id
sequence
severity
stage
exception_type
message
runtime_id
cluster_id
strategy_id
account_id
source_id
instrument_id
bar_type
ts_event
trading_day
order_request_id
order_id
execution_id
traceback
```

---

# 十、Collector 模块

Collector 负责在运行期间捕获事实。

Collector 必须：

```text
只读
确定性
不可修改交易状态
不可提交订单
不可取消订单
不可吞掉异常
不可改变事件顺序
```

建议核心类型：

```text
OnlyResultCollector
OnlyBacktestResultCollector
OnlyResultCollectorState
OnlyBacktestResultBuilder
OnlyResultCollectionContext
```

---

## 10.1 Collector 接入方式

优先级：

```text
第一优先：订阅现有标准 Event
第二优先：读取稳定公开 Manager/Result 接口
第三优先：增加供应商无关标准 Event
```

禁止：

```text
monkey patch
扫描日志
访问插件私有属性
解析对象 repr
```

Collector 应关注：

```text
Data loaded
Bar replay accepted
Bar replay rejected
Bar processing failed
Strategy callback started/completed
Signal recorded
Order request submitted
Order accepted
Order rejected
Order cancelled
Execution created
Position changed
Account changed
Trading day changed
Runtime failed
Cluster completed
Runtime completed
```

---

## 10.2 Collector 生命周期

建议：

```text
create
→ attach
→ start
→ collect
→ seal
→ build result
→ detach
```

Collector 完成后必须进入只读状态。

`seal()` 后继续记录应明确失败。

不得静默修改已经构造的 Result。

---

## 10.3 事件顺序

每条 Result Record 必须具有稳定：

```text
sequence
```

序号。

序号必须来自：

```text
现有 Event Bus sequence
或 Runtime 内确定性单调序号
```

不得使用：

```text
Python 对象 id
线程调度顺序
文件写入时间
随机 UUID
```

如果 Event Bus 已有稳定 sequence，严格复用。

---

## 10.4 Equity Snapshot 时点

必须明确净值采样顺序。

日线和 Bar 回测推荐：

```text
Bar 进入
→ Indicator
→ Factor
→ Strategy
→ Risk
→ Order
→ Broker Matching
→ Execution
→ Position
→ Ledger
→ Account
→ Equity Snapshot
```

如果当前 Runtime 正式顺序不同，以当前正式顺序为准。

必须：

```text
文档化
单元测试
集成测试
```

不得同一系统中同时存在：

```text
成交前 Equity
成交后 Equity
```

而没有字段区分。

可以加入：

```text
snapshot_phase=POST_EVENT
```

但第一阶段建议统一为：

```text
POST_BAR_PROCESSING
```

---

## 10.5 多标的估值

当一个账户持有多个 Instrument，而当前只收到其中一个 Instrument 的 Bar：

```text
当前 Instrument 使用本次 Bar close
其他 Instrument 使用最新合法 mark price
```

Collector 或 Account Valuation Service 需要维护：

```text
latest_mark_price_by_instrument
```

但 Collector 不应建立与 Account 冲突的会计真值。

如果 Account 已有估值服务，严格复用。

持仓存在但没有合法价格：

```text
不得按 0 静默估值
equity.complete=false
产生结构化 Warning 或 Failure
```

---

# 十一、Analytics 模块

Analytics 必须是纯分析层。

依赖方向：

```text
Analytics
    ↓
Result
    ↓
Domain Value Objects
```

Analytics 不得依赖：

```text
Runtime
Cluster
Strategy
Broker
DataSource
Tushare
MiniQMT
CLI
```

建议入口：

```python
class OnlyBacktestAnalyticsService:
    def analyze(
        self,
        result: OnlyBacktestResult,
        config: OnlyAnalyticsConfig | None = None,
    ) -> OnlyBacktestAnalysis:
        ...
```

---

## 11.1 OnlyBacktestAnalysis

至少包含：

```text
performance
trade_analysis
drawdown_analysis
equity_analysis
order_analysis
execution_analysis
exposure_analysis
warnings
```

---

## 11.2 Trade Reconstruction

必须区分：

```text
Order Request
Order
Execution
Trade
```

一条 Execution 不等于一笔完整 Trade。

实现：

```text
OnlyTradeBuilder
OnlyTradeRecord
OnlyTradeMatchingPolicy
```

第一阶段支持：

```text
Long-only
BUY OPEN
SELL CLOSE
```

如果当前系统支持分批买卖或部分成交，Trade Builder 必须正确处理。

推荐配对规则：

```text
FIFO
```

必须显式定义：

```text
一个买入 Execution 可以被多个卖出 Execution 分配
一个卖出 Execution 可以关闭多个买入批次
每个 Trade Segment 有独立数量和盈亏
```

可选择输出：

```text
Trade Segment
或聚合 Round Trip Trade
```

推荐同时定义：

```text
OnlyTradeLotMatch
OnlyRoundTripTrade
```

但第一阶段可以只输出 FIFO Trade Segment，避免模糊聚合。

每条 Trade 至少包含：

```text
trade_id
cluster_id
strategy_id
account_id
instrument_id
direction
quantity
entry_time
exit_time
entry_price
exit_price
gross_pnl
commission
fees
net_pnl
holding_duration
entry_execution_id
exit_execution_id
entry_order_id
exit_order_id
```

费用分配必须确定性。

如果一个 Execution 的费用需要分配到多个 Trade，按数量比例分配，并处理 Decimal 尾差。

最后一个分配项承接余数，保证费用总和完全一致。

---

## 11.3 收益计算

基础定义：

```text
equity = cash + market_value
```

如果 Account 已有更完整净资产定义，使用 Account 官方定义。

实现：

```text
initial_equity
ending_equity
net_profit
total_return
```

定义：

```text
net_profit = ending_equity - initial_equity
```

```text
total_return = ending_equity / initial_equity - 1
```

使用 Decimal。

初始净值为零：

```text
total_return=None
产生 ZERO_INITIAL_EQUITY Warning
```

---

## 11.4 回撤

基于 Equity Curve：

```text
running_peak = max(previous_peak, equity)
drawdown_amount = equity - running_peak
drawdown_ratio = equity / running_peak - 1
```

实现：

```text
OnlyDrawdownPoint
OnlyDrawdownAnalysis
```

至少输出：

```text
max_drawdown_amount
max_drawdown_ratio
max_drawdown_peak_time
max_drawdown_trough_time
recovery_time
recovered
current_drawdown
```

Peak 为零时比例回撤为 `None`。

---

## 11.5 交易统计

至少实现：

```text
trade_count
winning_trade_count
losing_trade_count
breakeven_trade_count
win_rate
gross_profit
gross_loss
net_trade_pnl
average_trade_pnl
average_win
average_loss
largest_win
largest_loss
profit_factor
average_holding_duration
maximum_holding_duration
```

定义：

```text
profit_factor = gross_profit / abs(gross_loss)
```

若无亏损：

```text
gross_profit > 0 → profit_factor=None 或 Infinity 枚举
```

不要把无限值写为 float `inf`。

建议使用：

```text
None
并添加 NO_GROSS_LOSS Warning
```

---

## 11.6 订单和成交统计

订单统计：

```text
submitted_count
accepted_count
rejected_count
cancelled_count
expired_count
filled_count
partially_filled_count
open_count
```

成交统计：

```text
execution_count
buy_execution_count
sell_execution_count
buy_quantity
sell_quantity
buy_turnover
sell_turnover
gross_turnover
commission
fees
slippage_cost
```

必须基于正式订单状态和 Execution 事实。

不得根据订单标签猜状态。

---

## 11.7 Exposure

基础支持：

```text
gross_exposure
net_exposure
maximum_gross_exposure
average_gross_exposure
time_in_market_ratio
```

如果只支持 Long-only：

```text
net_exposure == gross_exposure
```

但不要在模型中写死这一假设。

Exposure Ratio 的分母必须明确：

```text
equity
```

Equity <= 0 时比例为 `None` 并记录 Warning。

---

## 11.8 年化指标

第一阶段不要为了完整而错误实现：

```text
Sharpe
Sortino
Calmar
Annualized Return
Annualized Volatility
```

只有在以下语义明确后才实现：

```text
收益采样周期
一年交易日数量
风险自由利率
缺失交易日处理
日线与分钟线统一规则
```

如果这些语义当前未建立：

```text
模型中保留可选字段
值为 None
文档明确未实现
```

禁止虚构 Sharpe。

---

# 十二、Artifact 模块

Artifact 模块负责把 Result 和 Analysis 写入文件。

Artifact 不得重新计算：

```text
Trade
PnL
Return
Drawdown
Order Status
```

Artifact 只接受：

```text
OnlyBacktestResult
OnlyBacktestAnalysis
```

建议入口：

```python
class OnlyBacktestArtifactWriter:
    def write(
        self,
        result: OnlyBacktestResult,
        analysis: OnlyBacktestAnalysis,
        target: OnlyRunArtifactTarget,
    ) -> OnlyBacktestArtifactManifest:
        ...
```

---

## 12.1 标准输出目录

```text
<user_data>/runs/<engine_id>/<run_id>/
```

标准文件：

```text
manifest.json
summary.json
diagnostics.json
data_manifest.json
artifact_manifest.json
orders.parquet
executions.parquet
trades.parquet
positions.parquet
accounts.parquet
equity.parquet
signals.parquet
report.md
```

现有 `manifest.json` 必须兼容保留。

如果现有 Manifest 已承担 Run Manifest 职责：

```text
不要用新的 artifact_manifest.json 替代
而应区分 Run Manifest 与 Artifact Manifest
```

---

## 12.2 summary.json

建议结构：

```json
{
  "schema_version": 1,
  "run": {
    "run_id": "...",
    "engine_id": "...",
    "status": "COMPLETED",
    "started_at": "...",
    "finished_at": "...",
    "runtime_count": 1,
    "cluster_count": 1,
    "account_count": 1
  },
  "data": {},
  "strategies": [],
  "orders": {},
  "executions": {},
  "positions": {},
  "accounts": [],
  "trades": {},
  "performance": {},
  "diagnostics": {},
  "fingerprints": {},
  "artifacts": {}
}
```

所有 Decimal 在 JSON 中使用字符串。

不得转为 float。

Money 应明确：

```json
{
  "value": "1000000.00",
  "currency": "CNY"
}
```

---

## 12.3 diagnostics.json

至少包含：

```text
schema_version
failure_count
warning_count
truncated
total_failure_count
first_failure
failures
warnings
```

默认完整 Failure 上限：

```text
100
```

配置允许修改。

Traceback 可写入 Diagnostics，但：

```text
traceback 不进入结果指纹
绝对源码路径不进入结果指纹
```

---

## 12.4 data_manifest.json

复用 Historical Cache 和 DataSource 事实：

```text
data_source_ids
instrument_ids
bar_types
requested_ranges
resolved_ranges
observed_ranges
rows_fetched
rows_read
cache_hit
content_fingerprints
price_adjustments
adjustment_references
schema_versions
time_semantics_versions
```

不得扫描 Cache 目录猜测数据。

---

## 12.5 Parquet Schema

### orders.parquet

至少：

```text
sequence
request_id
order_id
runtime_id
cluster_id
strategy_id
account_id
instrument_id
side
offset
order_type
requested_quantity
filled_quantity
remaining_quantity
limit_price
stop_price
status
submitted_at
accepted_at
completed_at
rejection_code
rejection_message
tags_json
```

### executions.parquet

至少：

```text
sequence
execution_id
order_id
request_id
runtime_id
cluster_id
strategy_id
account_id
instrument_id
side
offset
quantity
price
turnover
commission
fees
slippage
ts_event
trading_day
venue
```

### trades.parquet

至少：

```text
trade_id
entry_execution_id
exit_execution_id
entry_order_id
exit_order_id
cluster_id
strategy_id
account_id
instrument_id
direction
quantity
entry_time
exit_time
entry_price
exit_price
gross_pnl
commission
fees
net_pnl
holding_duration_ns
```

### positions.parquet

至少：

```text
sequence
ts_event
trading_day
cluster_id
strategy_id
account_id
instrument_id
total_quantity
available_quantity
frozen_quantity
average_price
mark_price
market_value
realized_pnl
unrealized_pnl
```

### accounts.parquet

至少：

```text
sequence
ts_event
trading_day
account_id
currency
cash
frozen_cash
market_value
equity
realized_pnl
unrealized_pnl
commission
fees
```

### equity.parquet

至少：

```text
sequence
ts_event
trading_day
account_id
cluster_id
cash
market_value
equity
running_peak
drawdown_amount
drawdown_ratio
realized_pnl
unrealized_pnl
commission
fees
gross_exposure
net_exposure
position_count
complete
```

### signals.parquet

至少：

```text
sequence
signal_id
cluster_id
strategy_id
factor_id
instrument_id
signal_type
ts_event
trading_day
score
confidence
related_order_request_id
payload_json
```

---

## 12.6 Decimal Parquet

优先使用：

```text
Decimal128
```

或者当前项目已验证的确定性 Decimal 表示。

禁止：

```text
Decimal → float → Parquet
```

必须测试：

```text
0.1
0.01
大额资金
高精度价格
多次费用累加
```

写入后读回值必须完全一致。

---

## 12.7 空结果

无交易时仍应生成稳定 Schema 的：

```text
orders.parquet
executions.parquet
trades.parquet
```

允许零行，但文件可读。

Artifact Manifest 记录：

```text
row_count=0
```

这样下游不用判断文件是否存在。

---

## 12.8 Artifact Manifest

实现：

```text
OnlyArtifactDescriptor
OnlyBacktestArtifactManifest
```

每个 Artifact 至少记录：

```text
artifact_type
relative_path
format
schema_version
row_count
sha256
content_fingerprint
```

可以记录 `created_at`，但：

```text
created_at 不进入 content_fingerprint
```

绝对路径不得进入 Artifact Fingerprint。

---

## 12.9 原子写入

Artifact 必须使用安全发布流程：

```text
创建 staging
→ 写 Parquet
→ 回读验证
→ 写 JSON
→ 计算 Hash
→ 写 Artifact Manifest
→ 原子发布
```

不得先写正式 Manifest 再写明细。

如果运行失败，也应尽量发布部分有效结果。

Artifact 写入错误：

```text
增加 ARTIFACT_WRITE Failure
不得覆盖原始 Runtime Failure
```

---

# 十三、Report 模块

Report 是展示层。

Report 不得重新计算绩效。

Report 输入：

```text
OnlyBacktestResult
OnlyBacktestAnalysis
OnlyBacktestArtifactManifest
```

建议实现：

```text
OnlyConsoleBacktestReport
OnlyJsonBacktestReport
OnlyMarkdownBacktestReport
```

---

## 13.1 CLI JSON

保持默认 CLI 输出简洁。

成功示例：

```json
{
  "status": "COMPLETED",
  "run_id": "...",
  "engine_id": "onlyalpha",
  "cluster_count": 1,
  "bar_count": 500,
  "signal_count": 12,
  "order_count": 8,
  "execution_count": 8,
  "trade_count": 4,
  "initial_equity": {
    "value": "1000000.00",
    "currency": "CNY"
  },
  "ending_equity": {
    "value": "1035000.00",
    "currency": "CNY"
  },
  "total_return": "0.035",
  "max_drawdown": "-0.082",
  "determinism_fingerprint": "...",
  "result_fingerprint": "...",
  "summary_path": "...",
  "manifest_path": "..."
}
```

失败示例：

```json
{
  "status": "FAILED",
  "run_id": "...",
  "failure_count": 165,
  "first_failure": {
    "stage": "MARKET_DATA_PIPELINE",
    "exception_type": "OnlyMarketDataPipelineError",
    "message": "...",
    "instrument_id": "600000.XSHG",
    "ts_event": "..."
  },
  "diagnostics_path": "...",
  "manifest_path": "..."
}
```

CLI 不输出完整订单和净值列表。

---

## 13.2 Console Report

可增加配置或独立命令显示：

```text
Run
  Status: COMPLETED
  Run ID: ...
  Period: ...
  Bars: 500

Trading
  Signals: 12
  Orders: 8
  Executions: 8
  Trades: 4

Performance
  Initial Equity: 1,000,000.00 CNY
  Ending Equity: 1,035,000.00 CNY
  Net Profit: 35,000.00 CNY
  Total Return: 3.50%
  Max Drawdown: -8.20%

Artifacts
  Summary: ...
  Trades: ...
  Equity: ...
```

Console 只格式化 Analysis，不重新计算。

---

## 13.3 Markdown Report

生成：

```text
report.md
```

至少包含：

```text
Run Summary
Data Summary
Strategy Summary
Order Summary
Execution Summary
Trade Summary
Performance Summary
Final Account
Final Positions
Diagnostics
Artifacts
Fingerprints
```

第一阶段不生成图表。

HTML 报告不在本任务范围。

---

# 十四、Diagnostics

实现稳定诊断体系：

```text
OnlyResultDiagnosticSeverity
OnlyResultFailureStage
OnlyBacktestFailure
OnlyBacktestWarning
OnlyBacktestDiagnostics
```

Stage 至少包括：

```text
CONFIG
PLUGIN_DISCOVERY
DATA_LOAD
CACHE
REPLAY
MARKET_DATA_PIPELINE
INDICATOR
FACTOR
STRATEGY
RISK
ORDER
BROKER
MATCHING
EXECUTION
POSITION
LEDGER
ACCOUNT
RESULT_COLLECTION
ANALYTICS
ARTIFACT_WRITE
REPORT
```

必须保留第一个真实根因。

聚合错误可以存在，但不能覆盖根因。

例如不应只保留：

```text
historical replay failed=165 rejected=0
```

还必须保留：

```text
first_failure.stage
first_failure.exception_type
first_failure.message
first_failure.ts_event
first_failure.instrument_id
first_failure.sequence
```

---

# 十五、Fingerprint

当前已有：

```text
determinism_fingerprint
Historical Cache content_fingerprint
```

本任务增加：

```text
result_fingerprint
analysis_fingerprint
artifact_content_fingerprint
```

---

## 15.1 Result Fingerprint

基于稳定规范内容：

```text
Canonical Run Config
Data Content Fingerprints
排序后的 Signal Facts
排序后的 Order Facts
排序后的 Execution Facts
排序后的 Final Position Facts
排序后的 Equity Facts
Final Account State
Diagnostics Stable Identity
```

排除：

```text
run_id
started_at
finished_at
绝对路径
hostname
PID
临时目录
traceback
文件创建时间
对象 repr
随机 UUID
```

---

## 15.2 Analysis Fingerprint

基于：

```text
result_fingerprint
analytics_schema_version
trade_matching_policy
analytics_config
performance_statistics
trade_records
drawdown_results
```

---

## 15.3 重放一致性

相同：

```text
配置
数据
代码语义
事件顺序
```

两次运行即使：

```text
run_id 不同
路径不同
时间不同
```

也必须满足：

```text
determinism_fingerprint 一致
result_fingerprint 一致
analysis_fingerprint 一致
Order Facts 一致
Execution Facts 一致
Trade Facts 一致
Equity Curve 一致
Performance Statistics 一致
```

---

# 十六、配置模型

检查当前：

```yaml
output:
  formats:
    - JSON
```

在保持兼容的前提下扩展。

建议：

```yaml
output:
  formats:
    - JSON
    - PARQUET
    - MARKDOWN

  artifacts:
    summary: true
    diagnostics: true
    data_manifest: true
    orders: true
    executions: true
    trades: true
    positions: true
    accounts: true
    equity: true
    signals: true
    markdown_report: true

  diagnostics:
    max_failure_records: 100
    include_traceback: true

  analytics:
    trade_matching: FIFO
    calculate_annualized_metrics: false
```

默认必须：

```text
summary=true
diagnostics=true
orders=true
executions=true
trades=true
equity=true
```

用户不应必须手工开启基础结果。

---

# 十七、多 Runtime、多 Cluster、多账户

必须正确区分：

```text
Engine-level
Runtime-level
Cluster-level
Strategy-level
Account-level
```

---

## 17.1 多 Cluster 独立账户

可按相同币种聚合：

```text
initial_equity
ending_equity
net_profit
```

但必须保留 Cluster 独立结果。

---

## 17.2 多 Cluster 共享账户

不能把同一个 Account Equity 重复加总。

聚合必须按：

```text
account_id
```

去重。

Strategy Ledger 和 Broker Account 不能混为一谈。

---

## 17.3 多币种

如果账户币种不同且没有 FX 转换：

```text
Engine Aggregate Monetary Statistics=None
```

产生：

```text
MULTI_CURRENCY_AGGREGATION_UNAVAILABLE
```

保留每个账户独立结果。

禁止直接将：

```text
CNY + USD
```

相加。

---

# 十八、状态模型

复用现有状态，如果不足则扩展：

```text
COMPLETED
COMPLETED_WITH_WARNINGS
PARTIALLY_FAILED
FAILED
CANCELLED
```

建议：

```text
全部 Runtime/Cluster 成功且无 Warning
    → COMPLETED

成功但存在非致命 Warning
    → COMPLETED_WITH_WARNINGS

部分 Cluster 成功、部分失败
    → PARTIALLY_FAILED

全部失败或 Engine 致命错误
    → FAILED
```

失败运行仍应输出：

```text
summary.json
diagnostics.json
已有订单
已有成交
已有净值
Artifact Manifest
```

---

# 十九、标准信号接口

当前 MACD Strategy 可能通过自定义扩展记录：

```text
signals
callback_count
signal_state
```

本任务建立正式通用接口。

建议 Strategy Context 增加受限接口：

```python
context.strategy.results.record_signal(
    signal_type="GOLDEN_CROSS",
    instrument_id=...,
    factor_id=...,
    ts_event=...,
    score=...,
    confidence=...,
    related_order_request_id=...,
    payload={...},
)
```

接口不得暴露 Collector 可变内部状态。

MACD 示例迁移到标准接口。

兼容保留原 `build_result_extension()`。

核心 Analytics 不能识别：

```text
GOLDEN_CROSS
DEATH_CROSS
```

特殊业务含义。

核心只统计标准 Signal Record。

---

# 二十、示例纵切面

在 `OnlyAlpha-examples` 增加：

```text
examples/results_framework_demo/
```

必须使用正式：

```text
onlyalpha run
```

不得直接实例化 Runtime。

示例应使用：

```text
Synthetic Historical Data
固定第 10 根 Bar 买入
固定第 20 根 Bar 卖出
Virtual Broker
```

确保任何环境都产生：

```text
非零 Signal
非零 Order
非零 Execution
一笔完整 Trade
完整 Equity Curve
非零或可预测收益
完整 summary.json
完整 Parquet
完整 Markdown Report
```

该示例是 Results Framework 的确定性验收基准。

---

# 二十一、Tushare 日线纵切面

更新：

```text
OnlyAlpha-examples/examples/tushare_daily_backtest/
```

正式运行：

```bash
uv run onlyalpha run \
  --config OnlyAlpha-examples/examples/tushare_daily_backtest/config.yaml \
  --user-data OnlyAlpha-examples/user_data
```

记录：

```text
status
run_id
bar_count
callback_count
signal_count
order_count
execution_count
trade_count
initial_equity
ending_equity
net_profit
total_return
max_drawdown
rows_fetched
rows_read
cache_hit
content_fingerprint
determinism_fingerprint
result_fingerprint
analysis_fingerprint
summary_path
```

然后删除 Token，执行 CACHE_ONLY 配置。

验证：

```text
Bar Facts 一致
Signal Facts 一致
Order Facts 一致
Execution Facts 一致
Trade Facts 一致
Equity Curve 一致
Statistics 一致
Result Fingerprint 一致
Analysis Fingerprint 一致
```

如果 Tushare 服务不可用：

```text
不得虚构结果
优先使用已有 Cache
无 Cache 时只完成 Synthetic 正式验收
报告真实 Tushare 验收被阻塞
```

---

# 二十二、测试要求

必须增加完整测试矩阵。

---

## 22.1 Result 模型

验证：

```text
不可变
UTC aware
Decimal 保真
稳定排序
序列化
反序列化
非法状态拒绝
```

---

## 22.2 Collector 不改变行为

同一回测：

```text
开启 Collector
关闭 Collector
```

验证：

```text
订单一致
成交一致
持仓一致
账户一致
determinism_fingerprint 一致
```

如果产品模式强制 Collector，则使用 No-op Collector 做对比测试。

---

## 22.3 无交易

有 Bar，无 Signal。

验证：

```text
bar_count > 0
callback_count > 0
signal_count=0
order_count=0
execution_count=0
trade_count=0
ending_equity=initial_equity
total_return=0
max_drawdown=0
所有空 Parquet 可读
```

---

## 22.4 确定性固定买卖

第 10 根买入，第 20 根卖出。

验证：

```text
1 entry signal
1 exit signal
2 order requests
2 orders
2 executions
1 trade
最终无持仓
现金正确
净值正确
收益正确
```

---

## 22.5 MACD

Synthetic 价格序列产生：

```text
GOLDEN_CROSS
DEATH_CROSS
```

验证完整纵切面。

---

## 22.6 部分成交

如果当前 Broker 支持部分成交：

```text
一个 Order
多个 Execution
FIFO Trade 正确
Order 状态正确
费用分配正确
```

若当前不支持，明确 skip 原因。

---

## 22.7 分批买卖

验证：

```text
两次买入
一次部分卖出
一次剩余卖出
```

FIFO Trade 数量和 PnL 正确。

---

## 22.8 T+1

验证：

```text
T 日买入
T 日 available=0
T+1 available 恢复
```

Result Position Record 与正式 Position 一致。

---

## 22.9 多标的估值

持有两个 Instrument，只更新一个 Bar。

验证另一个 Instrument 使用最新合法价格。

没有价格时：

```text
equity.complete=false
产生诊断
```

---

## 22.10 多 Cluster

两个 Cluster，两个账户。

验证：

```text
Cluster Result 独立
Account Result 独立
Engine Aggregate 正确
```

---

## 22.11 共享账户

两个 Cluster 共享账户。

验证 Equity 不重复统计。

---

## 22.12 多币种

CNY 和 USD 两账户。

验证：

```text
每账户结果正常
Engine monetary aggregate=None
产生 Warning
```

---

## 22.13 Replay 失败

第 N 根 Bar 触发 Strategy 异常。

验证：

```text
first_failure.stage=STRATEGY
ts_event 正确
instrument_id 正确
部分 Result 保留
diagnostics.json 正确
```

---

## 22.14 Pipeline 失败

构造：

```text
ts_event != bar_end
```

验证底层异常没有被汇总错误完全遮蔽。

---

## 22.15 Analytics 边界

验证：

```text
无交易
全盈利
全亏损
无亏损 profit factor
初始净值为 0
Equity 为 0
Equity 为负
Drawdown 恢复
Drawdown 未恢复
```

---

## 22.16 Decimal

验证：

```text
0.1
0.01
多次手续费
大额成交
Parquet Round Trip
JSON Round Trip
```

完全一致。

---

## 22.17 Artifact 原子性

注入写入失败。

验证：

```text
不存在半写 Manifest
不存在 Manifest 引用缺失文件
原始 Runtime Failure 未丢失
追加 ARTIFACT_WRITE Failure
```

---

## 22.18 Fingerprint

同一输入运行两次。

验证：

```text
run_id 不同
started_at 不同
目录不同
```

但：

```text
result_fingerprint 一致
analysis_fingerprint 一致
Artifact 内容指纹一致
```

---

## 22.19 CACHE_ONLY

第一次 Provider + Cache。

第二次 CACHE_ONLY 无 Token。

验证所有结果一致。

---

# 二十三、文档要求

新增：

```text
docs/results_framework.md
docs/result_model.md
docs/result_collector.md
docs/analytics.md
docs/backtest_artifacts.md
docs/backtest_reports.md
docs/diagnostics.md
docs/adr/xxxx-results-framework.md
```

文档必须明确：

```text
Result、Collector、Analytics、Artifact、Report 的边界
Order 与 Execution 的区别
Execution 与 Trade 的区别
Trade FIFO 配对
Equity 采样时点
多标的估值
多 Cluster 聚合
共享账户处理
多币种限制
失败运行产物
空结果文件
Fingerprint 范围
Decimal 存储
```

更新：

```text
README.md
ROADMAP.md
HANDOFF.md
```

路线图中：

```text
Phase 2B 真实历史数据
```

应更新为：

```text
基础纵切面已完成，治理和规模化仍未完成
```

本任务完成后：

```text
Phase 2D 回测分析与报告
```

标记为：

```text
Results Framework 基础纵切面完成
```

不能标记为完全完成，因为以下仍未实现：

```text
Benchmark
Alpha/Beta
归因
高级风险指标
参数实验
HTML 图表报告
```

---

# 二十四、兼容性要求

不得破坏：

```text
Synthetic 回测
Tushare
MiniQMT
Historical Cache
Virtual Broker
Strategy Result Extension
现有 CLI JSON 字段
现有 Run Manifest
现有 Determinism Fingerprint
单 Cluster
多 Cluster
```

可以新增字段。

不得无迁移删除现有字段。

如果构造器签名变化：

```text
提供默认值
兼容旧调用
```

---

# 二十五、禁止事项

禁止：

```text
使用 float 计算 Money 和 PnL
从日志解析交易事实
由 Strategy 计算最大回撤
由 Broker 写回测报告
由插件定义 OnlyBacktestResult
Artifact Writer 重新计算 PnL
Report 重新计算 Return
Execution 数量直接当 Trade 数量
忽略部分成交
忽略分批交易
未知价格按 0 估值
共享账户重复加总
不同币种直接相加
虚构 Sharpe
将 run_id 放入 result_fingerprint
将绝对路径放入 result_fingerprint
将 traceback 放入 result_fingerprint
将巨大事实列表塞入 manifest.json
使用 Path.cwd() 猜 user_data
绕过 onlyalpha run
只写单元测试不做完整示例
为了输出结果改变事件顺序
为了收集结果修改 Position 或 Account
```

---

# 二十六、质量门禁

执行：

```bash
uv run --directory OnlyAlpha pytest -q
uv run --directory OnlyAlpha ruff check .
uv run --directory OnlyAlpha ruff format --check .
uv run --directory OnlyAlpha mypy

uv run --directory OnlyAlpha-plugins pytest -q
uv run --directory OnlyAlpha-plugins ruff check .
uv run --directory OnlyAlpha-plugins ruff format --check .
uv run --directory OnlyAlpha-plugins mypy

uv run --directory OnlyAlpha-examples pytest -q
uv run --directory OnlyAlpha-examples ruff check .
uv run --directory OnlyAlpha-examples ruff format --check .

git diff --check
```

如果全插件 Mypy 仍被既有 MiniQMT 类型问题阻塞：

```text
明确区分已有问题和本任务新增问题
至少保证本任务新增代码 Mypy 通过
不得把已有问题归因于 Results Framework
```

验证环境：

```text
Python 3.12
Python 3.13
Windows
Linux
macOS
```

无法执行的平台必须明确说明。

---

# 二十七、实施顺序

严格按以下顺序进行，避免一次性混乱修改。

## Stage 1：分析和模型

```text
阅读现有代码
梳理事实来源
设计 Result Models
设计稳定序号
设计 Diagnostics
设计 Fingerprint
```

## Stage 2：Collector

```text
接入现有事件
收集 Signal
收集 Order
收集 Execution
收集 Position
收集 Account
收集 Failure
构造 OnlyBacktestResult
```

## Stage 3：确定性示例

```text
固定第 N 根买入卖出
验证 Result Facts
```

## Stage 4：Analytics

```text
FIFO Trade
Equity
Return
Drawdown
Trading Statistics
```

## Stage 5：Artifact

```text
JSON
Parquet
Manifest
Atomic Write
Fingerprint
```

## Stage 6：Report

```text
CLI JSON
Console
Markdown
```

## Stage 7：真实示例

```text
MACD Synthetic
Tushare 日线
CACHE_ONLY
多 Cluster
```

## Stage 8：文档和质量门禁

---

# 二十八、完成标准

以下全部满足才算完成：

```text
Result 模块
Collector 模块
Analytics 模块
Artifact 模块
Report 模块

OnlyBacktestResult
OnlyClusterBacktestResult
OnlyAccountBacktestResult
OnlyBacktestFacts
OnlyBacktestDiagnostics

标准 Signal Record
标准 Order Record
标准 Execution Record
标准 Position Record
标准 Account Record
标准 Equity Record
标准 Failure Record

Collector 不影响交易行为
稳定 sequence
首个真实根因可见

FIFO Trade Reconstruction
基础收益
最大回撤
交易统计
订单统计
成交统计
Exposure

summary.json
diagnostics.json
data_manifest.json
artifact_manifest.json
orders.parquet
executions.parquet
trades.parquet
positions.parquet
accounts.parquet
equity.parquet
signals.parquet
report.md

result_fingerprint
analysis_fingerprint
Artifact Hash

无交易测试
固定买卖测试
MACD 测试
失败诊断测试
多标的估值测试
多 Cluster 测试
共享账户测试
多币种测试
Decimal 测试
原子写入测试
CACHE_ONLY 一致性测试

正式 onlyalpha run 纵切面
Examples
README
ADR
ROADMAP
HANDOFF
质量门禁
```

---

# 二十九、最终报告格式

完成后输出中文实现报告。

## 1. 修改前分析

说明当前 Result、Manifest、Event 和事实来源。

## 2. 架构设计

说明五个模块及依赖方向：

```text
Result
Collector
Analytics
Artifact
Report
```

## 3. Result 模型

列出所有核心类型和语义。

## 4. Collector

说明如何采集：

```text
Bar
Signal
Order
Execution
Position
Account
Failure
```

说明为什么不会影响交易行为。

## 5. Analytics

说明：

```text
FIFO Trade
PnL
Equity
Return
Drawdown
Exposure
Trading Statistics
```

## 6. Artifact

列出每个输出文件：

```text
Schema
行数
Hash
用途
```

## 7. Report

展示 CLI、Console 和 Markdown 示例。

## 8. Fingerprint

明确：

```text
包含什么
排除什么
两次运行是否一致
```

## 9. Diagnostics

展示一个真实结构化错误。

## 10. 测试

列出真实执行命令和真实结果。

## 11. Tushare 验收

记录：

```text
bar_count
signal_count
order_count
execution_count
trade_count
ending_equity
total_return
max_drawdown
result_fingerprint
analysis_fingerprint
```

对比首次运行和 CACHE_ONLY。

## 12. 未完成项

只列本任务范围内未完成内容。

不得虚构测试、交易、收益或跨平台结果。

---

# 三十、任务范围外

本任务暂不实现：

```text
Benchmark
Alpha
Beta
Brinson Attribution
行业归因
因子 IC
参数优化
Walk Forward
Monte Carlo
HTML 图表报告
Web API
Web UI
Notebook SDK
实时监控
Paper Trading
Live Trading
分布式回测
多进程优化
```

但是 Results Framework 的接口必须允许后续模块只消费：

```text
OnlyBacktestResult
OnlyBacktestAnalysis
OnlyBacktestArtifactManifest
```

而不访问 Runtime 内部状态。

最终目标：

> 建立 OnlyAlpha 的统一结果基础设施，让所有回测运行形成不可变、确定性、可诊断、可分析、可持久化、可展示的标准结果，并使未来 Research、Web、Paper、Live 和实验管理模块不再重复实现交易统计与结果模型。
