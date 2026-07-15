# Market Data Source Integration Report

- Date: 2026-07-15
- ADR: 0017
- Final conclusion: **ACCEPTED**

## 1. 新增与修改

新增 `src/onlyalpha/data/`，包含强 Source/Gateway/Update/Version/Sequence ID、Capability、Quality、Update Envelope、实时 Ports、
历史/Reference Ports、有界 MarketData Queue、Processor、Deduplicator、SequenceTracker、Session-aware GapDetector、Audit、Source
Registry/Factory、HistoricalReplayService、InMemory/CSV/Parquet Source、InMemory/Replay Gateway 和 Reference Source。

新增：

- `tests/data/test_market_data_sources.py`；
- Integration 场景 024～033；
- `examples/data_source_demo/` 七个 Demo；
- MarketData Source/Historical Source/Reference Source/Replay 文档、差距分析和 ADR 0017。

修改 Runtime、Pipeline、统一 Integration Environment、确定性 projection、历史 MarketData Demo、Architecture Principles、Runtime、
RuntimeContext、Time、Testing 和 Vertical Slice 文档。新增正式 Parquet 运行依赖 `pyarrow` 并更新 `uv.lock`。未修改本任务 Prompt，
未删除、Skip 或放宽任何历史测试/场景。

## 2. 组件边界与 MarketData/Broker 分离

```text
HistoricalDataSource → HistoricalReplayService → BacktestClock ┐
                                                               ├→ MarketDataProcessor → Pipeline → Snapshot → Cluster
MarketDataGateway → independent MarketData Inbound Queue ──────┘

Cluster → Order/Risk → BrokerGateway → independent Broker Inbound Queue → ExecutionProcessor
```

MarketDataGateway 与 BrokerGateway 是不同 Port、不同实例、不同连接状态和不同 Queue。MarketData Gateway 只写 Update Sink；不持有
Clock、Pipeline、Cache、Cluster、Broker 或 Manager。DataSource 只返回 Stream，不推进 Clock/策略。Cluster Context 没有暴露
DataSource、Gateway、Queue、Processor、Replay 或 Registry。

## 3. Ports、Envelope 与数据属性

- 实时：Connection/Authentication/Disconnect、Subscription/Unsubscription 和 Stream Sink Port；Capability 显式声明；
- 历史：Bar/Quote/Trade request 与 Stream，UTC `[start,end)`、Version、RAW Adjustment、batch；
- Reference：Instrument、TradingCalendar、MarketRule 独立候选 Port；Runtime Registry 仍是规范真值；
- Envelope：Runtime/Update/Source ID、Source Sequence、Data Version、Instrument、DataType、联合 payload、UTC `ts_event/ts_init`、
  Quality、correlation、稳定 metadata；
- Domain：实时与历史继续复用现有 `OnlyBar/OnlyQuoteTick/OnlyTradeTick`，没有重复或污染领域模型。

## 4. Processor、Validation、Deduplication 与 Gap

Processor 是 Queue/Replay 后统一入口，校验 Runtime Scope、Source Registry、Instrument、时间与 Lookahead，再执行去重、Sequence、
Gap、Quality、Pipeline、Dispatcher、事实和 Audit。重复 Bar key 为 Source/Instrument/BarType/EventTime/Version，第二条不会更新 Cache、
Aggregation、Indicator、Snapshot 或 Cluster。Source sequence 乱序返回 STALE，跳号产生 Gap。

GapDetector 使用 TradingCalendar/Session：同 Session 缺 Bar 为 `UNEXPECTED_GAP`，午间休市等跨 Session 合法间隔为
`EXPECTED_SESSION_GAP`。Quality 传播到 immutable Snapshot，策略只能读不能修改。

## 5. HistoricalReplay、排序、Clock 与 Lookahead

稳定全序：`ts_event → DataType priority → instrument_id → bar_type → source_priority → source_sequence → update_id`，不依赖文件、
dict、Source 或线程到达顺序。每条 Update 严格 `BacktestClock.advance_to(ts_event) → Processor.process(update)`；DataSource 和
Processor 都不能推进 Clock，Clock 回退被拒绝。

Lookahead 防护由 Replay 时间门、Processor `update <= Clock` 校验、Pipeline closed-Bar 约束和不可变 Snapshot 共同实现。Virtual
Broker 继续只用订单提交后的 Next Bar。旧 `OnlyBacktestRuntime.process_bar()` 是单记录版本化 InMemory Source/Request 的正式
Replay facade，不再直接推进 Clock 或调用 Pipeline。

## 6. 本地 Source 与在线边界

- InMemory：多 Instrument/类型、版本、稳定 Stream 和 batch；
- CSV：严格单列无损 Envelope schema，适合导入/测试/小数据；
- Parquet：pyarrow Dataset，严格 schema，Source/Instrument/DataType/BarType/UTC range/Version 下推过滤，按 batch 扫描；Decimal、
  UTC 纳秒和 Domain JSON 无损；
- Online：仅定义 Remote Port。正式确定性回测不隐式访问在线 API；探索源必须标记 `NON_DETERMINISTIC_SOURCE`，先落版本化本地
  快照再进入正式 Replay。

## 7. Runtime 与 Integration Environment

每个 Runtime 独占 Source Registry、Historical/Reference Source、InMemory Gateway、MarketData Queue、Processor、Deduplicator、
SequenceTracker、GapDetector、ReplayService 和 AuditStore。统一 `OnlyIntegrationEnvironment` 暴露这些 management 验证端口，但
Cluster Context 仍只读 Snapshot。确定性 projection 新增 MarketData Audit 和 Replay Event 序列。

新增 024～033 场景覆盖 Runtime 所有权、正式历史入口、Source/Version/Quality Audit、MarketData/Broker 双 Queue、Registry、
Reference Data、No Lookahead、Snapshot Quality、Sequence 和 DataSource→完整交易闭环。001～023 全部保留。

## 8. 测试结果

最终统一执行 `bash scripts/run_component_validation.sh`：

| 验证层 | 结果 |
|---|---|
| Data 专项 + Integration 定向 | 54 passed |
| 全部 Unit/Regression/Integration | **252 passed in 7.48s** |
| `tests/integration` | **43 passed in 6.69s** |
| Integration Demo | **33/33 PASS** |
| Deterministic Replay | **baseline + 100 次完全一致；1 passed in 5.34s** |
| DataSource Demo | **7/7 PASS** |
| 历史 Event/MarketData Demo（已迁移正式入口） | **4/4 PASS** |
| Ruff | All checks passed |
| Ruff format | 394 files already formatted |
| Mypy strict | 184 source files, 0 issues |

历史验证趋势均未回退：M1 196 passed → Account/Virtual Broker 219 passed → ExecutionProcessor 231 passed → 本任务 252 passed。
没有测试被删除、Skip 或放宽。

## 9. 关键不变量

全部通过：MarketData/Broker 分离；历史全经 ReplayService；实时全经 Queue/Processor；Processor 统一入口；ReplayService 唯一数据
Clock 推进者；Source/Sequence/Version/Quality/UTC 可追踪；多流顺序稳定；重复不重复下单；午休不误报；Snapshot 无未来数据；
派生 Bar/Indicator/Cluster 顺序不变；Cluster 不知道 Source；文件顺序不影响结果；完整 Order/Risk/Broker/Execution/Position/
Allocation/Ledger/Account 不变量继续成立；100 次重放一致。

## 10. Placeholder 与已知限制

使用的明确边界只有现有无 Broker Runtime 的 `OnlyPlaceholderExecutionService`；统一主交易场景仍使用 Virtual Broker。本任务没有
伪造商业行情能力。InMemory Gateway 是确定性正式 Port 实现，不宣称具备网络能力。

已知限制：同步单写入者；Quote/Trade/InstrumentStatus 已标准化、审计但现有 Pipeline 首版只应用 1m closed TIME Bar；未实现商业
Adapter、WebSocket、Level 2、自动重连、复杂背压/主备、多源融合、公司行动/复权引擎、持久 Audit/Replay cursor 或大规模数据
目录 manifest。CSV 定位小规模导入，Parquet 是正式本地格式。

## 11. 一票否决项

逐项检查未发现：没有把 MarketData 放入 Broker；DataSource/Gateway 不调用 Cluster/Cache；Runtime 不直接读文件驱动策略；历史
不绕 Replay；实时不绕 Processor；排序不依赖文件；Processor 不读系统时间；Clock 不回退；Context 不泄露 Source；无隐式在线
API；Version 可追踪；重复不重复下单；Session Gap 正确；无未来泄露；旧场景无删除/Skip/放宽；完整 Slice 与重放通过；未引入
ARL 或历史兼容 Wrapper。

## 12. 阶段建议

- OnlyPaperRuntime：**建议进入**，复用本次 Queue/Processor API；上线前仍需真实 Clock 调度、连接状态机和持续背压监控；
- 持久化数据目录：**建议作为下一优先级**，增加 manifest、checksum、schema/version registry、原子发布和恢复 cursor；
- 首个真实 MarketDataGateway：**建议在持久目录与 reconnect/backpressure 契约后接入**，Adapter 只能标准化并写 Queue；先做 Paper
  soak，不与 Broker SDK 连接对象共享。

## Final conclusion

**ACCEPTED**

所有一票否决项均未触发；组件、上下游、完整 Vertical Slice、全部历史测试、关键不变量和 100 次确定性重放全部通过。
