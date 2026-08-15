# ADR 0081: Live Genesis, Manual Workload, and Liquidation Control

Status: Accepted

Date: 2026-08-15

## Context

目标 Live Runtime 需要接管真实 Broker 账户、允许 Web 操作 Runtime 生命周期并支持人工交易。现有合同禁止 Broker Snapshot
覆盖本地 committed history，Cluster 又严格表示 `One Strategy` workload，因此不能通过直接写 Manager、伪造 Strategy、创建
unallocated Position 或绕过 Risk 的特殊接口实现人工操作。

真实账户首次接入还可能已经存在现金、持仓、成本、未完成订单和待结算事项。若没有正式 genesis authority，Live 只能错误地
假设空账户或静默采用 Broker Snapshot。账户级紧急清仓也不是一次原子订单：它涉及停止开仓、撤销冲突订单、按 Allocation
归因、Broker Unknown、市场不可卖状态和跨多个 Live Runtime 的部分完成。

## Decision

### Web control boundary

Web 是目标产品控制面。所有 lifecycle 和人工交易请求必须经过 authenticated Application/API → `OnlyEngine` → target Runtime
正式 Command boundary。Web 不访问 Runtime Manager，不创建 Fill，不修改 Account/Position，也不把 UI state 当作 authority。

Web 可以独立控制 Engine 中每个 Runtime 的 lifecycle；该控制权不改变 ADR 0080 的 Runtime lifecycle independence。

### Live account genesis import

Live Runtime 首次 Open 前必须从 exact Broker evidence 建立可审计的本地 genesis。正式导入范围至少包含：

```text
Cash
Positions + cost basis
Open orders
Pending settlements
Broker/account identity
Evidence timestamp, source and fingerprint
```

导入必须形成 immutable、versioned、idempotent genesis/import transactions，并在 Runtime Open 前完成 schema、identity、
aggregate 与 reconciliation validation。无法解释的缺失、冲突、重复或成本归属必须 fail closed；不得自动创建空 Runtime，
不得让 Broker Snapshot 覆盖已有 committed local history。

Broker 历史成交和历史资金流水只作为带来源、时间与 fingerprint 的 evidence attachments 保存，不伪造为本地历史 Trade 或
Cash transaction。genesis 之后的 Broker 差异只能通过正式 synchronization/reconciliation fact 与 policy 处理。

### Manual workload

人工交易只属于 `LIVE`。它使用 first-class `MANUAL` workload scope，与 Strategy Cluster 并列但不伪装成 Strategy。MANUAL
workload 必须拥有明确的 identity、Allocation scope、Ledger scope、operator provenance、permission 和 audit；其 Manager 仍由
Live Runtime 独占。

每个人工订单必须经过同一正式交易链：

```text
Authenticated Operator Intent
→ Market Rule
→ Risk
→ Reservation
→ Order
→ Real Broker
→ Normalized Broker Fact
→ Durable Transaction
→ Ordered Projection
→ Manual Allocation / Ledger
```

Backtest、Sim 和 Research 不接受交互式人工交易。测试/Scenario 中预声明的确定性 action 不是产品 Manual workload。

### Liquidation control

Live 提供两个清仓作用域：

```text
Single Live Runtime
All Live Runtimes owned by one Engine
```

全部 Live Runtime 清仓使用一个 Engine-level parent request，冻结目标 Runtime set，并为每个 Runtime 创建独立 durable child
request。父请求只是编排和聚合 evidence，不是跨 Runtime transaction 或经济 authority。每个 child 独立提交、恢复和报告；一个
Runtime 失败不得回滚其他 Runtime。

Runtime 接受清仓请求后立即撤销新的开仓权限并进入 liquidation control state。Runtime 必须继续处理行情、撤单、平仓、查询、
Broker facts、reconciliation 和 recovery。清仓完成、部分完成或阻断后，在授权人工显式复位前不得恢复任何 Strategy 或 Manual
开仓权限。

清仓必须先处理冲突 working orders，再按 stable Allocation/order key 生成 close intents。所有 close intent 仍经过 Market Rule、
显式 liquidation Risk policy、Reservation、Order、Broker 和 Durable Transaction；不得直接归零 Position、跨 Allocation 猜成本或
绕过 Broker。

默认紧急退出价格层级为：

```text
Counterparty level 1
→ Market execution when explicitly supported
→ Explicit emergency liquidation price
```

当前只冻结层级，不冻结短等待时间、重报 cadence、最大滑点、Market Order 表达或 emergency liquidation price 算法。实现前必须
以 versioned Liquidation Execution Policy、Market Product instruction、Broker capability 和安全门禁明确这些参数；不支持的市场
或 Broker 必须 fail closed，不能猜价或把 LIMIT 隐式称为 MARKET。

真实清仓不具有跨订单或跨 Runtime 原子性。正式 outcome 必须表达 `COMPLETED`、`PARTIALLY_COMPLETED`、`BLOCKED` 或
`ABORTED`，并保留每个 Runtime、Instrument、Allocation、Order 的剩余数量与稳定原因。T+1 不可卖、停牌、无有效报价、拒绝、
Broker Unknown、网络故障和未成交都不得被描述为清仓成功。重复请求必须通过稳定 request identity 幂等收敛。

## Rejected Alternatives

1. Web 直接调用 Manager 或 Broker SDK。
2. 将人工操作伪装成隐藏 Strategy Cluster。
3. 允许无 Allocation/Ledger 归属的账户级人工订单。
4. 首次 Live 启动假设空账户，或用 Broker Snapshot 覆盖本地历史。
5. 将 Broker 历史成交重放为伪造的本地历史交易。
6. 一键清仓直接修改 Position，或绕过 Market Rule/Risk/Reservation/Order。
7. 建立跨 Live Runtime 的原子经济事务和回滚。
8. 清仓完成后自动恢复开仓权限。
9. 在 capability 或定价证据不足时静默退化到任意价格。

## Consequences

- Live 需要正式 genesis transaction kind/contract、evidence attachment、import validation 和 recovery schema。
- Trading workload/attribution contract 需要在不削弱 Cluster=`One Strategy` 的前提下容纳 `MANUAL` scope。
- Web/API 需要 authenticated command、authorization、idempotency、audit 与独立 Runtime lifecycle endpoints。
- Live control plane 需要 liquidation/halted permission state，但该 operational state 不能成为经济规则或 Runtime-type permission。
- Result、Artifact、Observation 和 Web 必须区分 request accepted、orders submitted、partial completion 与 actual flat position。
- 当前 `LIVE` Factory unsupported；本 ADR 不激活真实资金、Manual workload 或 liquidation 产品能力。

## Validation / Architecture Guards

后续产品验收至少覆盖：

```text
Verified genesis import and new-process recovery
Existing-local-history conflict fail closed
Manual order full-kernel path and operator audit
No Manual workload outside LIVE
Single-runtime and all-runtime liquidation
Parent/child request idempotency and partial failure
No reopen before explicit authorized reset
T+1, suspension, stale quote, reject, unknown and reconnect outcomes
No Position/Account direct mutation
No success claim before verified flat authority
```
