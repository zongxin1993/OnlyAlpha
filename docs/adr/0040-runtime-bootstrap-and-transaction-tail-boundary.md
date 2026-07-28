# ADR 0040: Runtime Bootstrap and Transaction Tail Boundary

- Status: Accepted
- Date: 2026-07-28

## Context

Committed Trade Transaction 保存成交产生的完整 Manager After Projection，但它的合法 Before Authority 来自已组装 Runtime。把
PR3/PR3.1 描述为 Empty Runtime Full Replay 会掩盖初始化、订单前置生命周期和非 Trade 状态缺口。

## Decision

当前恢复能力明确为：

```text
Correct Bootstrap / Before Authority
+ Ordered Committed Transaction Tail
→ Runtime Authority Recovery
```

它不等于 Empty Runtime Full Replay。Trade planner/transaction 当前依赖 Runtime config、Account、Strategy Ledger、Instrument、
Market Profile/compiled rule reference、Order submitted/accepted state、Risk Reservation、Account/Strategy cash Reservation 和初始
valuation state。

未来 Runtime startup recovery 推荐采用 `Durable Bootstrap Snapshot + Ordered Transaction Tail`。以下非 Trade Authority 必须在未来
进入 Bootstrap 或独立事务：Account/Ledger creation，Order submit/accepted/rejected/cancelled，Reservation creation，external cash
flow，Broker account/position update，market valuation，trading-day settlement，fee adjustment 和 Broker connection state。

PR4 Execution Commit Coordinator 只负责一个已经具备正确 Before Authority 的 Runtime 如何执行：

```text
Prepared Transaction
→ Durable Commit
→ Projection Apply
→ Projection Ready
→ Durable Outbox
```

PR4 不实现 Runtime startup recovery、Bootstrap Snapshot、非 Trade transaction 或 legacy journal removal。

## Consequences

Pure Planner、Real Manager Targets 与 Recovery Boundary Hardening 可以独立完成，而不虚构完整启动恢复。后续恢复设计有明确的
Bootstrap/tail 所有权边界，PR4 无需重新解释 Target recovery、Applied Ledger authority 或 Fee/Settlement Current Authority。
