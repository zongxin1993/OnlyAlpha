# OnlyAlpha：将 Applied Trade Journal 重构为 Committed Execution Journal

## 一、任务背景

请认真阅读当前 OnlyAlpha 工程，以当前 `master` 源码、测试、ADR 和架构文档为事实基础，完成一次从第一性原则出发的成交事实模型重构。

当前 Virtual Broker 已从 Core 中剥离为独立插件。Broker 只负责产生标准化的外部 Broker Update，Runtime 通过 `OnlyExecutionProcessor` 将 Broker Update 应用到本地状态。

当前正式链路大致为：

```text
Broker Gateway / Broker Plugin
→ OnlyBrokerTradeUpdate
→ Broker Inbound Queue
→ OnlyExecutionProcessor
→ Order
→ Position
→ Allocation
→ Settlement
→ Margin
→ Fee
→ Account
→ Strategy Ledger
→ Invariant
→ Event Commit
→ OnlyAppliedTradeJournal
→ Result Collector
→ Analytics / Artifact / Report
```

现有 `OnlyAppliedTradeJournal` 主要保存原始 Broker Trade Update 中的 Fill 信息。它只能表达“某个 Broker Trade Update 已被处理”，但不能完整表达：

> Runtime 最终承认并成功提交了怎样的一笔本地成交事实。

这导致 Result Collector 无法仅通过 Journal 得到完整的本地成交语义，目前可能需要重新查询 Manager、Order 或其他状态，或者把以下字段错误地写为零或缺失：

```text
authoritative fee
commission
slippage
contract multiplier
notional
position side
position effect
position mode
realized PnL delta
settlement instruction
margin instruction
market rule identity
cluster / strategy attribution
```

本任务要从根本上重构这一边界。

---

# 二、核心目标

废弃当前语义不足的：

```text
OnlyAppliedTradeFact
OnlyAppliedTradeJournal
```

设计并实现一套完整、不可变、Runtime-owned 的：

```text
OnlyCommittedExecutionFact
OnlyCommittedExecutionJournal
```

名称可以根据现有工程命名体系适当调整，但语义必须明确：

> Committed Execution Fact 不是 Broker Fill 的副本，而是 Runtime 完整交易事务成功后形成的本地权威成交事实。

该事实必须成为以下组件的唯一成交数据来源：

```text
Backtest Result
Result Collector
Analytics
Artifact
Report
Scenario Assertion
Conformance Evidence
未来 Paper / Live Runtime 本地成交历史
```

这些组件不得再通过 Broker `query_trades()` 重建 Runtime 本地成交历史，也不得为了补充成交字段重新拼接多个可变 Manager 的最终状态。

---

# 三、第一性原则

## 3.1 外部输入不等于本地事实

必须明确区分：

```text
OnlyBrokerTradeUpdate
```

与：

```text
OnlyCommittedExecutionFact
```

`OnlyBrokerTradeUpdate` 是外部系统输入，可能存在：

* 重复；
* 乱序；
* 未知订单；
* Scope 不一致；
* Broker Report 费用缺失；
* 本地事务部分失败；
* Invariant 失败；
* 需要 Reconciliation；
* Broker Projection 与 Runtime 状态不一致。

因此，收到 Broker Trade Update 不代表产生了本地成交事实。

只有当本地交易事务满足以下条件时，才能写入 Committed Execution Journal：

```text
1. Broker Update 校验通过
2. 去重和顺序检查通过
3. Position Scope 成功解析
4. Market Trade Instruction 成功解析
5. Authoritative Fee 成功解析
6. Order 状态成功更新
7. Position 成功更新
8. Allocation 成功更新
9. Settlement 成功注册或应用
10. Margin 成功更新
11. FeeManager 成功更新
12. Account 成功更新
13. Strategy Ledger 成功更新
14. Reservation 和 Risk 状态成功协调
15. Runtime Invariant 检查通过
16. 本地事实 Event 成功提交
```

只有完成上述事务后，才允许追加一条 Committed Execution Fact。

以下情况不得写入成功 Journal：

```text
DUPLICATE
IGNORED
STALE
REJECTED
FAILED
RECONCILIATION_REQUIRED
PARTIAL_MUTATION
INVARIANT_VIOLATION
```

---

## 3.2 Journal 保存的是已提交结果，不是处理过程

Committed Execution Fact 应表达：

```text
Runtime 最终提交了什么
```

而不是：

```text
ExecutionProcessor 中间调用了哪些 Manager
```

不要把 Manager Mutation Result、Service 实例、可变 Entity、Callback、Resolver 或 Runtime 私有对象直接塞入 Fact。

Fact 必须是：

* 不可变；
* 可序列化；
* 可稳定排序；
* 可稳定哈希；
* 可跨进程持久化；
* 不依赖 Runtime 当前可变状态；
* 不依赖 Broker 插件具体类型；
* 不依赖 Virtual Broker；
* 不依赖 Result Collector 二次解释。

---

## 3.3 Journal 是 Runtime 本地成交权威

明确以下权威划分：

```text
Broker Trade Update
    外部报告事实

Committed Execution Fact
    Runtime 本地已提交成交事实

Broker query_trades()
    外部 Broker Projection，仅用于查询和 Reconciliation

Position / Account / Ledger Manager
    当前可变状态

Committed Execution Journal
    不可变的本地成交历史
```

Result、Analytics 和 Artifact 必须优先读取 Committed Execution Journal。

Broker Query 不得成为 Backtest Result 或 Runtime 本地成交历史的来源。

---

## 3.4 Journal 必须自包含，但不能成为状态快照垃圾桶

Committed Execution Fact 必须携带足够信息，使 Result Collector 不需要重新查询其他 Manager 来解释这笔成交。

但是不能简单地把以下所有对象完整复制进去：

```text
完整 Account Snapshot
完整 Position Snapshot
完整 Ledger Snapshot
完整 Market Rule Engine
完整 Mutation Bundle
完整 Runtime Snapshot
```

Fact 应只保存这笔成交本身的稳定业务事实和必要的作用域、经济含义、规则身份及事务结果增量。

---

# 四、目标领域模型

请先审计当前 Domain、Broker、Execution、Fee、Market Rule、Position、Account、Ledger、Settlement、Margin 和 Result 模型，再确定最终字段。

下面是建议的最低语义集合，不要求机械照抄字段名，但不得缺少其业务含义。

## 4.1 身份与作用域

```text
execution_id
trade_id
venue_trade_id
order_id
client_order_id
request_id
broker_update_id
runtime_id
gateway_id
account_id
cluster_id
strategy_id
instrument_id
venue_id
```

要求：

* `execution_id` 是 Runtime 本地已提交成交事实的稳定身份；
* 不要默认直接等同于 Broker Trade ID；
* 必须有稳定的幂等身份；
* 同一个 Broker Trade Update 重放时不得产生第二条 Committed Fact；
* Cluster 和 Strategy 归属必须在提交时固化。

## 4.2 因果和顺序

```text
source_sequence
processing_sequence
execution_sequence
correlation_id
causation_id
external_event_id
ts_event
ts_init
ts_committed
trading_day
```

要求区分：

* Broker 事件时间；
* Broker 初始化或接收时间；
* Runtime 本地提交时间；
* Broker Source Sequence；
* Runtime Processing Sequence；
* Journal 内稳定 Execution Sequence。

不要用列表下标隐式充当业务顺序。

## 4.3 订单和执行语义

```text
order_side
order_type
offset
position_side
position_effect
position_mode
liquidity_side
fill_quantity
fill_price
cumulative_filled_quantity
remaining_quantity
order_status_after
```

必须正确表示：

```text
BUY OPEN LONG
SELL CLOSE LONG
SELL OPEN SHORT
BUY CLOSE SHORT
CLOSE
CLOSE_TODAY
CLOSE_YESTERDAY
NETTING
HEDGING
```

不得重新引入 `BUY = LONG OPEN`、`SELL = LONG CLOSE` 的隐式假设。

## 4.4 经济事实

```text
currency
price
quantity
contract_multiplier
gross_notional
settled_notional
authoritative_fee_total
market_fee
broker_fee
tax
commission
other_fee
reported_broker_fee
slippage
realized_pnl_delta
cash_delta
```

要求：

```text
gross_notional
= price × quantity × contract_multiplier
```

金额必须遵守 Currency Precision 和现有 Decimal 规则。

`authoritative_fee_total` 必须来自 Runtime 的统一 Fee Resolver，不得重新使用 Virtual Broker 内部费用或默认零值。

Broker Report Fee 与 Runtime Authoritative Fee 必须分开表达：

```text
reported_broker_fee
authoritative_fee
```

如果当前 Broker 没有上报费用，使用明确的 `None` 或现有 Fee Reporting Mode 语义，不要用零表示未知。

## 4.5 费用身份

Committed Execution Fact 至少应保存足够的费用身份，使后续可以审计：

```text
fee_instruction_id
fee_authority
fee_status
market_fee_schedule_id
market_fee_schedule_version
broker_fee_schedule_id
broker_fee_schedule_version
fee_breakdown
```

优先复用现有不可变 Fee Domain，而不是在 Execution 包中再设计一套重复 Fee 类型。

## 4.6 市场规则身份

至少保存能够证明本次成交使用了哪套规则的信息：

```text
market_profile_id
market_profile_version
compiled_rule_fingerprint
reference_fingerprint
trade_instruction_id
```

不要把整个 `OnlyMarketRuleEngine` 或完整 Profile 对象存入 Fact。

## 4.7 Settlement 和 Margin

根据当前交易指令保存必要的稳定引用或已提交结果：

```text
settlement_instruction_id
settlement_status
asset_available_on
cash_available_on
legal_settlement_date

margin_instruction_id
margin_action
margin_currency
margin_amount
reserved_margin_delta
occupied_margin_delta
released_margin_delta
maintenance_margin_after
```

具体字段应以当前 Settlement 和 Margin Domain 为基础。

如果某类交易没有 Margin，则使用明确可选值，不要伪造零金额记录。

## 4.8 本地状态变更摘要

需要保存能够支持审计和 Result 的本地提交增量，例如：

```text
position_quantity_delta
position_realized_pnl_delta
allocation_quantity_delta
account_cash_delta
account_fee_delta
account_realized_pnl_delta
ledger_cash_delta
ledger_fee_delta
ledger_realized_pnl_delta
```

不要保存整个 Manager Snapshot。

这些增量必须来自本次成功事务的实际结果，不能由 Collector 事后根据最终状态反推。

---

# 五、推荐结构边界

建议形成类似结构：

```text
src/onlyalpha/execution/
├── committed.py
├── journal.py
├── processor.py
└── ...
```

可以采用：

```python
@dataclass(frozen=True, slots=True)
class OnlyCommittedExecutionFact:
    ...
```

以及：

```python
class OnlyCommittedExecutionJournal:
    def append(self, fact: OnlyCommittedExecutionFact) -> None:
        ...

    def records(self) -> tuple[OnlyCommittedExecutionFact, ...]:
        ...
```

但请根据当前包结构选择最清晰的位置。

## 5.1 Fact Builder

不要让 `OnlyExecutionProcessor.process()` 方法直接内联构造几十个字段。

应设计明确的内部构造边界，例如：

```text
OnlyCommittedExecutionBuilder
OnlyExecutionCommitContext
OnlyExecutionCommitAssembler
```

职责是从已经成功应用的事务上下文中生成不可变 Fact。

Builder 可以读取本次事务已经产生的局部值，例如：

```text
Broker Trade Update
Order Snapshot
Position Scope
Position Trade
Fee Instruction
Trade Application Instruction
Position Mutation Result
Account Mutation Result
Ledger Mutation Result
Settlement Record
Margin Record
```

Builder 不应：

* 重新执行 Fee Resolver；
* 重新执行 Market Rule；
* 重新修改 Manager；
* 查询 Broker；
* 重新推导已经完成的交易逻辑。

---

## 5.2 Commit 顺序

调整 `OnlyExecutionProcessor` 的成功路径，使语义顺序明确：

```text
应用所有本地状态
→ 检查 Invariant
→ 提交 Event Facts
→ 构造 Committed Execution Fact
→ 追加 Committed Execution Journal
→ 返回 APPLIED Result
```

需要认真决定：

```text
Event Commit
Committed Journal Append
```

之间的原子顺序。

最低要求：

* Event Commit 失败，不得产生 Journal Fact；
* Fact 构造失败，不得把交易报告为成功；
* Journal Append 失败，不得静默继续；
* 不得出现 Result 表示 APPLIED，但 Journal 没有记录；
* 不得出现 Journal 有记录，但本地状态事务失败。

当前系统不是数据库事务，可以保留显式 Reconciliation 策略，但必须使失败状态明确、可审计，不能吞掉异常。

---

# 六、删除旧接口，不做历史兼容

本任务不考虑历史兼容。

必须遵守以下要求：

## 6.1 直接删除旧模型

完成迁移后删除：

```text
OnlyAppliedTradeFact
OnlyAppliedTradeJournal
```

以及对应旧导出。

不要增加：

```text
OnlyAppliedTradeFact = OnlyCommittedExecutionFact
OnlyAppliedTradeJournal = OnlyCommittedExecutionJournal
```

不要保留：

* Deprecated Alias；
* Compatibility Wrapper；
* Re-export；
* 旧模块转发；
* 条件 Import；
* Fallback；
* 双 Journal；
* 双写逻辑。

## 6.2 重写所有调用方

请搜索并迁移所有生产代码、测试、示例和文档中的旧引用，包括但不限于：

```text
ExecutionProcessor
RuntimeServices
BacktestRuntime
BacktestRunPlan
Result Collector
Backtest Result
Analytics
Artifact Writer
Scenario
Conformance
Integration Tests
Unit Tests
Examples
README
Architecture Docs
Execution Docs
Result Docs
ADR
```

所有调用方必须切换到新模型。

## 6.3 不得为了旧测试保留错误接口

如果现有测试依赖旧模型，直接重写测试。

如果现有示例依赖旧模型，直接重写示例。

如果现有 Golden Fingerprint 因正确语义变化而改变，重新生成并更新 Golden 数据，同时解释变化原因。

不得为了让旧测试继续通过而：

* 保留旧类；
* 保留旧字段；
* 保留零费用；
* 保留错误 Turnover；
* 保留 Broker Query 路径；
* 添加兼容判断；
* 添加 `hasattr()`；
* 添加具体 Broker 类型分支；
* 在 Collector 中继续修补旧 Fact。

测试和示例必须服从正确架构，而不是生产架构服从历史测试。

---

# 七、Result Collector 重构要求

`OnlyBacktestResultCollector` 必须直接从 Committed Execution Journal 构造 Execution Result。

不得再：

* 从原始 Fill 猜测本地费用；
* 将费用固定为零；
* 将 Slippage 固定为零；
* 忽略 Contract Multiplier；
* 查询 Virtual Broker Trade Store；
* 查询 Broker `query_trades()`；
* 根据最终 Account Fee 反推单笔费用；
* 根据最终 Position 反推单笔成交含义。

Execution Result 至少应正确投影：

```text
execution_id
order_id
request_id
runtime_id
cluster_id
strategy_id
account_id
instrument_id
side
offset
position_side
position_effect
quantity
price
contract_multiplier
turnover
commission
fees
slippage
realized_pnl_delta
ts_event
trading_day
venue
market_profile_id
market_profile_version
```

如现有 Result Schema 缺少必要字段，应直接升级 Schema。

不考虑旧 Schema 兼容，不保留重复旧字段。

如果 JSON/Parquet Schema Version 需要升级，应正式升级版本，并同步更新：

* Serializer；
* Parquet Schema；
* Artifact Manifest；
* Reader；
* Tests；
* Docs；
* Golden Files。

---

# 八、Analytics 与 Artifact

检查当前 Analytics 是否仍然从不完整 Execution Record 推导：

```text
Turnover
Fee
Commission
Slippage
Trade PnL
Win/Loss
Exposure
```

迁移后必须使用 Committed Execution Fact 或其标准 Result Projection。

Artifact 中的成交记录必须能够证明：

```text
Broker 报告了什么
Runtime 使用了什么规则
Runtime 计算了什么费用
Runtime 实际提交了什么状态变化
```

不要在 Artifact 阶段重新执行交易逻辑。

---

# 九、测试要求

必须重新设计测试，不要只修改现有断言。

## 9.1 Journal 单元测试

至少覆盖：

```text
成功追加
稳定顺序
重复 Trade 不重复追加
重复 Update 不重复追加
不可变性
序列化
稳定哈希
不同 Runtime Scope 隔离
不同 Gateway Scope 隔离
```

需要明确幂等键是：

```text
execution_id
trade_id
update_id
或组合身份
```

并说明原因。

## 9.2 ExecutionProcessor 提交测试

至少覆盖：

```text
APPLIED Trade 形成一条 Committed Fact
DUPLICATE 不形成 Fact
OUT_OF_ORDER 不形成 Fact
UNKNOWN_ORDER 不形成 Fact
INVARIANT_FAILURE 不形成成功 Fact
DEPENDENCY_FAILURE 不形成成功 Fact
RECONCILIATION_REQUIRED 不形成成功 Fact
Event Commit 失败不形成 Fact
Journal Append 失败不能被报告为成功
```

## 9.3 费用一致性测试

必须证明：

```text
CommittedExecution.authoritative_fee
= Position Trade Fee
= Account Fee Delta
= Strategy Ledger Fee Delta
= FeeManager Trade Records Total
= Result Execution Fee
```

覆盖：

```text
market fee only
broker model fee
broker reported fee
market + broker combined fee
fee NONE
fractional quantity
currency precision
partial fill
minimum commission
```

如果最低佣金跨部分成交累计当前尚未实现，应明确记录为剩余缺口，不得伪造通过。

## 9.4 Notional 与 Multiplier 测试

至少覆盖：

```text
Equity multiplier = 1
Futures multiplier > 1
Fractional quantity
不同价格和数量精度
```

验证：

```text
notional = price × quantity × multiplier
```

## 9.5 Position Scope 测试

至少覆盖：

```text
BUY OPEN LONG
SELL CLOSE LONG
SELL OPEN SHORT
BUY CLOSE SHORT
CLOSE_TODAY
CLOSE_YESTERDAY
NETTING
HEDGING
```

Committed Fact 中的：

```text
position_side
position_effect
position_mode
```

必须正确。

## 9.6 Settlement 与 Margin 测试

覆盖：

```text
T0 Cash
A-share T+1
Futures Margin OCCUPY
Futures Margin RELEASE
无 Margin 交易
跨交易日 Settlement
```

## 9.7 Result Collector 测试

明确禁止：

```text
commission = 0
fees = 0
slippage = 0
```

这种无条件默认。

必须验证：

* Result 中费用来自 Committed Fact；
* Futures Turnover 使用 Multiplier；
* Result 不调用 Broker Query；
* Result 不依赖 Virtual Broker 类型；
* Core-only 测试不导入 Virtual Broker 插件；
* Result 可由手工构造的标准 Broker Adapter 成交产生。

## 9.8 产品纵切面测试

至少运行：

```text
Synthetic DataSource
→ Virtual Broker Plugin
→ Runtime
→ Committed Execution Journal
→ Result
→ Analytics
→ Artifact
```

并覆盖：

```text
Generic T0
CN A-share T+1
Generic Futures LONG
Generic Futures SHORT
Partial Fill
Fee Model
```

重复运行必须保持确定性 Fingerprint。

---

# 十、架构边界测试

增加静态或运行时架构测试，证明：

```text
Core 不导入 Virtual Broker 插件
Committed Execution Fact 不依赖 Virtual Broker 类型
Result Collector 不调用 Broker query_trades()
Result Collector 不导入 Virtual Broker
Committed Journal 属于 Runtime
Broker Plugin 不写 Committed Journal
Broker Plugin 不构造 Committed Execution Fact
OnlyExecutionProcessor 是唯一 Journal Writer
Analytics 和 Artifact 不重新调用 Fee Resolver
```

应避免依赖字符串搜索作为唯一验证手段，但可以作为辅助门禁。

---

# 十一、示例迁移

检查所有示例。

示例中不得：

* 直接实例化旧 Applied Trade Fact；
* 直接写入旧 Journal；
* 直接读取 Broker Trade Store 作为回测结果；
* 依赖 `onlyalpha.broker.virtual`；
* 把费用和滑点写死为零；
* 通过旧兼容入口运行 Backtest。

至少更新一个完整示例，能够打印或验证：

```text
Trade ID
Position Side
Position Effect
Price
Quantity
Multiplier
Notional
Fee Breakdown
Slippage
Realized PnL Delta
Settlement
Margin
Market Profile
```

示例只能使用公开 API。

---

# 十二、文档与 ADR

新增 ADR，建议标题：

```text
Committed Execution Fact as Runtime Local Trade Authority
```

ADR 至少说明：

1. 为什么 Broker Trade Update 不是本地成交事实；
2. 为什么旧 Applied Trade Fact 信息不足；
3. 为什么 Journal 必须属于 Runtime；
4. 为什么 Result 不允许查询 Broker 重建本地交易；
5. Fact 中保存哪些稳定事实；
6. Fact 中明确不保存哪些可变状态；
7. Journal 的写入时机；
8. 幂等语义；
9. Event Commit 与 Journal Append 的失败策略；
10. 对 Backtest、Paper 和 Live 的影响；
11. 为什么不保留旧接口兼容。

同步更新：

```text
README
docs/architecture.md
docs/runtime.md
docs/execution_processor.md
docs/results_framework.md
docs/virtual_broker.md
docs/roadmap.md
AGENTS.md
HANDOFF.md
```

历史 ADR 和历史报告可以保留原文，但必须明确标记为 Historical/Superseded，不能修改历史事实来伪装当前设计一直如此。

---

# 十三、实施顺序

请严格按以下顺序工作。

## 阶段一：修改前审计

先阅读和记录：

* 当前 Applied Trade Fact；
* Journal；
* ExecutionProcessor 成功路径；
* Runtime 装配；
* Result Collector；
* Result Schema；
* Artifact；
* Analytics；
* Scenario；
* Conformance；
* 所有生产代码、测试和示例引用。

输出一份修改前审计报告，明确：

```text
旧模型保存了什么
丢失了什么
哪些组件依赖旧模型
哪些结果字段当前错误或固定为零
哪些组件仍查询 Broker 或 Manager 补数据
```

不得在未完成审计前直接批量改名。

## 阶段二：领域设计

设计：

```text
OnlyCommittedExecutionFact
OnlyCommittedExecutionJournal
幂等身份
稳定排序
序列化模型
Builder / Assembler
```

确认与现有 Fee、Market Rule、Position Scope、Settlement 和 Margin Domain 的复用边界。

## 阶段三：ExecutionProcessor 迁移

先让 ExecutionProcessor 在成功事务末尾生成完整 Fact。

完成失败路径测试后，再删除旧 Journal。

## 阶段四：Result 与 Analytics 迁移

把 Result Collector、Analytics、Artifact 全部切换到新 Fact。

不得在 Collector 中保留旧新双路径。

## 阶段五：测试和示例重写

重写所有依赖旧接口的测试和示例。

## 阶段六：删除兼容面

全仓搜索并删除：

```text
OnlyAppliedTradeFact
OnlyAppliedTradeJournal
applied_trade_journal
onlyalpha.broker.virtual
旧 Result 修补逻辑
Broker query_trades() 的本地结果用途
```

`query_trades()` 可以保留为 Broker 外部查询和 Reconciliation Port，但不得用于构建 Runtime 本地历史。

## 阶段七：全量门禁

执行完整 CI 等价门禁。

---

# 十四、验收门槛

只有全部满足以下条件，任务才算完成。

## 14.1 架构

* Core 中不存在旧 Applied Trade Fact 和 Journal；
* 不存在 Alias、Wrapper 或兼容模块；
* Committed Journal 由 Runtime 独占；
* Broker 插件无法直接写入；
* ExecutionProcessor 是唯一成功 Fact Writer；
* Result 不查询 Broker 重建本地成交；
* Result 不依赖 Virtual Broker；
* Core-only 安装可正常导入。

## 14.2 正确性

* 每个 APPLIED Trade 对应且只对应一条 Committed Fact；
* 非 APPLIED Update 不形成成功 Fact；
* Fee 在 Fact、Account、Ledger、FeeManager 和 Result 中一致；
* Notional 正确使用 Contract Multiplier；
* LONG/SHORT、OPEN/CLOSE 语义正确；
* Settlement 和 Margin 信息可审计；
* Cluster 和 Strategy Attribution 正确；
* Partial Fill 每笔形成独立稳定 Fact；
* 重放不产生重复 Fact。

## 14.3 Result

* Execution Result 不再无条件使用零费用；
* Futures Turnover 正确；
* Slippage 有明确来源；
* Unknown Broker Fee 使用 `None` 或明确状态，不伪装为零；
* JSON/Parquet Schema 与新模型一致；
* Artifact Manifest 和 Fingerprint 已更新；
* 重复运行结果确定。

## 14.4 工程门禁

至少执行并记录：

```text
ruff check .
ruff format --check .
mypy Core
mypy Virtual Broker Plugin
mypy Tushare Plugin
mypy MiniQMT Plugin
Core pytest
Virtual Broker pytest
Tushare offline pytest
MiniQMT offline pytest
Scenario tests
Conformance tests
Integration tests
Integration demo tests
Build wheel/sdist
Twine metadata check
Core-only clean install
Full workspace clean install
Entry Point smoke
```

如果某项受 Token、网络、本地 MiniQMT 环境或平台限制未执行，必须明确说明，不得宣称通过。

---

# 十五、禁止事项

禁止：

* 仅把 `OnlyAppliedTradeFact` 重命名；
* 给旧 Fact 增加几个可选字段后继续使用；
* 新旧 Journal 双写；
* 保留 Deprecated Alias；
* 为旧测试增加兼容分支；
* 为旧示例增加 Adapter；
* 在 Collector 中继续查 Manager 拼装交易；
* 从 Broker Query 生成本地结果；
* 在 Result 中将未知费用、佣金或滑点默认成零；
* 在 Journal 中存 Manager 或 Runtime 可变对象；
* 重新执行 Fee Resolver 或 Market Rule 来生成 Result；
* 在 Core 中导入 Virtual Broker 插件；
* 使用 `hasattr()`、具体类型判断或动态探测选择旧新路径；
* 为了保持旧 Fingerprint 而保留错误字段；
* 为了测试通过降低领域约束；
* 只修改测试，不修复生产边界；
* 未运行全仓搜索就宣称旧接口已删除。

---

# 十六、最终交付

完成后输出一份实施报告，至少包含：

## 1. 修改前问题

说明旧 Applied Trade Journal 为什么不具备本地成交权威语义。

## 2. 新架构

说明：

```text
Broker Update
→ Local Transaction
→ Committed Execution Fact
→ Result / Analytics / Artifact
```

## 3. 领域模型

列出新 Fact 的完整字段及每个字段的权威来源。

## 4. 事务边界

说明 Fact 的准确写入时机，以及失败和 Reconciliation 策略。

## 5. 删除内容

列出删除的旧类、模块、Alias、兼容路径和旧测试。

## 6. 调用方迁移

列出迁移的生产组件、测试、示例和文档。

## 7. 验证结果

列出每项测试、Lint、Format、Mypy、Build、Install 和产品场景的真实结果。

## 8. 剩余问题

明确区分：

```text
本任务已完成的问题
后续 Equity Timeline 问题
Multi-Cluster Aggregate 问题
Futures Daily MTM 问题
Live Fee Reconciliation 问题
Paper / Live Runtime 问题
```

不得把不属于本任务的后续能力伪装成本次已经完成。
