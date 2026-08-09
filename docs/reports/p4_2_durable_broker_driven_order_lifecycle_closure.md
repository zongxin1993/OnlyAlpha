# P4.2 Durable Broker-Driven Order Lifecycle Closure

## Baseline

实施基线为 `8ec5359470de3b7853a78e63c1a6fb88d9e227dd`，与 `origin/master` 一致。P4.1 已建立唯一的
Execution Capability Resolver 和 Durable Trade / SELL CLOSE Terminal，但 Broker Accepted 与 BUY OPEN Terminal 仍在事务链外。

## Root Cause

根因不是缺少更多 Manager，而是同一 Broker 生命周期存在两种 Authority：Trade 与部分 Terminal 走 Durable Transaction，
Accepted 和 BUY OPEN Terminal 仍由 `OnlyExecutionProcessor`、`OnlyOrderUpdateProcessor` 及 Reservation Port 直接协调。结果是
Planner 无法冻结完整 before/after，Projection 缺少显式 Authority，Commit 后故障只能依赖当前 Manager 状态猜测恢复。

## Before Architecture

旧路径包括：

```text
Accepted → _accepted → OrderUpdateProcessor → Order / Position Reservation direct mutation
BUY Terminal → _terminal_order → OrderUpdateProcessor → Cash / Position / Risk direct release
SELL Terminal → Durable Transaction（但 Position Reservation Target 内仍调用 release command）
```

因此相同产品 shape 的 lifecycle operation 具有不同的持久化、幂等、事件和恢复语义。

## Hidden Mutation Audit

实施前审计见 `p4_2_broker_driven_order_lifecycle_pre_implementation_audit.md`。确认的隐藏变更包括：

- `OnlyPositionReservationExecutionProjectionTarget` 通过 `release()` 间接修改 Position 与 Allocation；
- `OnlyOrderUpdateProcessor.coordinate_reservations` 跨 Order、Position/Cash Reservation 与 Risk 编排；
- Processor 的 `_accepted`、`_terminal_order` 在 Transaction Store 外修改经济 Authority；
- Terminal 专用 Query 重复了 stable transaction identity 查询能力。

## Policy Version Correction

Execution Support 版本从错误的 schema 命名改为 `policy_version`，Fact 字段统一为
`execution_support_policy_version`。P4.2 support policy 升为 `2`；Prepared/Committed Transaction schema 升为 `7`，Runtime
Persistence schema 升为 `5`。Fact 自身的 `schema_version` 与 capability policy version 保持独立。

不存在 `execution_support_schema_version` compatibility alias。

## ORDER_ACCEPTED Architecture

新增 `ORDER_ACCEPTED` operation kind、`OnlyExecutionOrderAcceptedAuthority`、Accepted draft/committed fact、planning context、pure
planner 和强类型 Order Accepted projection。Processor 只负责 capture → resolve → plan → coordinate → translate，不再计算 Accepted
经济迁移。

BUY OPEN Accepted 的精确 Projection 集合：

```text
ORDER → STRATEGY_LEDGER → STRATEGY_CASH_RESERVATION
```

SELL CLOSE Accepted 的精确 Projection 集合：

```text
ORDER → POSITION → POSITION_RESERVATION
```

SELL Accepted 只消除账户级重复 Position risk freeze；Allocation hold 保留到 Fill 或 Terminal。

## Accepted Fact / Identity

Accepted identity 使用 `EACK-<sha256>`，输入包含 Runtime、Gateway、Account、Order、Broker Update identity 和 operation
semantic，不包含 processing sequence、wall clock 或 mutable Manager state。payload fingerprint 对完整 normalized
`OnlyBrokerOrderAcceptedUpdate` canonical payload 计算；same identity + changed payload fail closed。

查询复用 `get_by_transaction_id()` 与通用 `get_by_update()`，没有增加 lifecycle-specific Query。

## Terminal Genericization

Terminal Planner 现同时支持 BUY OPEN 与 SELL CLOSE。Terminal Fact schema 3 只保存最小业务事实：terminal identity/status/reason、
filled/remaining quantity、Cash 或 Position release summary、Risk release summary；不复制完整 Projection after state，也不伪造 Trade ID。

## BUY OPEN Terminal

Cancel、Reject、Expire 均形成一个 `ORDER_TERMINAL` transaction，精确 Projection 集合为：

```text
ORDER
→ ACCOUNT
→ STRATEGY_LEDGER
→ ACCOUNT_CASH_RESERVATION
→ STRATEGY_CASH_RESERVATION
→ RISK_RESERVATION
→ RISK
```

Partial Fill 后只释放 Account/Strategy 两本现金 Reservation 的 exact remaining amount；Account 和 Strategy Ledger 的 aggregate
cash state 使用同一冻结结果。

## SELL CLOSE Terminal

ACK 前 Terminal 显式释放账户 Position hold 与 Allocation hold；ACK 后 Position duplicate hold 已由 Accepted 消除，因此只释放
Allocation remaining hold。两种路径都显式投影 Position Reservation、Risk Reservation 和 Risk Snapshot。Partial/Multi-Fill 已提交
事实不被 Terminal 修改。

## Partial Fill + Terminal

BUY 与 SELL 都按 remaining Authority 释放，不按原始订单量或 Broker snapshot 重算。重复 Terminal 通过 stable identity 返回
duplicate；same identity + changed payload 返回 conflict。Cancel、Reject、Expire 分别有产品测试，不互相替代。

## Projection Purity

Lifecycle reducers 是纯函数，Planner 只消费 immutable planning context。Projection Target 只比较 current state 与 committed
before/after，并安装 exact after authority。Position Reservation Target 不再调用 `release()`；架构门禁禁止 Target 调用
`release/consume/acknowledged/reserve` 或历史 trade orchestration commands。

## Deleted Interfaces

已删除：

- `OnlyExecutionProcessor._accepted` direct mutation；
- `OnlyExecutionProcessor._terminal_order` direct mutation；
- `OnlyOrderUpdateProcessor.coordinate_reservations`；
- Order Update Processor 的 Risk、Position Reservation、Cash Reservation dependencies；
- Position Reservation Projection Target 的 `release()` orchestration；
- `execution_support_schema_version` 旧命名；
- lifecycle direct fallback 与 compatibility wrapper；
- `get_by_terminal_identity()` 及 Memory Store 的 Terminal 专用索引。

Order command-side Reservation Ports 仍用于订单创建、提交失败 cleanup 和 outbound command lifecycle，不是 Broker inbound
Projection Authority。

## Recovery

Accepted、Trade、Terminal 都由 Transaction Store 作为 durable authority。Recovery 顺序保持 Restore → Resolve Tail → Ordered
Projection → Rebuild Index → Validate → Open → Deliver。新增 Accepted stored-before-project、每个 Accepted Projection component
before/after fault、Memory/SQLite round-trip 与 duplicate/conflict 测试；Terminal 保留 stored-before-project、mid-projection、outbox、
checkpoint、A→B→C restart 和 uninterrupted/recovered equality 覆盖。恢复只 forward，不 rollback committed transaction。

## Architecture Guards

门禁冻结以下事实：

- Processor 中不存在 `_accepted`、`_terminal_order` 或 `coordinate_reservations`；
- Planner 不导入 Manager、Runtime、Broker Gateway 或 Transaction Store；
- Projection Target 不调用 lifecycle orchestration command；
- lifecycle support 仍由唯一 Resolver 决定，Planner 不重新授权；
- Accepted/Terminal 精确 Projection set 和 precondition/hash 完整。

## Test Matrix

覆盖：BUY/SELL Accepted、Accepted stable identity/payload conflict、Trade without explicit Accepted、BUY Cancel/Reject/Expire、SELL
before/after ACK、partial/multi-fill Terminal、exact Projection set、store failure zero mutation、duplicate idempotency、Memory/SQLite、
stored-before-project、mid-projection、outbox、checkpoint/restart、multi-cluster close cost、result boundary 与 architecture guards。

## Quality Gates

最终本地门禁全部通过：

- `uv sync --frozen --all-packages --all-groups`；
- Ruff check 与 Ruff format check：1114 files；
- Core mypy：500 source files；
- Tushare mypy：15 source files；
- MiniQMT mypy：36 source files；
- version sync：所有包为 `0.3.5`；
- `fast`：1047 passed、1 个既有环境条件 skip；
- `integration`：130 passed；
- `core-full`：1177 passed、1 个既有环境条件 skip；
- `recovery`：305 passed；
- `ashare`：5 passed；
- `miniqmt-contract`：32 passed；
- `exhaustive`：112 passed；
- 独立 architecture 复核：148 passed；
- `uv build --all-packages`：Core、Virtual Broker、Tushare、MiniQMT 的 sdist/wheel 全部成功。

GitHub `Layered Quality / final quality gate` 必须在本报告对应的远端 commit 上为绿色；本地 PASS 不替代该门禁。

## Explicit Non-Scope

NOT IMPLEMENTED IN P4.2：

- CN A-share Production Product Conformance；
- A-share production-date full dataset；
- A-share T+1 E2E product certification；
- Paper Streaming Recovery；
- Live Runtime；
- Durable Broker Outbound Command；
- Broker command retry / idempotency；
- Broker state synchronization product；
- Margin execution；
- Short execution；
- Hedging execution；
- Futures product；
- Crypto product；
- Market Product Composition Neutralization；
- Multi-account；
- Multi-broker；
- Vectorized Backtest。

## Next Phase

P4.3 继续处理 residual planner semantic cleanup 与 CN A-share 产品 Conformance 接入；不得重新引入 Broker inbound direct
mutation 或以 Market Profile 名称替代 semantic capability authority。
