你现在负责在 OnlyAlpha 三仓 Workspace 中实现正式的：

# OnlyAlpha 回测结果、交易流水、净值曲线与诊断报告纵切面

本任务目标不是修改策略逻辑，也不是增加新的数据源，而是把当前“能够完成真实历史数据回测”的系统升级为：

```text
能够观察
能够解释
能够验证
能够比较
能够复现
```

的正式回测产品基础。

Workspace 包含：

```text
OnlyAlpha/
OnlyAlpha-plugins/
OnlyAlpha-examples/
```

Workspace 根仓库：

```text
OnlyAlpha-workspace/
```

---

# 一、当前背景

OnlyAlpha 当前已经具备：

```text
OnlyEngine
Runtime
Cluster
Historical Replay
Market Data Pipeline
Strategy
Factor
Indicator
Risk
Order
Virtual Broker
ExecutionProcessor
Position
Strategy Ledger
Account
Historical Cache
Parquet
Manifest
Fingerprint
Tushare Historical DataSource
MiniQMT Historical DataSource
```

当前真实链路已经能够运行：

```text
Tushare 日线
    ↓
Historical Cache
    ↓
Parquet 重读
    ↓
Historical Replay
    ↓
Market Data Pipeline
    ↓
MACD Indicator
    ↓
Factor
    ↓
Strategy
    ↓
Order
    ↓
Virtual Broker
    ↓
Execution
    ↓
Position / Ledger / Account
```

此前 Market Data Pipeline 错误限制外部母线必须是 `step=1`，导致日线 `step=1440` 无法进入 Pipeline。该问题已经修复。

当前外部日线 Bar 应能够：

```text
作为 base_bar 直接进入 Pipeline
不生成无意义的 derived bar
正常分发给 Cluster
触发 Factor 和 Strategy
```

本任务不得重新引入：

```text
base input must be 1m
```

之类的周期限制。

---

# 二、当前问题

当前 CLI 最终主要输出：

```text
status
run_id
engine_id
cluster_count
failures
determinism_fingerprint
manifest_path
```

但无法直接回答以下问题：

```text
实际读取了多少根 Bar？
策略收到多少次 on_bar？
产生了多少个 Factor 信号？
提交了多少个订单？
多少订单被接受、拒绝、取消？
成交了多少笔？
每笔成交价格和数量是什么？
手续费是多少？
最终现金是多少？
最终持仓是多少？
最终总资产是多少？
策略收益是多少？
最大回撤是多少？
交易胜率是多少？
回测失败时第一个真实异常是什么？
```

当前某些错误只会汇总为：

```text
historical replay failed=N rejected=M
```

而没有暴露：

```text
第一个失败事件时间
Instrument
Bar Type
Cluster
异常类型
异常消息
所属处理阶段
Order Request
```

当前缺少统一的回测结果模型和标准输出产物。

---

# 三、最终目标

实现正式链路：

```text
Historical Data
    ↓
Replay
    ↓
Strategy / Order / Execution
    ↓
Position / Ledger / Account
    ↓
OnlyBacktestResultCollector
    ├── Data Statistics
    ├── Strategy Statistics
    ├── Order Records
    ├── Execution Records
    ├── Trade Records
    ├── Position Snapshots
    ├── Cash Snapshots
    ├── Equity Curve
    ├── Drawdown Curve
    ├── Performance Statistics
    └── Diagnostics
    ↓
Run Artifact Writer
    ├── manifest.json
    ├── summary.json
    ├── diagnostics.json
    ├── orders.parquet
    ├── executions.parquet
    ├── trades.parquet
    ├── positions.parquet
    ├── equity.parquet
    ├── signals.parquet
    └── data_manifest.json
```

运行完成后，CLI 应能够输出简洁摘要，同时完整结果写入：

```text
<user_data>/runs/<engine_id>/<run_id>/
```

必须支持：

```text
单 Cluster
多 Cluster
共享 Runtime
真实 Tushare 日线
CACHE_ONLY 离线重放
Synthetic 数据
Virtual Broker
成功运行
部分失败
完整失败
```

---

# 四、开始前必须阅读

完整阅读：

```text
OnlyAlpha/AGENTS.md
OnlyAlpha/HANDOFF.md
OnlyAlpha/ROADMAP.md
OnlyAlpha/README.md

OnlyAlpha/src/onlyalpha/engine/
OnlyAlpha/src/onlyalpha/runtime/
OnlyAlpha/src/onlyalpha/cluster/
OnlyAlpha/src/onlyalpha/data/
OnlyAlpha/src/onlyalpha/market_data/
OnlyAlpha/src/onlyalpha/strategy/
OnlyAlpha/src/onlyalpha/factor/
OnlyAlpha/src/onlyalpha/order/
OnlyAlpha/src/onlyalpha/risk/
OnlyAlpha/src/onlyalpha/execution/
OnlyAlpha/src/onlyalpha/position/
OnlyAlpha/src/onlyalpha/ledger/
OnlyAlpha/src/onlyalpha/account/
OnlyAlpha/src/onlyalpha/broker/
OnlyAlpha/src/onlyalpha/cache/
OnlyAlpha/src/onlyalpha/storage/
OnlyAlpha/src/onlyalpha/config/
OnlyAlpha/src/onlyalpha/plugins/
OnlyAlpha/tests/

OnlyAlpha-plugins/packages/onlyalpha-plugin-virtual/
OnlyAlpha-plugins/packages/onlyalpha-plugin-tushare/
OnlyAlpha-plugins/packages/onlyalpha-plugin-miniqmt/

OnlyAlpha-examples/examples/tushare_daily_backtest/
OnlyAlpha-examples/src/onlyalpha_examples/strategies/macd/
OnlyAlpha-examples/src/onlyalpha_examples/factors/macd_signal/
```

重点确认：

```text
OnlyEngineRunResult
OnlyRuntimeResult
OnlyClusterResult
OnlyStrategyResult
OnlyExecution
OnlyOrder
OnlyOrderRequest
OnlyPosition
OnlyPositionAllocation
OnlyStrategyLedger
OnlyAccount
OnlyCashBalance
OnlyBar
OnlyTradingDay
OnlyMoney
OnlyPrice
OnlyQuantity
OnlyRunManifest
OnlyOutputFormat
OnlyJsonValue
```

如果实际名称不同，以当前代码为准，不得建立功能重复的同义模型。

---

# 五、实现前分析

开始修改前，先输出中文分析，至少包含：

1. 当前 `onlyalpha run` 调用链；
2. Engine、Runtime、Cluster 各层已有结果对象；
3. 当前订单、成交、持仓、账户数据存储在哪里；
4. 当前 Virtual Broker 如何产生 Execution；
5. 当前 Strategy 如何记录自定义扩展结果；
6. 当前 Manifest 写入位置和内容；
7. 当前 Determinism Fingerprint 的构造范围；
8. 当前回测结束时现金、持仓和账户状态如何读取；
9. 当前失败异常如何从 Replay 汇总到 CLI；
10. 当前是否已有 Equity、PnL、Trade、Performance 类型；
11. 当前 Event Bus 是否适合由 Collector 订阅交易事件；
12. 当前多 Cluster 和共享 Runtime 的结果聚合方式；
13. 当前输出格式配置如何解析；
14. 当前用户数据目录边界；
15. 当前 Tushare 日线示例的实际正式运行入口。

必须先复用现有边界。

禁止看到缺少一个字段就立即新建平行体系。

---

# 六、设计原则

必须遵守：

```text
1. 核心拥有标准回测结果语义
2. 插件不定义回测报告格式
3. Strategy 不负责统计账户收益
4. Broker 不负责生成最终报告
5. Collector 不改变交易行为
6. 报告生成不得影响事件顺序
7. 报告时间统一使用 UTC aware
8. 金额和数量不得用 float
9. 统计必须确定性
10. 输出文件不得包含机器相关绝对路径指纹
11. CACHE_ONLY 与在线首次运行结果必须可比较
12. 失败时也必须尽最大可能生成诊断产物
```

不得：

```text
在 Strategy 中手工写 CSV
在 Tushare 插件中写回测报告
在 Virtual Broker 中计算最大回撤
通过扫描日志反推交易记录
使用 pandas float 作为领域真值
重新计算一套与 Ledger 不一致的账户状态
```

---

# 七、推荐核心模型

实际实现应遵循现有命名和模块结构，以下为建议语义。

## 7.1 OnlyBacktestResult

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyBacktestResult:
    run_id: OnlyRunId
    engine_id: OnlyEngineId
    status: OnlyRunStatus
    started_at: datetime
    finished_at: datetime
    cluster_results: tuple[OnlyClusterBacktestResult, ...]
    aggregate_statistics: OnlyBacktestStatistics
    data_statistics: OnlyBacktestDataStatistics
    diagnostics: OnlyBacktestDiagnostics
    artifact_manifest: OnlyBacktestArtifactManifest
    determinism_fingerprint: str
```

不得把巨大订单和净值数组全部塞进顶层 JSON 模型。

大规模明细使用 Parquet。

顶层对象只保留：

```text
摘要
统计
引用
指纹
诊断
```

## 7.2 OnlyClusterBacktestResult

至少包括：

```text
cluster_id
runtime_id
strategy_id
account_id
status
strategy_statistics
order_statistics
execution_statistics
position_statistics
performance_statistics
diagnostics
artifact references
```

## 7.3 OnlyBacktestDataStatistics

至少包括：

```text
requested_bar_count
loaded_bar_count
replayed_bar_count
accepted_bar_count
rejected_bar_count
failed_bar_count
first_bar_time
last_bar_time
instrument_count
bar_type_count
cache_hit
rows_fetched
rows_read
content_fingerprint
data_source_ids
```

不能把：

```text
requested_bar_count
```

伪造为供应商请求日期天数。

如果当前层无法获知精确值，则字段允许为 `None`，但必须明确语义。

## 7.4 OnlyStrategyStatistics

至少包括：

```text
callback_count
factor_update_count
signal_count
entry_signal_count
exit_signal_count
order_request_count
```

通用核心不能依赖 MACD 的：

```text
GOLDEN_CROSS
DEATH_CROSS
```

核心只统计标准信号事件或 Strategy Result 中明确暴露的记录。

如果当前系统没有标准 Signal Event，应设计通用接口，而不是解析 Strategy 自定义 JSON 字符串。

## 7.5 OnlyOrderStatistics

至少包括：

```text
submitted_count
accepted_count
rejected_count
cancel_requested_count
cancelled_count
expired_count
open_count
partially_filled_count
filled_count
```

状态统计必须基于订单状态机最终事实。

不得根据 Execution 数量猜订单状态。

## 7.6 OnlyExecutionStatistics

至少包括：

```text
execution_count
buy_execution_count
sell_execution_count
filled_quantity
buy_turnover
sell_turnover
gross_turnover
commission
fees
slippage_cost
```

所有金额使用：

```text
OnlyMoney
Decimal
```

## 7.7 OnlyPositionStatistics

至少包括：

```text
opening_position_count
closing_position_count
final_open_position_count
maximum_simultaneous_positions
final_market_value
unrealized_pnl
realized_pnl
```

若现有 Position/Ledger 还不能准确表达某个指标：

```text
先返回 None
记录 capability/diagnostic
不得虚构
```

## 7.8 OnlyBacktestStatistics

第一阶段必须包括：

```text
initial_cash
ending_cash
ending_market_value
ending_equity
gross_profit
gross_loss
net_profit
total_return
max_drawdown
max_drawdown_start
max_drawdown_end
trade_count
winning_trade_count
losing_trade_count
breakeven_trade_count
win_rate
average_trade_pnl
average_win
average_loss
profit_factor
commission
fees
turnover
exposure_ratio
```

可选：

```text
annualized_return
annualized_volatility
sharpe_ratio
sortino_ratio
calmar_ratio
```

如果周期、无风险利率、年化日数等语义尚未建立，第一阶段不要强行实现错误年化指标。

宁可明确标记：

```text
not available
```

也不要提供看似专业但语义错误的数字。

---

# 八、交易记录模型

必须区分：

```text
Order Request
Order
Execution / Fill
Round-Trip Trade
```

不得把成交直接等同于一笔完整 Trade。

## 8.1 Order Record

`orders.parquet` 至少包含：

```text
run_id
cluster_id
strategy_id
account_id
request_id
order_id
instrument_id
side
offset
order_type
requested_quantity
limit_price
stop_price
status
submitted_at
accepted_at
first_fill_at
completed_at
rejection_code
rejection_message
tags
```

## 8.2 Execution Record

`executions.parquet` 至少包含：

```text
run_id
cluster_id
strategy_id
account_id
order_id
execution_id
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

如果当前模型没有某字段，不得编造。

应从真实 Domain/Event 中提取。

## 8.3 Trade Record

`trades.parquet` 表示已经配对的交易结果。

至少包含：

```text
trade_id
cluster_id
strategy_id
account_id
instrument_id
entry_time
exit_time
entry_price
exit_price
quantity
direction
gross_pnl
commission
fees
net_pnl
holding_period
entry_order_id
exit_order_id
```

第一阶段只需支持当前系统已经支持的：

```text
Long-only
OPEN buy
CLOSE sell
```

如果存在：

```text
分批买入
分批卖出
部分成交
```

必须定义明确配对规则。

推荐：

```text
FIFO
```

但应先检查现有 Strategy Ledger 和 Position 是否已有批次语义。

不得在 Trade Builder 中修改 Position 真值。

Trade Builder 只是读取 Execution 流生成分析视图。

---

# 九、净值曲线

实现：

```text
OnlyEquityPoint
```

至少包含：

```text
ts_event
trading_day
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
```

输出：

```text
equity.parquet
```

## 9.1 估值时间

日线回测第一阶段：

```text
每根主 Bar 处理完成后
使用该 Bar close 对持仓估值
```

必须明确事件顺序：

```text
Bar arrives
→ Indicator / Factor
→ Strategy
→ Order
→ Broker matching
→ Execution
→ Position / Ledger / Account update
→ Equity snapshot
```

或者如果现有正式顺序不同，应按现有架构选择，但必须：

```text
文档化
测试化
确定性
```

不能出现同一根 Bar 有时成交前估值、有时成交后估值。

## 9.2 多标的

在同一 Cluster 中有多个 Instrument 时：

```text
只有部分标的在某个时间更新
```

估值应使用每个持仓标的的最新已知合法价格。

需要维护：

```text
latest_mark_price_by_instrument
```

不得将没有当前 Bar 的标的市值置零。

## 9.3 无价格

持仓存在但没有合法估值价格时：

```text
产生诊断
不得静默按 0 估值
```

根据现有 `stop_on_data_error` 决定：

```text
失败
或标记估值不完整
```

---

# 十、收益和回撤

定义：

```text
equity = cash + market_value
```

若现有账户模型还包含：

```text
frozen_cash
margin
debt
receivable
```

则必须复用现有 Account Equity 语义，不得自行简化覆盖。

总收益：

```text
total_return = ending_equity / initial_equity - 1
```

全部使用 Decimal。

最大回撤：

```text
drawdown = equity / running_peak - 1
```

记录：

```text
max_drawdown
max_drawdown_start
max_drawdown_end
```

输出可选择：

```text
equity.parquet 中增加 peak_equity、drawdown
```

或者独立：

```text
drawdown.parquet
```

优先避免重复文件。

## 10.1 零初始资产

如果初始资产为零：

```text
return、drawdown 等比例指标为 None
生成结构化 Warning
```

不得除零。

---

# 十一、已实现盈亏与未实现盈亏

必须先检查现有：

```text
Position
Allocation
Ledger
Account
ExecutionProcessor
```

中的成本基础和盈亏定义。

禁止重复建立另一套相互矛盾的成本价。

如果现有系统使用：

```text
平均成本
```

分析层应沿用。

如果现有系统没有完整成本批次，第一阶段可以：

```text
Trade 视图使用 FIFO
Position/Account 继续使用正式 Ledger 成本语义
```

但必须在文档说明：

```text
Trade analytics pairing 与账户会计成本可能采用不同视图
```

如果这会造成无法解释的差异，应暂缓 Trade PnL，先输出 Execution 和 Equity。

---

# 十二、Collector 设计

推荐：

```python
class OnlyBacktestResultCollector:
    ...
```

Collector 应通过现有事件或只读管理器获取事实。

优先订阅：

```text
Bar processed
Strategy callback completed
Order submitted
Order accepted
Order rejected
Order cancelled
Execution occurred
Position changed
Cash changed
Trading day changed
Runtime failed
```

如果当前 Event Bus 中已有这些事件，严格复用。

如果缺少标准事件，允许添加通用核心事件，但不得：

```text
在插件中创建报告事件
通过 monkey patch 拦截方法
通过解析日志收集
```

Collector 必须：

```text
只读
不可影响撮合
不可改变订单状态
不可提交订单
不可修改 Position
不可吞掉异常
```

---

# 十三、失败诊断

新增：

```text
OnlyBacktestDiagnostics
OnlyBacktestFailure
OnlyBacktestWarning
```

每个 Failure 至少包含：

```text
failure_id
severity
stage
exception_type
message
cluster_id
runtime_id
strategy_id
instrument_id
bar_type
ts_event
trading_day
order_request_id
order_id
execution_id
source_id
sequence
```

字段允许缺失，但必须尽量捕获。

`stage` 使用稳定枚举，例如：

```text
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
REPORTING
ARTIFACT_WRITE
```

不得只保存：

```text
RuntimeError: historical replay failed=165 rejected=0
```

必须保留首个根因。

## 13.1 Replay 汇总

Replay 仍可保留：

```text
accepted
rejected
failed
```

但失败结果必须增加：

```text
first_failure
failure_samples
```

为避免巨大 Manifest：

```text
只在 summary 中保留首个和有限样本
完整列表写 diagnostics.json 或 diagnostics.parquet
```

推荐默认最多：

```text
100 条结构化 failure
```

超出后记录：

```text
truncated=true
total_failure_count
```

## 13.2 异常堆栈

允许在：

```text
diagnostics.json
```

保存 traceback。

但：

```text
traceback 不进入 Determinism Fingerprint
绝对路径不进入 Determinism Fingerprint
```

因为不同机器路径不同。

---

# 十四、标准输出产物

运行目录：

```text
<user_data>/runs/<engine_id>/<run_id>/
```

建议：

```text
manifest.json
summary.json
diagnostics.json
data_manifest.json
orders.parquet
executions.parquet
trades.parquet
positions.parquet
equity.parquet
signals.parquet
```

不是所有文件都必须非空。

当没有交易时：

```text
orders.parquet
executions.parquet
trades.parquet
```

应选择以下统一策略之一：

方案 A：

```text
生成带稳定 Schema 的空 Parquet
```

方案 B：

```text
不生成文件，在 artifact manifest 中标记 row_count=0、path=None
```

推荐方案 A，因为更利于后续分析工具稳定读取。

但必须遵循当前 Storage 设计。

## 14.1 summary.json

至少包含：

```json
{
  "schema_version": 1,
  "run_id": "...",
  "engine_id": "...",
  "status": "COMPLETED",
  "started_at": "...",
  "finished_at": "...",
  "cluster_count": 1,
  "data": {},
  "strategy": {},
  "orders": {},
  "executions": {},
  "positions": {},
  "performance": {},
  "diagnostics": {},
  "artifacts": {},
  "determinism_fingerprint": "...",
  "result_fingerprint": "..."
}
```

## 14.2 data_manifest.json

至少包含：

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
content_fingerprint
price_adjustment
adjustment_reference
schema_version
time_semantics_version
```

必须复用 Historical Cache 的已有事实。

不得由 Result Collector 自行扫描 Cache 目录猜测。

## 14.3 positions.parquet

至少记录：

```text
ts_event
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

如果当前 Position 不支持某字段，用 nullable Schema。

---

# 十五、信号输出

当前 MACD Strategy 已维护自定义：

```text
signals
callback_count
signal_state
```

本任务应建立通用信号输出边界。

推荐定义：

```python
@dataclass(frozen=True, slots=True)
class OnlyStrategySignalRecord:
    signal_id: str
    strategy_id: OnlyStrategyId
    instrument_id: OnlyInstrumentId | None
    signal_type: str
    ts_event: datetime
    payload: Mapping[str, OnlyJsonValue]
    related_order_request_id: OnlyOrderRequestId | None
```

Strategy 可通过受限 Context：

```python
context.strategy.results.record_signal(...)
```

或现有等价接口记录。

不要让 Collector 解析：

```text
build_result_extension()["signals"]
```

中的任意字典结构来形成标准表。

MACD 示例应迁移到标准信号记录接口，同时可以保留兼容扩展。

输出：

```text
signals.parquet
```

至少包含：

```text
signal_id
cluster_id
strategy_id
instrument_id
signal_type
ts_event
related_order_request_id
payload_json
```

---

# 十六、Artifact Manifest

新增或扩展现有 Manifest：

```text
OnlyBacktestArtifactManifest
OnlyArtifactDescriptor
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
created_at
```

注意：

```text
绝对路径不进入结果指纹
created_at 不进入结果指纹
临时路径不进入结果指纹
```

运行结果可以展示绝对 Manifest 路径，但持久化身份只用相对路径。

---

# 十七、Fingerprint

当前已有：

```text
determinism_fingerprint
Historical Data content_fingerprint
```

本任务增加：

```text
result_fingerprint
```

`result_fingerprint` 应基于稳定规范内容：

```text
Run Config Canonical Form
Data Content Fingerprint
排序后的订单事实
排序后的成交事实
最终账户状态
净值序列
统计结果
```

不得包含：

```text
run_id
started_at
finished_at
绝对路径
PID
hostname
Python 临时对象 repr
traceback 绝对路径
文件创建时间
```

必须保证：

```text
同一配置
同一数据
同一代码语义
同一事件顺序
```

重复运行时：

```text
result_fingerprint 一致
```

即使：

```text
run_id 不同
目录不同
运行时间不同
```

## 17.1 失败结果

失败运行也可生成：

```text
failure_fingerprint
```

但不要把不稳定 traceback 文本放进去。

可以基于：

```text
stage
exception_type
规范化 message
事件序号
instrument
ts_event
```

---

# 十八、CLI 输出

保持 CLI 默认输出简洁 JSON。

成功时至少增加：

```json
{
  "status": "COMPLETED",
  "run_id": "...",
  "cluster_count": 1,
  "bar_count": 500,
  "signal_count": 12,
  "order_count": 8,
  "execution_count": 8,
  "trade_count": 4,
  "initial_equity": "1000000.00 CNY",
  "ending_equity": "1035000.00 CNY",
  "total_return": "0.035",
  "max_drawdown": "-0.082",
  "determinism_fingerprint": "...",
  "result_fingerprint": "...",
  "summary_path": "...",
  "manifest_path": "..."
}
```

失败时至少增加：

```json
{
  "status": "FAILED",
  "failure_count": 165,
  "first_failure": {
    "stage": "MARKET_DATA_PIPELINE",
    "exception_type": "OnlyMarketDataPipelineError",
    "message": "...",
    "instrument_id": "600000.XSHG",
    "ts_event": "..."
  },
  "diagnostics_path": "..."
}
```

CLI 不得输出整个订单列表和净值曲线。

---

# 十九、配置

检查当前：

```yaml
output:
  formats:
    - JSON
```

在不破坏兼容性的前提下扩展：

```yaml
output:
  formats:
    - JSON
    - PARQUET
  artifacts:
    summary: true
    diagnostics: true
    orders: true
    executions: true
    trades: true
    positions: true
    equity: true
    signals: true
  diagnostics:
    max_failure_records: 100
    include_traceback: true
```

如果当前输出配置已有类似类型，严格复用。

默认必须适合正式回测：

```text
summary 开启
diagnostics 开启
orders 开启
executions 开启
trades 开启
equity 开启
positions 可配置
signals 可配置
```

不得要求用户手动开启 summary。

---

# 二十、多 Cluster 聚合

必须区分：

```text
Cluster-level result
Engine-level aggregate result
```

如果多个 Cluster 使用独立账户：

```text
不能简单相加不同币种
```

第一阶段只对同一 Base Currency 进行聚合。

不同币种时：

```text
Aggregate monetary statistics = None
产生 MULTI_CURRENCY_AGGREGATION_UNAVAILABLE Warning
保留每个 Cluster 独立结果
```

多个 Cluster 共享同一账户时：

```text
账户级 Equity 不能被重复加总
```

必须通过：

```text
account_id
```

去重。

不能把每个 Strategy Ledger 的虚拟资金和 Broker Account 资金混为一谈。

---

# 二十一、成功与失败状态

定义清晰状态：

```text
COMPLETED
COMPLETED_WITH_WARNINGS
PARTIALLY_FAILED
FAILED
CANCELLED
```

若现有状态枚举不同，优先复用。

建议：

```text
所有 Cluster 成功 → COMPLETED
成功但有非致命诊断 → COMPLETED_WITH_WARNINGS
部分 Cluster 成功、部分失败 → PARTIALLY_FAILED
所有 Cluster 失败或 Engine 致命失败 → FAILED
```

失败运行仍应写出：

```text
manifest.json
summary.json
diagnostics.json
已有的部分流水
```

Artifact Writer 自身失败时：

```text
不得覆盖原始运行失败
应追加 REPORTING/ARTIFACT_WRITE 诊断
```

---

# 二十二、原子写与文件安全

结果产物应使用：

```text
staging
fsync/flush（按现有存储能力）
atomic replace
```

至少保证：

```text
summary.json 不出现半文件
Parquet 不出现只写一半却被 Manifest 引用
Manifest 最后写入
```

建议顺序：

```text
写所有明细到 staging
→ 回读验证
→ 计算 Hash
→ 写 summary
→ 写 diagnostics
→ 写 artifact manifest
→ 原子发布
```

如果当前 Run 目录在运行开始时已经创建，则可以在子目录中使用：

```text
artifacts.staging
```

发布到：

```text
artifacts
```

但需遵循现有 user_data 目录设计。

---

# 二十三、Decimal 和 Parquet

金额、价格、数量不得转换为二进制 float。

推荐 Parquet 表示：

```text
Decimal128
```

或使用现有确定性 JSON/raw integer 表示方式。

必须确保：

```text
写入
读取
重新计算统计
```

不产生精度漂移。

测试：

```text
0.1
0.01
大额成交
多次手续费累加
```

结果应完全一致。

---

# 二十四、测试要求

## 24.1 无交易

输入有 Bar，但 Strategy 不产生信号。

验证：

```text
status=COMPLETED
bar_count > 0
callback_count > 0
signal_count=0
order_count=0
execution_count=0
trade_count=0
ending_equity=initial_equity
total_return=0
max_drawdown=0
空明细 Schema 可读
```

## 24.2 确定性买卖

实现测试 Strategy：

```text
第 10 根 Bar 买入
第 20 根 Bar 卖出
```

验证：

```text
1 个 entry
1 个 exit
2 个 order
2 个 execution
1 个 round-trip trade
最终无持仓
现金和净值计算正确
```

## 24.3 MACD 示例

使用 Synthetic 可控价格序列产生：

```text
GOLDEN_CROSS
DEATH_CROSS
```

验证：

```text
Signal
Order
Execution
Trade
Equity
Statistics
```

完整链。

## 24.4 部分成交

若当前 Virtual Broker 已支持部分成交：

```text
一个订单多个 Execution
Trade Builder 正确合并
Order 最终状态正确
```

若不支持，明确跳过并说明，不要伪造测试。

## 24.5 T+1

验证：

```text
T 日买入
T 日 available=0
T+1 available 恢复
T 日卖出请求行为符合现有规则
```

## 24.6 多 Cluster

至少测试：

```text
两个 Cluster
独立 Strategy
独立账户
统一 Engine summary
各自独立产物
Aggregate 正确
```

## 24.7 共享账户

如果当前支持：

```text
两个 Cluster 共享一个 Account
```

验证不会重复统计账户净值。

## 24.8 Replay 失败

构造第 N 根 Bar 触发 Strategy 异常。

验证：

```text
failed_count
first_failure.stage
first_failure.ts_event
first_failure.instrument_id
exception_type
message
diagnostics.json
部分 equity/orders 仍可输出
```

## 24.9 Pipeline 失败

构造：

```text
ts_event != bar_end
```

验证真实根因不会被：

```text
historical replay failed=N
```

完全遮蔽。

## 24.10 Artifact 写失败

注入文件写入异常。

验证：

```text
原始回测结果不被改写
追加 ARTIFACT_WRITE failure
不存在错误引用的 Manifest
```

## 24.11 指纹

同一输入运行两次：

```text
run_id 不同
路径不同
started_at 不同
```

但：

```text
determinism_fingerprint 一致
data content_fingerprint 一致
result_fingerprint 一致
Bar 序列一致
Order 序列一致
Execution 序列一致
Equity 序列一致
Statistics 一致
```

## 24.12 Cache Online / Offline

第一次：

```text
Tushare / Fake Provider
→ Cache 写入
→ 回测
```

第二次：

```text
CACHE_ONLY
无 Token
→ Cache 读取
→ 回测
```

验证：

```text
result_fingerprint 一致
trade records 一致
equity curve 一致
summary statistics 一致
```

---

# 二十五、真实 Tushare 日线验收

使用：

```text
OnlyAlpha-examples/examples/tushare_daily_backtest/config.yaml
```

正式执行：

```bash
uv run onlyalpha run \
  --config OnlyAlpha-examples/examples/tushare_daily_backtest/config.yaml \
  --user-data OnlyAlpha-examples/user_data
```

必须记录：

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
total_return
max_drawdown
rows_fetched
rows_read
cache_hit
content_fingerprint
determinism_fingerprint
result_fingerprint
summary_path
manifest_path
```

随后删除 Token，执行：

```bash
uv run onlyalpha run \
  --config OnlyAlpha-examples/examples/tushare_daily_backtest/config_cache_only.yaml \
  --user-data OnlyAlpha-examples/user_data
```

必须对比：

```text
Bar Count
Signals
Orders
Executions
Trades
Equity Curve
Final Positions
Ending Equity
Performance Statistics
Result Fingerprint
```

如果真实 Tushare 服务不可用：

```text
不得虚构成功结果
必须使用已有 Cache 完成 CACHE_ONLY 验收
如果也无 Cache，则执行 Fake Provider/Synthetic 完整纵切面
并明确报告真实验收未执行原因
```

---

# 二十六、Examples 更新

更新：

```text
OnlyAlpha-examples/examples/tushare_daily_backtest/README.md
```

增加：

```text
运行命令
summary.json 位置
orders.parquet 说明
executions.parquet 说明
trades.parquet 说明
equity.parquet 说明
diagnostics.json 说明
结果字段解释
首次在线运行
CACHE_ONLY 重跑
指纹一致性验证
```

增加一个确定性结果示例：

```text
examples/deterministic_trade_report/
```

使用 Synthetic 数据和固定第 N 根买卖 Strategy，确保任何开发环境都能看到：

```text
非零订单
非零成交
完整 Trade
完整 Equity
完整 Summary
```

禁止正式验收只依赖外部 Tushare 服务。

---

# 二十七、文档

至少新增：

```text
docs/backtest_results.md
docs/backtest_artifacts.md
docs/performance_statistics.md
docs/diagnostics.md
docs/adr/xxxx-backtest-result-and-artifact-model.md
```

必须说明：

```text
Order 与 Execution 的区别
Execution 与 Trade 的区别
Equity 估值时点
多标的估值规则
PnL 规则
Trade 配对规则
结果指纹范围
失败产物行为
空产物行为
多 Cluster 聚合
多币种限制
```

更新：

```text
ROADMAP.md
HANDOFF.md
README.md
```

路线图应把：

```text
Phase 2B 真实历史数据
```

更新为基础纵切面已完成。

本任务完成后：

```text
Phase 2D 回测分析与报告
```

应标记为：

```text
基础纵切面完成
```

不能标记为完整完成，因为尚未包含完整归因、Benchmark、参数实验和高级统计。

---

# 二十八、兼容性

不得破坏：

```text
现有 Synthetic 回测
现有 MiniQMT 插件
现有 Tushare 插件
现有 Virtual Broker
现有 Strategy Result Extension
现有 CLI JSON 字段
现有 Historical Cache
现有 Determinism Fingerprint
```

允许新增字段，但不得无迁移直接删除现有字段。

如果 Result 类型签名变化影响插件：

```text
提供默认值
或兼容构造器
```

---

# 二十九、禁止事项

禁止：

```text
使用 float 计算账户收益
从日志解析订单
让 Strategy 计算最大回撤
让 Broker 写 summary.json
让 Tushare 插件定义 OnlyBacktestStatistics
把 run_id 放入 result_fingerprint
把绝对路径放入 result_fingerprint
把 traceback 放入 result_fingerprint
将 Execution 数量直接视为 Trade 数量
忽略部分成交
静默按 0 估值未知价格持仓
在多 Cluster 共享账户时重复计算 Equity
为显示好看虚构 Sharpe
把失败运行的所有部分结果直接丢弃
使用 Path.cwd() 推断 user_data
绕过 onlyalpha run
只添加单元测试而不做正式纵切面
只输出 JSON 而没有 Parquet 明细
把巨大交易列表放入 manifest.json
```

---

# 三十、质量门禁

执行：

```bash
uv run --directory OnlyAlpha pytest -q
uv run --directory OnlyAlpha ruff check .
uv run --directory OnlyAlpha ruff format --check .
uv run --directory OnlyAlpha mypy

uv run --directory OnlyAlpha-plugins pytest -q
uv run --directory OnlyAlpha-plugins ruff check .
uv run --directory OnlyAlpha-plugins ruff format --check .

uv run --directory OnlyAlpha-examples pytest -q
uv run --directory OnlyAlpha-examples ruff check .
uv run --directory OnlyAlpha-examples ruff format --check .
```

如果某仓库没有 pytest：

```text
明确报告
不要虚构
```

检查：

```bash
git diff --check
```

验证：

```text
Python 3.12
Python 3.13
Windows
Linux
macOS
```

当前环境无法执行的平台必须明确列出。

---

# 三十一、验收标准

以下全部完成才算任务完成：

```text
标准 OnlyBacktestResult
Cluster-level Result
Data Statistics
Strategy Statistics
Order Statistics
Execution Statistics
Position Statistics
Performance Statistics
结构化 Diagnostics
首个真实根因可见
orders.parquet
executions.parquet
trades.parquet
equity.parquet
positions.parquet
signals.parquet
summary.json
diagnostics.json
data_manifest.json
Artifact Manifest
结果文件 Hash
result_fingerprint
空交易回测正确
确定性买卖回测正确
MACD 纵切面正确
Replay 失败诊断正确
多 Cluster 结果正确
共享账户不重复
在线/Cache-only 结果一致
真实 Tushare 或已有 Cache 纵切面
README 和 ADR 完成
质量门禁通过
```

---

# 三十二、最终报告格式

完成后输出中文报告：

## 1. 修改前分析

列出当前结果链、缺口和复用边界。

## 2. 核心模型

列出新增或修改的 Result、Statistics、Diagnostics 和 Artifact 类型。

## 3. 事件和 Collector

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

## 4. 净值与收益语义

明确：

```text
估值时点
Mark Price
Cash
Market Value
Equity
Realized PnL
Unrealized PnL
Return
Drawdown
```

## 5. Trade 配对

明确：

```text
FIFO 或其他规则
部分成交
分批买卖
费用归属
```

## 6. 输出产物

逐个说明文件、Schema、行数和用途。

## 7. Fingerprint

明确：

```text
包含什么
排除什么
两次运行是否一致
```

## 8. Diagnostics

展示成功捕获的一个结构化故障示例。

## 9. 测试

列出真实命令和真实结果。

## 10. Tushare 验收

列出：

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
```

对比在线和 CACHE_ONLY。

## 11. 未完成项

只列本任务范围内尚未完成内容。

不得虚构测试、交易或收益结果。

---

# 三十三、任务定位

本任务不是完整的量化分析平台。

本任务暂不实现：

```text
Benchmark
Alpha/Beta
行业归因
Brinson 归因
IC 分析
参数优化
Monte Carlo
Walk Forward
HTML 报告
图形界面
Web API
实时监控
Live 交易
多进程回测
分布式回测
```

但设计必须为这些后续模块提供稳定输入。

最终目标是：

> 让 OnlyAlpha 的每一次回测，不论成功、无交易、部分失败或完整失败，都能留下结构化、确定性、可审计、可比较的结果产物，并能够证明真实 Tushare 日线回测与 CACHE_ONLY 离线重放产生完全一致的交易事实和净值结果。
