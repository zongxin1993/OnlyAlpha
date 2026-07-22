# Committed Execution Journal 修改前审计

- 状态：Pre-implementation audit
- 日期：2026-07-22
- 范围：Core、Virtual Broker 插件、Tushare/MiniQMT Broker 边界、测试、示例、ADR 与当前文档
- 事实基线：当前工作树源码和测试；`prompts/` 仅用于规定本次任务，不作为既有实现事实

## 1. 当前链路与所有权

当前正式成交链为 Broker Gateway → `OnlyBrokerTradeUpdate` → Runtime-owned inbound queue →
`OnlyExecutionProcessor`。Processor 同步更新 Order、Position、Allocation、Settlement、Margin、Fee、Account、
Strategy Ledger、Reservation 和 Risk，检查 invariant，提交事件后，才向 Runtime-owned
`OnlyAppliedTradeJournal` 追加记录。Virtual Broker 已是独立插件；Core Collector 当前未调用
`query_trades()` 构建结果。

Runtime 在 `OnlyBacktestRuntime` 内创建一个 `OnlyAppliedTradeJournal`，通过 `OnlyRuntimeServices` 持有并暴露；
`OnlyExecutionProcessor` 是生产代码中唯一写入者。该所有权方向正确，但 Journal 的事实模型不足。

## 2. 旧模型实际保存的内容

`OnlyAppliedTradeFact` 只保存：

1. `runtime_id`
2. `gateway_id`
3. `account_id`
4. `order_id`
5. `trade_id`
6. `update_id`
7. `source_sequence`
8. 原始 `OnlyOrderFill`

`OnlyOrderFill` 提供成交价、成交量、Broker 事件/初始化时间、Venue Trade/Order ID、Broker reported fee、
fee reporting mode、liquidity side、external sequence/event ID 和 metadata。旧 Journal 仅按全局 `trade_id`
去重，按 append 顺序保存；没有 Runtime/Gateway 复合幂等键、显式 execution sequence、稳定本地 execution ID
或稳定 hash。

因此它表达的是“被处理的外部 fill 副本”，不是“Runtime 完整事务最终提交的本地成交事实”。

## 3. 丢失的已提交语义

旧 Fact 没有固化以下成功事务结果：

- Order：request/client ID、side/type/offset、累计成交量、剩余量、提交后状态；
- Scope：cluster/strategy、instrument/venue、position side/effect/mode；
- Causality：processing/execution sequence、correlation/causation ID、committed time、trading day；
- Economy：currency、contract multiplier、gross/settled notional、authoritative fee、fee breakdown、commission、
  slippage、realized PnL 和 cash delta；
- Authority identities：fee instruction/source/status/schedule identity、market profile/version、compiled/reference
  fingerprint、trade instruction identity；
- Settlement/Margin：已应用 instruction/record、可用日、法定结算日、margin action/delta/after state；
- Local mutation deltas：Position、Allocation、Account 和 Strategy Ledger 的实际本次提交增量。

这些值已经在 Processor 的局部事务中产生，但事务完成后没有形成自包含的不可变事实。

## 4. 旧模型调用方

生产调用方包括：

- `onlyalpha.execution` 公共导出；
- `OnlyExecutionProcessor` 构造和成功路径；
- `OnlyRuntimeServices`、`OnlyRuntime.applied_trade_journal`；
- `OnlyBacktestRuntime` 装配；
- `OnlyBacktestRunPlan` 的 trade summary/result；
- `OnlyBacktestResult.trades`；
- `OnlyBacktestResultCollector` 的 execution projection。

直接测试调用方包括 `tests/execution/test_applied_trade_journal.py` 和
`tests/execution/test_execution_processor.py`。当前文档引用包括 ADR 0032、`docs/execution_processor.md`、
`docs/results_framework.md`、`docs/runtime.md`、`docs/virtual_broker.md`。`HANDOFF.md` 同时包含旧历史审计文字，
需要区分当前事实与 Historical 内容。

## 5. Result 中已确认的错误或缺失

`OnlyBacktestResultCollector._execution_record()` 当前必须额外查询最终 Order snapshot，并通过外部传入的
Cluster → Strategy 映射补充归属。它还存在以下确定性错误：

- `execution_id` 直接等于 Broker `trade_id`，没有本地 committed identity；
- `turnover = price × quantity`，遗漏 contract multiplier；
- `commission = 0`；
- `fees = 0`；
- `slippage = 0`；
- 未投影 position side/effect/mode、realized PnL delta、完整 fee identity、market profile version/fingerprint、
  settlement/margin committed outcome；
- `trading_day` 由 `ts_event.date()` 推导，而非 Calendar/Market Rule 已解析的 trading day。

`OnlyExecutionResultRecord` 虽已有部分可选字段，但仍以 mandatory zero-compatible 的 commission/fees/slippage
设计，market rule identity 也不完整。Artifact schema version 当前为 1，Parquet execution schema与上述旧投影一致。

## 6. Manager/Broker 补数据现状

- Core Result Collector 当前没有调用 Broker `query_trades()`；该 Port 仍由 Virtual Broker 和 MiniQMT 用于外部查询/
  同步，符合保留为 reconciliation/query 的边界。
- Collector 仍查询 Order Manager 来解释每条成交，并查询 Position、Allocation、Account、Settlement、Margin、Fee
  Manager 的最终记录分别生成其他结果表。这些表可继续表达各自状态/ledger，但 execution record 不应再靠这些最终
  状态补成交语义。
- Analytics 只消费 `OnlyExecutionResultRecord`，不会重跑 Fee Resolver 或 Market Rules；然而由于 Collector 投影错误，
  turnover、fee、commission、slippage 和基于它们的 trade/net PnL 当前继承错误。
- Artifact 只序列化 Result/Analysis，不重跑交易逻辑；它同样继承旧 execution schema 的信息缺失。

## 7. 可复用领域边界

- Fee：`OnlyFeeInstruction`、`OnlyFeeBreakdown`、`OnlyFeeComponent` 已提供 authoritative total、authority、status、
  schedule ID/version 和 Broker reporting mode。Committed Fact 应投影这些不可变值，不重新 resolve。
- Market Rule：`OnlyTradeApplicationInstruction` 已包含 position、settlement、margin、cash instruction 和
  `OnlyCompiledMarketRuleIdentity`。Committed Fact 应固化 identity 和已应用结果，不保存 Rule Engine/Profile。
- Position Scope：`OnlyExecutionPositionScope` 已明确 LONG/SHORT、OPEN/CLOSE 和 NETTING/HEDGING，应直接复用本次
  已解析 scope。
- Settlement/Margin：Manager 返回不可变 record；应捕获本次 record，而不是由 Collector 扫描最终 manager 状态反推。
- Account/Position/Ledger：mutation result 已带 before/after 或明确 delta，可在事务局部计算本次增量；Fact 不保存完整 snapshot。

## 8. 事务缺口与风险

当前顺序是 event commit → 构造 Processing Result/Audit → append old Fact。Fact 构造只是复制 update，几乎不会失败；
新 Fact 构造和 Journal append 都可能失败。迁移必须保证：event commit 失败无 Fact；Fact 构造或 append 失败不返回
APPLIED；失败进入显式 reconciliation/audit。系统没有数据库事务，event commit 后的 builder/journal failure 无法回滚已提交
Manager 状态与事件，只能标记 partial mutation 并阻断 scope，不能伪装原子成功。

## 9. 迁移结论

不能只重命名旧类。需要以 Processor 本次事务局部值建立 commit context/builder，创建 Runtime-scoped、按 Runtime/Gateway/
Trade 与 Runtime/Gateway/Update 双重幂等的 Committed Journal；随后一次性迁移 Result、Analytics/Artifact schema、测试、
示例和文档，并彻底删除旧类型、旧导出和旧字段修补路径。
