# ADR-0012: Runtime Risk Pipeline、Profile 与 Reservation

- 状态：Accepted
- 日期：2026-07-14

## 背景

不同策略需要不同风险约束，但系统安全规则不能被策略关闭。订单最终审批必须发生在正式 Order 创建和外部 Execution
调用之前；仅在 `on_bar` 前计算状态不足以覆盖同一回调中的连续订单。

## 决策

- 每个 Runtime 拥有唯一 `OnlyRiskService` 及其可变 Risk State。
- Risk 使用只读 Context、抽象 Rule 和固定 Scope 顺序的组合 Pipeline。
- Cluster 通过配置绑定 Profile；Mandatory System Rules 不可关闭、替换或改为 Observing。
- Runtime 在 `on_bar` 前同步生成不可变 Risk Snapshot；每次 submit 仍执行最终 Pre-Trade Risk。
- REJECT 和 ERROR 均不创建 Order 或调用 Execution；ERROR 默认 Fail Closed。
- ACCEPT 后先创建 Order，再立即创建 Reservation，然后发布 Order Fact 并调用 Execution。
- Risk Command/Query 使用同步函数，Event 只通知已经发生的判定或状态事实。
- Account/Position 只定义只读 Port 和 unavailable 占位，不假设资金或持仓充足。
- 本阶段不定义策略 `on_risk_xxx` 回调。

## 结果

收益是确定性顺序、可审计的零副作用拒绝、同回调预占可见以及 Runtime/Cluster 隔离。代价是 Runtime 装配必须提供
Instrument/Calendar/Order Query，OrderService 强制依赖 RiskService，且订单终态必须经标准 UpdateProcessor 才能
自动释放 Reservation。未来 Account/Position、部分成交 Reservation 消耗和 Live 串行回报需另行决策。

## 被否决方案

- 依赖 EventBus priority 或 Rule 注册顺序：无法表达稳定业务依赖，重放脆弱。
- Risk 拒绝后仍创建 REJECTED Order：污染正式订单空间并使 Execution 副作用更难证明。
- on_bar Snapshot 作为最终审批：看不到同回调内前序订单的新预占。
- Account/Position unavailable 时提供无限额度：制造虚假安全保证。
