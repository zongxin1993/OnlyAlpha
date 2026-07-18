# 持续集成与 Vertical Slice 强制要求

## Product-style Demo 扩展

完整产品 Demo 不得使用 `OnlyIntegrationEnvironment` 作为用户入口。用户入口必须是配置 → 正式 Runtime → Result；统一集成 Demo
可以调用该正式 API 并将 Result fingerprint 纳入其投影，但不能复制装配或手工驱动 Manager。合成数据必须实现
HistoricalDataSource，策略必须实现 Cluster，成交必须经 VirtualBroker queue 与 ExecutionProcessor。

本任务必须遵守：

```text
AGENTS.md
docs/integration_vertical_slice.md
```

除了本组件的单元测试外，必须完成：

1. 将新组件接入当前统一 `OnlyIntegrationEnvironment`；
2. 在 `examples/integration_demo/scenarios/` 中新增或更新对应场景；
3. 在 `tests/integration/` 中新增对应集成测试；
4. 更新完整 Vertical Slice；
5. 运行所有历史集成场景；
6. 运行确定性重放；
7. 验证全部跨组件不变量；
8. 生成本组件集成报告。

不得：

* 通过直接修改内部状态完成 Demo；
* 绕过 Runtime、Context、Pipeline 或 Manager 正式接口；
* 删除、跳过或放宽历史场景；
* 使用未明确标注的虚假能力；
* 只运行新增测试。

当前新组件必须接入以下纵向链路的正确位置：

```text
Bar → MarketData Pipeline → Snapshot → Cluster → Order → Risk → ExecutionService
→ Virtual Broker → Matching Engine → Broker Update → Runtime Inbound Queue → OnlyExecutionProcessor → Order
→ Position → Position Allocation → Strategy Ledger → Account → Risk Update → Event → Final Snapshot
```

如果某个后续能力尚未实现，必须使用明确命名的 Placeholder/Test Adapter，并在报告中说明。

最终必须生成：

```text
docs/reports/<component>_integration_report.md
```

报告至少包含：

```text
新组件接入点
新增集成场景
历史场景结果
单元测试结果
上下游集成结果
完整 Vertical Slice 结果
确定性重放结果
不变量检查结果
使用的 Placeholder
发现的回归
已知限制
最终结论
```

未完成 Vertical Slice 更新或历史场景回归时，不得标记本任务完成。

## M1 架构整合实现

统一测试环境位于 `tests/integration_demo/`，只组装现有 Runtime 资源和正式接口。23 个场景覆盖 Runtime 启动、
1m→3m、Order/Risk、Virtual Broker 买卖成交、Position、Allocation、Strategy Ledger、Account、T+1、部分成交、撤单、
多 Cluster、Broker/Local 冲突、重复/乱序回报和最终 Snapshot。

标准化成交由 `OnlyVirtualBrokerGateway` 的独立 Broker Store 与 Matching Engine 产生，经 Runtime inbound queue 后由
Runtime 独占 `OnlyExecutionProcessor` 在单写入者线程按固定顺序编排。Placeholder 仍保留为无 Broker 配置 Runtime 的
明确边界，但统一集成主场景不再使用它或手工制造成交。

自动化入口为 `tests/integration/`、`python -m tests.integration_demo.run_all` 和 `scripts/run_component_validation.sh`。

## Market Data Source 扩展

当前完整入口为：

```text
HistoricalDataSource / MarketDataGateway
→ HistoricalReplayService / independent MarketData Inbound Queue
→ MarketDataProcessor → Pipeline / Aggregation / immutable Snapshot
→ Cluster-scoped Indicator → Factor → Strategy → Order → Risk → Virtual Broker → Broker Queue → ExecutionProcessor
→ Position → Allocation → StrategyLedger → Account → Event / Report
```

旧 `Runtime.process_bar()` 只是单记录本地 Replay facade，不再直接推进 Clock 或调用 Pipeline。统一环境当前为 35 个场景；
024～033 验证装配、正式历史入口、Audit、双 Queue、Registry、Reference Data、Lookahead、Snapshot Quality、顺序和闭环，
034 验证 Synthetic/Virtual 产品回测，035 验证外部 DataSource/Broker 通过 Entry Point 接入同一纵向链路。

Product MACD 场景使用单 Cluster 文档的 `strategy + factors[]` 配置，经 CLI 等价 Engine 入口与 Factory 运行；Runtime 不识别 MACD。通用结果通过 Cluster extension、Factor result 和 Indicator diagnostics 输出。该场景与完整 Vertical Slice 均执行 100 次确定性重放。
