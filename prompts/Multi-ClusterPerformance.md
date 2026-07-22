# OnlyAlpha：彻底修复 Multi-Cluster Performance 与 `ledgers[0]` 隐式单底修复 Multi-Cluster Performance 与 `ledgers[0]`账本假设

## 一、任务目标

认真重新阅读当前 OnlyAlpha 工程，以当前 `master` 源码、测试、配置、文档和 CI 为事实源，从第一性原则出发，彻底修复 Multi-Cluster 场景下的以下问题：

```text
1. ExecutionProcessor 使用 list_ledgers()[0] 获取 Ledger 币种
2. Backtest Result 使用 ledgers[0] 的收益率和最大回撤代表 Runtime
3. 多个 Cluster 默认重复获得完整 Account 初始资金
4. Cluster Performance 与 Runtime Performance 权威边界混乱
5. Account 缗少权益时间线，无法正确计算 Runtime 最大回撤
6. Account 与所有 Cluster Ledger 之间缺少正式对账不变量
```

本任务不是将：

```python
ledgers[0]
```

机械替换为：

```python
next(...)
```

而是重新建立完整、明确、可验证的 Multi-Cluster 会计和绩效架构。

本任务不考虑历史兼容性。

允许并要求直接重写：

* Strategy Ledger 定位接口；
* Cluster 资本配置；
* Runtime Assembly；
* ExecutionProcessor；
* Order Reservation Adapter；
* Strategy Valuation；
* Backtest Result；
* Cluster Result；
* Analytics；
* Artifact；
* Scenario；
* Tests；
* Examples；
* Documentation。

不要为了旧测试、旧示例、旧 Golden 文件或旧 API 保留错误结构。

---

# 二、修改前必须完成的审计

开始修改前必须重新检查当前仓库状态：

```bash
git status
git log -n 10 --oneline
```

然后全仓搜索：

```bash
rg "ledgers\[0\]"
rg "list_ledgers\(\)\[0\]"
rg "list_ledgers"
rg "get_by_cluster"
rg "OnlyStrategyLedgerKey"
rg "strategy_initial_capital"
rg "OnlyBacktestPerformanceSummary"
rg "OnlyClusterResult"
rg "maximum_drawdown"
rg "return_since_start"
rg "account\.equity"
rg "ledger\.performance"
```

必须先形成修改前依赖报告，至少说明：

1. 哪些生产代码通过列表顺序定位 Ledger；
2. 哪些结果字段来自 Account；
3. 哪些结果字段来自第一个 Ledger；
4. 每个 Cluster 当前如何获得初始资本；
5. Account 是否保存权益历史；
6. Cluster Ledger 是否保存权益历史或只有当前快照；
7. Analytics、Artifact 和 Report 如何读取 Runtime Performance；
8. Scenario、测试和示例依赖哪些旧结果字段；
9. 当前多个 Cluster 是否共用同一个 Account；
10. 当前是否允许多 Account 或多 Currency。

当前源码是唯一事实源，不得机械套用本提示词中的旧文件路径。

---

# 三、第一性原则

## 3.1 Account 与 Strategy Ledger 是不同权威

必须明确：

```text
Shared Account
    Runtime 真实资金、持仓和组合权益权威

Strategy Ledger
    某个 Cluster 的虚拟资本、交易归属和绩效权威

Runtime Performance
    共享 Account 组合权益路径的绩效

Cluster Performance
    对应 Strategy Ledger 权益路径的绩效

Reconciliation
    验证 Account 与所有 Cluster Ledger 加总关系
```

不得再使用某个 Cluster Ledger 代表整个 Runtime。

---

## 3.2 列表顺序不是业务身份

禁止通过以下方式定位业务实体：

```python
ledgers[0]
list_ledgers()[0]
zip(clusters, ledgers)
sorted(...)[0]
next(iter(...))
```

Ledger 必须通过完整业务作用域定位：

```text
runtime_id
account_id
cluster_id
base_currency
```

完整作用域已经由 `OnlyStrategyLedgerKey` 表达，应围绕该 Key 建立正式 Locator/Registry API。

---

## 3.3 Runtime 绩效不能从 Cluster 绩效推导

禁止使用：

```text
第一个 Cluster 的收益率
所有 Cluster 收益率平均值
所有 Cluster 收益率之和
最大的 Cluster 回撤
最小的 Cluster 回撤
所有 Cluster 回撤平均值
```

表示 Runtime Performance。

Runtime Performance 必须来自共享 Account 自身的权益时间线：

```text
Account Equity Timeline
→ High Water Mark
→ Drawdown Timeline
→ Maximum Drawdown
→ Runtime Return
```

---

## 3.4 当前阶段只正式支持 FIXED_CAPITAL

当前 Strategy Ledger 领域模型只完整实现固定资本模式，因此本任务必须明确：

```text
正式支持：FIXED_CAPITAL

本任务不实现：
SHARED_POOL
EQUITY_PERCENTAGE
动态资本再分配
Cluster 间自动借用资金
```

禁止通过给每个 Cluster 分配完整 Account 初始资金来伪装共享资金池。

---

# 四、正式资本模型

## 4.1 单 Cluster

只有一个 Cluster 时，可以允许省略 Cluster 资本配置：

```text
Cluster Initial Capital
= Account Initial Cash
```

## 4.2 多 Cluster

存在两个或更多 Cluster 时：

* 每个 Cluster 必须显式配置资本；
* 模式必须为 `FIXED_CAPITAL`；
* Currency 必须与 Account Base Currency 相同；
* Capital 必须非负；
* 所有 Cluster Capital 总和必须严格等于 Account Initial Cash；
* 不得隐式复制 Account Initial Cash；
* 不得自动平均分配；
* 不得把剩余资金偷偷分给第一个 Cluster；
* 不得保留未分配资金，除非正式引入 System Ledger，本任务暂不引入。

推荐配置结构：

```yaml
cluster:
  cluster_id: cluster-a
  capital:
    mode: FIXED_CAPITAL
    amount: 400000
    currency: CNY
```

另一个 Cluster：

```yaml
cluster:
  cluster_id: cluster-b
  capital:
    mode: FIXED_CAPITAL
    amount: 600000
    currency: CNY
```

Account：

```yaml
accounts:
  - account_id: account-main
    initial_cash:
      amount: 1000000
      currency: CNY
```

必须满足：

```text
400000 + 600000 = 1000000
```

如果现有配置模型不适合，应直接升级，不保留旧的：

```text
strategy_initial_capital
```

松散兼容字段。

---

# 五、删除旧资本接口

本任务不考虑历史兼容，完成迁移后删除：

```text
OnlyRuntimeAssemblyConfig.strategy_initial_capital
```

以及所有等价的 Runtime 级默认 Strategy Capital 字段。

删除 Cluster 配置中旧的松散形式：

```yaml
strategy_initial_capital: ...
```

不要增加：

* Deprecated Alias；
* 旧字段转发；
* 自动迁移；
* 新旧配置双读；
* 默认回退；
* Warning 后继续运行。

所有测试、示例和配置文件直接迁移到新的正式资本模型。

---

# 六、建立精确 Ledger Locator

## 6.1 目标

所有生产代码必须通过一个正式的 Ledger 定位边界获取 Ledger Key 或 Snapshot。

建议新增：

```python
class OnlyStrategyLedgerLocator:
    def require_key(
        self,
        *,
        runtime_id: OnlyRuntimeId,
        account_id: OnlyAccountId,
        cluster_id: OnlyClusterId,
        currency: OnlyCurrency,
    ) -> OnlyStrategyLedgerKey:
        ...

    def require_snapshot(
        self,
        *,
        runtime_id: OnlyRuntimeId,
        account_id: OnlyAccountId,
        cluster_id: OnlyClusterId,
        currency: OnlyCurrency,
    ) -> OnlyStrategyLedgerSnapshot:
        ...
```

也可以将其实现为 `OnlyStrategyLedgerManager` 或 Query Service 的明确方法，但职责必须统一。

## 6.2 Scope Index

在 Strategy Ledger Manager 内建立明确索引：

```python
_scope_index: dict[
    tuple[
        OnlyRuntimeId,
        OnlyAccountId,
        OnlyClusterId,
        OnlyCurrency,
    ],
    OnlyStrategyLedgerKey,
]
```

创建 Ledger 时：

* 检查 Runtime Scope；
* 检查完整 Scope 是否重复；
* 注册 Scope；
* 不允许同一完整 Scope 对应多个 Ledger；
* 不允许通过列表遍历作为正常定位路径。

## 6.3 删除歧义 API

审查并删除或限制：

```text
get_by_cluster(cluster_id)
by_cluster(cluster_id)
```

仅凭 Cluster ID 无法支持未来：

* 多 Account；
* 多 Currency；
* 同 Cluster 多 Ledger。

如果这些接口没有明确且唯一的业务语义，直接删除。

不要为了旧测试保留。

---

# 七、迁移所有 Ledger 调用方

以下生产路径必须使用同一个 Ledger Locator：

```text
ExecutionProcessor
Order Cash Reservation
Order Reservation Release
Strategy Valuation
Risk Ledger Query
Fee Adjustment
Result Collector
Scenario Assertion
Reconciliation
其他所有 Ledger 读写路径
```

## 7.1 ExecutionProcessor

删除：

```python
self._ledgers.list_ledgers()[0].key.base_currency
```

目标方式：

```python
ledger_key = self._ledger_locator.require_key(
    runtime_id=trade.runtime_id,
    account_id=trade.account_id,
    cluster_id=trade.cluster_id,
    currency=fee_instruction.fee_breakdown.currency,
)
```

并验证：

```text
Trade Settlement Currency
= Fee Currency
= Account Base Currency
= Ledger Base Currency
```

当前阶段不支持 FX 时，币种不一致必须明确失败。

## 7.2 Order Reservation Adapter

不得自行使用全局 Runtime Base Currency 拼接 Ledger Key。

必须根据：

```text
Order
Instrument Settlement Currency
Account
Cluster
```

通过 Locator 获取 Ledger。

## 7.3 Strategy Valuation

Strategy Valuation 必须明确写入对应：

```text
Runtime + Account + Cluster + Currency
```

的 Ledger。

不得按 Cluster 列表或 Ledger 列表的顺序配对。

## 7.4 Risk

Risk 查询 Strategy Ledger 时也必须使用完整 Scope。

禁止 Risk 在 Cluster 没有唯一 Ledger 时选择第一个匹配项。

---

# 八、Cluster Performance 模型

## 8.1 新增正式 Cluster Performance

当前 Cluster Result 必须正式包含对应 Strategy Ledger 的绩效。

建议新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyClusterPerformanceSummary:
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    ledger_id: OnlyStrategyLedgerId
    currency: OnlyCurrency

    initial_equity: OnlyMoney
    final_equity: OnlyMoney

    realized_pnl: OnlyMoney
    unrealized_pnl: OnlyMoney
    net_pnl: OnlyMoney
    fees: OnlyMoney

    return_since_start: OnlyRate | None
    current_drawdown: OnlyRate
    maximum_drawdown: OnlyRate

    trade_count: int
    winning_trade_count: int
    losing_trade_count: int
    win_rate: OnlyRate | None
    profit_factor: OnlyRate | None

    valuation_count: int
    quality_flags: tuple[str, ...]
```

字段可根据当前 Ledger Domain 调整，但必须明确：

> Cluster Performance 的唯一权威来源是该 Cluster 对应的 Strategy Ledger。

## 8.2 升级 Cluster Result

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyClusterResult:
    cluster_id: OnlyClusterId
    performance: OnlyClusterPerformanceSummary
    strategy_result_extension: Mapping[str, object]
    factor_results: tuple[Mapping[str, object], ...]
    indicator_diagnostics: tuple[Mapping[str, object], ...]
```

构建 Cluster Result 时必须：

1. 获取 Cluster ID；
2. 获取该 Cluster 绑定的 Account；
3. 获取 Account Base Currency；
4. 通过 Locator 获取唯一 Ledger；
5. 从 Ledger Snapshot/Timeline 构建 Cluster Performance。

禁止：

```python
zip(clusters, ledgers)
```

---

# 九、Runtime Portfolio Performance

## 9.1 新的权威模型

当前泛化的 Backtest Performance Summary 应升级为明确的 Runtime 组合绩效模型，例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimePortfolioPerformanceSummary:
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    authority: str  # 固定为 ACCOUNT
    currency: OnlyCurrency

    initial_equity: OnlyMoney
    final_equity: OnlyMoney

    realized_pnl: OnlyMoney
    unrealized_pnl: OnlyMoney
    net_pnl: OnlyMoney
    fees: OnlyMoney
    external_cash_flow: OnlyMoney

    return_since_start: OnlyRate | None
    current_drawdown: OnlyRate
    maximum_drawdown: OnlyRate
    high_water_mark: OnlyMoney

    valuation_count: int
    quality_flags: tuple[str, ...]
```

Runtime Performance 的所有字段必须来自共享 Account 及其绩效投影。

不得读取 Strategy Ledger 作为 Runtime Performance 的补充来源。

---

# 十、建立 Account Equity Timeline

## 10.1 不要把 Performance 逻辑塞入 AccountManager

AccountManager 是账户当前可变状态权威。

绩效是状态序列的派生读模型。

新增明确组件，例如：

```text
OnlyAccountPerformanceProjector
```

或：

```text
OnlyRuntimePortfolioPerformanceProjector
```

职责：

* 消费不可变 Account Snapshot 或 Account Valuation Fact；
* 保存确定性权益时间线；
* 维护高水位；
* 计算当前回撤；
* 计算最大回撤；
* 计算收益率；
* 生成 Runtime Performance Summary。

不得：

* 修改 Account；
* 修改 Position；
* 修改 Ledger；
* 查询 Broker；
* 重新执行交易逻辑；
* 使用 Cluster Ledger 代替 Account 事实。

## 10.2 Equity Point

建议模型：

```python
@dataclass(frozen=True, slots=True)
class OnlyAccountEquityPoint:
    sequence: int
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    ts_event: OnlyTimestamp
    trading_day: OnlyTradingDay | None

    currency: OnlyCurrency
    cash: OnlyMoney
    position_market_value: OnlyMoney
    realized_pnl: OnlyMoney
    unrealized_pnl: OnlyMoney
    fees: OnlyMoney
    equity: OnlyMoney
    external_cash_flow: OnlyMoney

    source: OnlyAccountValuationSource
    account_version: int
    quality_flags: tuple[str, ...]
```

## 10.3 采样时机

至少在以下状态完成后记录 Account Equity Point：

```text
Account 创建
每次 Market Valuation 完成后
每次 Committed Execution 完成后
Settlement 状态变化后
Margin 状态变化后
Fee Adjustment 后
External Cash Flow 后
回测结束 Seal 前
```

同一个时间戳可能存在多次变化，因此必须使用显式 Sequence，不得只按时间戳去重。

## 10.4 收益率

无外部现金流时：

```text
return_since_start
= (final_equity - initial_equity) / initial_equity
```

有外部现金流而尚未实现 TWR/MWR 时：

```text
return_since_start = None
quality_flags += EXTERNAL_CASH_FLOW_REQUIRES_TWR
```

不得继续给出错误简单收益率。

## 10.5 最大回撤

必须基于 Account Equity Timeline：

```text
high_water_mark[t]
= max(equity[0:t])

drawdown[t]
= (equity[t] - high_water_mark[t]) / high_water_mark[t]

maximum_drawdown
= min(drawdown[t])
```

不得使用任意 Cluster Ledger 的回撤。

---

# 十一、Cluster Equity Timeline

如果当前 Strategy Ledger 已内部维护高水位和最大回撤，可以继续作为 Cluster Performance 权威。

但必须确保：

* 每次 Cluster 相关估值都会更新对应 Ledger；
* 不同 Cluster 的估值不会写错 Ledger；
* Cluster Ledger 的 `valuation_count` 可审计；
* Cluster Performance 使用对应 Ledger；
* 不使用最终 Snapshot 反推中途最大回撤。

如果当前 Ledger 仅保存当前状态，没有足够的时间线证据，应新增不可变的：

```text
OnlyStrategyLedgerEquityPoint
```

或正式 Ledger Valuation Journal。

不要为了减少改动，让 Runtime 使用 Ledger Timeline、Cluster 使用最终 Snapshot 的混合模型。

---

# 十二、Account 与 Cluster Ledger 对账

本任务必须新增 Runtime 级正式对账服务，例如：

```text
OnlyRuntimeLedgerReconciliationService
```

## 12.1 初始资本不变量

```text
sum(cluster.initial_capital)
= account.initial_cash
```

## 12.2 最终状态不变量

固定资本、单 Account、单 Currency 模型下：

```text
sum(cluster.cash_balance)
= account.cash_balance

sum(cluster.position_market_value)
= account.position_market_value

sum(cluster.realized_pnl)
= account.realized_pnl

sum(cluster.unrealized_pnl)
= account.unrealized_pnl

sum(cluster.fees)
= account.fees

sum(cluster.equity)
= account.equity
```

## 12.3 中途估值不变量

优先在每个 Account Equity Point 或正式 Valuation Barrier 后执行对账。

如果当前阶段只能完成最终对账，必须：

* 将中途对账列为明确后续问题；
* 不得声称实时 Multi-Cluster Reconciliation 已完成。

## 12.4 不一致处理

不一致时：

* 生成结构化差异结果；
* 明确字段；
* 明确 Account 值；
* 明确 Ledger 汇总值；
* 明确 Difference；
* 明确涉及的 Cluster；
* Backtest 不得静默成功；
* 不得将差异归给第一个 Cluster；
* 不得自动修改 Ledger 或 Account 以强行对齐。

建议模型：

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimeLedgerReconciliationResult:
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    status: OnlyRuntimeLedgerReconciliationStatus
    differences: tuple[OnlyRuntimeLedgerDifference, ...]
    ts_event: OnlyTimestamp
```

---

# 十三、System Ledger 边界

当前阶段禁止出现无法归属 Cluster 的 Account 级金额。

例如：

* Account-only Fee；
* 手工账户调整；
* 融资成本；
* Account Interest；
* Broker Maintenance Fee；
* FX 差额。

如果当前实现已有这些路径，必须选择：

1. 在本任务范围内明确归属对应 Cluster；
2. 或在固定资本 Multi-Cluster 模式下拒绝执行；
3. 或正式设计 System Ledger。

不要临时将这些金额归属到：

```text
ledgers[0]
第一个 Cluster
默认 Cluster
```

本任务默认不引入 System Ledger，除非当前源码已有无法删除的账户级事实需要正式承载。

---

# 十四、Result Schema 重构

本任务不考虑历史兼容。

应直接升级 Result Schema。

推荐 Backtest Result 结构：

```text
OnlyBacktestResult
├── run
├── data
├── execution
├── runtime_performance
├── cluster_results[]
│   └── cluster_performance
├── final_account
├── final_ledgers[]
├── account_equity_timeline[]
├── cluster_equity_timelines[]
├── reconciliation
├── facts
├── diagnostics
└── fingerprints
```

删除旧的模糊字段或模型：

```text
performance
```

如果其含义不明确。

使用：

```text
runtime_performance
```

明确它属于共享 Account。

不得保留旧字段 Alias。

---

# 十五、Analytics 重构

## 15.1 Runtime Analytics

Runtime 级 Analytics 必须读取：

```text
Account Equity Timeline
Runtime Performance Summary
Committed Execution
```

计算：

* Runtime Return；
* Runtime Maximum Drawdown；
* Runtime Exposure；
* Runtime Trade Statistics；
* Runtime Fees。

## 15.2 Cluster Analytics

Cluster 级 Analytics 必须按：

```text
cluster_id
```

过滤 Committed Execution，并结合对应 Strategy Ledger Timeline 计算：

* Cluster Return；
* Cluster Drawdown；
* Cluster Trade Statistics；
* Cluster Fees；
* Cluster Exposure；
* Cluster Attribution。

禁止 Runtime Analytics 默认使用第一个 Cluster。

---

# 十六、Artifact 与 Report

必须同时展示：

## Runtime 组合绩效

```text
Account
Initial Equity
Final Equity
Net PnL
Fees
Return
Maximum Drawdown
High Water Mark
Valuation Count
```

## 每个 Cluster 绩效

```text
Cluster ID
Ledger ID
Allocated Capital
Final Equity
PnL
Fees
Return
Maximum Drawdown
Trade Count
```

## 对账

```text
Account Equity
Sum Cluster Ledger Equity
Difference
Status
```

不能只输出 Cluster 结果，也不能只输出 Account 最终值。

JSON、Parquet、Markdown 和 Console 输出都应升级。

如果 Golden Fingerprint 改变，应更新并说明：

```text
Result authority and schema changed from first-ledger performance to Account portfolio performance.
```

---

# 十七、删除历史接口

完成迁移后，全仓删除：

```text
ledgers[0]
list_ledgers()[0]
strategy_initial_capital
旧 Cluster 资本松散字段
旧 Backtest Performance Summary
旧 Cluster Result 无绩效结构
旧 Runtime Performance 从 Ledger 获取的逻辑
旧 Capital Default/Fallback
旧 by_cluster 歧义接口
旧 Result Schema 兼容层
```

禁止增加：

* Deprecated Alias；
* Compatibility Wrapper；
* 新旧 Schema 双写；
* 旧配置自动转换；
* 测试专用生产分支；
* 示例专用回退；
* `hasattr()`；
* `getattr()`；
* 具体 Cluster ID 特判；
* “第一个 Ledger”语义的任何变体。

---

# 十八、测试重构

不要只修改旧断言，必须围绕新的业务不变量重新设计测试。

## 18.1 Ledger Locator 测试

覆盖：

```text
完整 Scope 正确定位
不存在 Scope 明确失败
重复 Scope 创建失败
Runtime 不一致失败
Account 不一致失败
Cluster 不一致失败
Currency 不一致失败
注册顺序不影响定位
排序顺序不影响定位
```

## 18.2 资本配置测试

覆盖：

```text
单 Cluster 未配置资本：默认等于 Account Initial Cash
单 Cluster 显式资本等于 Account：通过
单 Cluster 资本不等于 Account：拒绝

多 Cluster 均显式且总和正确：通过
多 Cluster 任一未配置：拒绝
多 Cluster 总和小于 Account：拒绝
多 Cluster 总和大于 Account：拒绝
多 Cluster Currency 不一致：拒绝
非 FIXED_CAPITAL：拒绝
负资本：拒绝
零资本：根据正式设计明确允许或拒绝
```

## 18.3 Cluster 隔离测试

两个 Cluster 分别交易：

```text
Cluster A Trade
只影响 Ledger A

Cluster B Trade
只影响 Ledger B
```

验证：

* Cash；
* Position Allocation；
* Fee；
* PnL；
* Trade Count；
* Equity。

改变 Cluster 注册顺序，结果必须一致。

## 18.4 一赚一亏场景

设计：

```text
Account Initial Cash = 1000

Cluster A Capital = 400
Cluster B Capital = 600

Cluster A PnL = +40
Cluster B PnL = -10
```

必须验证：

```text
Cluster A Final Equity = 440
Cluster B Final Equity = 590
Account Final Equity = 1030

Runtime PnL = +30
```

Runtime Return 必须基于：

```text
1030 / 1000
```

不能等于 Cluster A 或 Cluster B 的 Return。

## 18.5 回撤路径测试

构造两个 Cluster 不同权益路径：

```text
时间 1：
Cluster A 大幅盈利
Cluster B 小幅亏损

时间 2：
Cluster A 回撤
Cluster B 上涨
```

验证：

```text
Runtime Maximum Drawdown
来自 Account 聚合权益路径
```

并明确证明它不等于任一 Cluster Maximum Drawdown。

## 18.6 费用测试

两个 Cluster 分别发生不同 Fee：

```text
Account Fee
= Ledger A Fee + Ledger B Fee
```

费用不能进入错误 Cluster。

## 18.7 Position 和 Valuation 测试

两个 Cluster 可以交易同一 Instrument。

必须验证：

```text
Account Position
= Runtime 聚合 Position

Cluster A Allocation
只进入 Ledger A Valuation

Cluster B Allocation
只进入 Ledger B Valuation
```

不能按 Instrument 将两个 Cluster 的估值混在一个 Ledger。

## 18.8 对账失败测试

分别注入：

```text
漏记 Ledger Fee
漏记 Account Fee
错误 Cluster Attribution
错误 Currency
漏更新某个 Ledger Valuation
Account-only Cash Flow
```

验证：

* 产生结构化差异；
* Runtime 不静默成功；
* 不修改第一个 Ledger 强制平账。

## 18.9 Result 测试

验证：

```text
Runtime Performance 只来自 Account Performance Projector
Cluster Performance 只来自对应 Strategy Ledger
Runtime Result 不读取任何 ledgers[0]
Cluster Result 不依赖列表顺序
```

## 18.10 静态架构门禁

增加 AST 或等价静态检查，禁止生产代码中出现：

```text
list_ledgers()[0]
ledgers[0]
```

同时检查：

```text
RunPlan 不得从 Strategy Ledger 构造 Runtime Performance
ExecutionProcessor 不得自行拼接 Ledger Key
Result Collector 不得按列表顺序配对 Cluster 和 Ledger
```

字符串搜索可以作为辅助，但不要作为唯一测试方法。

---

# 十九、Scenario 产品纵切面

至少新增正式 Multi-Cluster Scenario：

```text
Config
→ Engine
→ 一个 Runtime
→ 一个共享 Account
→ 两个 Cluster
→ 两个固定资本 Ledger
→ 两个策略产生不同交易
→ ExecutionProcessor
→ Committed Execution
→ Account Equity Timeline
→ Cluster Performance
→ Runtime Performance
→ Reconciliation
→ Artifact
```

场景至少覆盖：

```text
两个 Cluster 都盈利
一个盈利一个亏损
两个 Cluster 交易同一 Instrument
两个 Cluster 不同 Fee
不同注册顺序
不同 Cluster ID 排序
重复运行 Fingerprint 一致
```

---

# 二十、实施顺序

必须按以下顺序实施。

## Phase 1：审计和领域决策

输出当前：

* Ledger 定位路径；
* 资本创建路径；
* Account 与 Ledger 权威；
* Result 权威；
* Analytics 权威；
* 测试依赖。

确认本任务正式采用：

```text
FIXED_CAPITAL
单 Account
单 Base Currency
多 Cluster
```

## Phase 2：重构配置和资本校验

实现新 Capital Config。

删除旧 Runtime Strategy Capital 默认字段。

在 Runtime Assembly 阶段完成总和和 Currency 校验。

## Phase 3：实现 Ledger Locator

建立完整 Scope Index 和 Locator API。

迁移所有生产调用方。

## Phase 4：修复 Execution 和 Reservation

删除所有隐式 Ledger 选择。

确保 Trade、Order、Fee、Valuation 使用对应 Ledger。

## Phase 5：实现 Cluster Performance

升级 Cluster Result，并从对应 Ledger 构建绩效。

## Phase 6：实现 Account Performance Projector

建立 Account Equity Timeline、Return、High Water Mark 和 Maximum Drawdown。

## Phase 7：实现 Runtime Performance

Runtime Performance 完全切换到 Account 权威。

## Phase 8：实现跨账本 Reconciliation

增加资本、现金、持仓价值、PnL、Fee 和 Equity 对账。

## Phase 9：升级 Result、Analytics、Artifact 和 Report

直接迁移新 Schema，不保留旧字段。

## Phase 10：重写测试、Scenario 和示例

所有旧调用方切换到正式路径。

## Phase 11：删除兼容面

全仓搜索，确认旧接口和隐式假设完全删除。

## Phase 12：完整门禁

执行所有适用 CI 等价命令。

---

# 二十一、验收标准

只有全部满足以下条件，本任务才算完成。

## 架构

* 生产代码中不存在 `ledgers[0]`；
* 生产代码中不存在 `list_ledgers()[0]`；
* Ledger 通过完整 Scope 精确定位；
* Cluster Result 精确绑定对应 Ledger；
* Runtime Performance 只来自 Account；
* Cluster Performance 只来自 Strategy Ledger；
* 不存在新旧资本模型双轨；
* 不存在旧 Result Schema 兼容层。

## 资本

* 多 Cluster 必须显式 FIXED_CAPITAL；
* Cluster Capital 总和严格等于 Account Initial Cash；
* Currency 全部一致；
* 不再重复复制 Account Initial Cash。

## 正确性

* Cluster A Trade 不影响 Ledger B；
* Cluster B Trade 不影响 Ledger A；
* Runtime PnL 等于所有 Cluster PnL 汇总；
* Runtime Fee 等于所有 Cluster Fee 汇总；
* Runtime Equity 等于所有 Cluster Equity 汇总；
* Runtime Return 基于 Account；
* Runtime Maximum Drawdown 基于 Account Equity Timeline；
* Cluster Return/Drawdown 基于对应 Ledger；
* 注册顺序和列表排序不影响结果。

## Result

* Runtime 与 Cluster 绩效是不同结构；
* Artifact 明确展示两种绩效；
* Reconciliation 结果可审计；
* JSON/Parquet/Markdown/Console 全部迁移；
* 重复运行 Fingerprint 一致。

## 工程门禁

至少执行并记录：

```text
ruff check .
ruff format --check .

mypy Core
mypy Virtual Broker Plugin
mypy Tushare Plugin
mypy MiniQMT Plugin

Core tests
Virtual Broker tests
Tushare offline tests
MiniQMT offline tests
Integration tests
Scenario tests
Conformance tests
Integration demo tests

Build wheel/sdist
Twine metadata check
Core-only clean install
Full workspace clean install
Entry Point smoke
```

无法执行的外部网络、真实 MiniQMT 或平台测试必须明确说明，禁止伪造通过结果。

---

# 二十二、禁止事项

禁止：

1. 只把 `ledgers[0]` 改成 `next()`。
2. 继续通过列表顺序匹配 Cluster 和 Ledger。
3. 使用第一个 Ledger 的 Currency。
4. 使用第一个 Ledger 的 Return 或 Drawdown。
5. 平均或求和 Cluster Return。
6. 从 Cluster Drawdown 推导 Runtime Drawdown。
7. 给每个 Cluster 默认完整 Account 资金。
8. 自动平均分配多 Cluster 资金。
9. 实现不完整的伪共享资金池。
10. 为旧配置保留 Fallback。
11. 为旧测试保留 Alias。
12. 为旧示例保留 Wrapper。
13. 新旧 Result Schema 双写。
14. 不一致时修改第一个 Ledger 强制平账。
15. 将 Account-only 金额归给默认 Cluster。
16. 只修改测试，不修生产权威边界。
17. 为保持旧 Fingerprint 保留错误绩效语义。
18. 声称未执行的测试已通过。

---

# 二十三、最终交付报告

任务完成后输出结构化报告。

## 1. 修改前问题

列出：

* 所有 `ledgers[0]`；
* 所有列表顺序依赖；
* 资本重复分配；
* Runtime Performance 权威混乱；
* Account Timeline 缺失。

## 2. 资本模型

说明：

```text
为什么正式选择 FIXED_CAPITAL
单 Cluster 默认规则
多 Cluster 显式规则
为什么不实现 SHARED_POOL
```

## 3. Ledger 定位

说明完整 Scope、Locator、Index 和所有调用方迁移。

## 4. 绩效权威

说明：

```text
Cluster Performance → Strategy Ledger
Runtime Performance → Shared Account
Reconciliation → 两者一致性
```

## 5. Result Schema

列出新增、删除和重命名字段。

明确说明没有兼容层。

## 6. 对账不变量

列出所有正式不变量和失败处理。

## 7. 测试结果

提供真实命令和真实结果数量。

## 8. 剩余问题

明确区分本任务未实现的：

```text
SHARED_POOL
多 Account
多 Currency
FX
System Ledger
动态资本再分配
TWR/MWR
Paper Runtime
Live Runtime
持久恢复
Futures Daily MTM
```

不得将这些能力描述为已完成。

---

# 最终目标

重构完成后，系统必须满足：

```text
交易归属：
Trade Scope
→ Ledger Locator
→ 唯一 Strategy Ledger

Cluster 绩效：
Cluster
→ 对应 Ledger Equity Timeline
→ Cluster Performance

Runtime 绩效：
Shared Account
→ Account Equity Timeline
→ Runtime Portfolio Performance

一致性：
sum(Cluster Ledgers)
↔ Shared Account
```

优先保证会计权威、资本语义、绩效路径和结果可审计性。不要为了减少改动量、维持旧测试或保持旧示例而保留任何隐式单 Ledger 假设。
