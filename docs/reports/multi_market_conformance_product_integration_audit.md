# Multi-Market Conformance Product Integration 修改前审计

日期：2026-07-19。结论以本任务开始时的源码与测试为准，不以 ADR、提示词或类型名称替代运行证据。

## 任务 2 实际完成度

| 项目 | 状态 | 修改前证据 |
| --- | --- | --- |
| Domain | 已完成 | `onlyalpha.scenario.models` 提供不可变 Scenario、Action、Expectation 与 Bar。 |
| Parser | 已完成 | 严格 YAML/JSON parser，复用产品 Market/Reference Config。 |
| Planner | 已完成 | 生成 runtime-neutral Command；非 Backtest 返回 capability issue。 |
| Action Strategy | 未完成 | Parser 装配 `OnlyNoopStrategy`，Action 从未进入 `ctx.orders`。 |
| Synthetic Data | 部分完成 | 通用 Synthetic 可生成 Bar，但不能逐条保留 Scenario exact bar。 |
| Runner | 未完成 | 没有调用 `OnlyEngine` 的 Scenario application service。 |
| Collector | 部分完成 | Order/Execution/Position/Account 等存在；timeline/compiled/action/fee 等未收口。 |
| Assertion | 已完成 | 只比较传入的标准 fact mapping，不导入交易组件。 |
| Artifact | 未完成 | Backtest Artifact 存在，Scenario definition/plan/assertion/manifest 不存在。 |
| Input Fingerprint | 已完成 | canonical input fingerprint 已存在。 |
| Result Fingerprint | 未完成 | Scenario 没有 result fingerprint。 |
| Runtime Mode Contract | 部分完成 | Action/Command 共享；仅规划阶段显式拒绝 PAPER/LIVE/SHADOW。 |

## Conformance 当前状态

| 项目 | 状态 | 修改前结论 |
| --- | --- | --- |
| Pack Identity | 部分存在 | 仅字符串 `pack_id`，没有独立 Version/Schema/Source。 |
| Scenario Identity | 部分存在 | binding 只有 id/version/capability。 |
| Pack Registry | 部分存在 | 可注册/读取，但错误为裸 `ValueError`，不校验版本范围或 Scenario repository。 |
| Capability Coverage | 不真实 | 由定义中 `expected_unsupported` 反推，不读取正式 Scenario run result。 |
| Profile Status Gate | 不真实 | Stable gate 只比较手工 capability 名，不验证执行、确定性、Artifact 或质量门禁。 |
| Pack Execution | 未完成 | 没有 Conformance Runner。 |
| Pack Artifact | 未完成 | 不存在。 |
| Pack Summary | 未完成 | 不存在。 |
| Release Gate | 未完成 | 不存在。 |

## 产品入口现状

| 入口 | 状态 |
| --- | --- |
| CLI | 只有既有 Engine run/dry-run；没有 scenario/conformance/market 命令。 |
| Query DTO / Result Query Port | 未完成。 |
| Web compatibility | 未完成；没有稳定 JSON DTO 边界。 |
| Examples | 没有可由正式 Scenario CLI 运行的五个定义。 |
| Profile inspection | 未完成。 |
| Scenario run / Pack run | 未完成。 |
| Artifact location | 仅 Backtest run artifact，Scenario/Pack 无约定。 |
| Exit codes | 没有本任务定义的 0--5 语义。 |

## 边界风险

- 旧 Conformance 通过定义内容重算 coverage，尚未执行规则但会产生“已覆盖”错觉。
- CLI 当前没有越权实现，因为产品命令尚不存在；新增入口必须只调用 Application Service。
- Pack Runtime 尚不存在；后续必须只调用公开 Scenario Runner。
- Profile 状态仍是源码定义，普通运行没有修改 Registry；这一点应保持。
- Collector 缺 Profile timeline、compiled identity、action、完整 market decision/settlement/margin/fee 事实。
- Scenario Parser 曾生成 No-op Strategy，既不能证明 Backtest，也不存在可供其他模式复用的正式 Action Strategy。
- Futures/Crypto Config 只接受 Equity/ETF；HEDGING、Margin/Account 与 base/quote 仍有正式内核缺口。
- Virtual Broker position snapshot 把数量精度硬编码为 0，阻断 fractional cash/Crypto 正式纵切面。

## 修改前结论

任务开始时不能运行任何正式 Conformance Pack，也没有 Profile 有资格升级 Stable。实施顺序必须保持：先补 Scenario
Engine 纵切面，再收口事实与 Artifact，然后实现 Pack Runtime、coverage/stability、产品入口和发布门禁。
