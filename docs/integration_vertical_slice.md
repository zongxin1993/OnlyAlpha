# 持续集成与 Vertical Slice 强制要求

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
Bar
→ MarketData Pipeline
→ Snapshot
→ Cluster
→ Order
→ Risk
→ Execution Placeholder
→ Trade
→ Order Update
→ Position
→ Position Allocation
→ Strategy Ledger
→ Event
→ Final Snapshot
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

统一环境位于 `examples/integration_demo/`，只组装现有 Runtime 资源和正式接口。12 个顺序场景覆盖 Runtime 启动、
1m→3m、Order/Risk、买卖成交、Position、Allocation、Strategy Ledger、T+1、收益和最终 Snapshot。

标准化成交由 `OnlyBacktestRuntime.process_trade()` 在 Runtime 单写入者线程按固定顺序编排：Order Fill Update →
Position Reservation → Account Position → Cluster Allocation → Strategy Ledger Accounting/Valuation → Risk Reservation
完成 → fact Event drain。Placeholder 仍只记录请求，不生成 Accepted、Fill 或 Trade。

自动化入口为 `tests/integration/` 和 `scripts/run_component_validation.sh`。
