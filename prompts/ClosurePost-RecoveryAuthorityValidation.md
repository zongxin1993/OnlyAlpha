# OnlyAlpha PR4.2.2b Closure：Post-Recovery Authority Validation 补强

## 一、任务目标

请基于 OnlyAlpha 当前 `master` 分支的真实代码、测试和文档，完成一个小范围 Closure Commit：

```text
PR4.2.2b Closure
Post-Recovery Authority Validation Gaps Hardening
```

当前预期基线提交为：

```text
45b135160fbc378c94f62f36ee2e21a969426e74
Feat: Post-Recovery Authority Validation 与 Recovery Finalization Hardening
```

如果实际 `master` 已更新，以当前真实代码为准，并在实施报告中说明差异。

本任务不重新设计 Recovery 架构，只补齐：

```text
跨 Authority 校验
+
Finalizer Quiescence 错误诊断
+
默认 Checker 的直接行为测试
```

当前已经完成并必须保持不变的主链是：

```text
Recovery Outcome
→ Cluster RECOVERY_FINALIZING
→ on_recovery_complete()
→ EventBus Drain
→ Quiescence
→ Post-Recovery Authority Validation
→ Checkpoint Capture
→ Checkpoint Write
→ Durable Read-Back Verify
→ Cluster RECOVERED
→ Runtime READY
```

---

# 二、任务范围

本任务必须完成：

1. 区分 Inbound Queue 与 EventBus Quiescence 错误；
2. 明确 Outbox Key 是 Durable Delivery 的幂等身份；
3. 分开验证 Outbox Event ID 和 Outbox Key；
4. 增加 Outbox Runtime Scope 校验；
5. 区分未知 Order Reservation 和终态 Order Active Reservation；
6. 补齐 Account Reservation 跨对象 Scope；
7. 补齐 Strategy Reservation 跨对象 Scope；
8. 补齐 Risk Reservation 跨对象 Scope；
9. 补齐 Position Reservation 跨对象 Scope；
10. 补齐 Margin Reservation 跨对象 Scope；
11. 增加 Reservation Currency 校验；
12. 增加 Fee Record Scope 与 Orphan 校验；
13. 增加 Settlement Record Scope、Orphan 和状态一致性校验；
14. 增加 Margin Reservation 与 Account Margin 汇总校验；
15. 为默认 Post-Recovery Checker 增加直接单元测试；
16. 重新执行全部现有 Recovery 集成测试；
17. 小范围更新 Recovery 文档和 Roadmap。

---

# 三、明确禁止扩展的范围

本任务不得实现：

```text
Unified Recovery Event Gate
Runtime Event Router
Direct Publisher 迁移
历史 Direct Event 抑制
Exactly-once Outbox
新的 Recovery Phase
新的 Cluster State
新的 Checkpoint Schema
新的 SQLite 表
新的持久化 Authority
Partial / Multi-Fill
SELL / CLOSE
Futures / Margin 正式 Transaction
Paper / Live Recovery
Full Broker Reconciliation
```

不得修改 PR4.2.2a 的 Causal Replay 和 Exact Boundary 语义。

---

# 四、编码前审计

开始修改前，重新阅读至少以下文件：

```text
src/onlyalpha/runtime/recovery/validation.py
src/onlyalpha/runtime/recovery/finalizer.py
src/onlyalpha/runtime/recovery/outcome.py
src/onlyalpha/runtime/recovery/orchestrator.py

src/onlyalpha/execution/persistence_ports.py

src/onlyalpha/account/models.py
src/onlyalpha/strategy_ledger/models.py
src/onlyalpha/position/reservation.py
src/onlyalpha/risk/reservation.py
src/onlyalpha/margin/models.py
src/onlyalpha/margin/manager.py
src/onlyalpha/fee/manager.py
src/onlyalpha/settlement/manager.py

tests/runtime/recovery/
tests/integration/test_engine_recovery_*.py
```

重点搜索：

```bash
rg "OnlyOutboxAuthorityCheck"
rg "OnlyOrderReservationAuthorityCheck"
rg "OnlyFeeSettlementMarginAuthorityCheck"
rg "POST_RECOVERY_INBOUND_QUEUE_NOT_EMPTY"
rg "POST_RECOVERY_EVENT_BUS_NOT_DRAINED"
rg "OnlyExecutionTransactionOutboxKey"
rg "account_reservations"
rg "strategy_reservations"
rg "position_reservations"
rg "risk_reservations"
rg "margin_reservations"
rg "fee_records"
rg "settlement_records"
rg "margin_records"
```

新增预实现审计：

```text
docs/reports/pr4_2_2b_validation_closure_pre_implementation_audit.md
```

审计必须回答：

1. Finalizer 当前如何执行 Quiescence 检查；
2. EventBus Pending 当前为何被归类为 Inbound Queue 错误；
3. Outbox 的正式幂等身份是什么；
4. Outbox 是否存在独立字符串 Idempotency Key；
5. 各 Reservation 模型自身已经保证哪些内部不变量；
6. 哪些 Reservation 跨 Order Scope 尚未校验；
7. Fee Record 可以和 Transaction Fact 比较哪些字段；
8. Settlement Record 可以和 Transaction Fact 比较哪些字段；
9. Settlement 状态为什么不能简单等于历史 Transaction 的 Settlement Status；
10. Margin Reservation 如何与 Account Margin 字段归约；
11. 哪些 Checker 当前没有直接单元测试；
12. 本任务实际需要修改哪些生产文件。

审计完成后再修改生产代码。

---

# 五、设计原则

## 5.1 Closure 不复制 Domain Model 内部不变量

以下模型已经在构造时保证自身合法：

```text
OnlyAccountReservation
OnlyStrategyCashReservation
OnlyPositionReservation
OnlyRiskReservation
OnlyMarginReservation
```

Validator 不应重新实现：

```text
consumed + remaining = reserved
reserved + occupied + released = original
remaining <= quantity
状态与剩余数量对应
币种内部一致
```

Closure 只验证：

> 单个对象虽然合法，但它是否属于正确的 Runtime、Account、Cluster、Instrument、Order 和 Currency。

## 5.2 不新增第二个 Outbox 幂等键

正式 Outbox 幂等身份是：

```python
OnlyExecutionTransactionOutboxKey(
    runtime_id,
    execution_sequence,
    event_sequence,
)
```

不得新增额外字符串 `idempotency_key`。

## 5.3 不重新计算 Fee、Settlement 或 Margin 业务

Validator 只比较：

```text
Committed Execution Fact
↔ Manager-owned Authority Records
```

不得重新调用：

* Fee Resolver；
* Settlement Rule；
* Margin Formula；
* Position Reducer；
* Account Reducer。

## 5.4 核心实现应小，测试应完整

预期：

```text
少量生产代码修改
+
较多精准 Checker 测试
```

---

# 六、Finalizer Quiescence 错误细化

修改：

```text
src/onlyalpha/runtime/recovery/finalizer.py
```

新增私有函数：

```python
def _require_quiescent(
    context: OnlyPostRecoveryValidationContext,
) -> None:
    boundary = context.runtime_boundary_view

    if (
        boundary.broker_inbound_count != 0
        or boundary.market_data_inbound_count != 0
    ):
        raise RuntimeError("POST_RECOVERY_INBOUND_QUEUE_NOT_EMPTY")

    if boundary.event_bus_pending_count != 0:
        raise RuntimeError("POST_RECOVERY_EVENT_BUS_NOT_DRAINED")
```

Finalizer 流程保持：

```text
begin_recovery_finalization_all()
→ EventBus drain
→ build validation context
→ _require_quiescent()
→ validator.validate()
```

不得删除 Runtime Boundary Checker 中相同检查。

两者职责不同：

```text
Finalizer Preflight
→ 快速阻止不稳定 Runtime 进入完整 Validation

Runtime Boundary Checker
→ 将检查结果纳入 Validation Report 与 Fingerprint
```

测试必须断言：

* Broker Queue 非空使用 `POST_RECOVERY_INBOUND_QUEUE_NOT_EMPTY`；
* MarketData Queue 非空使用同一错误；
* EventBus Pending 使用 `POST_RECOVERY_EVENT_BUS_NOT_DRAINED`；
* 失败 Phase 为 `QUIESCENCE_CHECK`；
* Validator 未执行；
* Checkpoint Capture 未执行；
* Cluster 进入 FAILED。

---

# 七、Outbox Authority 补强

修改：

```text
OnlyOutboxAuthorityCheck
```

## 7.1 Event ID

继续检查：

```text
event.event_id 唯一
```

错误码：

```text
POST_RECOVERY_DUPLICATE_OUTBOX_EVENT
```

Scope：

```text
event-id
```

## 7.2 Durable Outbox Key

使用完整 Key：

```python
keys = tuple(
    (
        str(item.key.runtime_id),
        item.key.execution_sequence,
        item.key.event_sequence,
    )
    for item in outbox
)
```

检查唯一性，错误码：

```text
POST_RECOVERY_DUPLICATE_OUTBOX_KEY
```

Scope：

```text
outbox-key
```

## 7.3 Runtime Scope

检查：

```python
item.key.runtime_id == context.runtime_id
```

错误码：

```text
POST_RECOVERY_OUTBOX_SCOPE_MISMATCH
```

## 7.4 保留现有校验

继续验证：

* Orphan Transaction；
* 引用 Unready Transaction；
* Continuation Outbox Missing；
* Continuation Outbox Prematurely Published；
* Pending Count。

不得改变 Durable Outbox 发布语义。

---

# 八、Order / Reservation Authority 补强

修改：

```text
OnlyOrderReservationAuthorityCheck
```

先建立：

```python
all_orders = {item.order_id: item for item in context.orders}
open_orders = {
    order_id: order
    for order_id, order in all_orders.items()
    if order.status not in terminal_statuses
}
terminal_order_ids = set(all_orders) - set(open_orders)
```

分别建立 Active Reservation Map：

```text
account
strategy
position
risk
margin
```

---

## 8.1 Unknown Order Reservation

Reservation 引用的 Order 完全不存在：

```text
POST_RECOVERY_ORPHAN_RESERVATION
```

`actual` 中应带类型前缀：

```text
account:ORDER-1
strategy:ORDER-2
position:ORDER-3
risk:ORDER-4
margin:ORDER-5
```

---

## 8.2 Terminal Order Active Reservation

Order 存在但已经处于：

```text
FILLED
CANCELLED
REJECTED
EXPIRED
FAILED
```

仍有 Active Reservation：

```text
POST_RECOVERY_TERMINAL_ORDER_ACTIVE_RESERVATION
```

不得继续与 Orphan 混为一个错误。

---

## 8.3 Account Reservation Scope

检查：

```text
reservation.runtime_id == order.runtime_id
reservation.account_id == order.account_id
reservation.order_id == order.order_id
```

找到对应 Account Snapshot 后检查：

```text
reservation.reserved_amount.currency == account.base_currency
```

---

## 8.4 Strategy Reservation Scope

检查：

```text
reservation.key.runtime_id == order.runtime_id
reservation.key.account_id == order.account_id
reservation.key.cluster_id == order.cluster_id
reservation.order_id == order.order_id
```

并检查：

```text
reservation.key.base_currency == account.base_currency
```

---

## 8.5 Risk Reservation Scope

检查：

```text
runtime_id
account_id
cluster_id
instrument_id
order_id
```

全部与 Order 一致。

保留现有 Risk Scope 校验，不得弱化。

---

## 8.6 Position Reservation Scope

如果存在 Position Reservation，检查：

```text
runtime_id
account_id
cluster_id
instrument_id
order_id
```

并检查：

```text
reservation.quantity.precision == order.quantity.precision
reservation.quantity.value <= order.quantity.value
```

当前正式 SELL / CLOSE Transaction 尚未完成，因此不要强制所有 SELL Order 必须有 Position Reservation。

---

## 8.7 Margin Reservation Scope

如果存在 Margin Reservation，检查：

```text
runtime_id
account_id
instrument_id
source_order_id
```

并检查：

```text
reservation.currency == account.base_currency
```

Generic T0 Cash 不应被强制要求 Margin Reservation。

---

## 8.8 错误码

控制错误码数量：

```text
POST_RECOVERY_OPEN_ORDER_RESERVATION_MISSING
POST_RECOVERY_ORPHAN_RESERVATION
POST_RECOVERY_TERMINAL_ORDER_ACTIVE_RESERVATION
POST_RECOVERY_RESERVATION_SCOPE_MISMATCH
POST_RECOVERY_RESERVATION_CURRENCY_MISMATCH
```

具体 Reservation 类型放入 `scope`、`actual` 或 `detail`，不要为每种 Reservation 创建大量重复错误码。

---

# 九、Fee Authority 补强

修改：

```text
OnlyFeeSettlementMarginAuthorityCheck
```

## 9.1 Fee Scope

将 Fee Record 按 `instruction_id` 分组。

对每个 Durable Transaction 对应的 Fee Record 检查：

```text
record.account_id == str(fact.account_id)
record.instrument_id == str(fact.instrument_id)
record.order_id == str(fact.order_id)
record.trade_id == str(fact.trade_id)
record.currency == fact.currency.code
```

错误：

```text
POST_RECOVERY_FEE_SCOPE_MISMATCH
```

## 9.2 Orphan Fee Record

Fee Record 的 `instruction_id` 不属于任何 Durable Transaction：

```text
POST_RECOVERY_ORPHAN_FEE_RECORD
```

## 9.3 保留现有校验

继续验证：

```text
POST_RECOVERY_FEE_RECORD_MISSING
POST_RECOVERY_FEE_TOTAL_MISMATCH
```

不得重新计算 Fee。

---

# 十、Settlement Authority 补强

## 10.1 Settlement Scope

对 Settlement Record 检查：

```text
record.account_id == str(fact.account_id)
record.instrument_id == str(fact.instrument_id)
record.source_order_id == str(fact.order_id)
record.source_trade_id == str(fact.trade_id)
record.legal_settlement_date == fact.legal_settlement_date
```

错误：

```text
POST_RECOVERY_SETTLEMENT_SCOPE_MISMATCH
```

## 10.2 Orphan Settlement Record

Settlement Record 的 `instruction_id` 不属于任何 Durable Transaction：

```text
POST_RECOVERY_ORPHAN_SETTLEMENT_RECORD
```

## 10.3 Settlement 状态内部一致性

不要直接要求：

```text
record.status == fact.settlement_status
```

因为 Transaction Fact 是提交时事实，Settlement Record 可能已经随 Trading Day 推进。

只检查 Record 自身：

```text
legal_settled is True
→ status == "SETTLED"

legal_settled is False
→ status in {"BOOKED", "PENDING"}

status == "SETTLED"
→ legal_settled is True
```

错误：

```text
POST_RECOVERY_SETTLEMENT_STATE_MISMATCH
```

继续保留：

```text
POST_RECOVERY_SETTLEMENT_RECORD_MISSING
```

---

# 十一、Margin 与 Account Authority 补强

按：

```text
account_id + currency
```

归约 Active Margin Reservation：

```python
reserved_total = sum(item.reserved)
occupied_total = sum(item.occupied)
released_total = sum(item.released)
```

对于设置了完整 Margin 字段的 Account Snapshot，检查：

```text
account.reserved_margin.amount == reserved_total
account.occupied_margin.amount == occupied_total
account.released_margin.amount == released_total
```

并检查 Currency 一致。

错误：

```text
POST_RECOVERY_MARGIN_ACCOUNT_MISMATCH
```

保留现有：

```text
POST_RECOVERY_MARGIN_STATE_MISMATCH
```

如果同时满足：

```text
没有 Margin Transaction
没有 Margin Record
没有 Margin Reservation
Account Margin 字段为空
```

Margin 检查继续返回：

```text
NOT_APPLICABLE
```

不得使 Generic T0 Cash 恢复失败。

---

# 十二、生产代码结构要求

建议仅修改：

```text
src/onlyalpha/runtime/recovery/finalizer.py
src/onlyalpha/runtime/recovery/validation.py
```

可以在 `validation.py` 中增加少量私有辅助函数：

```python
_only_active_reservation_maps(...)
_only_reservation_scope_failures(...)
_only_fee_authority_failures(...)
_only_settlement_authority_failures(...)
_only_margin_account_failures(...)
```

要求：

```text
Checker.evaluate()
→ 读取 Context
→ 调用纯辅助函数
→ 返回 Validation Check
```

不要继续堆积巨型条件表达式。

除非测试暴露真实问题，不修改：

```text
outcome.py
orchestrator.py
cluster/manager.py
checkpoint/service.py
runtime/backtest/runtime.py
runtime/runtime.py
persistence/store.py
```

---

# 十三、测试 Fixture

新增统一测试支持，例如：

```text
tests/runtime/recovery/support/authority_fixture.py
```

提供一个默认全部通过的 Context：

```python
@dataclass
class OnlyPostRecoveryAuthorityFixture:
    ...

    def context(
        self,
        **overrides: object,
    ) -> OnlyPostRecoveryValidationContext:
        ...
```

基本要求：

```text
default fixture
→ only_default_post_recovery_authority_validator()
→ report.passed is True
```

每个失败测试只修改一个 Authority，避免同时触发多个无关错误。

不得通过以下方式制造非法对象：

```text
object.__new__()
object.__setattr__()
修改 Manager 私有容器
修改 Runtime 私有字段
```

测试应构造：

> 单个 Domain Object 自身合法，但对象之间 Scope 或归约不一致。

---

# 十四、Checker 直接测试

建议新增：

```text
tests/runtime/recovery/test_post_recovery_outbox_authority.py
tests/runtime/recovery/test_post_recovery_order_reservation_authority.py
tests/runtime/recovery/test_post_recovery_fee_settlement_margin.py
tests/runtime/recovery/test_post_recovery_boundary_authority.py
```

可按仓库现有测试风格适当合并。

---

## 14.1 Outbox 测试

至少覆盖：

1. 正常 Outbox；
2. Orphan Transaction；
3. 引用 Unready Transaction；
4. Duplicate Event ID；
5. Duplicate Outbox Key；
6. Wrong Runtime Scope；
7. Continuation Outbox Missing；
8. Continuation Outbox Prematurely Published；
9. Pending Count Mismatch。

---

## 14.2 Reservation 测试

至少覆盖：

1. 正常 BUY Open Order；
2. Missing Account Reservation；
3. Missing Strategy Reservation；
4. Missing Risk Reservation；
5. Reservation 引用未知 Order；
6. Terminal Order 仍有 Active Reservation；
7. Account Scope Mismatch；
8. Account Currency Mismatch；
9. Strategy Scope Mismatch；
10. Strategy Currency Mismatch；
11. Risk Scope Mismatch；
12. Position Scope Mismatch；
13. Position Quantity 超过 Order；
14. Margin Scope Mismatch；
15. Margin Currency Mismatch。

---

## 14.3 Fee 测试

至少覆盖：

1. 正常；
2. Missing Fee Record；
3. Fee Total Mismatch；
4. Account Scope Mismatch；
5. Instrument Scope Mismatch；
6. Order Scope Mismatch；
7. Trade Scope Mismatch；
8. Currency Mismatch；
9. Orphan Fee Record。

---

## 14.4 Settlement 测试

至少覆盖：

1. 正常 BOOKED；
2. 正常 PENDING；
3. 正常 SETTLED；
4. Missing Settlement Record；
5. Account Scope Mismatch；
6. Instrument Scope Mismatch；
7. Order Scope Mismatch；
8. Trade Scope Mismatch；
9. Legal Settlement Date Mismatch；
10. Orphan Settlement Record；
11. `legal_settled=True` 但 Status 不是 SETTLED；
12. Status=SETTLED 但 `legal_settled=False`。

---

## 14.5 Margin 测试

至少覆盖：

1. Generic T0 Cash 返回 NOT_APPLICABLE；
2. 正常 Account Margin 汇总；
3. Reserved Margin Mismatch；
4. Occupied Margin Mismatch；
5. Released Margin Mismatch；
6. Currency Mismatch；
7. Negative Margin Record；
8. Margin Reservation Scope Mismatch。

---

## 14.6 Finalizer Quiescence 测试

修改现有：

```text
tests/runtime/recovery/test_recovery_finalizer.py
```

至少增加：

1. Broker Queue 非空；
2. MarketData Queue 非空；
3. EventBus Pending；
4. 全部为空正常继续；
5. Quiescence 失败时 Validator 不执行；
6. Quiescence 失败时 Checkpoint 不 Capture。

---

# 十五、架构门禁

增加或更新架构测试，至少保证：

1. Closure 不新增 Recovery Phase；
2. Closure 不新增 Cluster State；
3. Closure 不修改 Checkpoint Schema；
4. Closure 不新增 Applied Projection 持久表；
5. Closure 不新增 Outbox String Idempotency Key；
6. Outbox Key 使用 `runtime_id + execution_sequence + event_sequence`；
7. Finalizer 区分 Inbound Queue 和 EventBus 错误；
8. Validator 不访问 Manager 私有字段；
9. Validator 不调用 Mutation API；
10. Validator 不调用 Fee Resolver；
11. Validator 不调用 Settlement Rule；
12. Validator 不调用 Margin Formula；
13. Validator 不依赖具体 Virtual Broker；
14. Closure 不引入 Event Gate；
15. Closure 不改变 READY / Outbox / Resume 顺序。

源码字符串门禁只能作为辅助，正确性必须由行为测试证明。

---

# 十六、文档更新

不新增 ADR。

更新：

```text
docs/execution_runtime_recovery.md
docs/roadmap.md
```

补充说明：

```text
OnlyExecutionTransactionOutboxKey 是 Durable Outbox 的幂等身份。

PR4.2.2b Validation Closure 增加 Reservation、Fee、Settlement、
Margin 和 Outbox 的跨 Authority Scope 校验。

Validator 不复制 Domain Model 内部不变量，也不重新执行 Fee、
Settlement 或 Margin 业务计算。
```

Roadmap 将 PR4.2.2b 状态调整为：

```text
PR4.2.2b 已通过 Validation Closure 补齐跨 Authority 门禁和直接 Checker 测试。
```

仍明确：

```text
Unified Recovery Event Gate 属于 PR4.2.2c。
```

---

# 十七、实施顺序

## Step 1

完成预实现审计。

## Step 2

建立默认全部通过的统一 Validation Fixture。

## Step 3

先写红色测试，顺序：

```text
Quiescence Error
→ Outbox Key / Scope
→ Terminal Reservation
→ Reservation Scope
→ Fee Scope / Orphan
→ Settlement Scope / State / Orphan
→ Margin Account Aggregate
```

## Step 4

修改 Finalizer Quiescence。

## Step 5

修改 Outbox Checker。

## Step 6

重构 Order / Reservation Checker。

## Step 7

补强 Fee / Settlement / Margin Checker。

## Step 8

运行全部 Checker 单元测试。

## Step 9

运行现有 Recovery 集成测试。

## Step 10

运行完整 Ruff、Mypy、Pytest 门禁。

---

# 十八、必须重新运行的 Recovery 测试

至少执行：

```bash
uv run pytest tests/runtime/recovery -q

uv run pytest tests/integration/test_engine_recovery_same_bar_continuation.py -q
uv run pytest tests/integration/test_engine_recovery_multi_boundary_tail.py -q
uv run pytest tests/integration/test_engine_recovery_multiple_continuations.py -q
uv run pytest tests/integration/test_engine_recovery_finalization.py -q
uv run pytest tests/integration/test_engine_recovery_validation_failure.py -q
uv run pytest tests/integration/test_engine_recovery_checkpoint_after_commit.py -q
uv run pytest tests/integration/test_engine_recovery_three_stage_restart.py -q
```

根据仓库实际测试文件名调整。

现有 A→B→C 测试必须继续验证：

* Canonical Business Projection；
* Result Fingerprint；
* Orders；
* Trades；
* Signals；
* Artifact Manifest。

---

# 十九、完整门禁命令

至少执行：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha

uv run mypy packages/fake/onlyalpha-plugin-broker-virtual/src
uv run mypy packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare
uv run mypy packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt

uv run pytest tests/runtime/recovery -q
uv run pytest tests/runtime/checkpoint -q
uv run pytest tests/execution -q
uv run pytest tests/integration -q
uv run pytest tests/architecture -q

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"

uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q

uv run pytest packages/provider/onlyalpha-plugin-tushare/tests -q \
  -m "not external and not requires_network and not requires_tushare"

uv run pytest packages/provider/onlyalpha-plugin-miniqmt/tests -q \
  -m "not external and not requires_network and not requires_local_qmt"

git diff --check
```

不得伪造未执行的测试结果。

---

# 二十、建议修改文件

预期文件范围：

```text
src/onlyalpha/runtime/recovery/finalizer.py
src/onlyalpha/runtime/recovery/validation.py

tests/runtime/recovery/support/authority_fixture.py
tests/runtime/recovery/test_post_recovery_outbox_authority.py
tests/runtime/recovery/test_post_recovery_order_reservation_authority.py
tests/runtime/recovery/test_post_recovery_fee_settlement_margin.py
tests/runtime/recovery/test_post_recovery_boundary_authority.py
tests/runtime/recovery/test_recovery_finalizer.py

docs/reports/pr4_2_2b_validation_closure_pre_implementation_audit.md
docs/execution_runtime_recovery.md
docs/roadmap.md
```

如果需要修改更多生产文件，必须在最终报告中说明原因。

---

# 二十一、完成标准

只有全部满足才能声明 Closure Commit 完成：

1. Inbound Queue 和 EventBus 使用不同错误码；
2. Quiescence Failure 发生在 Validator 前；
3. Quiescence Failure 阻止 Checkpoint Capture；
4. Outbox Event ID 独立验证；
5. Outbox Durable Key 独立验证；
6. Outbox Runtime Scope 被验证；
7. 不新增第二个 Outbox Idempotency Key；
8. Unknown Order Reservation 独立诊断；
9. Terminal Order Active Reservation 独立诊断；
10. Account Reservation Scope 完整；
11. Strategy Reservation Scope 完整；
12. Risk Reservation Scope 完整；
13. Position Reservation Scope 完整；
14. Margin Reservation Scope 完整；
15. Reservation Currency 与 Account 一致；
16. 不复制 Reservation 自身金额公式；
17. Fee Scope 与 Transaction 一致；
18. Orphan Fee Record 被拒绝；
19. Fee Total 校验仍保留；
20. Settlement Scope 与 Transaction 一致；
21. Orphan Settlement Record 被拒绝；
22. Settlement 状态内部一致；
23. 不要求 Settlement Record 状态等于历史 Transaction 状态；
24. Margin Reservation 与 Account Margin 汇总一致；
25. Generic T0 Cash Margin 检查仍为 NOT_APPLICABLE；
26. 默认 Checker 均有直接单元测试；
27. 一个测试尽量只触发一个目标错误；
28. Validation Report Fingerprint 保持稳定；
29. Recovery Outcome 未修改；
30. Finalizer Phase 未修改；
31. Cluster Lifecycle 未修改；
32. Checkpoint Schema 未修改；
33. 4.2.2a Replay 语义未修改；
34. READY / Outbox / Resume 顺序未修改；
35. 未实现 Event Gate；
36. 所有 Recovery 集成测试通过；
37. A→B→C 与 Baseline 继续完全等价；
38. Ruff、Mypy、Pytest 和 Architecture Gate 全部通过。

---

# 二十二、禁止实现

以下任一情况视为任务失败：

```text
重新设计 Recovery Finalizer
增加新的 Recovery Phase
增加新的 Cluster State
增加新的 Checkpoint Schema
新增 SQLite Authority 表
给 Outbox 增加第二个字符串幂等键
删除 Runtime Boundary Checker
在 Validator 中重新计算 Fee
在 Validator 中重新计算 Settlement Date
在 Validator 中重新计算 Margin
在 Validator 中复制 Reservation Domain 不变量
把所有 Reservation 错误都归类为 Orphan
把 EventBus Pending 继续归类为 Inbound Queue
强制 Generic T0 Cash 存在 Margin Reservation
强制当前未正式支持的 SELL/CLOSE 完整 Reservation 模型
测试修改 Runtime 私有字段
测试修改 Manager 私有容器
测试绕过 Domain Model 构造非法对象
增加生产故障开关
实现 Recovery Event Gate
迁移 Direct Publisher
实现 Partial / Multi-Fill
实现 SELL / CLOSE
```

---

# 二十三、最终交付报告

完成后输出：

## 1. 修改前缺口

说明：

* Quiescence 诊断；
* Outbox Identity；
* Reservation Scope；
* Fee Scope；
* Settlement Scope/State；
* Margin Account Aggregate；
* Checker 测试覆盖。

## 2. 实际修改文件

列出每个文件及职责。

## 3. 新增错误码

列出并说明：

```text
POST_RECOVERY_DUPLICATE_OUTBOX_KEY
POST_RECOVERY_OUTBOX_SCOPE_MISMATCH
POST_RECOVERY_TERMINAL_ORDER_ACTIVE_RESERVATION
POST_RECOVERY_RESERVATION_CURRENCY_MISMATCH
POST_RECOVERY_FEE_SCOPE_MISMATCH
POST_RECOVERY_ORPHAN_FEE_RECORD
POST_RECOVERY_SETTLEMENT_SCOPE_MISMATCH
POST_RECOVERY_ORPHAN_SETTLEMENT_RECORD
POST_RECOVERY_SETTLEMENT_STATE_MISMATCH
POST_RECOVERY_MARGIN_ACCOUNT_MISMATCH
```

如果实际代码已有等价错误码，应复用并说明，不要重复定义。

## 4. 不变量边界

说明哪些由 Domain Model 保证，哪些由 Post-Recovery Validator 保证。

## 5. 测试结果

列出真实执行命令和结果。

## 6. 未改变的架构

明确：

```text
Recovery Outcome 未改变
Finalizer 状态机未改变
Cluster 生命周期未改变
Checkpoint Schema 未改变
Causal Replay 未改变
Event Gate 未实现
```

## 7. 下一步

明确：

```text
PR4.2.2b Closure 已完成
下一步进入 PR4.2.2c Unified Recovery Event Gate
```

---

# 二十四、最终结论

本提交完成后，PR4.2.2b 应从：

```text
恢复收尾架构完整
但部分跨 Authority 规则和直接测试不足
```

升级为：

```text
Recovery Finalization 架构完整
+
每个主要跨 Authority 关系有明确检查
+
每个错误分支有直接行为测试
+
故障诊断可准确定位
```

最终必须证明：

> OnlyAlpha 的 Post-Recovery Validator 不仅能确认 Transaction 和 Runtime Boundary 完整，还能确认 Outbox、Order、Reservation、Fee、Settlement、Margin 与其对应业务 Authority 的 Scope 和归约关系一致，同时不复制各 Domain Model 已经拥有的内部业务不变量。
