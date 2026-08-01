# OnlyAlpha 大任务：Multi-Cluster Close Cost Authority 完整收口

## 一、任务名称

在 OnlyAlpha 当前 `master` 分支上完成一个完整、不可拆分的大型 PR：

```text
Multi-Cluster Close Cost Authority
```

建议 PR 标题：

```text
Feat: Complete Multi-Cluster Close Cost Authority
```

本任务必须从第一性原则重新审视 OnlyAlpha 多 Cluster 共享账户时的仓位成本、平仓归因和实现盈亏模型，彻底解决当前 Account Position 与 Cluster Allocation 分别计算平仓成本所造成的经济权威分裂。

本任务不是为了让现有失败测试暂时通过，也不是在当前错误模型上增加兼容分支。

最终必须形成：

```text
一个明确的成本归因模型
一个明确的平仓成本权威
一条简单且唯一的计算路径
一套完整的经济不变量
一套支持恢复和确定性的测试体系
```

必须删除已经失去意义的旧接口、旧参数、旧计算路径、旧测试夹具和过时文档。

不得因为旧示例、旧测试或历史实现仍在使用某个接口，就保留不合理的兼容层。

---

# 二、连续执行要求

这是一个完整大任务、一个完整分支、一个完整 PR。

必须连续完成：

```text
源码审计
问题复现
第一性原则设计
核心模型实现
Planner 接线
Reducer 重构
旧接口删除
经济不变量
恢复与确定性验证
现有测试修复
新增测试
文档更新
全量质量门禁
最终报告
```

禁止在中间阶段停止并询问：

```text
是否继续
是否删除旧接口
是否保留兼容代码
是否拆成第二个 PR
是否先只修改测试
是否暂时绕过 Multi-Cluster
```

如真实源码与本提示词中的文件名、类名或假设存在差异：

1. 以当前源码为唯一事实源；
2. 从业务正确性和架构清晰度出发选择最小完整方案；
3. 删除已经无意义的历史接口；
4. 修改所有调用点、示例、测试和文档；
5. 不得通过兼容层掩盖架构问题；
6. 在最终报告中说明实际差异。

---

# 三、任务背景

OnlyAlpha 当前使用两层仓位模型：

```text
Account Position
+
Cluster Allocation
```

其中：

```text
Account Position
表示账户在某个 Instrument 上的聚合仓位

Cluster Allocation
表示该仓位在不同 Cluster/Strategy 之间的内部归属
```

在单 Cluster 或多个 Cluster 开仓成本完全相同时，账户 Position 和 Cluster Allocation 分别按平均成本计算平仓释放成本，结果可能恰好一致。

当多个 Cluster 在不同价格建仓后，当前模型会出现经济权威分裂。

示例：

```text
Cluster A:
BUY 1000 @ 10
Allocation Cost = 10000

Cluster B:
BUY 1000 @ 12
Allocation Cost = 12000
```

账户聚合 Position：

```text
Quantity = 2000
Cumulative Cost = 22000
Average Price = 11
```

Cluster A 执行：

```text
SELL CLOSE 1000 @ 13
```

如果 Position 按账户平均成本释放：

```text
Position Released Cost
= 22000 × 1000 / 2000
= 11000
```

如果 Allocation A 按自身成本释放：

```text
Allocation Released Cost
= 10000
```

出现：

```text
Position Released Cost != Allocation Released Cost
```

进一步导致：

```text
Position Realized PnL
!=
Allocation Realized PnL

Account Realized PnL
!=
Strategy Ledger Realized PnL

Position Remaining Cost
!=
Remaining Allocation Cost

Account Equity
!=
sum(Strategy Ledger Equity)
```

这是当前 Multi-Cluster 集成测试失败的核心经济原因。

---

# 四、第一性原则

## 4.1 一个实际持仓数量不能拥有两套相互矛盾的成本

账户 Position 是多个 Allocation 的聚合。

必须成立：

```text
Position Quantity
=
sum(Allocation Quantity)
+
Unallocated Quantity
```

以及：

```text
Position Cumulative Cost
=
sum(Allocation Cumulative Cost)
+
Unallocated Cumulative Cost
```

只要 Position 和 Allocation 分别独立计算平仓成本，上述关系就无法在不同成本 Cluster 场景中持续成立。

---

## 4.2 Cluster 订单必须只平掉当前 Cluster 拥有的 Allocation

一个策略提交的 Close Order 已经具有：

```text
runtime_id
account_id
cluster_id
strategy_id
instrument_id
```

因此本次 Close 的归属不是模糊的。

本次可平数量必须来自：

```text
当前 order.cluster_id 对应的 Allocation
```

本次释放成本也必须来自：

```text
当前 Cluster Allocation 的成本权威
```

Account Position 是聚合视图，不具备决定“本次卖出属于哪个策略成本批次”的信息。

---

## 4.3 Allocation 决定本次释放成本，Position 消费同一结论

正确方向：

```text
Allocation Before
        │
        ▼
Close Cost Attribution
        │
        ├── released cost
        ├── allocation quantity after
        └── allocation cost after
        │
        ▼
Position 使用同一个 released cost
```

禁止继续：

```text
Position 独立计算 released cost

Allocation 再独立计算 released cost
```

---

## 4.4 Realized PnL 只能有一个计算来源

本次平仓实现盈亏：

```text
Realized PnL
=
(
    Fill Value
    -
    Attributed Released Cost
)
× Contract Multiplier
```

只允许计算一次。

之后将同一个结果传递给：

```text
Position
Allocation
Account
Strategy Ledger
Committed Fact
Result
```

禁止 Account、Ledger、Position、Allocation 分别重算。

---

## 4.5 精确累计成本是权威，平均开仓价是派生值

正式权威：

```text
cumulative_open_price_quantity
```

派生值：

```text
average_open_price
```

平均价不能反向决定精确累计成本。

Multi-Cluster 归因平仓后，账户 Position 的剩余平均开仓价必须根据剩余精确成本重新派生：

```text
Position Average Price After
=
Position Cumulative Cost After
/
Position Quantity After
```

并按照 Instrument Price Precision 量化。

不能继续无条件保持平仓前的 Position Average Price。

---

# 五、正式支持范围

本任务严格针对：

```text
Market Profile : GENERIC_T0_CASH
Account Type   : CASH
Order Type     : LIMIT
Order Side     : SELL
Offset         : CLOSE
Position Side  : LONG
Position Mode  : NETTING
Runtime        : BACKTEST
Currency       : Single Currency
Margin         : Disabled
Cluster Count  : One or More
```

必须支持：

```text
单 Cluster Close
Multi-Cluster Close
Whole Fill
Partial Fill
Multi-Fill
不同 Cluster 不同成本
同 Bar Multi-Fill
跨 Bar Multi-Fill
Checkpoint / Restart
Cluster 注册顺序变化
```

当前任务不实现：

```text
无归属的 Unallocated Position 主动卖出
自动选择其他 Cluster Allocation
跨 Cluster 减仓
FIFO/LIFO Lot Selection
Short
Hedging
Futures
Margin
CloseToday
CloseYesterday
多币种
FX
```

如果无法将 Close 唯一归属到一个 Cluster Allocation，必须在 Commit 前 Fail Closed。

---

# 六、开始前必须审计当前仓库

开始修改前必须重新读取当前 `master`。

至少检查：

```text
src/onlyalpha/execution/trade_planner.py
src/onlyalpha/execution/planning_context.py
src/onlyalpha/execution/execution_state.py
src/onlyalpha/execution/economic_invariants.py
src/onlyalpha/execution/transaction.py
src/onlyalpha/execution/committed_fact.py

src/onlyalpha/execution/reducers/close_cost.py
src/onlyalpha/execution/reducers/trade_state.py
src/onlyalpha/execution/reducers/trade_accounting.py
src/onlyalpha/execution/reducers/trade_reservations.py

src/onlyalpha/position/
src/onlyalpha/account/
src/onlyalpha/strategy_ledger/
src/onlyalpha/result/
src/onlyalpha/runtime/recovery/
src/onlyalpha/runtime/checkpoint/
```

相关测试：

```text
tests/execution/
tests/position/
tests/account/
tests/strategy_ledger/
tests/integration/
tests/scenario/
tests/runtime/recovery/
tests/runtime/checkpoint/
tests/result/
tests/analytics/
tests/artifact/
tests/report/
tests/architecture/
```

重点搜索：

```bash
rg "only_reduce_average_cost_close"
rg "released_open_price_quantity"
rg "average_open_price_after"
rg "cumulative_open_price_quantity"
rg "realized_pnl_delta"
rg "allocation_before"
rg "position_before"
rg "CLOSE_COST_AUTHORITY"
rg "runtime_result.trades =="
rg '"executions": 1'
rg "execution_count.*1"
rg "trade_count.*0"
```

---

# 七、预实施审计文档

新增：

```text
docs/reports/
multi_cluster_close_cost_authority_pre_implementation_audit.md
```

必须说明：

1. 当前 Position Close 如何计算 released cost；
2. 当前 Allocation Close 如何计算 released cost；
3. 为什么单 Cluster 场景不会暴露问题；
4. 为什么不同成本 Multi-Cluster 会失败；
5. 当前 Position Average Price 在 Close 后如何处理；
6. 当前 Realized PnL 由哪个组件计算；
7. Account 和 Ledger 是否重新计算 PnL；
8. Committed Fact 当前保存哪些成本字段；
9. Economic Invariant 当前缺少哪些校验；
10. Runtime Reconciliation 当前校验哪些聚合关系；
11. 是否存在正式 Unallocated Cost Authority；
12. 当前 Multi-Cluster 测试的真实失败错误；
13. 哪些测试只是旧 Execution/Trade 数量断言；
14. 哪些接口应删除而不是兼容；
15. 哪些 Reducer 参数已经失去意义；
16. 哪些示例依赖旧接口；
17. 是否需要修改 Persistence Schema；
18. 是否需要修改 Transaction Codec；
19. 是否需要修改 Recovery Phase；
20. 最终选定的简单统一方案。

审计完成后继续执行，不得停止。

---

# 八、核心设计：Attributed Close Cost Authority

## 8.1 新增不可变业务权威

建议新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyAttributedCloseCostAuthority:
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId

    position_id: OnlyPositionId
    allocation_id: OnlyAllocationId

    fill_quantity: OnlyQuantity

    position_quantity_before: OnlyQuantity
    allocation_quantity_before: OnlyQuantity

    position_cumulative_cost_before: Decimal
    allocation_cumulative_cost_before: Decimal

    released_open_price_quantity: Decimal

    position_quantity_after: OnlyQuantity
    allocation_quantity_after: OnlyQuantity

    position_cumulative_cost_after: Decimal
    allocation_cumulative_cost_after: Decimal

    position_average_open_price_after: OnlyPrice | None
    allocation_average_open_price_after: OnlyPrice | None

    realized_pnl_delta: OnlyMoney

    terminal_position_close: bool
    terminal_allocation_close: bool
```

实际字段可根据项目类型系统调整，但必须保持：

```text
不可变
纯数据
无 Manager 依赖
无 Store 依赖
无 Runtime 依赖
可确定性重建
```

这个对象不是 Manager，不需要独立持久化表，也不是新的 Transaction 类型。

---

## 8.2 Authority 的唯一职责

它只回答：

```text
本次 Close 归属于哪个 Allocation
本次释放多少精确成本
Position After 是什么
Allocation After 是什么
本次 Realized PnL 是多少
```

它不负责：

```text
应用 Projection
修改 Manager
写 Store
发送 Event
更新 Account
更新 Ledger
更新 Risk
```

---

# 九、成本归因算法

## 9.1 由当前 Cluster Allocation 计算 released cost

使用当前 Allocation：

```python
allocation_reduction = only_reduce_average_cost_close(
    cumulative_open_price_quantity_before=
        allocation_before.cumulative_open_price_quantity,
    quantity_before=allocation_before.total_quantity,
    fill_quantity=trade.quantity,
)
```

得到：

```text
released_open_price_quantity
allocation_quantity_after
allocation_cumulative_cost_after
terminal_allocation_close
```

该 `released_open_price_quantity` 是本次 Close 的唯一成本权威。

---

## 9.2 Position 不再独立按账户平均成本分摊

Position After：

```text
position_quantity_after
=
position_quantity_before
-
fill_quantity
```

```text
position_cumulative_cost_after
=
position_cumulative_cost_before
-
released_open_price_quantity
```

必须检查：

```text
position_cumulative_cost_after >= 0
```

若 Position 全平：

```text
position_quantity_after = 0
position_cumulative_cost_after = 0
position_average_open_price_after = None
```

若 Position 仍有数量：

```text
position_average_open_price_after
=
quantize(
    position_cumulative_cost_after
    /
    position_quantity_after,
    instrument_price_precision,
    ROUND_HALF_EVEN
)
```

---

## 9.3 Allocation After

Allocation After 必须使用前面已经计算出的同一个结果：

```text
allocation_quantity_after
allocation_cumulative_cost_after
```

不得在 Allocation Reducer 中再次调用成本计算函数。

若 Allocation 全平：

```text
allocation_quantity_after = 0
allocation_cumulative_cost_after = 0
allocation_average_open_price_after = None
```

若仍有数量：

```text
allocation_average_open_price_after
```

应由剩余精确成本重新派生，或者保持现有值并通过派生结果进行严格校验。

优先采用统一派生方式，减少隐式假设。

---

## 9.4 Realized PnL

定义：

```text
fill_value_price_quantity
=
fill_price
×
fill_quantity
```

```text
realized_pnl_raw
=
(
    fill_value_price_quantity
    -
    released_open_price_quantity
)
×
contract_multiplier
```

按 Currency Precision 转换为 `OnlyMoney`。

费用不进入毛 Realized PnL。

---

# 十、Planner 实现

## 10.1 在 Planner 中创建共享 Authority

Planner 当前已经持有：

```text
Position Before
Allocation Before
Order
Fill
Multiplier
Instrument Precision
```

因此 Attributed Close Cost Authority 应在 Planner 的纯规划阶段创建。

建议流程：

```text
Order Reduction
        │
        ▼
Close Attribution Builder
        │
        ▼
Attributed Close Cost Authority
        │
        ├── Position Reducer
        ├── Allocation Reducer
        ├── Account Reducer
        ├── Strategy Ledger Reducer
        └── Fact Builder
```

不得在 Projection Target 或 Manager 应用阶段重新计算。

---

## 10.2 Close Scope 严格验证

构建 Authority 前验证：

```text
order.cluster_id == allocation.cluster_id
order.account_id == position.account_id
order.account_id == allocation.account_id
order.instrument_id == position.instrument_id
order.instrument_id == allocation.instrument_id
order.runtime_id == position.runtime_id
order.runtime_id == allocation.runtime_id
```

数量验证：

```text
fill_quantity <= allocation.total_quantity
fill_quantity <= position.total_quantity
fill_quantity <= position_reservation.remaining_quantity
```

成本验证：

```text
allocation_cumulative_cost_before >= 0
position_cumulative_cost_before >= allocation_released_cost
```

当前范围要求：

```text
Position Cost
=
sum(Allocation Cost)
```

如发现无法解释的 Unallocated Cost，Fail Closed：

```text
MULTI_CLUSTER_CLOSE_UNALLOCATED_COST_UNSUPPORTED
```

不得用账户平均成本填补差额。

---

# 十一、Reducer 重构

## 11.1 Position Reducer

Close 分支必须改为消费：

```text
OnlyAttributedCloseCostAuthority
```

删除 Position Close 分支中对：

```python
only_reduce_average_cost_close(...)
```

的独立调用。

Position Reducer只负责：

```text
校验 Authority Scope
安装 Position After
追加 Realized PnL
追加 Fee
生成 Position Projection
```

---

## 11.2 Allocation Reducer

同样消费同一个 Authority。

删除 Allocation Close 分支中对：

```python
only_reduce_average_cost_close(...)
```

的重复调用。

Allocation Reducer只负责：

```text
校验 Allocation Authority
安装 Allocation After
追加同一个 Realized PnL
追加 Fee
生成 Allocation Projection
```

---

## 11.3 Account 与 Strategy Ledger

继续接收 Planner 传入的：

```text
realized_pnl_delta
```

不得增加任何重新计算逻辑。

检查并删除：

```text
基于 average_open_price 的 PnL fallback
缺少 Authority 时自行推算
单 Cluster 专用兼容分支
```

缺少正式 PnL Authority 时必须 Fail Closed。

---

# 十二、旧接口清理要求

本任务必须主动删除旧接口残留。

## 12.1 删除重复成本计算参数

如果 Position/Allocation Reducer 仍同时接收：

```text
realized_pnl_delta
close_authority
average_open_price
```

且其中部分可以由 Authority 唯一得出，应删除冗余参数。

接口应表达唯一数据来源，不应为了兼容旧调用而保留多个同义入口。

---

## 12.2 删除旧成本计算路径

必须删除：

```text
Position Close 自己计算 released cost
Allocation Close 自己计算 released cost
Position Close 默认保持 average_open_price
缺少 Allocation 时退回 Position 平均成本
```

不得保留：

```text
legacy_close_cost=True
use_position_average_cost=False
compatibility_mode
```

这类开关。

---

## 12.3 删除无意义包装接口

审计以下接口：

```text
仅被旧测试调用的 helper
仅为旧示例保留的 adapter
只做参数转发的 compatibility wrapper
重复的 Close Cost dataclass
旧的测试专用生产入口
```

如果没有正式业务价值，删除并更新调用者。

---

## 12.4 示例和测试必须跟随正式模型

禁止为了让旧示例继续运行而保留错误接口。

应修改：

```text
examples/
tests/fixtures/
test helper
plugin test fixture
```

让它们使用新的正式 API。

示例不是兼容合同。

测试不是旧接口的保留理由。

---

# 十三、Committed Fact

必须继续保存并严格校验：

```text
position_quantity_before
position_quantity_after

allocation_quantity_before
allocation_quantity_after

position_cumulative_open_price_quantity_before
position_cumulative_open_price_quantity_after

allocation_cumulative_open_price_quantity_before
allocation_cumulative_open_price_quantity_after

released_open_price_quantity

realized_pnl_delta
position_realized_pnl_delta
allocation_realized_pnl_delta
account_realized_pnl_delta
ledger_realized_pnl_delta
```

建议不新增重复字段。

如果现有字段已经足以表达 Authority，不要增加：

```text
position_released_cost
allocation_released_cost
shared_released_cost
```

三个同义字段。

只保留：

```text
released_open_price_quantity
```

作为正式唯一事实。

---

# 十四、Economic Invariant

扩展 `OnlyPreparedExecutionEconomicInvariantValidator`。

## 14.1 数量

```text
position_quantity_before - fill_quantity
=
position_quantity_after
```

```text
allocation_quantity_before - fill_quantity
=
allocation_quantity_after
```

---

## 14.2 成本

计算：

```text
position_released_cost
=
position_cost_before
-
position_cost_after
```

```text
allocation_released_cost
=
allocation_cost_before
-
allocation_cost_after
```

必须满足：

```text
position_released_cost
=
allocation_released_cost
=
fact.released_open_price_quantity
```

---

## 14.3 平均价

如果 Position After Quantity 大于零：

```text
quantize(
    position_cost_after / position_quantity_after
)
=
position_average_open_price_after
```

Allocation 同理。

全平时：

```text
quantity_after = 0
cost_after = 0
average_open_price_after = None
```

---

## 14.4 PnL

```text
fact.realized_pnl_delta
=
(
    fill_price × fill_quantity
    -
    fact.released_open_price_quantity
)
× multiplier
```

并验证：

```text
position PnL delta
=
allocation PnL delta
=
account PnL delta
=
ledger PnL delta
=
fact PnL delta
```

---

# 十五、Runtime 聚合不变量

增加正式 Runtime 级对账。

对每个：

```text
runtime_id
account_id
instrument_id
position_side
position_mode
```

验证：

```text
Position Quantity
=
sum(Allocation Quantity)
```

```text
Position Cumulative Cost
=
sum(Allocation Cumulative Cost)
```

当前范围不支持 Unallocated Cost 时，必须要求：

```text
Unallocated Quantity = 0
Unallocated Cost = 0
```

账户和 Ledger：

```text
Account Realized PnL
=
sum(Strategy Ledger Realized PnL)
```

```text
Account Position Market Value
=
sum(Strategy Ledger Position Market Value)
```

```text
Account Equity
=
sum(Strategy Ledger Equity)
```

需考虑固定 Cluster Capital 模型中允许的现金归集差异；按照现有资本模型定义精确不变量，不得硬写不成立的公式。

---

# 十六、恢复和确定性

## 16.1 不增加 Recovery Phase

Attributed Close Cost Authority 必须被冻结到：

```text
Projection Before/After
Committed Fact
Authority Hash
Payload Hash
```

恢复时：

```text
重建相同 Prepared Transaction
或直接应用持久化 Projection
```

不得在 Recovery 阶段读取当前 Manager 并重新选择成本。

---

## 16.2 Checkpoint 场景

必须覆盖：

```text
Cluster A BUY @ 10
Cluster B BUY @ 12
Cluster A CLOSE
Checkpoint
Restart
Cluster B CLOSE
```

恢复后：

```text
Position Remaining Cost
=
Cluster B Allocation Cost

Cluster A Realized PnL 保持不变

Cluster B Realized PnL 正确

最终 Position Cost = 0
```

---

## 16.3 注册顺序确定性

运行两次：

```text
Run A:
先注册 Cluster A
后注册 Cluster B

Run B:
先注册 Cluster B
后注册 Cluster A
```

最终比较：

```text
Transactions
Orders
Trades
Positions
Allocations
Account
Ledgers
Facts
Result Fingerprint
Determinism Fingerprint
Canonical Business Projection
```

成本归因只能依赖正式 Key，不得依赖：

```text
dict insertion order
cluster registration index
list index
object creation sequence
```

---

# 十七、必须先增加的失败测试

在生产修改前增加能够稳定暴露当前问题的测试。

## 场景一：不同成本全平一个 Cluster

```text
Cluster A:
BUY 1000 @ 10

Cluster B:
BUY 1000 @ 12

Cluster A:
SELL CLOSE 1000 @ 13
```

预期：

```text
Position:
quantity = 1000
cost = 12000
average = 12

Allocation A:
quantity = 0
cost = 0
realized pnl = 3000

Allocation B:
quantity = 1000
cost = 12000

Account realized pnl = 3000
Ledger A realized pnl = 3000
Ledger B realized pnl = 0
```

---

## 场景二：Partial Close

```text
A:
1000 @ 10

B:
1000 @ 12

A CLOSE 400
```

预期：

```text
Released Cost = 4000

Allocation A:
quantity = 600
cost = 6000

Position:
quantity = 1600
cost = 18000
average = 11.25
```

---

## 场景三：Multi-Fill

```text
A Close:
300 @ 11
400 @ 13
300 @ 9
```

预期：

```text
Released Cost:
3000
4000
3000

Realized PnL:
300
1200
-300

Total:
1200
```

---

## 场景四：两个 Cluster 顺序平仓

```text
A BUY 1000 @ 10
B BUY 1000 @ 12

A SELL 1000 @ 13
B SELL 1000 @ 14
```

预期：

```text
A PnL = 3000
B PnL = 2000
Account PnL = 5000
sum(Ledger PnL) = 5000

Position = CLOSED
Position Cost = 0
Allocations = CLOSED
```

---

## 场景五：反向平仓顺序

先平 B，再平 A。

各 Cluster PnL 不变，总结果不变。

---

# 十八、现有 10 个失败的处理

当前失败应严格分类处理。

## 18.1 旧结果断言

以下测试因完整 BUY/OPEN + SELL/CLOSE 后 Execution 数由 1 变为 2，Round-Trip Trade 数由 0 变为 1：

```text
analytics
artifact
report
CLI report
result collector
```

应更新正式业务期望：

```text
execution_count = 2
trade_count = 1
```

不得修改 Collector 隐藏 Close Execution。

---

## 18.2 Multi-Cluster 失败

以下测试必须通过生产逻辑修复解决：

```text
test_two_clusters_are_isolated_and_share_registry_resources
test_multi_cluster_registration_order_does_not_change_result
test_two_clusters_can_both_profit_in_one_shared_runtime
test_engine_multi_cluster_performance_full_vertical_slice
```

禁止通过以下方式绕过：

```text
禁用 SELL/CLOSE
让两个 Cluster 使用同一价格
移除 Reconciliation
修改 FAILED 断言
清空 trades
```

---

## 18.3 Recovery 测试

旧测试如果要求恢复已有 Transaction 时再次 Commit，并因此要求第二次 `AFTER_COMMIT` 失败，应修正测试语义。

恢复已有持久化 Transaction 不应重复 Commit。

可改为：

```text
Engine A 故障
Engine B 恢复并完成
Engine C 再次打开保持幂等
```

若需要真正 A→B→C 两次故障，必须使用明确的第二故障边界或新的 Continuation Transaction。

不得破坏正确恢复逻辑来满足旧测试。

---

# 十九、测试工作包

建议新增或调整以下测试。

## 19.1 纯 Authority

```text
tests/execution/
test_multi_cluster_close_cost_authority.py
```

覆盖：

```text
不同成本
部分平仓
全部平仓
多次 Fill
精确 Decimal
最终归零
Scope 冲突
数量不足
```

---

## 19.2 Reducer

```text
tests/execution/
test_multi_cluster_position_close_reducer.py

tests/execution/
test_multi_cluster_allocation_close_reducer.py
```

验证两个 Reducer 消费同一 Authority。

---

## 19.3 Economic Invariant

```text
tests/execution/
test_multi_cluster_close_economic_invariants.py
```

必须主动构造错误 Prepared Transaction，验证：

```text
Position released cost 不一致
Allocation released cost 不一致
Fact released cost 不一致
PnL 不一致
Average Price 不一致
```

都会 Fail Closed。

---

## 19.4 Engine Vertical Slice

```text
tests/integration/
test_engine_multi_cluster_close_cost_authority.py
```

必须通过正式：

```text
OnlyEngine
Strategy
Order
Virtual Broker
ExecutionProcessor
Prepared Transaction
Projection
Result
```

不能只调用 Reducer。

---

## 19.5 Registration Order

```text
tests/integration/
test_engine_multi_cluster_close_registration_order.py
```

---

## 19.6 Recovery

```text
tests/integration/
test_engine_recovery_multi_cluster_close_cost.py
```

覆盖：

```text
After Commit
Position Projection 后
Allocation Projection 后
Projection Ready 后
Checkpoint 后重启
```

---

## 19.7 Architecture

```text
tests/architecture/
test_multi_cluster_close_cost_authority_architecture.py
```

至少检查：

1. Position Close 不调用 `only_reduce_average_cost_close()`；
2. Allocation Close 不调用 `only_reduce_average_cost_close()`；
3. 只有 Authority Builder 调用成本函数；
4. Position 和 Allocation 接收同一 Authority 类型；
5. Account 不计算 Realized PnL；
6. Ledger 不计算 Realized PnL；
7. 无兼容模式开关；
8. 无旧 Close Cost Adapter；
9. 无新的 Store；
10. 无新的 Coordinator；
11. 无新的 Recovery Phase；
12. 无生产故障开关。

---

# 二十、需要清理的代码类型

完成实现后执行全仓搜索，清理：

```text
旧 Position Close 成本算法
旧 Allocation Close 成本算法
旧 average_price fallback
legacy close cost helper
compatibility adapter
多余 Reducer 参数
只为旧测试暴露的接口
无调用的 dataclass
无调用的 enum
过时错误码
过时文档描述
```

执行：

```bash
rg "legacy.*close"
rg "compat.*close"
rg "average_open_price.*fill_quantity"
rg "only_reduce_average_cost_close"
rg "CLOSE_COST"
rg "PARTIAL_CLOSE_NOT_READY"
```

最终 `only_reduce_average_cost_close()` 应只有唯一正式业务调用位置，或者极少数明确的纯单元测试调用。

---

# 二十一、文档

新增 ADR：

```text
docs/adr/
0054-multi-cluster-close-cost-authority.md
```

ADR 必须说明：

1. 问题背景；
2. 为什么 Position 平均成本不能决定 Cluster Close 成本；
3. Allocation 是 Close Attribution Authority；
4. Position 是聚合状态 Authority；
5. 精确累计成本与平均价的关系；
6. Realized PnL 唯一来源；
7. Planner 计算顺序；
8. Projection 顺序保持不变；
9. Runtime 聚合不变量；
10. Recovery 和 Determinism；
11. Unallocated Position 当前边界；
12. 删除的旧接口；
13. 不支持范围。

更新：

```text
README.md
docs/architecture.md
docs/execution.md
docs/position.md
docs/account.md
docs/strategy_ledger.md
docs/runtime_recovery.md
docs/roadmap.md
```

不得保留与实际实现冲突的旧描述。

---

# 二十二、建议提交顺序

最终是一个 PR，但内部 Commit 应清晰：

```text
1. Add failing multi-cluster cost attribution tests
2. Add attributed close cost authority
3. Refactor position and allocation close reducers
4. Enforce economic and aggregate invariants
5. Complete multi-cluster engine and recovery coverage
6. Remove obsolete close-cost interfaces and adapters
7. Update result expectations, documentation and full regression
```

不得把旧接口清理留给后续 PR。

---

# 二十三、质量门禁

先执行定向测试：

```bash
uv run pytest \
  tests/execution/test_multi_cluster_close_cost_authority.py \
  tests/execution/test_multi_cluster_position_close_reducer.py \
  tests/execution/test_multi_cluster_allocation_close_reducer.py \
  tests/execution/test_multi_cluster_close_economic_invariants.py \
  -q
```

再执行：

```bash
uv run pytest \
  tests/integration/test_engine_cluster_product_entry.py \
  tests/scenario/test_multi_cluster_performance_scenario.py \
  tests/integration/test_engine_multiple_causal_restart.py \
  -q
```

然后执行结果系统：

```bash
uv run pytest \
  tests/result \
  tests/analytics \
  tests/artifact \
  tests/report \
  -q
```

最后完整质量门禁：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha
uv run mypy packages/fake/onlyalpha-plugin-broker-virtual/src
uv run mypy packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare
uv run mypy packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt

uv run pytest tests/execution -q
uv run pytest tests/position -q
uv run pytest tests/account -q
uv run pytest tests/strategy_ledger -q
uv run pytest tests/result -q
uv run pytest tests/analytics -q
uv run pytest tests/artifact -q
uv run pytest tests/report -q
uv run pytest tests/runtime/checkpoint -q
uv run pytest tests/runtime/recovery -q
uv run pytest tests/integration -q
uv run pytest tests/scenario -q
uv run pytest tests/architecture -q

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"

uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q

uv run python scripts/version_sync.py check
git diff --check
```

不得伪造未执行的结果。

---

# 二十四、完成标准

只有以下全部满足才可声明完成：

1. Multi-Cluster Close 成本由当前 Cluster Allocation 决定；
2. Position 不再独立按账户平均成本释放；
3. Allocation 不再独立重复计算；
4. Position 和 Allocation 使用同一 released cost；
5. Position 剩余平均价从剩余精确成本派生；
6. Allocation 剩余平均价与精确成本一致；
7. Realized PnL 只计算一次；
8. Account、Ledger、Fact 使用同一 PnL；
9. Position Cost 等于 Allocation Cost 汇总；
10. Account 与 Ledger 对账成立；
11. Partial/Multi-Fill 成本守恒；
12. 最终 Close 成本严格归零；
13. 不依赖 Cluster 注册顺序；
14. Checkpoint/Restart 与 Baseline 等价；
15. 当前 10 个失败全部解决；
16. 单 Cluster 正式结果不回归；
17. BUY/OPEN 不回归；
18. Long Close Whole/Partial/Multi-Fill 不回归；
19. Durable Terminal 不回归；
20. 不新增 Store；
21. 不新增 Coordinator；
22. 不新增 Recovery Phase；
23. 旧成本计算路径已删除；
24. 旧兼容接口已删除；
25. 示例和测试已迁移到正式 API；
26. 文档与实际实现一致；
27. Ruff、Mypy、Pytest 和架构门禁全部通过。

---

# 二十五、禁止实现

以下任一情况视为失败：

```text
只修改测试断言而不修复 Multi-Cluster 成本

让两个 Cluster 使用相同买入价格规避问题

禁用 Multi-Cluster Close

禁用 Reconciliation

Position 和 Allocation 继续各算一次成本

使用账户平均成本作为 Cluster PnL Authority

缺少 Allocation 时退回 Position 平均成本

通过 compatibility flag 保留旧算法

因为旧测试调用而保留旧接口

因为示例调用而保留旧接口

新增 legacy adapter 转发到新接口

Account 重新计算 Realized PnL

Ledger 重新计算 Realized PnL

Recovery 时重新选择成本

依赖 Cluster 注册顺序

新增 Close Store

新增 Close Coordinator

新增 Close Recovery Phase

增加生产 Fault Switch

删除经济不变量以让测试通过

伪造测试结果
```

---

# 二十六、最终交付报告

整个任务完成后输出一次最终报告。

必须包含：

## 1. 基线

```text
起始 Commit
最终 Commit
分支
版本
```

## 2. 根因

说明 Position 和 Allocation 独立计算成本为什么错误。

## 3. 第一性原则模型

说明：

```text
Allocation Attribution Authority
Position Aggregate Authority
Exact Cost Authority
Single Realized PnL Authority
```

## 4. 新接口

列出新增的正式模型和接口。

## 5. 删除的旧接口

逐项列出：

```text
删除文件
删除类
删除方法
删除参数
删除兼容层
更新调用点
```

## 6. Planner 与 Reducer

说明新的规划和计算顺序。

## 7. Economic Invariant

列出新增不变量。

## 8. Multi-Cluster 结果

展示：

```text
A BUY @ 10
B BUY @ 12
A CLOSE
B CLOSE
```

的 Position、Allocation、Account 和 Ledger 结果。

## 9. Recovery

说明 Commit、Projection、Checkpoint 和 Restart 验证。

## 10. 原 10 个失败

逐项说明：

```text
哪些是旧断言
哪些由生产修复解决
哪些恢复测试被修正
```

## 11. 测试

列出真实执行命令和结果。

## 12. 未实现范围

明确：

```text
Unallocated Close
Cross-Cluster Close
FIFO/LIFO
Short
Hedging
Futures
Margin
```

如果任何正式完成标准未满足，不得声明任务完成。
