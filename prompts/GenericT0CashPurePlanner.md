# OnlyAlpha PR2.1：Generic T0 Cash Pure Planner 真实性、业务等价性与故障矩阵收口

## 一、任务目标

以 OnlyAlpha 当前 `master` 最新源码、测试、已接受 ADR 和正式领域模型为唯一事实源，对已经实现的：

```text
Generic T0 Cash
LIMIT BUY OPEN
Pure Reducers
OnlyTradeExecutionTransactionPlanner
```

进行完整的真实性、业务正确性、无副作用和故障边界验证。

当前审计基线提交为：

```text
86b0ac25b7281077a7ac577c30ba6f1c1f364f36
Feat: Generic T0 Cash Pure Reducers 与 Prepared Transaction Planner
```

开始工作时必须重新读取实际 `HEAD`。如果 `master` 已变化，以最新源码为准，不得机械依赖本提示词中的文件行号、字段或历史判断。

本 PR 的最终目标不是增加更多交易类型，而是证明：

```text
真实 Manager Before Authority
+ 真实 Broker Trade Update
+ 真实 Market/Fee Instruction
→ Pure Planner
→ 完整 Prepared Transaction
```

在当前支持范围内具有：

```text
业务正确
状态完整
经济一致
结果确定
无外部副作用
故障原子
足以成为 PR3 Projection Target 的唯一业务输入
```

本 PR 完成后，下一步必须能够直接开展：

```text
PR3：Real Manager Projection Targets
```

不得遗留“以后再补 Manager 等价性”“以后再补 Reducer 测试”“以后再验证无副作用”等尾项。

---

# 二、当前问题背景

PR2 已实现：

* `OnlyTradeExecutionPlanningContext`；
* `OnlyPlannedTrade`；
* Position/Allocation Creation Authority；
* Order、Position、Allocation、Settlement、Fee Reducer；
* Account、Strategy Ledger Reducer；
* Cash/Risk Reservation Reducer；
* Risk、Valuation Reducer；
* Projection Builder；
* Preconditions；
* Deterministic Durable Events；
* `OnlyTradeExecutionTransactionPlanner`；
* 12 项 Generic T0 Cash Projection；
* Prepared Transaction；
* 基础确定性测试。

但当前测试没有充分证明实现可以作为后续 Projection Target 的权威业务结果。

现有问题至少包括：

## 2.1 Manager Parity 测试并未运行真实 Manager

当前所谓 Manager Parity 主要检查少数字段和人工公式，例如：

```text
Order Filled Quantity
Position Quantity
Allocation Quantity
Account Cash
Ledger Cash
```

它没有执行完整真实 Manager 路径，也没有比较完整 After State。

## 2.2 测试 Context 不是从真实 Manager Authority 构造

当前 Factory 主要从已有测试 Projection Fixture 提取 Before State，再人工修改：

```text
Frozen Cash
Available Cash
Reservation
```

因此它不能证明：

```text
真实 Snapshot Converter
→ Execution State
→ Planner
```

能够处理真实 Manager 状态。

## 2.3 Reducer 测试覆盖不足

当前 Reducer 测试没有逐项覆盖：

* 新实体；
* 已存在实体；
* Scope；
* Currency；
* Sequence；
* Version；
* Timestamp；
* Precision；
* Reservation State；
* Record Sequence；
* 失败输入；
* 输入不可变；
* 完整经济结果。

## 2.4 Planner 无副作用证明不足

当前仅验证：

```python
context == before
```

这不能证明：

* Manager 没有变化；
* Repository 没有变化；
* Manager 内部索引没有变化；
* Store 没有写入；
* EventBus 没有发布；
* Legacy Journal 没有写入；
* Audit/Reconciliation Queue 没有变化。

## 2.5 故障矩阵缺失

尚未证明任意 Reducer 或事务构造阶段失败时：

```text
无 Prepared Transaction
无 Manager Mutation
无 Store Write
无 Event Publish
无 Journal Append
无部分结果泄漏
```

## 2.6 部分业务语义仍需重新验证

必须重点审计：

* Account 和 Ledger Version 实际推进次数；
* Account Cash Reservation 消费和释放顺序；
* Strategy Cash Reservation 消费和释放顺序；
* Frozen Cash 与 Cash Reserved 的最终状态；
* Settlement Record Sequence；
* Fee Record Sequence；
* Position/Allocation 新建 Cycle；
* Risk State 到底代表订单剩余风险、已成交持仓风险还是其他权威；
* Valuation 的更新时间和 Version；
* Account 与 Ledger 在单 Cluster 场景中的相等约束是否被错误固化为通用约束；
* Event Intent 与旧 Manager Event 的语义差异；
* `ts_event` 与 `ts_init` 在各状态中的实际使用规则。

这些问题必须在 PR2.1 中解决，不得推迟到 PR3。

---

# 三、第一性原则

## 3.1 当前源码和真实 Manager 行为优先

判断优先级：

```text
当前源码与真实测试行为
→ 已接受 ADR
→ 当前架构文档
→ README / AGENTS
→ 历史报告
→ 历史 Prompt
```

不得仅根据 PR2 Prompt 假定 Manager 行为。

## 3.2 旧路径不是无条件正确，但必须被完整解释

当前正式 Manager-before-Journal 路径是已运行的产品行为，因此是重要的行为基线。

但如果旧路径存在明确错误，不能为了“测试一致”把错误复制到 Pure Reducer。

发生差异时必须分类：

```text
A. Pure Reducer Bug
B. Legacy Manager Bug
C. Snapshot Converter Bug
D. Fixture Bug
E. Contract/ADR 不明确
F. 有意的事务语义变化
```

每个差异必须：

1. 找到真实根因；
2. 明确业务权威；
3. 修正对应实现；
4. 增加回归测试；
5. 更新 ADR 或设计文档。

不得用宽松字段过滤掩盖差异。

## 3.3 Pure Planner 仍然不能接触 Manager

即使为了测试真实 Manager，也必须保持生产边界：

```text
Manager Snapshot
→ Test Context Builder
→ Immutable Planning Context
→ Planner
```

禁止改成：

```text
Planner
→ 查询 Manager
```

Planner 和 Reducer 不得新增任何 Manager、Repository、Runtime、Store 或 EventBus 依赖。

## 3.4 测试可以白盒检查，生产代码不得增加测试后门

为了验证 Manager 内部 Authority，可以在 `tests/` 中建立白盒状态摘要。

禁止在生产代码中新增：

```text
debug_state()
test_snapshot()
unsafe_dump()
skip_validation
test_only
```

如果新增只读导出接口，它必须具有明确的正式恢复、审计或查询价值，并通过架构评审；不能只为测试服务。

## 3.5 不扩大交易范围

本 PR 仍然只支持：

```text
Market Profile: GENERIC_T0_CASH
Order Type: LIMIT
Order Side: BUY
Offset: OPEN
Position Side: LONG
Position Mode: NETTING
Fill: 整单成交
Account: 单 Account
Cluster: 单 Cluster
Currency: 单币种
Margin: 无
```

不得在本 PR 实现：

```text
SELL
CLOSE
Partial Fill
多次成交
最低佣金累计
Margin
Futures
Multi-Currency
Multi-Account
Multi-Cluster Shared Account 正式支持
```

可以增加这些输入的拒绝测试，但不得实现其业务路径。

---

# 四、实施前重新审计

开始修改前执行：

```bash
git status
git rev-parse HEAD
git log -n 15 --oneline

rg "OnlyTradeExecutionTransactionPlanner"
rg "OnlyTradeExecutionPlanningContext"
rg "OnlyPlannedTrade"

rg "class OnlyOrderTradeReducer"
rg "class OnlyPositionTradeReducer"
rg "class OnlyAllocationTradeReducer"
rg "class OnlySettlementTradeReducer"
rg "class OnlyFeeTradeReducer"
rg "class OnlyAccountTradeReducer"
rg "class OnlyStrategyLedgerTradeReducer"
rg "class OnlyAccountCashReservationTradeReducer"
rg "class OnlyStrategyCashReservationTradeReducer"
rg "class OnlyRiskReservationTradeReducer"
rg "class OnlyRiskTradeReducer"
rg "class OnlyValuationTradeReducer"

rg "test_trade_planner_manager_parity"
rg "only_test_generic_t0_trade_planning_context"

rg "class OnlyExecutionProcessor"
rg "def _trade"
rg "apply_trade"
rg "apply_trade_cash_flow"
rg "apply_trade_accounting"
rg "consume_cash_reservation"
rg "release_cash_reservation"
rg "settlement_manager"
rg "fee_manager"
```

形成修改前审计报告，至少回答：

1. 正式旧 Trade 路径实际调用顺序；
2. 每个 Manager 修改前后的 Snapshot；
3. 每个 Manager 的 Version 实际推进次数；
4. 每个 Manager 使用 `ts_event` 还是 `ts_init`；
5. Position Cycle 如何产生；
6. Allocation Cycle 如何产生；
7. Settlement Record Sequence 如何产生；
8. Fee Record Sequence 如何产生；
9. Account Reservation 的消费、释放和状态转换顺序；
10. Strategy Reservation 的消费、释放和状态转换顺序；
11. Risk Reservation 与 Risk State 的实际语义；
12. Valuation 是成交过程中直接修改还是后续服务修改；
13. 旧路径产生哪些 Event；
14. 旧路径写入哪些 Journal、Audit、Dedup、Sequence 和 Reconciliation 状态；
15. 当前 PR2 Reducer 与上述真实行为存在哪些差异。

不得在审计完成前直接修改实现。

---

# 五、建立真实 Manager Baseline Harness

新增正式测试基础设施，例如：

```text
tests/execution/factories/real_trade_manager_factory.py
tests/execution/support/manager_authority_digest.py
tests/execution/support/generic_t0_trade_harness.py
```

具体文件可调整，但职责必须清晰。

## 5.1 Harness 必须使用真实生产类

至少使用真实：

```text
OnlyOrderManager
OnlyOrderUpdateProcessor
OnlyPositionManager
OnlyPositionAllocationManager
OnlyAccountManager
OnlyStrategyLedgerManager
OnlySettlementManager
OnlyFeeManager
OnlyRiskService
OnlyRiskReservationManager
OnlyAccountReservationManager
OnlyStrategyCashReservationManager
OnlyExecutionProcessor
```

具体依赖以当前源码为准。

不得用简化 Fake Manager 替代被比较组件。

允许使用确定性的 Test Port：

* Fixed Clock；
* In-memory Repository；
* Capturing Publisher；
* In-memory EventBus；
* In-memory Audit/Journal/Store；
* Deterministic Broker Update Source。

这些 Port 只能替代外部基础设施，不能替代核心领域 Manager。

## 5.2 建立同源双环境

从同一场景定义创建两个完全独立环境：

```text
Environment A：Legacy Execution Environment
Environment B：Pure Planning Environment
```

两者必须拥有相同的：

* Runtime ID；
* Account ID；
* Cluster ID；
* Instrument；
* Initial Cash；
* Order；
* Risk Reservation；
* Account Cash Reservation；
* Strategy Cash Reservation；
* Market Profile；
* Market Rule Instruction；
* Fee Instruction；
* Broker Trade Update；
* Clock Time；
* Trading Day。

不得在环境 A 执行后再从其 After State 构造环境 B。

必须从同一个不可变 Scenario Definition 独立构造。

## 5.3 Environment A

Environment A 必须执行真实正式业务路径。

优先级：

```text
真实 OnlyExecutionProcessor.process(OnlyBrokerTradeUpdate)
```

如果完整 Processor 装配不适合单元测试，可以使用真实 Manager 的正式公共调用顺序构造一个测试级 Legacy Driver。

但该 Driver 必须：

* 严格复制当前 `OnlyExecutionProcessor` 的实际 Trade 顺序；
* 调用真实生产方法；
* 不复制业务公式；
* 不直接修改私有字段；
* 有测试证明调用顺序与 Processor 当前实现一致。

优先使用真实 Processor，避免产生第二套测试业务路径。

## 5.4 Environment B

Environment B：

1. 从真实 Manager Snapshot 读取 Before Authority；
2. 使用正式 Snapshot→Execution State Converter；
3. 构造 `OnlyTradeExecutionPlanningContext`；
4. 调用 `OnlyTradeExecutionTransactionPlanner.prepare()`；
5. 不调用任何 Projection Target；
6. 不修改 Manager。

Context Factory 必须从真实状态构造，不得从测试 Projection Fixture 反向提取。

---

# 六、Manager Authority Digest

建立测试侧完整 Authority Digest。

示例：

```python
@dataclass(frozen=True, slots=True)
class OnlyTestRuntimeAuthorityDigest:
    orders: object
    positions: object
    allocations: object
    accounts: object
    account_reservations: object
    ledgers: object
    strategy_reservations: object
    risk_state: object
    risk_reservations: object
    settlement: object
    fees: object
    deduplication: object
    sequences: object
    journal: object
    event_buffer: object
    event_bus: object
    reconciliation: object
```

具体类型放在 `tests/`，不必使用 `Only` 前缀要求，但推荐保持一致。

Digest 必须覆盖：

## Order

* 所有 Order Snapshot；
* ID Generator State；
* External Sequence；
* Event Sequence；
* Request/Client/Venue ID 映射，如属于 Manager 权威。

## Position

* Active；
* Closed；
* Trade Fingerprints；
* Cycles；
* Repository Snapshot；
* Event Sequence。

## Allocation

* Active Allocation；
* Closed/History；
* Trade Fingerprints；
* Cycles；
* Repository；
* Event Sequence。

## Account

* Account Snapshot；
* Account Reservation Manager；
* Trade IDs；
* Fee IDs；
* Cash Change IDs；
* Valuation Versions；
* Repository；
* Event Sequence。

## Strategy Ledger

* Ledger Snapshot；
* Scope Index；
* Reservation Managers；
* Trade Fingerprints；
* Fee IDs；
* Cash Flow IDs；
* Valuation Versions；
* Equity Timeline；
* Repository；
* Event Sequence。

## Risk

* Risk Decision State；
* Risk Reservations；
* Request Cache；
* Audit；
* Kill Switch State；
* Event Sequence。

## Settlement

* Pending Instruction State；
* Records；
* Record Sequence。

## Fee

* Records；
* Instruction Idempotency Keys；
* Record Sequence。

## Execution

* Deduplicator；
* Source Sequence Tracker；
* Processing Sequence；
* Audit Store；
* Reconciliation Queue；
* Legacy Journal；
* Prepared Transaction Store；
* Event Buffer；
* EventBus。

Digest 必须使用稳定排序，避免字典插入顺序影响比较。

---

# 七、完整业务等价性测试

新增或彻底重写：

```text
tests/execution/test_trade_planner_manager_parity.py
```

旧的少数字段公式测试不得继续称为 Manager Parity。

## 7.1 Baseline：新 Position、新 Allocation、零费用

场景：

```text
GENERIC_T0_CASH
LIMIT BUY OPEN
LONG NETTING
整单成交
新 Position
新 Allocation
零费用
Reservation 精确等于成交成本
```

比较完整状态。

## 7.2 非零费用

场景：

```text
成交 Notional + 非零 Fee
Reservation 精确等于 Notional + Fee
```

验证：

```text
Fee Projection Total
=
Fact Fee Total
=
Account Fee Delta
=
Ledger Fee Delta
=
Position Fee Delta
=
Allocation Fee Delta
```

## 7.3 超额 Cash Reservation

场景：

```text
Reserved Amount > Actual Notional + Fee
```

验证：

* Consumed；
* Released；
* Remaining；
* Reservation State；
* Account Frozen Cash；
* Ledger Cash Reserved；
* Account Available Cash；
* Ledger Cash Available。

## 7.4 已存在 Position 和 Allocation

场景：

```text
已有 LONG NETTING Position
已有 Cluster Allocation
第二笔 BUY OPEN
```

仍是单笔整单成交，不是同一个 Order 的 Partial Fill。

验证：

* Average Open Price；
* Total/Settled/Unsettled Quantity；
* Fee Accumulation；
* Stable Order；
* Version；
* Last Trade Sequence；
* Opened At 不被覆盖；
* Position/Allocation ID 不变。

## 7.5 Existing Settlement/Fee Sequence Head

使用非零：

```text
settlement_record_sequence
fee_record_sequence
```

验证生成 Record ID 和 Sequence 与真实 Manager 一致。

---

# 八、字段级比较规则

默认必须逐字段完全比较。

至少比较：

## Order

```text
Order ID
Request ID
Client Order ID
Venue Order ID
Runtime
Cluster
Account
Instrument
Side
Offset
Type
TIF
Quantity
Filled Quantity
Remaining Quantity
Average Fill Price
Status
Created/Submitted/Accepted/Updated/Filled Time
Version
Last External Sequence
Failure/Rejection
Tags/Metadata
```

## Position

```text
Position ID
Key
Status
Total Quantity
Settled Quantity
Unsettled Quantity
Order Frozen
Risk Reserved
Restricted
Average Open Price
Realized PnL
Fees
Opened/Updated/Closed Time
Version
Last Trade Sequence
Last Trade Order
Quality Flags
Broker Available
```

## Allocation

比较完整正式 Execution State 所有字段。

## Account

比较：

```text
Cash Balance
Frozen Cash
Unsettled Cash
Available Cash
Realized PnL
Unrealized PnL
Fees
Position Market Value
Equity
Margin Fields
Status
Updated At
Valuation Time
Version
Last External Sequence
Quality Flags
```

## Strategy Ledger

比较：

```text
Capital
Cash Balance
Cash Reserved
Cash Available
Position Cost
Position Market Value
Realized PnL
Unrealized PnL
Fees
Equity
Cash Entries
Fee Entries
Reservations
Updated At
Valuation Time
Version
Last Trade Sequence
Last Trade Order
Quality Flags
```

## Reservations

比较所有正式字段，不只比较 Remaining Amount。

## Settlement、Fee、Risk、Valuation

比较完整 State、Record 和 Version。

---

# 九、Version 和时间语义必须收口

不得默认所有 Projection 都是：

```python
after.version = before.version + 1
```

必须根据真实业务语义逐项验证。

旧 Manager 可能在一个 Trade 中调用多个正式 Mutation，例如：

```text
Consume Reservation
→ Apply Trade Cash Flow
```

这可能导致 Version 多次推进。

PR2.1 必须明确选择以下其中一种语义：

## 方案 A：保持现有 Manager 最终 Version

Projection After State 的 Version 与旧路径最终 Snapshot 完全一致。

即使 Projection 是一次原子安装，也允许：

```text
result_version > expected_version + 1
```

该方案更利于平滑切换和真实 Snapshot 一致性。

## 方案 B：重新定义原子 Transaction Version

每个 Projection 只推进一次 Version。

只有在有充分架构理由并更新 ADR 后才允许。

如果选择该方案，必须：

* 明确版本语义改变；
* 说明旧路径与新路径差异；
* 证明不会破坏现有 Query、Dedup、Recovery 和 Concurrency；
* 修改所有相关测试；
* 为主链切换制定一次性迁移方案。

默认优先采用方案 A。

不得在测试中简单忽略 Version 差异。

时间字段同样必须收口：

```text
created_at
opened_at
updated_at
filled_at
valuation_time
ts_event
ts_init
```

不得用“时间差异不重要”跳过比较。

---

# 十、Event 语义等价性

Legacy Event 和新 Durable Event 的 ID 生成机制不同，因此不要要求两者 Event ID 相同。

但必须比较：

* Event Type；
* Component；
* Business Scope；
* Order/Trade/Position/Account/Cluster；
* Event Timestamp；
* Event Payload；
* Event 顺序；
* 是否缺失重要业务事件；
* 是否重复产生同一业务语义。

建立明确映射，例如：

```text
Legacy ORDER_FILLED
↔ Planner ORDER_FILLED Intent

Legacy POSITION_OPENED
↔ Planner POSITION_OPENED Intent
```

如果新事务设计有意合并或删除旧内部事件，必须更新 ADR 并证明：

* Durable 业务事实没有丢失；
* Result/Analytics 不依赖被删除事件；
* Event Consumer 不会失去必要语义。

新 Planner 自身必须继续满足：

```text
相同 Context
→ 相同 Event Count
→ 相同 Event Sequence
→ 相同 Event IDs
→ 相同 Event Payload
```

---

# 十一、Risk 语义审计

当前 `OnlyRiskExecutionState` 和 `OnlyRiskTradeReducer` 必须认真重新审计。

必须回答：

1. `quantity_exposure` 代表什么？
2. `notional_exposure` 代表什么？
3. 它们是：

   * 订单未成交风险；
   * Reservation Remaining；
   * 成交后持仓风险；
   * Cluster 总风险；
   * 单 Order 风险；
   * 其他？
4. Fill 后应该归零、转移还是增加？
5. Risk State 的 Entity Key 为什么包含 Order ID？
6. Risk Reservation After 与 Risk State After 是否应完全相同？
7. 当前真实 RiskService 在成交后执行什么操作？

不能仅因为测试 Fixture 可通过，就保留语义不清晰的 Risk Projection。

如果现有 `OnlyRiskExecutionState` 只是 PR1/PR2 的错误抽象，必须在 PR2.1 中修正 Contract、Codec、Fixture、Reducer 和测试。

不得把 Risk Contract 问题推迟给 PR3。

---

# 十二、Account 与 Strategy Ledger 单 Cluster 限制

当前 Planner 可能要求：

```text
Account Cash Balance == Strategy Ledger Cash Balance
Account Position Market Value == Strategy Ledger Position Market Value
```

这在：

```text
单 Account
单 Cluster
无外部资金分配差异
```

的初始纵切面中可能成立。

但它不能成为通用 Account/Ledger Contract。

PR2.1 必须确保：

* 该约束只存在于 Generic T0 单 Cluster Planner Validation；
* 错误信息明确说明是首期场景限制；
* 不下沉到通用 Projection Contract；
* 不下沉到通用 Execution State；
* 不影响未来多 Cluster 共用 Account；
* 使用稳定错误码；
* ADR 明确标注其临时业务范围。

禁止通过 `assert` 表达该限制。

---

# 十三、逐 Reducer 单元测试

建立或拆分：

```text
tests/execution/reducers/test_order_trade_reducer.py
tests/execution/reducers/test_position_trade_reducer.py
tests/execution/reducers/test_allocation_trade_reducer.py
tests/execution/reducers/test_settlement_trade_reducer.py
tests/execution/reducers/test_fee_trade_reducer.py
tests/execution/reducers/test_account_trade_reducer.py
tests/execution/reducers/test_strategy_ledger_trade_reducer.py
tests/execution/reducers/test_cash_reservation_trade_reducers.py
tests/execution/reducers/test_risk_trade_reducers.py
tests/execution/reducers/test_valuation_trade_reducer.py
```

文件可合理合并，但不得只保留一个十几行的总测试。

每个 Reducer 必须覆盖：

## 13.1 正常路径

* Before；
* After；
* Projection；
* Version；
* State Hash；
* Payload Hash；
* Event Intent；
* Domain Delta；
* 输入对象保持不变。

## 13.2 新实体与已有实体

适用 Position、Allocation、Settlement、Fee 等。

## 13.3 Scope

* Runtime；
* Account；
* Cluster；
* Instrument；
* Order；
* Trade；
* Currency。

## 13.4 Precision

* Price Precision；
* Quantity Precision；
* Money Quantization；
* Average Price Rounding；
* Contract Multiplier。

## 13.5 Sequence

* External Sequence；
* Stable Trade Order；
* Record Sequence；
* Version；
* Idempotency Key。

## 13.6 非法状态

* Terminal Order；
* Missing Creation Authority；
* Unexpected Creation Authority；
* Insufficient Reservation；
* Negative Cash；
* Currency Mismatch；
* Stale Trade；
* Invalid Settlement Instruction；
* Invalid Fee Instruction；
* Invalid Risk State。

## 13.7 确定性

同一输入运行至少 100 次：

```text
Reduction Result 完全相等
Projection 完全相等
Encoded Projection 完全相等
```

---

# 十四、Planner Validation 测试

覆盖全部稳定错误码。

至少包括：

```text
UNSUPPORTED_MARKET_PROFILE
UNSUPPORTED_ORDER_TYPE
UNSUPPORTED_ORDER_SIDE
UNSUPPORTED_OFFSET
UNSUPPORTED_POSITION_SIDE
UNSUPPORTED_POSITION_MODE
PARTIAL_FILL_UNSUPPORTED
MARGIN_UNSUPPORTED
POSITION_RESERVATION_FORBIDDEN
SCOPE_MISMATCH
CURRENCY_MISMATCH
MISSING_BEFORE_STATE
MISSING_CREATION_AUTHORITY
UNEXPECTED_CREATION_AUTHORITY
STALE_EXTERNAL_SEQUENCE
INVALID_ORDER_STATE
INVALID_RESERVATION_STATE
REDUCTION_INVARIANT_FAILED
```

对于每个错误：

* 验证准确 Error Code；
* 验证不返回 Prepared Transaction；
* 验证 Manager Authority Digest 不变；
* 验证 Store/Event/Journal 不变。

不得只检查抛出 `ValueError`。

---

# 十五、真实无副作用测试

新增：

```text
tests/execution/test_trade_planner_real_manager_side_effects.py
```

流程：

1. 创建真实 Manager 环境；
2. 建立完整 Authority Digest；
3. 从真实 Snapshot 构造 Planning Context；
4. 调用 Planner；
5. 再建立 Authority Digest；
6. 完整比较。

必须证明：

```text
Before Digest == After Digest
```

至少包括：

* Manager Entity State；
* Repository；
* Fingerprint；
* Cycle；
* Index；
* Reservation；
* Event Sequence；
* Store；
* Journal；
* Audit；
* Reconciliation；
* Dedup；
* Source Sequence；
* Event Buffer；
* EventBus。

同时验证 Prepared Transaction 已正常生成。

---

# 十六、故障注入矩阵

需要能够在每个规划阶段注入确定性故障。

不得在生产代码中增加测试分支。

可使用以下方式：

* 直接测试单 Reducer；
* 测试专用 Planner Assembly；
* Monkeypatch Reducer 实例；
* 注入符合正式 Protocol 的 Test Reducer；
* 构造会自然触发错误的输入。

故障点至少覆盖：

```text
Context Validation
Planned Trade Construction
Order Reduction
Position Reduction
Allocation Reduction
Settlement Reduction
Fee Reduction
Account Reduction
Strategy Ledger Reduction
Account Reservation Reduction
Strategy Reservation Reduction
Risk Reservation Reduction
Risk Reduction
Valuation Reduction
Fact Draft Construction
Projection Finalization
Precondition Construction
Event Construction
Prepared Transaction Invariant Validation
```

每个故障必须验证：

```text
No Prepared Transaction
No Partial Projection Escape
No Partial Event Escape
No Manager Mutation
No Store Write
No Journal Append
No EventBus Publish
No Dedup Mutation
No Sequence Mutation
No Reconciliation Request
```

---

# 十七、Prepared Transaction 完整一致性测试

对于所有合法场景，验证：

## Projection 顺序

严格是：

```text
ORDER
POSITION
ALLOCATION
SETTLEMENT
FEE
ACCOUNT
STRATEGY_LEDGER
ACCOUNT_CASH_RESERVATION
STRATEGY_CASH_RESERVATION
RISK_RESERVATION
RISK
VALUATION
```

## Presence Matrix

必须不包含：

```text
POSITION_RESERVATION
MARGIN
MARGIN_RESERVATION
```

## Preconditions

每个 Projection 恰好一个：

```text
component
entity_key
expected_version
expected_state_hash
```

并与 Projection Identity 完全一致。

## Economic Invariants

至少验证：

```text
Fill Quantity
=
Order Filled Delta
=
Position Quantity Delta
=
Allocation Quantity Delta
```

```text
Authoritative Fee
=
Fee State Total
=
Position Fee Delta
=
Allocation Fee Delta
=
Account Fee Delta
=
Ledger Fee Delta
```

```text
Cash Delta
=
-(Settled Notional + Fee)
```

```text
Account Cash Delta
=
Ledger Cash Delta
```

```text
Account Reservation Consumed
=
Strategy Reservation Consumed
=
Settled Notional + Fee
```

```text
Released Amount
=
Reserved Amount - Consumed Amount
```

```text
Account Equity
=
Account Cash + Account Position Market Value
```

```text
Ledger Equity
=
Ledger Cash + Ledger Position Market Value
```

```text
Valuation Equity
=
Valuation Cash + Valuation Position Market Value
```

---

# 十八、确定性压力测试

保留现有 100 次字节级测试，并扩展：

## 同一 Context

```text
Prepared Transaction 相等
Canonical Payload 字节级相等
Transaction ID 相等
Authority Hash 相等
Payload Hash 相等
Projection Hash 相等
State Hash 相等
Event IDs 相等
```

## `prepared_at` 改变

```text
Transaction ID 不变
Authority Hash 不变
Payload Hash 改变
```

## Mapping 插入顺序改变

对 Metadata、Tags、Breakdown 等 Mapping 使用不同插入顺序，结果必须相同。

## Planner/Reducer 实例重建

每轮创建新对象，结果仍必须相同。

## 环境无关

禁止依赖：

* Python Hash Seed；
* Object ID；
* 当前系统时间；
* UUID4；
* Set 遍历；
* Dict 非规范顺序；
* 本地时区；
* 进程启动顺序。

---

# 十九、架构边界测试

扩展：

```text
tests/architecture/test_trade_planning_boundaries.py
```

确保：

* Planner 不 import Manager；
* Reducer 不 import Manager；
* Planner 不 import Repository；
* Reducer 不 import Repository；
* Planner 不 import Store；
* Reducer 不 import Store；
* Planner 不 import EventBus；
* Reducer 不 import EventBus；
* Planner 不 import Runtime；
* Planner 不 import Broker Gateway；
* Planner 不调用 Clock；
* Planner 不调用系统时间；
* Planner 不使用 UUID4；
* Planner 不调用 `OnlyEventId.new()`；
* Planner 不调用 Legacy Journal；
* Planner 不调用 Manager Mutation；
* Planner 不调用 `apply_trade()`；
* Planner 不调用 `consume()`；
* Planner 不调用 `release()`；
* Reducer 不修改输入对象；
* 生产代码不存在 Test Hook；
* 不存在 Validation Bypass；
* 不存在 Compatibility Planner；
* 不存在 Legacy Reducer Alias；
* 不存在生产双写。

---

# 二十、允许的生产代码修改

PR2.1 不是只允许改测试。

如果真实等价性验证发现错误，允许修改：

* Planning Context；
* Planned Trade；
* Reducer；
* Projection Builder；
* Planner Validation；
* Fact Draft；
* Event Intent；
* Projection Contract；
* Economic Invariant Validator；
* Execution State；
* Snapshot Converter；
* Codec；
* Fixture；
* ADR。

但必须满足：

1. 修改由真实业务差异驱动；
2. 不扩大支持交易类型；
3. 不引入 Manager 依赖；
4. 不实现 Projection Target；
5. 不接入 Store；
6. 不切换 ExecutionProcessor；
7. 不保留被替代接口；
8. 更新所有调用方和测试。

---

# 二十一、禁止事项

本 PR 禁止实现：

```text
Real Manager Projection Targets
Commit Coordinator
Projection Ready Coordinator
ExecutionProcessor Cutover
Runtime Full Replay
Snapshot Checkpoint
Live Runtime
Paper Runtime
SELL/CLOSE
Partial Fill
Margin/Futures Transaction
```

禁止：

```text
skip
xfail
放宽关键断言
只比较少数字段
忽略 Version
忽略 Timestamp
忽略 Reservation
忽略 Record Sequence
异常吞噬
Mock 被比较的 Manager
复制 Manager 公式冒充 Parity
新增 test_only 生产接口
Compatibility Alias
Legacy Wrapper
双写
```

---

# 二十二、清理旧测试与 Fixture

删除或重写：

* 只比较少数字段的旧 Manager Parity；
* 从测试 Projection 反向构造 Planning Context 的错误 Factory；
* 重复的 Generic T0 Fixture；
* 仅检查 Hash 长度的弱测试；
* 无实际故障注入的占位测试；
* 与当前 Contract 不一致的历史 Fixture。

保留一个明确分层：

```text
Scenario Definition
→ Real Manager Environment Factory
→ Real Before Authority Converter
→ Planning Context Factory
→ Expected State / Prepared Transaction
```

不得形成多套互相不一致的 Generic T0 Baseline。

---

# 二十三、文档和 ADR

更新：

```text
docs/execution_trade_planning.md
docs/execution_prepared_transaction.md
docs/adr/0037-generic-t0-cash-pure-trade-planner.md
```

建议新增：

```text
docs/reports/pr2_1_trade_planner_parity_report.md
```

文档必须说明：

1. 使用哪些真实 Manager 建立 Baseline；
2. 旧路径真实调用顺序；
3. 新 Planner 调用顺序；
4. 哪些字段完全一致；
5. Version 的最终语义；
6. Timestamp 的最终语义；
7. Reservation 消费和释放规则；
8. Settlement/Fee Sequence 规则；
9. Risk State 的最终业务含义；
10. Account/Ledger 单 Cluster 约束；
11. Legacy Event 与 Durable Event 的语义映射；
12. 故障矩阵；
13. 无副作用证据；
14. 哪些差异被修复；
15. 当前仍不支持哪些交易类型；
16. 为什么现在可以进入 PR3。

不得声称：

```text
Real Manager Projection Target 已完成
Commit Coordinator 已完成
ExecutionProcessor 已切换
Runtime Replay 已完成
生产主链已解决 Manager-before-Journal
```

---

# 二十四、工程门禁

至少执行：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha
```

定向测试：

```bash
uv run pytest tests/execution/test_trade_planning_context.py -q
uv run pytest tests/execution/test_trade_transaction_planner.py -q
uv run pytest tests/execution/test_trade_planner_determinism.py -q
uv run pytest tests/execution/test_trade_planner_manager_parity.py -q
uv run pytest tests/execution/test_trade_planner_real_manager_side_effects.py -q
uv run pytest tests/execution/test_trade_planner_failures.py -q
uv run pytest tests/execution/reducers -q
uv run pytest tests/architecture/test_trade_planning_boundaries.py -q
```

完整回归：

```bash
uv run pytest tests/execution -q
uv run pytest tests/architecture -q
uv run pytest tests/integration -q
uv run pytest tests/scenario -q
uv run pytest tests/conformance -q

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"
```

插件：

```bash
uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q

uv run pytest packages/provider/onlyalpha-plugin-tushare/tests -q \
  -m "not external and not requires_network and not requires_tushare"

uv run pytest packages/provider/onlyalpha-plugin-miniqmt/tests -q \
  -m "not external and not requires_network and not requires_local_qmt"
```

还必须执行：

```text
Wheel Build
Sdist Build
Twine Check
Clean Install
Entry Point Smoke
Generic T0 Scenario
```

如果某项无法执行，必须明确记录：

* 未执行命令；
* 原因；
* 是否阻塞 PR2.1；
* 不得声称通过。

---

# 二十五、验收标准

PR2.1 只有同时满足以下条件才算完成。

## 25.1 真实 Baseline

* 使用真实 Manager；
* 使用真实 Snapshot；
* 使用真实 Converter；
* 使用真实 Broker Update；
* 使用真实 Market/Fee Instruction；
* 不从 Projection Fixture 反向伪造 Before Authority。

## 25.2 完整等价

至少四个合法场景全部通过：

```text
新实体 + 零费用
新实体 + 非零费用
超额 Cash Reservation
已有 Position/Allocation 增仓
```

旧路径和新 Planner 的完整业务状态一致。

## 25.3 Version、Timestamp、Sequence 已明确

不存在未解释的：

```text
Version 差异
Timestamp 差异
Record Sequence 差异
Reservation State 差异
Event 语义差异
```

## 25.4 Pure

Planner 和 Reducer：

* 不读取 Manager；
* 不修改 Manager；
* 不写 Store；
* 不写 Journal；
* 不发 Event；
* 不请求 Reconciliation；
* 不修改 Dedup/Sequence；
* 不读取系统时间；
* 不生成随机 ID。

## 25.5 故障原子

所有故障点：

```text
No Prepared Transaction
No External Side Effect
No Partial Result Escape
```

## 25.6 测试充分

* 每个 Reducer 有完整单元测试；
* 每个 Planner Error Code 有测试；
* 有真实 Manager Parity；
* 有真实无副作用测试；
* 有故障矩阵；
* 有确定性压力测试；
* 有架构边界测试。

## 25.7 Contract 可供 PR3 使用

每个 Projection 必须具有：

```text
完整 Before State
完整 After State
正确 Entity Key
正确 Expected Version
正确 Result Version
正确 Expected State Hash
正确 Result State Hash
正确 Payload Hash
稳定 Projection Sequence
```

PR3 不应再需要重新解释成交业务公式。

---

# 二十六、最终交付报告

完成后输出以下报告。

## 1. 修改前审计

列出：

* HEAD；
* 旧 Trade 路径；
* 当前 PR2 路径；
* 初始差异。

## 2. 真实测试 Harness

说明：

* 使用哪些真实 Manager；
* 如何创建双环境；
* 如何构造真实 Planning Context；
* 如何生成 Authority Digest。

## 3. Manager Parity

按组件列出：

```text
Order
Position
Allocation
Settlement
Fee
Account
Strategy Ledger
Account Reservation
Strategy Reservation
Risk Reservation
Risk
Valuation
```

每项说明：

* Before；
* Legacy After；
* Planner After；
* 是否一致；
* 修复内容。

## 4. Version 与 Timestamp

逐组件列出最终规则。

## 5. Reservation 语义

列出：

```text
Reserved
Consumed
Released
Remaining
State
Frozen/Available Cash
```

的完整金额守恒。

## 6. Risk 语义

明确 `OnlyRiskExecutionState` 的正式含义。

## 7. Event 映射

列出 Legacy Event 和 Planner Durable Event 的映射。

## 8. 无副作用证明

提供真实 Authority Digest 比较结果。

## 9. 故障矩阵

按阶段列出测试结果。

## 10. 确定性

提供 100 次重复运行结果。

## 11. 删除内容

列出删除的弱测试、错误 Fixture、Alias 或重复实现。

## 12. 工程验证

提供真实命令和实际通过数量。

不得伪造测试结果。

## 13. PR3 Readiness

明确回答：

```text
是否可以开始 Real Manager Projection Targets
```

只有所有验收条件满足时才回答：

```text
GO
```

否则必须回答：

```text
NO-GO
```

并列出阻塞项。

---

# 最终目标

PR2.1 完成后，OnlyAlpha 必须具备经过真实领域实现证明的：

```text
Real Manager Before Authority
→ Immutable Planning Context
→ Pure Reducers
→ Deterministic Prepared Transaction
```

并证明：

```text
Planner 计算结果足以直接安装到真实 Manager
Planner 不依赖真实 Manager
Planner 不修改真实 Manager
Planner 故障不会留下任何外部副作用
```

PR3 只负责：

```text
验证 Projection Preconditions
→ 安装 Projection After State
→ 恢复 Manager-owned Indexes
→ 保证 Idempotency
```

PR3 不得再重新计算：

```text
成交数量
平均价格
费用
现金
持仓
预留
风险
估值
结算
```

这些业务权威必须在本 PR2.1 中彻底完成并验证。
