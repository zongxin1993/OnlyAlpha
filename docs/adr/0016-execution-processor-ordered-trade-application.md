# ADR 0016: Execution Processor ordered trade application

- Status: Accepted
- Date: 2026-07-15
- Modules: execution, runtime, broker, order, position, strategy_ledger, account, risk, event

## Context

标准化 Broker Update 到达后必须固定更新 Order、Position、Allocation、Strategy Ledger、Account、Reservation 和 Risk。此前
Backtest Runtime 自身分支处理 Update，并在 Trade 中直接编排 Manager；各 Manager 事实也会在后续步骤成功前进入 EventBus。
这种结构无法为重复/乱序回报、中途失败、统一审计和恢复提供稳定事务边界。使用 EventBus 分散 Handler 更无法保证一致性。

## Decision

- 每个 Runtime 独占一个 `OnlyExecutionProcessor`、去重器、sequence tracker、Audit Store、Invariant Checker、事实缓冲和
  Reconciliation Queue；
- 所有 `OnlyBrokerInboundUpdate` 必须先进入 Runtime 有界 Queue，Processor 是唯一业务入口；
- Gateway 不持有 Manager，Backtest/Virtual Broker/Paper/Live 共用 `process(update)`；
- Trade 顺序固定为 Order → Position → Allocation → Strategy Ledger → Account → Reservation → Risk → Invariant → Event；
- Manager 使用同步函数调用，EventBus 不参与业务状态迁移；
- 事实在完整状态形成后一次性提交；中途失败丢弃成功事实，只发布失败/对账事实；
- Processor 统一协调四类独立 Reservation，部分成交只消费实际 exposure；
- update ID 与 Trade identity 分层幂等；迟到状态不回退，乱序 Trade 强制 Reconciliation；
- Broker Account/Position Snapshot 只做字段级对账，不覆盖本地历史；
- 第一版以预检、单写入者、Audit 和阻断对账提供逻辑事务，不伪装数据库原子事务。

## Rejected alternatives

- Broker callback 或 Gateway 直接修改 Manager；
- 多个 Event Handler 分散更新成交链；
- 每个 Manager 通过 Event 自行猜测 Reservation 生命周期；
- Demo 手工依次调用多个 Manager；
- 中途失败后继续发布完整成功事实或无审计反向补偿；
- Backtest 与 Live 使用不同成交编排。

## Consequences

执行更新的所有权、顺序、幂等、失败证据与最终 Snapshot 现在可确定性验证。代价是 Runtime 装配增加一个应用层 Orchestrator，
Manager Publisher 必须经过 Runtime 事实缓冲；持久事务和自动恢复需要后续 Recovery Orchestrator 决策。

## Validation

Execution 专项测试、23 个统一 Integration 场景、全部历史测试、100 次完整 Replay、Ruff 和 Mypy 共同验证本决策。
