# Risk 组件验收报告

- 日期：2026-07-14
- 结论：**ACCEPTED**

## 1. 新增文件

- `src/onlyalpha/risk/`：Decision、Rule、Pipeline、Profile/Registry/Factory、Context/Port、State/Snapshot、
  Reservation、Kill Switch、Event/Publisher、Audit、View、Identifier、Enum 与异常边界。
- `tests/risk/`：Rule、Profile、Scope、Fail Closed、Reservation、OrderService 集成、Runtime/Cluster 隔离、
  Snapshot、幂等与重放确定性测试。
- `examples/risk_demo/`：7 个可执行场景与 README。
- `docs/risk.md`、`docs/risk_component_analysis.md`。
- `docs/adr/0012-risk-pipeline-profile-and-reservation.md`。

## 2. 修改文件

- Order：`service.py`、`results.py`、Execution update model/processor 和相关测试装配。
- Runtime：`runtime.py`、`context.py`，加入 Runtime Risk 所有权、Instrument 注册、Profile 绑定、Pre-Bar
  Snapshot 与受限 Context View。
- Demo：Runtime Context Demo 注册真实领域 Instrument；Order Demo 改为强制经过 Risk。
- 文档：architecture、architecture_principles、cluster、event、order、runtime_context、testing。

## 3. Risk 组件边界与三阶段模型

每个 Runtime 一个 `OnlyRiskService`，独占 Profile、State、Reservation、Kill Switch、Audit 和事件序列。
Cluster 只持有只读 `ctx.risk`，不能推进 Clock、修改 Cache、访问 Gateway/Aggregator、执行 Rule 或修改
Reservation。

执行顺序已固定为：Pre-Bar State/Snapshot → 每次 submit 的 Pre-Trade Pipeline → ACCEPT 后即时 Reservation →
Order Fact → Placeholder Execution。Snapshot 不替代最终审批。

## 4. Rule、Scope、Mode 与 Mandatory Rules

- 抽象接口：`OnlyRiskRule.evaluate(request, context) -> OnlyRiskDecision`。
- Scope：SYSTEM → RUNTIME → ACCOUNT → INSTRUMENT → CLUSTER。
- 同层顺序：显式 `order` → 稳定 `rule_id`，与注册顺序、EventBus priority 无关。
- Mode：ENFORCING 与 OBSERVING；首个 enforcing rejection 停止，observing 仅记录。
- Mandatory：Runtime/Cluster Scope、Instrument exists/tradable、OrderType、Price、Quantity、Kill Switch；
  Profile 不能删除、替换或降级。
- Instrument/Market：tick、step、min/max quantity、min notional、session、price limit。
- Runtime/Cluster：active order、quantity/notional、Account/Instrument permission。

## 5. Decision、Fail Closed 与 OrderService

Decision 区分 ACCEPT、REJECT、ERROR，并保留已执行 Rule、结构化拒绝/错误和 Observation。规则异常被 Pipeline
捕获为 ERROR；默认 Fail Closed。实测 REJECT 与 ERROR 均返回 `created=False`、无 OrderId/Snapshot、Order
Repository 为空、Reservation 为空且 Placeholder Execution 调用数为零。

Order 通过后立即建立 Reservation；额度 1500 CNY 下连续两笔各 1000 CNY 的结果稳定为第一笔 ACCEPT、第二笔
`RISK_RESERVATION_EXCEEDED`，第二笔不创建 Order 或调用 Execution。

## 6. Profile、自定义 Rule 与 Risk Context

Profile 支持配置化内建规则与显式 Registry 扩展，非法名称、重复注册、重复 RuleId 和 Mandatory 冲突在绑定阶段
失败。Rule Context 只提供 Runtime/Cluster/Account Scope、业务时间和只读 Instrument、MarketRule、Order、
Reservation、Permission、Account、Position Port。跨 Runtime Context 被拒绝。

## 7. Snapshot、Reservation 与 Kill Switch

Snapshot 为 frozen、版本化且带纳秒时间和 Scope；Pre-Bar 测试确认 Snapshot 在策略回调对应时间片完成刷新。
Reservation ID/遍历确定，按 OrderId 创建幂等，释放校验 Scope 并幂等；标准终态 UpdateProcessor 负责释放。
Kill Switch 是 Runtime 管理能力，Mandatory Rule 强制执行，Cluster 只读取 Snapshot 状态。

## 8. Account/Position Port 与 Risk Event

Account/Position 仅定义只读 Snapshot Port；默认 Placeholder 明确 `available=False`，Snapshot 输出
`ACCOUNT_RISK_UNAVAILABLE` 与 `POSITION_RISK_UNAVAILABLE`，没有无限资金或充足持仓假数据。

Risk Accepted/Rejected/RuleFailed、State Updated、Reservation Created/Released 都是结果事实。Rule 执行不由
Event 驱动；本阶段未增加任何策略 `on_risk_xxx` 回调。

## 9. 验证结果

- Ruff：通过，0 error。
- Mypy：通过，99 个 source files，0 issue。
- Pytest 全量：157 passed，0 failed，0 skipped，0.52s。
- Risk 定向：21 passed。
- Demo：Risk 7、Order 6、Runtime Context 4，共 17 个脚本全部退出码 0。
- 重放：相同 Runtime/Cluster/Clock/Request 两次独立运行得到相同 Decision、OrderId 和 Reservation Snapshot；
  确定性测试通过。

## 10. 已知限制

- 未实现真实 AccountManager、PositionManager、ExecutionSimulator、撮合、真实 SDK 或券商 Risk。
- 未实现部分成交对 Reservation 的消耗/转换及持久化恢复。
- Market Order 若配置需要可靠名义金额的规则，在缺少价格源时 Fail Closed。
- Live Runtime 的 SDK 回报串行化仍属于后续阶段。
- 没有策略 Risk 回调；未来只能消费已发生的 Risk Fact，需独立 ADR。

## 11. 一票否决项

- REJECT/ERROR 创建 Order：未发生。
- REJECT/ERROR 调用 Execution：未发生。
- Mandatory Rule 可删除或降级：未发生。
- Account/Position 伪造无限可用：未发生。
- Risk 逻辑依赖 EventBus priority/注册顺序：未发生。
- Cluster 获得 Risk 写权限、Gateway 或 Cache：未发生。

## 12. 后续阶段建议

- 是否建议进入 PositionManager：**可以进入，但需新任务与 ADR，不在本阶段实现。**
- 是否建议进入 AccountManager：**可以进入，但需先定义可靠 Snapshot/恢复语义。**
- 是否建议进入 ExecutionSimulator：**可以进入，但需保持 Order/Risk/Execution 边界和确定性单写顺序。**

最终结论：`ACCEPTED`。
