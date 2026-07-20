你现在负责 OnlyAlpha 的下一项核心一致性任务：

# OnlyAlpha Position-Side-Aware Execution Audit and Reconciliation

中文名称：

# OnlyAlpha SHORT 审计、Snapshot、阻断与 Reconciliation 一致性修复

本任务必须从第一性原理出发，修复 Execution、Position、Allocation、Broker Snapshot、异常阻断和 Reconciliation 链路中对 LONG/SHORT 方向的错误推断和硬编码。

任务目标不是只把几个：

```python
OnlyPositionSide.LONG
```

替换成条件表达式，而是建立：

> 一次 Broker Update 进入 ExecutionProcessor 后，只解析一次它真正影响的 Position Scope；后续成交应用、Snapshot、Audit、失败阻断、Reconciliation、Invariant、Collector 和 Artifact 全部消费同一个不可变 Scope，不允许各模块重新猜测 Position Side。

完成后必须保证：

```text
BUY  + OPEN                    → LONG
SELL + CLOSE                   → LONG
SELL + CLOSE_TODAY             → LONG
SELL + CLOSE_YESTERDAY         → LONG

SELL + OPEN                    → SHORT
BUY  + CLOSE                   → SHORT
BUY  + CLOSE_TODAY             → SHORT
BUY  + CLOSE_YESTERDAY         → SHORT
```

并保证 LONG 和 SHORT 始终使用：

```text
非负数量
独立 Position Key
独立 Allocation Key
独立 Reservation
独立 Snapshot
独立 Reconciliation Scope
```

禁止使用负 LONG 数量模拟 SHORT。

---

# 一、问题本质

当前系统中存在多个相关但不同的概念：

```text
Order Side
Direction
Offset
Position Effect
Position Side
Position Mode
Settlement Bucket
```

它们不能互相替代。

## 1.1 Order Side

```text
BUY
SELL
```

只描述交易动作。

它不能单独决定 Position Side。

例如：

```text
BUY + OPEN  → LONG
BUY + CLOSE → SHORT
```

同一个 BUY 可以影响不同方向的 Position。

---

## 1.2 Offset

```text
OPEN
CLOSE
CLOSE_TODAY
CLOSE_YESTERDAY
NONE
```

Offset 描述订单对持仓的作用。

只有：

```text
Order Side + Offset
```

才能在大多数市场中解析目标 Position Side。

---

## 1.3 Position Side

```text
LONG
SHORT
```

Position Side 是 Position Identity 的组成部分。

OnlyAlpha 中的 Position Identity 必须是：

```text
runtime_id
+ account_id
+ instrument_id
+ position_side
```

Cluster Allocation Identity 必须是：

```text
runtime_id
+ account_id
+ cluster_id
+ instrument_id
+ position_side
```

Position Side 不是用于展示的附加字段，而是状态定位、冻结、成交、审计和恢复的关键主键。

---

## 1.4 Position Effect

Position Effect 描述：

```text
OPEN_POSITION
CLOSE_POSITION
```

它不能替代 Position Side。

例如：

```text
OPEN LONG
OPEN SHORT
CLOSE LONG
CLOSE SHORT
```

必须同时表达 Effect 和 Side。

---

## 1.5 Position Mode

```text
NETTING
HEDGING
```

Position Mode 不改变 Position Side 的基本语义。

在 HEDGING 模式下：

```text
LONG 和 SHORT 可以同时存在
```

在 NETTING 模式下：

```text
市场规则可能限制同一标的同时存在 LONG 与 SHORT
```

但无论哪种模式，都禁止通过带符号数量模糊表达方向。

---

# 二、当前已知缺陷

编码前必须重新核对当前主分支，不得直接依赖旧报告。

至少验证以下问题是否仍存在。

## 2.1 成交路径能够解析 SHORT

当前成交转换已经根据：

```text
Order Side
Offset
Market Trade Instruction
```

生成 `OnlyPositionTrade.position_side`。

该路径属于正确方向，应保留并收敛为正式公共解析能力。

---

## 2.2 Execution Snapshot 写死 LONG

当前 Execution Snapshot 在读取 Position 和 Allocation 时使用固定：

```python
OnlyPositionSide.LONG
```

导致 SHORT 成交后可能出现：

```text
实际更新了 SHORT Position
但 Audit Snapshot 保存的是 LONG Position
```

如果 LONG 不存在：

```text
Snapshot 中 position=None
allocation=None
```

即使 SHORT 实际已经被修改。

如果 LONG 同时存在，则会出现更严重的问题：

```text
Audit 保存了另一个完全无关的 LONG Position
```

---

## 2.3 异常阻断写死 LONG

当前 `_block_scope()` 固定把 LONG Position 设置为 RECONCILING。

因此 SHORT 成交在 Position、Margin、Account 或 Ledger 中途失败时可能出现：

```text
真正受影响的 SHORT 没有被阻断
无关的 LONG 被阻断
```

这会使后续订单错误地继续使用已不可信的 SHORT 状态。

---

## 2.4 Broker Position 被固定转换为 LONG

当前 Broker 公共 Position Snapshot 没有 Position Side。

ExecutionProcessor 将 Broker Position 转换为本地 Reconciliation DTO 时固定使用 LONG。

结果是：

```text
Broker SHORT Snapshot
被错误解释为 LONG Snapshot
```

这会破坏：

```text
期货
融资融券
Crypto Perpetual
双向持仓
HEDGING
```

---

## 2.5 Reconciliation Request 缺少精确 Position Scope

当前 Execution Reconciliation Request 只有：

```text
account_id
instrument_id
order_id
trade_id
cluster_id
```

没有：

```text
position_side
position_key
allocation_key
position_effect
position_mode
```

恢复任务拿到 Request 后无法知道应该查询和阻断：

```text
LONG
SHORT
还是两个方向
```

---

## 2.6 Position Side 解析逻辑重复

当前方向解析可能分散在：

```text
ExecutionProcessor
Position Reservation Adapter
Market Rule Engine
Virtual Broker
Broker Adapter
Scenario
测试 Fixture
```

只要存在两套映射，后续就可能出现：

```text
成交更新 SHORT
Reservation 冻结 LONG
Audit 查询 LONG
Reconciliation 比较 LONG
```

本任务必须消除重复推断。

---

# 三、任务开始前的全局审计

不得直接修改代码。

首先审计：

```text
src/onlyalpha/execution/
src/onlyalpha/position/
src/onlyalpha/order/
src/onlyalpha/risk/
src/onlyalpha/broker/
src/onlyalpha/market/
src/onlyalpha/runtime/
src/onlyalpha/result/
src/onlyalpha/artifact/
src/onlyalpha/scenario/

packages/**/broker/
tests/
examples/
```

搜索：

```text
OnlyPositionSide.LONG
OnlyPositionSide.SHORT
position_side
position_key
allocation_key
OnlyOffset
OnlyPositionEffect
set_reconciling
clear_reconciling
reconciliation
block_scope
BrokerPositionSnapshot
PositionSnapshot
AllocationSnapshot
```

生成：

```text
docs/reports/short_execution_scope_audit.md
```

报告必须列出：

1. 所有 Side + Offset → Position Side 映射入口；
2. 所有 Position Key 构造入口；
3. 所有 Allocation Key 构造入口；
4. 所有 Position Snapshot 读取入口；
5. 所有 Reconciliation 阻断入口；
6. 所有 Broker Position 归一化入口；
7. 所有默认 LONG 参数；
8. 哪些默认 LONG 合法；
9. 哪些默认 LONG 是语义错误；
10. 需要删除的重复推断函数；
11. Broker Adapter 是否能提供 LONG/SHORT；
12. 当前 SHORT 测试覆盖缺口。

审计必须区分：

```text
股票现货天然 LONG-only
```

与：

```text
通用 Core 错误假设 LONG-only
```

不能因为 MiniQMT 当前只支持股票，就在通用 Broker DTO 中删除 Position Side。

---

# 四、建立唯一 Position Scope 模型

必须建立一个不可变的正式模型。

建议名称：

```python
OnlyExecutionPositionScope
```

或：

```python
OnlyResolvedPositionImpact
```

具体名称服从现有命名规范。

至少包含：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionPositionScope:
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId | None
    instrument_id: OnlyInstrumentId
    position_side: OnlyPositionSide
    position_effect: OnlyPositionEffect
    position_mode: OnlyPositionMode
    position_key: OnlyPositionKey
    allocation_key: OnlyPositionAllocationKey | None
    resolution_source: OnlyPositionScopeResolutionSource
```

建议的 `resolution_source`：

```text
MARKET_RULE_INSTRUCTION
BROKER_POSITION_SNAPSHOT
EXPLICIT_ORDER_OFFSET
NORMALIZED_CASH_ORDER
POSITION_RESERVATION
```

该模型必须满足：

```text
position_key.position_side == position_side
allocation_key.position_side == position_side
```

如果 `cluster_id` 不存在，则 `allocation_key` 可以为 None。

不得允许调用方分别传：

```text
position_side
position_key
allocation_key
```

然后产生相互矛盾的值。

---

# 五、建立唯一 Position Scope Resolver

建议建立：

```python
OnlyExecutionPositionScopeResolver
```

它负责把正式输入解析成一个 Scope。

至少提供以下入口。

## 5.1 从 Market Trade Instruction 解析

```python
resolve_trade(
    order,
    broker_trade_update,
    trade_instruction,
) -> OnlyExecutionPositionScope
```

Market Trade Instruction 是成交应用时的最高优先级。

如果 Market Rule 已经生成：

```text
position_side
position_effect
position_mode
```

ExecutionProcessor 不得再使用 Side + Offset 覆盖它。

---

## 5.2 从显式 Order 解析

用于：

```text
Accepted
Rejected
Cancelled
提交前 Reservation
尚未成交的 Audit
```

例如：

```python
resolve_order(order) -> OnlyExecutionPositionScope
```

映射矩阵：

| Side | Offset          | Position Side | Effect |
| ---- | --------------- | ------------- | ------ |
| BUY  | OPEN            | LONG          | OPEN   |
| SELL | OPEN            | SHORT         | OPEN   |
| SELL | CLOSE           | LONG          | CLOSE  |
| SELL | CLOSE_TODAY     | LONG          | CLOSE  |
| SELL | CLOSE_YESTERDAY | LONG          | CLOSE  |
| BUY  | CLOSE           | SHORT         | CLOSE  |
| BUY  | CLOSE_TODAY     | SHORT         | CLOSE  |
| BUY  | CLOSE_YESTERDAY | SHORT         | CLOSE  |

---

## 5.3 对 Offset.NONE 的处理

不得在通用 Core 中无条件执行：

```text
BUY  → LONG OPEN
SELL → LONG CLOSE
```

`NONE` 的含义必须来自：

```text
Market Rule
Instrument/Market Capability
已经规范化的订单语义
```

对于明确的 Cash Long-only 市场，可以规范化为：

```text
BUY  + NONE → LONG OPEN
SELL + NONE → LONG CLOSE
```

对于 Futures、Perpetual 或支持双向持仓的市场：

```text
Offset.NONE
```

如果无法从正式 Market Rule 解析，必须拒绝并返回明确错误，不能猜测。

建议错误：

```text
AMBIGUOUS_POSITION_EFFECT
POSITION_SIDE_RESOLUTION_FAILED
```

---

## 5.4 从 Broker Position Snapshot 解析

Broker Position Snapshot 必须直接携带规范化后的：

```text
position_side
```

Resolver 不得根据数量正负或账户类型再次猜测。

如果某个供应商使用带符号净持仓：

```text
positive quantity → LONG + abs(quantity)
negative quantity → SHORT + abs(quantity)
zero quantity     → 根据供应商返回的 side 或查询范围决定
```

带符号数量只能存在于 Broker Adapter 的原始解析阶段。

进入 Core DTO 后必须满足：

```text
quantity >= 0
position_side 显式
```

---

## 5.5 从 Position Reservation 解析

Position Reservation 已经保存 `position_side`。

对于平仓订单，后续：

```text
Broker Accepted
Fill
Cancel
Reject
Failure Recovery
```

应优先校验 Scope 与 Reservation 中保存的 Position Side 一致。

如果不一致，应视为严重冲突：

```text
POSITION_SCOPE_CONFLICT
```

不能选其中一个继续执行。

---

# 六、一次解析，整条链复用

ExecutionProcessor 对一个 Update 必须：

```text
Validate Update
→ Resolve Position Scope once
→ Dispatch
→ Snapshot
→ Audit
→ Block
→ Reconciliation
```

不允许：

```text
_trade() 自己解析一次
_snapshot() 再解析一次
_block_scope() 再猜一次
_make_reconciliation() 丢失方向
```

建议把 Scope 加入：

```python
OnlyExecutionProcessingContext
```

或由 `process()` 局部持有并显式传给所有后续函数。

例如：

```python
scope = self._position_scope_resolver.resolve(update, order, instruction)
```

之后：

```python
_dispatch(update, scope, ...)
_snapshot(update, scope, ...)
_audit_record(update, scope, ...)
_make_reconciliation(update, scope, ...)
_block_scope(update, scope, ...)
```

对于不涉及 Position 的 Update：

```text
Broker Account Update
Broker Connection Update
```

Scope 为 None。

---

# 七、修复 Trade 转换

`OnlyPositionTrade` 必须直接使用正式 Scope：

```python
position_side=scope.position_side
position_mode=scope.position_mode
offset=resolved_offset
```

不得在 `_position_trade()` 内保留另一套 Side + Offset 分支。

如果 Market Rule Instruction 和 Order 映射不一致：

```text
Order 映射为 SHORT
Instruction 映射为 LONG
```

必须阻止成交应用并生成：

```text
POSITION_SCOPE_CONFLICT
RECONCILIATION_REQUIRED
```

不能静默信任其中任意一个。

---

# 八、修复 Execution Snapshot

## 8.1 Snapshot 必须保存精确 Scope

建议扩展：

```python
OnlyExecutionSnapshotBundle
```

至少增加：

```text
position_scope
position_key
allocation_key
```

即使 Position 不存在，也必须保存 Key。

这样：

```text
SHORT OPEN 前 position=None
```

仍然可以知道：

```text
本次 Update 目标是 SHORT Position
```

---

## 8.2 Snapshot 必须读取正确方向

必须使用：

```python
scope.position_key
scope.allocation_key
```

禁止继续构造固定 LONG Key。

---

## 8.3 全部平仓后的 Snapshot

如果成交使 Position 归零并从 active store 移到 closed store：

```text
Snapshot 不能因为 active get_snapshot() 返回 None 而丢失成交后的最终状态
```

优先顺序建议：

```text
PositionMutationResult.after
→ closed Position snapshot
→ active Position snapshot
```

Audit 必须能够显示：

```text
SHORT quantity: previous > 0
SHORT quantity: after = 0
status: CLOSED
```

Allocation 同样处理。

---

## 8.4 终态订单 Snapshot

对于：

```text
Rejected
Cancelled
```

Snapshot 必须展示：

```text
正确 Position Side
正确 Position Reservation 已释放
正确 Allocation Reservation 已释放
```

特别验证：

```text
BUY CLOSE SHORT 被取消
```

不能返回 LONG Snapshot。

---

# 九、修复 Audit Record

扩展 `OnlyExecutionAuditRecord`，至少保存：

```text
position_side
position_effect
position_mode
position_key
allocation_key
position_scope_resolution_source
```

对于 Position Broker Update，还应保存：

```text
broker_position_side
```

Audit 必须回答：

```text
这次 Update 本来要修改哪个 Position？
实际修改了哪个 Position？
失败后阻断了哪个 Position？
Reconciliation 要查询哪个 Position？
```

不得要求读取者根据 Side 和 Offset重新推导。

Audit DTO 必须：

```text
不可变
JSON-safe
稳定序列化
进入 determinism fingerprint
```

---

# 十、修复失败阻断

## 10.1 阻断精确 Position Key

部分事务失败时：

```text
SHORT Trade
```

必须阻断：

```text
SHORT Position Key
```

不得阻断 LONG。

---

## 10.2 不得依赖 Position 已经存在

当前逻辑如果 Position Snapshot 不存在，可能什么都不阻断。

这是错误的。

以下情况也必须能够阻断：

```text
SHORT OPEN 在创建 Position 前失败
SHORT CLOSE 后 Position 已被移入 closed store
Broker 报告本地不存在的 SHORT Position
```

必须建立独立于 Position Entity 是否存在的阻断状态。

建议建立：

```python
OnlyReconciliationScopeRegistry
```

或在现有 Reconciliation State 中正式维护：

```text
blocked account
blocked instrument
blocked position key
blocked allocation key
reason
source update
created_at
resolved_at
```

不要使用临时 set 或测试专用状态。

---

## 10.3 阻断等级

至少支持：

```text
POSITION_SIDE
INSTRUMENT
ACCOUNT
RUNTIME
```

建议策略：

### Position Mutation 部分失败

```text
阻断精确 Position Side
必要时阻断对应 Instrument
```

### Account Mutation 部分失败

```text
阻断 Account
```

### 无法解析 Position Side

```text
不得默认 LONG
保守阻断 Instrument 或 Account
```

### 系统级状态不可信

```text
阻断 Runtime
```

---

## 10.4 下单路径必须检查阻断状态

仅记录阻断没有意义。

Order/Risk 提交链必须拒绝：

```text
目标 Position Scope 正处于 RECONCILING
```

例如：

```text
SHORT Position 被阻断
```

则至少拒绝：

```text
新的 SHORT OPEN
SHORT CLOSE
会依赖该 SHORT 可用数量的订单
```

LONG 是否同时阻断应由阻断等级决定，不能隐式连带。

---

## 10.5 解除阻断

只有当同一个 Scope 的正式 Reconciliation 成功后，才能解除。

禁止：

```text
任意一个 LONG Snapshot 成功
→ 清除 SHORT 阻断
```

解除必须匹配：

```text
runtime
account
instrument
position_side
```

---

# 十一、修复 Reconciliation Request

扩展：

```python
OnlyExecutionReconciliationRequest
```

至少增加：

```text
position_scope
position_side
position_key
allocation_key
position_effect
position_mode
block_level
```

`required_recovery` 不应只是一个不可解析字符串。

建议增加结构化恢复动作：

```text
QUERY_BROKER_POSITION
QUERY_BROKER_ORDERS
QUERY_BROKER_TRADES
REPLAY_MISSING_UPDATES
REBUILD_POSITION
REBUILD_ALLOCATION
REVALUE_ACCOUNT
VERIFY_RESERVATIONS
```

至少保证恢复执行器能直接确定：

```text
查询 LONG 还是 SHORT
对比哪个 Position Key
重建哪个 Allocation Key
解除哪个 Block Scope
```

不保留缺少方向的旧 Request 兼容路径。

---

# 十二、修复 Broker Position DTO

## 12.1 公共 DTO 必须携带 Position Side

修改：

```python
OnlyBrokerPositionSnapshot
```

增加：

```python
position_side: OnlyPositionSide
```

建议同时考虑：

```text
position_mode
today_quantity
yesterday_quantity
```

但只增加实际需要且有正式语义的字段。

---

## 12.2 Broker Adapter 负责归一化

### Virtual Broker

必须输出实际：

```text
LONG
SHORT
```

不得根据订单 Side 临时猜测。

### MiniQMT 股票

当前只支持股票现货时，可以显式输出：

```text
LONG
```

但必须在 Adapter 中表达：

```text
该 Account/Instrument Capability 为 LONG-only
```

不能让 Core 默认 LONG。

### 未来 MiniQMT Futures

必须根据供应商真实持仓字段映射：

```text
LONG
SHORT
```

不能沿用股票适配逻辑。

### 其他 Broker

如果无法确定方向：

```text
拒绝归一化
或产生明确 AMBIGUOUS_POSITION_SIDE 错误
```

不得填 LONG 以通过类型检查。

---

## 12.3 Position Update Sequence Scope

审计 Broker Position Update 的顺序作用域。

如果供应商的 sequence 是按 Position 流递增，作用域应至少包含：

```text
runtime
gateway
account
instrument
position_side
```

不得让无关标的或另一方向的 Snapshot 错误互相判定 stale。

如果供应商 sequence 是账户全局递增，则保留账户级 Scope，并在 Adapter Capability 中明确说明。

不要凭猜测修改；必须根据当前 Broker 语义和测试作出明确决策。

---

# 十三、修复 Position Reconciliation

Position Reconciliation 必须严格遵循：

```text
Broker Position Key
==
Local Position Key
```

即：

```text
runtime_id
account_id
instrument_id
position_side
```

## 13.1 LONG 与 SHORT 独立比较

禁止：

```text
Broker SHORT
与 Local LONG
进行数量比较
```

---

## 13.2 本地不存在、Broker 非零

必须生成：

```text
MISSING_LOCAL_POSITION
```

并阻断精确 Position Side。

---

## 13.3 本地非零、Broker 为零

必须生成：

```text
MISSING_BROKER_POSITION
```

并根据 Authority Policy 决定：

```text
阻断
查询订单成交
重放缺失事实
```

不得直接覆盖本地状态。

---

## 13.4 HEDGING

必须允许：

```text
LONG 和 SHORT 同时存在
```

并分别 Reconcile。

一个方向成功不得清除另一方向的冲突。

---

## 13.5 NETTING

如果市场规则不允许同时持有双向 Position，而本地或 Broker 同时报告 LONG 和 SHORT：

```text
生成 POSITION_MODE_CONFLICT
```

不得自动相减或净额覆盖，除非正式 Authority Policy 明确定义该操作。

---

## 13.6 Broker 可用数量

Broker available quantity 只能影响相同 Position Side。

不能把：

```text
Broker SHORT available
```

写入：

```text
Local LONG broker_available_quantity
```

---

# 十四、修复 Reservation

当前 Position Reservation 已经保存 `position_side`，应将其作为正式证据。

必须确保：

```text
SELL CLOSE LONG  → 冻结 LONG
BUY CLOSE SHORT  → 冻结 SHORT
```

并覆盖：

```text
CLOSE
CLOSE_TODAY
CLOSE_YESTERDAY
```

删除 Reservation Adapter 中重复的 Side + Offset 推断，改为使用统一 Scope Resolver。

必须验证：

```text
SHORT CLOSE Accepted
SHORT CLOSE Partial Fill
SHORT CLOSE Cancel
SHORT CLOSE Reject
```

过程中只修改 SHORT Reservation。

---

# 十五、修复 Invariant

当前 Invariant 聚合同一 Instrument 下所有 Position 数量，可能掩盖方向错配。

应增加按 Position Side 的不变量。

至少包括：

```text
LONG Position quantity
=
LONG Allocation quantity
+ LONG Unallocated quantity

SHORT Position quantity
=
SHORT Allocation quantity
+ SHORT Unallocated quantity
```

增加：

```text
POSITION_SIDE_KEY_MATCH
ALLOCATION_SIDE_KEY_MATCH
RESERVATION_SIDE_KEY_MATCH
BROKER_LOCAL_SIDE_MATCH
RECONCILIATION_SCOPE_MATCH
AUDIT_SCOPE_MATCH
BLOCK_SCOPE_MATCH
```

HEDGING 模式应分别验证两个方向。

NETTING 模式根据 Market Rule 验证是否允许双向同时存在。

---

# 十六、Result、Collector 与 Artifact

审计以下输出是否丢失 Position Side：

```text
Execution Fact
Position Fact
Allocation Fact
Reconciliation Fact
Execution Audit
Diagnostics
Scenario Artifact
Parquet Schema
JSON Result
```

所有 Position 相关事实必须显式包含：

```text
position_side
position_key
```

Reconciliation Fact 还必须包含：

```text
broker_position_side
local_position_side
block_level
resolution_status
```

不得由前端、报表或 Web 层根据数量正负推断方向。

---

# 十七、必须新增的测试矩阵

## 17.1 Position Scope Resolver 单元测试

覆盖完整矩阵：

```text
BUY  OPEN            → LONG OPEN
SELL OPEN            → SHORT OPEN
SELL CLOSE           → LONG CLOSE
BUY  CLOSE           → SHORT CLOSE
SELL CLOSE_TODAY     → LONG CLOSE
BUY  CLOSE_TODAY     → SHORT CLOSE
SELL CLOSE_YESTERDAY → LONG CLOSE
BUY  CLOSE_YESTERDAY → SHORT CLOSE
```

覆盖：

```text
NONE + Cash Long-only
NONE + Futures
NONE + ambiguous market
Market Instruction 与 Order 冲突
Reservation 与 Order 冲突
```

---

## 17.2 Snapshot 测试

验证每种成交后：

```text
snapshot.position.key.position_side
snapshot.allocation.key.position_side
snapshot.position_key
snapshot.allocation_key
```

全部正确。

特别覆盖：

```text
SHORT OPEN 后 Snapshot
SHORT Partial Fill 后 Snapshot
SHORT 全部平仓后的 CLOSED Snapshot
SHORT Rejected/Cancelled 后 Snapshot
LONG 与 SHORT 同时存在时 Snapshot 不串方向
```

---

## 17.3 失败注入测试

对 SHORT OPEN 和 SHORT CLOSE，在以下每一步注入失败：

```text
ORDER
POSITION
ALLOCATION
SETTLEMENT
MARGIN
FEE
ACCOUNT
STRATEGY_LEDGER
RESERVATION
RISK
INVARIANT
EVENT
```

每个测试必须验证：

```text
真正受影响的 SHORT Scope 被阻断
无关 LONG Scope 不被错误阻断
Account 在需要时被阻断
Reconciliation Request 保存 SHORT Key
Audit 保存 SHORT Scope
```

---

## 17.4 Broker Position Reconciliation 测试

覆盖：

```text
Broker LONG vs Local LONG
Broker SHORT vs Local SHORT
Broker SHORT 但 Local 只有 LONG
Broker LONG 和 SHORT 同时存在
Local SHORT 不存在
Broker SHORT 为零
SHORT available quantity 差异
SHORT settled/unsettled 差异
重复 Snapshot
乱序 Snapshot
```

---

## 17.5 Broker Adapter 测试

### Virtual Broker

验证查询：

```text
LONG Position Snapshot
SHORT Position Snapshot
```

都携带明确 Position Side。

### MiniQMT

股票 Position 明确映射 LONG。

如果供应商返回无法识别的方向：

```text
必须失败
不得回退 LONG
```

---

## 17.6 Reservation 测试

覆盖：

```text
LONG CLOSE reserve/consume/release
SHORT CLOSE reserve/consume/release
SHORT CLOSE partial fill
SHORT CLOSE cancel remainder
SHORT CLOSE reject
```

---

## 17.7 HEDGING 测试

同一账户和标的同时：

```text
LONG=10
SHORT=7
```

验证：

```text
两个 Position Key 独立
两个 Allocation Key 独立
两个 Snapshot 独立
两个 Reconciliation 独立
一个方向阻断不影响另一个方向
```

---

## 17.8 NETTING 测试

验证：

```text
允许的方向切换
不允许的双向冲突
错误 Broker Snapshot
```

不能使用简单数量相减掩盖冲突。

---

## 17.9 Determinism

相同 SHORT Scenario 重复运行，以下必须一致：

```text
Position Key
Allocation Key
Audit Record
Reconciliation Request
Block Scope
Result Fingerprint
Artifact Fingerprint
```

---

# 十八、正式 Engine Scenario

必须通过 OnlyEngine 新增或完善：

```text
GENERIC_FUTURES_SHORT_OPEN_CLOSE
GENERIC_FUTURES_SHORT_PARTIAL_FILL_CANCEL
GENERIC_FUTURES_SHORT_FAILURE_RECONCILIATION
GENERIC_FUTURES_LONG_SHORT_HEDGING
GENERIC_FUTURES_BROKER_SHORT_RECONCILIATION
```

Scenario 必须经过：

```text
Scenario
→ Parser
→ Planner
→ Exact DataSource
→ Action Strategy
→ OnlyEngine
→ Runtime
→ Virtual Broker
→ ExecutionProcessor
→ Standard Facts
→ Assertion
→ Artifact
```

Scenario Assertion 只能读取标准事实。

不得直接读取 Position Manager 私有状态重新判断方向。

---

# 十九、Conformance

把上述 Scenario 接入：

```text
GENERIC_MARGIN_FUTURES
```

Conformance Pack。

至少覆盖能力：

```text
LONG_OPEN
LONG_CLOSE
SHORT_OPEN
SHORT_CLOSE
HEDGING
POSITION_RECONCILIATION
PARTIAL_MUTATION_BLOCKING
DETERMINISTIC_RECOVERY_SCOPE
```

Capability 只有在正式 Engine Scenario PASSED 后才算 Covered。

---

# 二十、禁止事项

禁止：

```text
只替换两个 LONG 常量后宣称完成
在 Snapshot 中重新使用 Side + Offset 猜方向
在 _block_scope 中重新猜方向
Broker Position 缺少 side 时默认 LONG
使用负数量表示 SHORT
把 BUY 永远解释为 LONG
把 SELL 永远解释为 LONG close
把 Offset.NONE 在所有市场解释为股票语义
用 Instrument 类型硬编码期货逻辑
用 Profile ID 字符串分支
让 Scenario 直接修改 Position
让 Reconciliation 静默覆盖本地状态
LONG Reconciliation 成功后清除 SHORT Block
保留旧 Broker Position DTO 兼容路径
```

---

# 二十一、迁移阶段

严格按以下阶段执行。

## Stage 1：全链审计

生成：

```text
short_execution_scope_audit.md
```

## Stage 2：Scope Domain Model

建立：

```text
OnlyExecutionPositionScope
OnlyPositionScopeResolutionSource
结构化 Block Scope
```

## Stage 3：统一 Resolver

收敛：

```text
Execution
Reservation
Snapshot
Blocking
Reconciliation
```

的方向解析。

## Stage 4：Broker DTO

为 Broker Position 增加显式 Position Side，并迁移全部 Adapter。

## Stage 5：ExecutionProcessor

一次解析 Scope，并传递到完整处理链。

## Stage 6：Snapshot 和 Audit

保存精确 Position/Allocation Scope。

## Stage 7：Block Registry

阻断状态独立于 Position Entity 是否存在。

## Stage 8：Reconciliation Request

增加完整 Position Scope 和结构化恢复动作。

## Stage 9：Position Reconciliation

LONG/SHORT 独立比较、阻断和解除。

## Stage 10：Invariant

增加 Side-aware 跨组件恒等式。

## Stage 11：Scenario 与 Conformance

建立 SHORT 正式证据。

## Stage 12：删除旧路径

删除所有重复映射、默认 LONG 和兼容接口。

## Stage 13：文档与交接

更新当前架构说明。

---

# 二十二、文档要求

新增：

```text
docs/execution_position_scope.md
docs/short_position_reconciliation.md
docs/reconciliation_blocking.md
docs/adr/xxxx-position-side-aware-execution-scope.md
docs/reports/short_execution_scope_audit.md
```

更新：

```text
README.md
AGENTS.md
HANDOFF.md
docs/architecture.md
docs/execution_processor.md
docs/position.md
docs/position_modes.md
docs/virtual_broker.md
docs/runtime.md
docs/results_framework.md
docs/market_conformance_suite.md
```

文档必须明确回答：

```text
Position Side 在哪里解析？
解析优先级是什么？
谁创建 Position Key？
谁创建 Allocation Key？
谁决定阻断范围？
谁解除阻断？
Broker 如何表达 SHORT？
Reconciliation 如何区分 LONG 和 SHORT？
```

---

# 二十三、质量门禁

必须真实执行：

```text
uv sync --all-groups --all-packages

uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
git diff --check
```

显式执行：

```text
Core tests
Execution tests
Position tests
Reservation tests
Virtual Broker tests
MiniQMT tests
Scenario tests
Conformance tests
Examples tests
```

不得依赖根 pytest 的默认 `testpaths` 自动覆盖所有 Package。

如 MiniQMT 真实历史环境可用，可执行非破坏性真实数据测试；本任务不要求发送真实订单。

---

# 二十四、完成标准

只有以下全部满足才算完成：

```text
Side + Offset 解析只有一个正式 Resolver
Market Rule Instruction 是成交 Side 的最终业务依据
Broker Position Snapshot 显式包含 Position Side
Core 不再默认 Broker Position 为 LONG

SHORT Trade 更新 SHORT Position
SHORT Trade 更新 SHORT Allocation
SHORT Trade Snapshot 返回 SHORT
SHORT Trade Audit 保存 SHORT
SHORT Trade 失败阻断 SHORT
SHORT Reconciliation Request 指向 SHORT
SHORT Broker Snapshot 与 SHORT 本地状态比较

LONG 和 SHORT Snapshot 不串方向
LONG 和 SHORT Block 不串方向
LONG 和 SHORT Reconciliation 不串方向
LONG 和 SHORT Reservation 不串方向

Position 不存在时仍可建立正式 Block Scope
Position 关闭后仍可生成最终 Audit Snapshot
Reconciliation 成功只解除完全匹配的 Scope

HEDGING 双向持仓通过
NETTING 冲突行为明确
部分成交通过
撤单和拒单通过
重复和乱序 Update 通过

Position/Allocation/Reservation Side Invariant 通过
SHORT Engine Scenario 通过
GENERIC_MARGIN_FUTURES Pack 覆盖 SHORT 能力
重复运行确定性通过

所有默认 LONG 硬编码已审计
错误默认 LONG 已删除
旧 Broker DTO 兼容接口已删除
文档已更新
HANDOFF 已更新
全部质量门禁通过
```

---

# 二十五、最终报告格式

完成后输出中文报告。

## 1. 修改前审计

列出所有默认 LONG 和重复 Side 推断入口。

## 2. 第一性原理

说明：

```text
Order Side
Offset
Position Effect
Position Side
Position Mode
```

之间的区别。

## 3. 唯一 Scope Resolver

展示输入、优先级、输出和冲突处理。

## 4. Execution 主链

展示：

```text
Broker Update
→ Resolve Position Scope
→ Position/Allocation Mutation
→ Snapshot
→ Audit
→ Block/Reconciliation
```

## 5. Broker Position

说明 Virtual Broker、MiniQMT 和公共 DTO 如何表达 LONG/SHORT。

## 6. Snapshot 与 Audit

列出 SHORT OPEN、SHORT CLOSE、失败和全部平仓结果。

## 7. 阻断

说明 Position-side、Instrument、Account 和 Runtime 阻断条件。

## 8. Reconciliation

说明如何查询、比较、阻断和解除精确 Position Scope。

## 9. HEDGING 与 NETTING

报告两个 Position Mode 的测试结果。

## 10. Scenario 与 Conformance

列出正式 Engine Scenario、Artifact 和 Coverage。

## 11. Determinism

列出重复运行的 Scope、Audit、Request 和 Fingerprint 结果。

## 12. 质量门禁

列出真实命令、退出码和结果。

## 13. 未完成项

不得把完整期货盯市、强平、MiniQMT 期货实盘等本任务范围外能力写成完成。

---

# 二十六、最终架构原则

最终实现必须满足：

> Position Side 是状态身份，不是从数量符号或展示文本推导的属性。

> Order Side 不能单独决定 Position Side。

> Market Rule Instruction 是成交应用时 Position Effect 和 Position Side 的最终业务依据。

> 一次 Execution Update 只允许解析一次 Position Scope。

> Position、Allocation、Reservation、Snapshot、Audit、Blocking 和 Reconciliation 必须使用同一个 Scope。

> Broker Adapter 必须把供应商持仓归一化为显式 LONG 或 SHORT 和非负数量。

> 无法解析方向时必须失败或扩大阻断范围，绝不能默认 LONG。

> Reconciliation 的阻断状态不能依赖 Position 实体是否仍存在。

> LONG 与 SHORT 必须独立审计、独立阻断、独立恢复。

> 不为旧的默认 LONG 行为保留兼容路径。
