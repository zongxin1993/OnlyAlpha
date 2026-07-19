# OnlyAlpha 工程交接说明

> 更新时间：2026-07-19（Asia/Shanghai）  
> 当前任务：`prompts/Multi-Market_Conformance_Packs_and_Product_Integration.md`
> Multi-Market Conformance Packs and Product Integration

## Multi-Market Conformance Packs and Product Integration（进行中，2026-07-19）

### 本轮完成

- 正式 exact Scenario DataSource、Action Strategy 和 `OnlyEngine` Scenario Runner；Generic T0 场景重复运行 result fingerprint 一致；
- 修复 Virtual Broker fractional quantity snapshot 与货币精度，修正 INFO reconciliation 被误判为 blocking failure；
- Collector/Backtest Artifact 增加 profile timeline、compiled identity 和 market decision；
- 删除旧手工 capability coverage Pack，新增版本化 Pack Domain/Registry、Conformance Runner、coverage、stability/release evaluator；
- 增加 Scenario/Market CLI、JSON Query DTO、审计报告、ADR 0028 和产品文档。

### 正式通过

- `CN_A_SHARE_T1_ENGINE@1.0`、`GENERIC_T0_CASH_ENGINE@1.0`、`GENERIC_CRYPTO_SPOT_ENGINE@1.0`：正式 Engine Scenario PASSED；
- Generic T0 自动 Pack Runner 测试 PASSED；Futures/Cross-Version 尚未通过，因此五 Pack 门禁未完成；
- BACKTEST 可自动执行；PAPER/LIVE/SHADOW 只规划并返回明确 capability error；
- 所有内建 Profile 仍为 Experimental。

### 明确未完成（不得宣称任务完成）

- CN A-share 完整 capability Pack、Futures SELL OPEN/BUY CLOSE Margin 事务链、Crypto 完整 Pack、Cross-Version Pack 尚未完成；
- Settlement/Margin/Fee 标准 Collector 事实仍未由完整交易事务生成；Conformance CLI/repository/query 尚未产品化；
- 因上述门禁未满足，没有 Profile 可升级 Stable，也没有五 Pack 全部通过证据；
- Plugins/Examples 三仓门禁、US/HK、Perpetual、Web Server、在线 Tushare 未执行。

### 本轮真实验证

- `../.venv/bin/pytest -q`：391 passed；
- 定向 Scenario/CLI/Conformance：12 passed；
- `../.venv/bin/ruff check .`：通过；`../.venv/bin/mypy`：352 source files 通过；`git diff --check`：通过；
- `../.venv/bin/ruff format --check .`：未通过，仅剩既有 `tests/market_data/test_pipeline_dispatch.py` 需格式化；本轮文件已格式化。

## Deterministic Multi-Market Scenario Framework（2026-07-19）

### 本轮完成

- 新增修改前源码审计报告和 ADR 0027；
- 新增独立 `onlyalpha.scenario` 包：不可变 Domain、稳定错误码、严格 YAML/JSON Parser、runtime-neutral Command
  planning、只读 Assertion Engine 和 canonical input fingerprint；
- Parser 拒绝未知字段、非字符串 Decimal、非 UTC 时间、重复 Action/Expectation 和缺失引用，并通过正式
  `OnlyClusterRunConfig.from_mapping()` 复用 Market/Reference 配置语义；
- BACKTEST/PAPER/LIVE/SHADOW 使用相同 Action/Command；后三者明确返回
  `SCENARIO_RUNTIME_MODE_UNSUPPORTED`，不降级为 Backtest；
- 删除 production 包中无调用方、明确 test-only 的 `OnlyNoOpExecutionReconciliationPort`；
- 新增/更新 Scenario、README、Runtime、Backtest、Results、Conformance、Roadmap 和 AGENTS 文档。

### 明确未完成（不得宣称）

- Action Strategy、exact-bar provider、正式 Engine Scenario Runner 和 Scenario Artifact 尚未实现；
- Collector 的 profile timeline、compiled identity、market decision、settlement、margin、fee、action 投影尚未收口；
- A-share T+1、Generic T0、Generic Futures、Crypto Spot、跨 Profile version 五个 Engine 场景尚未运行；
- Futures HEDGING Position、Margin/Account 事务链以及 Futures/Crypto 产品 Config 装配仍是正式内核缺口；
- 重复运行 result fingerprint、零行 Scenario schema、完整 Runtime factory contract 尚未完成；没有 Profile 可升级 Stable。

### 本轮真实验证

- `../.venv/bin/pytest -q tests/scenario`：6 passed；
- `../.venv/bin/pytest -q`：388 passed；
- `../.venv/bin/ruff check .`：通过；
- `../.venv/bin/mypy`：347 source files 通过；
- `git diff --check`：通过；
- `../.venv/bin/ruff format --check .`：未通过，仅报告既有文件 `src/onlyalpha/market/runtime_rules.py` 和
  `tests/market_data/test_pipeline_dispatch.py` 需要格式化；本轮 Scenario 文件已通过 format check。

### 下一步

1. 在现有 DataSource SPI 上提供 exact-bar Scenario Source，以正式 Strategy/Factor Factory 装配 Action Strategy；
2. Runner 只调用 `OnlyEngine.run()`，把 Backtest Result facts 投影到 Assertion；
3. 先补 Collector 再完成 A 股/T0；修复正式 Futures/Crypto 内核后再完成对应场景；
4. 扩展现有 Artifact Writer，最后执行五场景、确定性和全仓门禁。

## Unified Market Runtime Rules（2026-07-19）

### 本轮实现

- 新增 ADR 0026 和修改前审计报告；ADR 0024/0025 已标记部分被替代；
- 删除 `OnlyMarketSimulationConfig` 和可选旧路径，产品配置必须显式使用 `market`；旧 key 拒绝加载；
- 新增 Compiler、immutable Compiled Rules、compiled identity/fingerprint 和 `OnlyMarketRuleEngine`；引擎按
  Instrument/Trading Day/Reference fingerprint 解析与缓存规则；
- Composition Root 持有 Registry/Compiler，Backtest Factory 完成 Config → Registry → Compiler → Rule Engine →
  Runtime 注入；
- Risk 不再依赖旧 Market Rule Mapping；Virtual Broker 不再按日期写死 T+1，而是应用 Settlement
  Instruction；ExecutionProcessor 通过 Trade Instruction 选择 Position settlement bucket；
- 新增 Runtime-owned `OnlySettlementManager` 和 `OnlyMarginManager`，覆盖四维结算和
  reserve/occupy/release 生命周期；
- 删除旧 `OnlyMarketRule` Runtime/DataSource 接口，增加 Profile import 边界门禁。

### 明确未完成（不得宣称）

- Futures HEDGING 的生产 Position Manager 双向写入、Margin 与 Account 的完整事务链尚未收口；
- Collector 的 Profile timeline/compiled identity/market decision/settlement/margin/fee 全量事实投影尚未收口；
- Scenario YAML DSL、Conformance Packs、US/HK、Tushare Profile 自动加载、Web/CLI market commands 未实现。

### 本轮真实门禁

- `../.venv/bin/pytest -q`：382 passed；
- `../.venv/bin/ruff check .`：通过；
- `../.venv/bin/mypy`：340 source files 通过；
- `git diff --check`：通过；
- `ruff format --check .` 仍只被未修改的既有文件 `tests/market_data/test_pipeline_dispatch.py` 阻塞。

## Versioned Market Profiles and Conformance Suite（2026-07-19）

### 本轮完成

- 新增 `OnlyMarketProfileFamily/Version/Status/Request/Registry`，支持有效期不重叠校验、按日期 Auto 解析、Pinned Version、Removed 拒绝和 Deprecated 固定加载边界；
- 新增完整 Capability Set、受限 Override Policy、Resolved Profile 与 Rules Manifest；Reference/Override/Capability 进入确定性规则指纹；
- 该轮的 optional/Legacy 配置结论已被 ADR 0026 和本轮必填 `market` 设计替代；
- 新增 `OnlyOrderFeeAccumulator`，以累计应收减累计已收避免多 Fill 重复最低佣金；
- 新增 Conformance Pack/Scenario/Registry 身份与 Stable Capability coverage gate；
- 新增 ADR 0025 及 Registry、配置、Capability、Conformance、DSL、Override、Web Query 文档。

### 明确未完成

- Profile 尚未装配入 Runtime Factory、Risk、Virtual Broker、ExecutionProcessor、Settlement/Margin Manager 和 Collector；
- Scenario DSL Parser、Synthetic Reference Provider、Deterministic Action Strategy、Engine Runner、Assertion Engine 尚未实现；
- A 股、Generic T0/Futures/Crypto 以及 US/HK Experimental Packs 尚未创建和运行；所有内建版本因此保持 Experimental；
- Profile/Scenario Artifact、timeline、Query DTO/Port、CLI、OnlyAlpha-examples 和 Tushare Profile 自动加载尚未交付；
- Plugins/Examples 未修改，三仓完整门禁和在线 Tushare 验收尚未执行。

### 本轮已验证

- `tests/market`: 8 passed；
- config + market 定向：17 passed；
- 核心全量 `374 passed`；Ruff lint 全仓通过；Mypy `335 source files` 通过；`git diff --check` 通过；
- 全仓 `ruff format --check .` 仍仅被既有未修改的 `tests/market_data/test_pipeline_dispatch.py` 阻塞。

`uv` 使用新 cache 时因沙箱网络无法下载依赖；随后使用工作区既有 `../.venv/bin/*` 完成上述真实验证。

## 0. Multi-Market Simulation Framework（2026-07-19）

### 已完成

- 完整审计 Position/T+1/Futures/Crypto/Account/Broker/Results，确认复用现有 Instrument、Calendar、Position 与 Result；
- 新增 `onlyalpha.market`：版本化 Profile Resolver、Settlement 四维时间、LONG_ONLY/NETTING/HEDGING、Position Effect、
  Short Rule、Margin、Session Phase、Reference、Price/Quantity/Fee/Liquidity/Slippage/Matching；
- 内建 `CN_A_SHARE_CASH@2025.1`、`GENERIC_T0_CASH`、`GENERIC_MARGIN_FUTURES`、
  `GENERIC_24X7_CRYPTO_SPOT`；
- A 股基础规则覆盖 Reference 驱动的主板 10%、ST 5%、创业板/科创板 20%、停牌门禁、整手买入、零股清仓、
  最低佣金、卖出印花税、过户费、T+1 资产可用与现金当日交易可用；未知板块 strict error；
- 扩展现有 `OnlyBacktestFacts` 和 Artifact Writer：`settlements.parquet`、`margin.parquet`、
  `market_rule_decisions.parquet`，Cash Profile 保持零行稳定 Schema；
- 新增 ADR 0024 与八份专题文档，更新 roadmap 和仓库协作规则；
- 定向测试真实结果：22 passed（market + artifact + result）；核心全量 `374 passed`，Ruff lint、Mypy（333 source
  files）、本次修改文件 format check 与 `git diff --check` 通过。全仓 format check 仍仅被既有未修改文件
  `tests/market_data/test_pipeline_dispatch.py` 阻塞。

### 明确未完成（不得宣称正式支持）

- Profile 尚未装配进 Runtime config/factory、Virtual Broker 与 ExecutionProcessor；新 Result 事实目前只具备模型/Artifact，
  Collector 尚未从交易处理链生成记录；
- Generic Futures 的生产 SELL OPEN/BUY CLOSE、margin 占用/释放与 A 股 T+0/T+1 正式 Engine 纵切面尚未完成；
- 跨 Fill 最低佣金 accumulator、完整 Reference Provider/Repository、四个 OnlyAlpha-examples 示例尚未完成；
- Tushare 配置显式 Profile、在线/CACHE_ONLY 对照以及 Plugins/Examples 三仓门禁尚未执行；
- 港股、美股、正式期货、Perpetual、Borrow/Funding/Liquidation、Tick/Order Book 均仅预留。

### 下一步顺序

1. 已由 ADR 0026 完成必填 `market` 配置迁移；
2. Runtime 解析 Reference/Profile，在 Risk 与 Broker 分别执行 pre-trade/match-time 决策；
3. ExecutionProcessor 消费 settlement instruction、position effect、margin change、fee breakdown；
4. Collector 生成三类新增事实，完成指纹覆盖；
5. 通过正式 Engine 增加四个示例，再执行 Tushare 与三仓完整门禁。

## 1. 修改前分析

### 1.1 `onlyalpha run` 调用链

正式入口为：

```text
CLI
→ OnlyEngine.add_cluster_from_file
→ OnlyRuntimePlanner / OnlyEngineRunAssembler
→ OnlyBacktestRuntime.run
→ OnlyBacktestRunPlan.execute
→ HistoricalDataSource.load_bars
→ OnlyHistoricalReplayService
→ OnlyMarketDataProcessor
→ OnlyMarketDataPipeline
→ OnlyStrategyBarDispatcher
→ Cluster Indicator → Factor → Strategy
→ OrderService / Risk
→ Virtual Broker
→ Broker inbound queue
→ OnlyExecutionProcessor
→ Order / Position / Allocation / StrategyLedger / Account
→ OnlyBacktestRunPlan._build_result
→ OnlyEngineResultExporter
```

CLI 不直接读取 DataFrame、Cache 或 Manager。Engine 是产品入口，Runtime 拥有交易状态，Exporter 是当前唯一 run 文件写入边界。

### 1.2 现有结果对象与聚合

- `OnlyEngineRunResult`：`engine_id/run_id/status/cluster_results/failures/manifest_path/determinism_fingerprint`。
- `OnlyRuntimeResult`：协议边界；Backtest 和 Unsupported Result 实现它。
- `OnlyBacktestResult`：Run/Data/Execution/Performance 摘要、最终 Position/Allocation/Ledger/Account、全部 Order、Broker Trade、Cluster 扩展、不变量和确定性指纹。
- `OnlyClusterResult`：仅包含 `cluster_id`、Strategy 任意扩展、最终 Factor Snapshot 和 Indicator Diagnostics，不是提示词要求的 Cluster-level 标准统计结果。
- 共享 Runtime 的一个 `OnlyBacktestResult` 被 Engine 按 Cluster 投影；当前投影仍可能携带共享账户级完整结果，没有正式的 account_id 去重聚合器。

现有 `OnlyBacktestResult` 是应扩展/迁移的复用边界，不能另建同义平行体系。但它仍把订单和成交数组放入顶层 JSON，且 `OnlyBacktestExecutionSummary.trade_count` 实际取自 Broker `query_trades()` 的成交事实数量，不是 Round-Trip Trade 数量。

### 1.3 状态真值位置

- Order：Runtime-owned `OnlyOrderManager` / Repository，结束时 `snapshot_all()`。
- Broker 成交：Virtual Gateway Trade Store，结束时 `query_trades(account_id)`；当前模型命名为 `OnlyBrokerTradeSnapshot`，语义是 Execution/Fill。
- Position：`OnlyPositionManager`；Cluster 归因量在 `OnlyPositionAllocationManager`。
- Strategy 虚拟账：`OnlyStrategyLedgerManager`，每 Cluster 一个 Ledger。
- Account：`OnlyAccountManager`，当前产品回测要求一个共享现金账户。
- Execution 审计：`OnlyExecutionAuditStore` 与 `runtime.broker_results`。
- Market Data 审计：`OnlyMarketDataAuditStore`、Replay Event 和 Historical Cache Manifest。

Virtual Broker 在 `on_bar()` / `run_due()` 中撮合并把标准 Broker Update 放入 Runtime inbound queue；只有 `OnlyExecutionProcessor` 能依次修改 Order、Position、Allocation、Ledger、Account，并在不变量通过后发布事实。

### 1.4 Strategy 扩展与信号

Strategy 目前只通过 `build_result_extension()` 返回任意 Mapping。MACD 示例把 `signals/callback_count/signal_state` 存在自身列表并导出；核心没有 `OnlyStrategySignalRecord` 或受限的 `record_signal()` 接口。Collector 不能把任意扩展 JSON 当作标准信号表，需先建立通用信号记录边界，同时保留旧扩展兼容性。

### 1.5 Manifest、输出配置和 user_data

- 运行目录已统一为 `<user_data>/runs/<engine_id>/<run_id>/`，由 `OnlyUserDataLayout` 计算，不依赖 `Path.cwd()`。
- 当前 `manifest.json` 只有 schema、Engine/Run ID、Engine 确定性指纹和 Cluster 配置指纹。
- 当前产物是 Engine/Runtime/Cluster JSON、`orders.json`、Portfolio Snapshot、配置副本和简短 Markdown；没有 Artifact Descriptor、文件 Hash、行数、`summary.json` 顶层标准格式、`diagnostics.json`、`data_manifest.json` 或 Parquet 报告。
- `output.formats` 只解析 JSON/CSV/PARQUET 枚举集合与 overwrite，但 Exporter 尚未按该配置生成正式报告产物，也没有 artifacts/diagnostics 子配置。
- JSON 写入直接 `write_text`，不是 staging + atomic replace；Manifest 还是最先写入。

### 1.6 Fingerprint

Runtime `determinism_fingerprint` 基于 Backtest Result 投影以及 Market Data、Clock、Factor、Indicator、Execution Audit 和 Event Trace；Engine 再对 Cluster 投影构造 Engine 指纹。当前没有独立 `result_fingerprint`、失败指纹或明确稳定规范，也没有把 Historical Cache `content_fingerprint` 纳入标准结果对象。run_id/运行时间没有进入 Runtime 指纹，但仍需为新结果指纹建立显式包含/排除测试。

### 1.7 结束状态与失败传播

结束时通过 Manager 的 immutable snapshot 读取现金、权益、持仓、Allocation 和 Ledger。收益/最大回撤来自现有 Ledger Performance；没有逐 Bar Equity 序列，无法审计最大回撤路径。

Replay 只汇总 processed/applied/duplicate/gap/rejected/failed。`OnlyBacktestRunPlan.execute()` 遇到 failed/rejected 后抛出 `RuntimeError("historical replay failed=N rejected=M")`；Engine 捕获后只保存字符串。Pipeline 内虽有带异常类型/消息的 failure fact，Dispatcher 也有 Cluster callback failure，但没有贯通到 CLI 的结构化首个根因、阶段、Instrument、Bar Type、时间和 traceback。

### 1.8 现有分析类型能力

- 已有 Account/Position/Ledger 的现金、权益、已实现/未实现盈亏和 Ledger maximum drawdown。
- 已有 Broker 成交事实，但没有标准 `OnlyExecutionRecord`、FIFO Round-Trip Trade Builder、Trade PnL、Equity Point、Drawdown Curve、完整 Performance Statistics 或 Result Collector。
- 当前金额、价格和数量真值使用 `Decimal` 领域值，可复用；不得转成 float。

### 1.9 Event Bus 与 Collector 适配性

Event Bus 已发布 Order、Execution、Position、Ledger、Account、Risk 和 Market Data 的过去式事实，适合 Collector 做只读订阅；它不应驱动状态机。仍缺少标准 Signal、Equity Snapshot、Replay 根因上下文等采集事实。Collector 还应直接读取只读 Manager/Audit/Cache 结果，不能解析日志或让 Broker 生成报告。

当前每根 Bar 的正式边界是：

```text
Replay 推进 Clock
→ Pipeline 校验、缓存、聚合、Indicator、Snapshot
→ before_market_dispatch:
   发布 Market Data facts
   TradingDay settlement
   使用当前 close 对已有持仓估值
   Virtual Broker.on_bar 匹配此前订单
   ExecutionProcessor 回灌成交
→ Dispatcher:
   Cluster Indicator → Factor → Strategy
→ after_market_dispatch:
   Virtual Broker.run_due
   ExecutionProcessor 回灌到期更新
   EventBus.drain
```

因此当前估值发生在本 Bar 策略回调和新订单成交之前。正式 Equity Collector 必须明确选择并测试采样点；不能在报告层无依据改成“本 Bar 全部成交后估值”。多标的估值已有“各持仓最新 closed Bar”逻辑，缺价会抛错而不是静默按零。

### 1.10 Tushare 正式入口

在线入口为 `OnlyAlpha-examples/examples/tushare_daily_backtest/config.yaml`，CACHE_ONLY 入口为相邻 `config_cache_only.yaml`，均通过 `onlyalpha run`、插件 Entry Point、核心 Cache 和 Virtual Broker。Token 仅通过临时环境变量传入，未写入仓库、配置、Cache Manifest 或运行结果。

审计发现两个配置目前不可作为严格一致性对照：在线配置结束于 `2025-12-31T16:00Z` 且 `allow_reentry=true`；CACHE_ONLY 结束于 `2025-03-31T16:00Z` 且 `allow_reentry=false`。因此两次成功只能证明在线获取和无 Token 缓存重放均可用，不能证明结果指纹一致。

## 2. 真实 Tushare 在线验收

实际执行正式入口，user_data 使用隔离的 `/tmp/onlyalpha-backtest-result-user-data`，结果：

```text
status                  COMPLETED
run_id                  run-09d797af8d5e4432b8d365054688cfb4
bar_count               243 generated / 243 processed
callback_count          236
signal_count            36
order_count             0
execution_count         0（当前结果对象没有独立字段）
round_trip_trade_count  不可用（当前 trade_count 是 Broker fill 语义）
initial_equity          1000000.00 CNY
ending_equity           1000000.00 CNY
total_return            0E-8
max_drawdown            0
fees                    0 CNY
final_positions         0
cache_row_count         243
cache_hit               false（首次在线获取后写 Cache 并从 Parquet 重读）
content_fingerprint     8589d047e912876c16361e3de16ed28544a570fdec8653f54e258532b63a4980
runtime_fingerprint     5117bbbd669e5b765be714358b949c1e733113f15ccb92b2eb3f9d27991b364e
engine_fingerprint      6f1cbbf122f6891f3d7a064cf76897bfb7c60f87577f5ec8b37120dda3ff1fbd
result_fingerprint      不可用
```

36 个 MACD `GOLDEN_CROSS` 扩展信号均带 buy request ID，但最终没有 Order。这暴露出现有 Strategy/Order 边界需要单独诊断：标准报告不能把信号数量推断为订单数量，也不能虚构交易收益。

## 3. 无 Token CACHE_ONLY 验收

移除环境变量后使用同一 user_data 实际运行成功：

```text
status                  COMPLETED
run_id                  run-e18bd3727a3d4e309318f38f2b0c08e9
bar_count               57 generated / 57 processed
callback_count          50
signal_count            1
order_count             0
execution_count         0（当前结果对象没有独立字段）
initial_equity          1000000.00 CNY
ending_equity           1000000.00 CNY
total_return            0E-8
max_drawdown            0
final_positions         0
cache_hit               true
runtime_fingerprint     d5b4247c4d973014b5880b562a89b43a6a7534f1c75b69daaddabc72a1a6d446
engine_fingerprint      59d7a3b40f6aa8f214b6be469f36d721ffd0d16716d38a9758066e768d9606db
result_fingerprint      不可用
```

两次 Bar、Signal 和 Fingerprint 不同是配置范围和策略参数不同造成，不能判定为缓存非确定性。必须先使两份配置除 cache policy/token 外完全相同，再进行在线/CACHE_ONLY 一致性验收。

## 4. 当前输出产物实证

本次成功运行实际只生成：

```text
manifest.json
engine/config.json
engine/summary.json
runtimes/<runtime_id>/summary.json
runtimes/<runtime_id>/result.json
clusters/<cluster_id>/normalized_config.json
clusters/<cluster_id>/source_config.yaml
clusters/<cluster_id>/fingerprint.txt
clusters/<cluster_id>/summary.json
clusters/<cluster_id>/orders/orders.json
clusters/<cluster_id>/portfolio/snapshot.json
clusters/<cluster_id>/report.md
```

提示词要求的 `summary.json` 顶层规范、`diagnostics.json`、`data_manifest.json`、`orders.parquet`、`executions.parquet`、`trades.parquet`、`positions.parquet`、`equity.parquet`、`signals.parquet`、Artifact Hash/row_count 和 `result_fingerprint` 均尚未实现。

## 5. 本任务范围内未完成项

本轮完成的是严格现状分析、事件边界确认和真实 Tushare/CACHE_ONLY 验收，没有虚构 `backtest_result_summary.md` 所列的大型结果纵切面已经完成。后续实现仍需：

1. 以现有 `OnlyBacktestResult` 为迁移边界，建立 Engine/Runtime/Cluster 标准统计、Diagnostics 与 Artifact Descriptor；避免同义模型。
2. 在 Runtime 生命周期内装配只读 `OnlyBacktestResultCollector`，订阅已有事实，并补充标准 Signal 与确定性 Equity 采样边界。
3. 保留 Replay/Pipeline/Cluster/Execution 首个根因与有限样本，失败时也输出部分结果。
4. 基于真实 Order 状态机统计订单；基于 Broker fill 形成 Execution；用 FIFO 只读配对 Long-only Round-Trip Trade，不能把 fill 数当 Trade 数。
5. 输出稳定 Decimal Parquet Schema、原子发布、文件 Hash、`summary.json`、`diagnostics.json`、`data_manifest.json` 和 Artifact Manifest。
6. 定义不含 run_id、时间、绝对路径和 traceback 的 `result_fingerprint`，并增加重复运行测试。
7. 修正在线/CACHE_ONLY 示例的时间范围和 Strategy 参数，使两者只在 Cache Policy/Token 上不同，再验证 Bar、Signal、Order、Execution、Trade、Equity、Position、统计和结果指纹完全一致。
8. 诊断“36 个买入信号但 0 个 Order”的真实 Strategy/Order 原因；在原因确认前不得声称 MACD 完整交易纵切面通过。
9. 增加无交易、确定性买卖、部分成交能力判断、T+1、多 Cluster、共享账户、Replay/Pipeline/Artifact 失败和 Decimal 精度测试。
10. 补齐提示词要求的回测结果、Artifact、Performance、Diagnostics 文档、ADR、README/ROADMAP 和确定性非外部示例；当前仓库路线图实际路径是 `docs/roadmap.md`，不是根目录 `ROADMAP.md`。

## 6. 验证边界

- 本轮实际环境为 macOS、Python 3.13.11。
- 已执行一次真实 Tushare 在线正式回测和一次无 Token CACHE_ONLY 正式回测，二者均成功。
- 本轮未修改核心、插件或示例代码，未执行三仓全量 pytest/Ruff/Mypy；没有把这些门禁标记为通过。
- 未执行 Python 3.12、Windows、Linux 验证。

## 7. MACD 交易与收益复验（后续修正）

为响应“放宽 MACD 买卖点并校验收益”，已把 Tushare 示例设为 `allow_reentry=true, max_entries=2`，在线与 CACHE_ONLY 配置统一为全年区间。策略现在保存每次 `orders.submit()` 的真实 `created/submitted/order_id/error/risk_rejection`，不再把带 request ID 的 Signal 错当成已创建 Order。

本次发现并修正三个纵切面缺陷：

1. 日 Bar 在 15:00 session close 回调，半开 TradingCalendar 原先拒绝所有订单。`OnlyTradingSessionRiskRule` 现在只对“同 Instrument、同事件时间、immutable closed Bar Snapshot”放行收盘决策；任意盘后命令仍拒绝。
2. 卖单 Broker ACK 后本地 risk freeze 已释放，Broker available 又因该单冻结为零；Fill 被错误判为 oversell。Position apply 现在显式接收该订单自己的 remaining reservation，不能借用其他订单冻结量。
3. Allocation 重开新周期时，ExecutionProcessor 错把上一已关闭 Allocation 当作本次交易 before snapshot，导致历史 realized PnL 被反向计入第二次 BUY。before 现在只读 active snapshot；after 在平仓时才允许读取最新 closed snapshot。

全年 243 根 Tushare 日 Bar、两轮完整买卖的 CACHE_ONLY 实测结果：

```text
status                  COMPLETED
bar_count               243
callback_count          236
signal_count            4
order_count             4（全部 FILLED，0 rejected）
execution/fill_count    4
round_trip_count        2（由两组 OPEN BUY / CLOSE SELL 人工核对；当前结果模型无标准 Round-Trip Trade）

round_trip_1            BUY 1000 @ 10.1600 → SELL 1000 @ 10.1100 = -50.00 CNY
round_trip_2            BUY 1000 @ 10.4200 → SELL 1000 @ 10.3800 = -40.00 CNY
commission              4 × 1.00 = 4.00 CNY
realized_pnl            -90.00 CNY
net_pnl                 -94.00 CNY
initial_equity          1000000.00 CNY
ending_cash             999906.00 CNY
ending_market_value     0.00 CNY
ending_equity           999906.00 CNY
total_return            -0.00009400
maximum_drawdown        -0.00033993
winning_round_trips     0
losing_round_trips      2
final_positions         0
final_allocations       0
```

自洽校验全部成立：

```text
-50 - 40 = -90 realized PnL
-90 - 4 fees = -94 net PnL
1000000 - 94 = 999906 ending cash/equity
Account cash = Account equity = Ledger cash = Ledger equity = 999906
Ledger equity_by_cash_view = Ledger equity_by_pnl_view = 999906
最终 Position/Allocation 均为空，unrealized PnL 与 market value 均为 0
```

相同缓存分别通过 `PREFER_CACHE` 配置与无 Token `CACHE_ONLY` 配置运行：两次 Engine determinism fingerprint 均为 `ce4685a25fcd6ae2a2b5be79e1a351fab1455db58d8fe3964e9adac37b657ac9`，两份 Cluster `summary.json` 的 SHA-256 均为 `f4148b50a4ee2294d07157aefea0a7f9376b8cd3424057e4ef57f57faae6a12c`。

无限重复入场仍暴露 Virtual Broker Account Snapshot 与本地含手续费 Account 的长期 reconciliation difference；因此示例明确限制为两轮，未把该缺陷伪装成成功。正式 Result Collector、Round-Trip Trade、Equity Parquet 与 `result_fingerprint` 仍属于第 5 节未完成范围。

本轮质量验证：OnlyAlpha 全量 `342 passed`，Ruff check 通过，Mypy 313 source files 通过；本轮修改的三个核心文件已按 Ruff 格式化。核心全仓 format check 仍被用户工作区中既有的 `tests/market_data/test_pipeline_dispatch.py` 格式差异阻塞，本轮未改该无关文件。OnlyAlpha-examples Ruff check、11 files format check 和 `git diff --check` 均通过。

## 8. 用户现有 user_data 复验与对账修正

用户以工作区根目录命令、现有 `OnlyAlpha-examples/user_data` 运行时，最初出现 155 条
`OnlyBrokerAccountUpdate / RECONCILIATION_REQUIRED`。字段级诊断确认：Broker 与本地的
`cash_balance/equity` 始终一致，差异只在 `available_cash/frozen_cash`；两笔完全成交 BUY
因成交价优于下单预留价，分别遗留 40 和 20 CNY 的未释放账户预留（策略账本遗留 39 和
19 CNY，差 2 CNY 是两笔手续费）。

修正内容：

1. Account reconciliation 的审计摘要保留 `severity/action` 和字段级 local/broker 值，失败样本保留 `mutation_summary`，便于直接识别真实阻断与告警。
2. 回测收口按审计中的 `WARNING` 严重级别排除非阻断对账；`cash_balance/equity` 的 `BLOCK_ACCOUNT` 仍会失败。
3. BUY Order 完全成交后，ExecutionProcessor 在消费实际 notional/fee 后立即释放 Account 与 Strategy Ledger 的价格改善余量；不能以放行告警掩盖预留泄漏。

使用用户原命令等价方式对现有 165 行 Tushare Cache 复验，成功结果为：

```text
status                  COMPLETED
run_id                  run-e75cda054a9046c4bab614e08ef84c6a
engine_fingerprint      8d548d3577c2eecbb8970a0ed230b213680f074fa6106e0e2e83f759b88fa5c8
bar_count               165 generated / 165 processed
gap_count               34（EXPECTED_SESSION_GAP）
order_count             4（0 rejected）
execution/fill_count    4
round_trip_count        2（由 2 次 realized PnL delta 核对）
gross_profit            20.00 CNY
gross_loss              -280.00 CNY
realized_pnl            -260.00 CNY
fees                    4.00 CNY
net_pnl                 -264.00 CNY
initial_equity          1000000.00 CNY
ending_cash/equity      999736.00 CNY
total_return            -0.00026400
maximum_drawdown        -0.00034100
win_rate                0.50000000
profit_factor           0.07142857
final_positions         0
final_allocations       0
account_frozen_cash     0.00 CNY
ledger_reserved_cash    0.00 CNY
```

统计恒等式成立：`20 - 280 = -260 realized PnL`，`-260 - 4 = -264 net PnL`，
`1000000 - 264 = 999736 ending cash/equity`，收益率为 `-264 / 1000000 = -0.00026400`。
Account 与 Ledger 的 cash/equity/pnl 视图一致；所有预留剩余量为 0 且状态 `RELEASED`；五项
回测不变量 `ACCOUNT_EQUITY / LEDGER_EQUITY_VIEWS / NO_EXECUTION_FAILURE /
NO_ACTIVE_RISK_RESERVATION / NO_BLOCKING_RECONCILIATION` 全部 PASS。

同一现有 Cache 再次运行得到 `run-e26f23905feb4cbe8e8c9db733560068`，Engine determinism
fingerprint 仍为 `8d548d3577c2eecbb8970a0ed230b213680f074fa6106e0e2e83f759b88fa5c8`。
新增价格改善余量释放回归测试后，OnlyAlpha 全量 `343 passed`；Ruff、Mypy（313 source
files）、修改文件 format check、OnlyAlpha-examples Ruff/format check 与两仓 `git diff --check`
均通过。
