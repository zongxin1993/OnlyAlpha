你现在负责 OnlyAlpha 当前 `master` 最新代码上的专项修复任务：

# OnlyAlpha Unified Fee Migration Recovery

中文名称：

# OnlyAlpha 统一费用迁移回归修复与全量 CI 恢复

本任务的已知背景是：

```text
OnlyAlpha 已经开始从旧的 Broker Fill Fee / Fixed Commission 语义，
迁移到统一的 Fee Model、Fee Resolver、Fee Instruction 和 Fee Ledger。

当前迁移尚未完成，已导致大约 37 项 Core、Integration、
Scenario 或 Conformance 测试失败，并使最新 CI 无法达到绿色状态。
```

本任务必须从费用领域的第一性原则出发，修复正式产品实现。

禁止通过恢复旧接口、增加兼容分支、放宽断言、跳过测试或修改预期结果掩盖真实错误。

最终目标是：

> 建立一个唯一、确定、可审计、可配置、可对账的费用权威链路，并使当前最新代码上的所有 Core、Plugin、Integration、Scenario、Conformance 和 Build 门禁全部通过。

---

# 一、绝对执行原则

## 1. 不为旧接口保留兼容性

本任务不考虑旧版本兼容。

如果以下旧概念与新费用架构重复：

```text
fixed_commission
commission_model
fill.fee
trade.fee 作为 Broker 决定的本地费用
旧 Fee Record
旧 Fee Config
旧 Backtest 专用佣金配置
旧 Virtual Broker 费用实现
旧 Product Assembler
```

必须：

```text
删除旧接口
删除旧字段
删除旧配置
删除旧分支
迁移全部调用方
更新测试
更新示例
更新文档
```

禁止：

```python
if new_fee_enabled:
    ...
else:
    legacy_commission(...)
```

禁止：

```python
try:
    use_new_fee()
except:
    use_old_fee()
```

禁止通过 Deprecated 注解长期保存两套正式语义。

历史 ADR 可以记录旧设计，但生产代码只能有一套正式费用路径。

---

## 2. 不以“测试通过”为唯一设计目标

不能看到一个失败测试，就单独修改一处 Expected Value。

必须先判断失败属于：

```text
生产实现错误
测试仍使用旧语义
配置未进入装配链
费用权威重复
币种或精度错误
费用 Schedule 缺失
错误的测试 Fixture
Scenario 定义过时
Artifact Schema 过时
确定性指纹变化
```

只有确认业务语义后才能修改测试。

测试是对正式语义的证明，不是修复方向的来源。

---

## 3. 唯一费用权威

OnlyAlpha 必须只有一条本地费用权威链：

```text
Market Fee Schedule
+ Broker Fee Schedule
+ Broker Reported Fee
+ Runtime Context
        ↓
OnlyFeeResolver
        ↓
OnlyFeeInstruction
        ↓
OnlyFeeBreakdown
        ↓
ExecutionProcessor
        ↓
Account
Strategy Ledger
Position Trade
Fee Manager
Collector
Result
Artifact
```

禁止以下组件分别计算自己的费用：

```text
Virtual Broker
ExecutionProcessor
Account Manager
Strategy Ledger
Collector
Analytics
Scenario Assertion
```

这些组件只能消费已经解析完成的 Fee Instruction 或 Fee Breakdown。

---

## 4. 区分四类概念

必须明确区分：

### Estimated Fee

下单前用于：

```text
资金检查
现金预留
策略账本预留
风险判断
```

### Provisional Fee

成交时根据当前规则计算的暂定费用。

### Reported Fee

外部 Broker 或交易所实际返回的费用事实。

### Adjusted / Confirmed Fee

对账后应用到 Account、Ledger 和 Result 的最终调整。

这四者不能使用同一个模糊字段表达。

---

# 二、开始前必须重新同步和审计

## 2.1 基准记录

从仓库最新代码开始。

首先执行并记录：

```bash
git status
git branch --show-current
git rev-parse HEAD
git log -5 --oneline
uv --version
python --version
```

要求：

```text
工作区必须干净，或者明确记录已有修改
Python 版本必须符合 pyproject.toml
不得在 Python 3.13 上声称通过 Python 3.12 门禁
```

---

## 2.2 阅读工程约束

至少完整阅读：

```text
AGENTS.md
HANDOFF.md
NEXT.md
README.md
pyproject.toml
uv.lock

docs/architecture.md
docs/runtime.md
docs/order.md
docs/risk.md
docs/virtual_broker.md
docs/execution_processor.md
docs/account.md
docs/position.md
docs/settlement_model.md
docs/margin_model.md
docs/results_framework.md

所有 Fee 相关文档
所有 Fee 相关 ADR
最近 Unified Fee 相关 PR 或审计文档
```

---

## 2.3 搜索全部费用语义

必须执行类似搜索：

```bash
rg -n "fixed_commission|commission_model|OnlyFixedCommissionModel" .
rg -n "\.fee\b|fill\.fee|trade\.fee|reported_fee" src packages tests examples
rg -n "FeeResolver|FeeEngine|FeeInstruction|FeeBreakdown" src packages tests
rg -n "FeeSchedule|broker\.fees|market\.fees" src packages tests examples
rg -n "FeeAdjustment|FeeReconciliation" src packages tests
rg -n "OnlyBacktestRuntimeAssembler|_only_bind_product_runner" .
```

输出完整引用清单。

---

## 2.4 审计所有正式装配入口

必须确认当前是否存在多个 Backtest 装配路径。

重点检查：

```text
OnlyEngine
OnlyRuntimePlanner
OnlyEngineRunAssembler
OnlyBacktestRuntimeFactory
OnlyBacktestRuntime
Scenario Planner
Scenario Runner
Integration Demo
旧 OnlyBacktestRuntimeAssembler
测试专用 Runtime Builder
```

已知旧产品装配形式可能直接：

```text
构造 OnlyVirtualBrokerConfig
注入 OnlyFixedCommissionModel
创建 OnlyBacktestRuntime
绑定私有 Product Runner
```

这种路径如果仍存在，必须删除或迁移到唯一正式：

```text
Config
→ Planner
→ Engine Assembler
→ Runtime Factory
```

不能继续让旧 Product Demo 路径拥有独立费用语义。

---

# 三、首先生成失败基线报告

在修改生产代码前，执行当前完整门禁。

至少包括：

```bash
uv sync --all-groups --all-packages

uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
git diff --check
```

如果 CI 使用拆分命令，还要按照 CI 原样执行：

```text
Core tests
Tushare tests
MiniQMT tests
Integration tests
Scenario tests
Conformance tests
Integration Demo
Build Smoke
```

生成：

```text
docs/reports/unified_fee_migration_failure_baseline.md
```

报告必须列出：

```text
当前 commit SHA
Python / uv 版本
测试总数
失败总数
失败测试完整名称
失败堆栈摘要
失败所属模块
失败类型分类
可能共享的根因
```

当前已知约 37 项回归。

如果最新 HEAD 的失败数量不是 37，必须使用真实数量，并解释差异。

不得为了保持“37”这个数字而忽略新增或消失的失败。

---

# 四、从第一性原则确定费用领域真值

## 4.1 唯一费用输入

一次成交费用只能由以下输入决定：

```text
instrument
venue
market profile
broker
account
side
offset
liquidity role
quantity
price
notional
contract multiplier
trading day
fee schedule effective date
broker reported fee
previous fee state
```

禁止使用：

```text
随机状态
墙钟时间
对象地址
测试运行顺序
全局可变单例
未排序字典
```

---

## 4.2 唯一费用输出

一次费用解析必须生成不可变的：

```text
OnlyFeeInstruction
OnlyFeeBreakdown
```

至少包含：

```text
instruction_id
idempotency_key
authority
status

account_id
broker_id
instrument_id
order_id
trade_id

currency
trading_day
effective_schedule_id
effective_schedule_version
schedule_fingerprint

commission
minimum_commission_adjustment
tax
stamp_duty
transfer_fee
exchange_fee
clearing_fee
broker_fee
maker_fee
taker_fee
close_today_fee
other_fee
total
```

具体字段以当前正式模型为准。

不得重新创建第二套 DTO。

---

## 4.3 费用权威优先级

必须在正式代码和 ADR 中明确优先级。

推荐语义：

```text
1. Broker/Exchange Confirmed Report
2. Broker Reported Provisional Fee
3. Broker Fee Schedule
4. Market Fee Schedule
5. Explicit NONE
```

但实际优先级必须根据当前 `OnlyFeeAuthority`、`OnlyFeeReportingMode` 和正式文档实现。

禁止各调用方自行决定优先级。

所有优先级判断只能存在于：

```text
OnlyFeeResolver
```

---

## 4.4 市场费用与券商费用

必须正交区分：

### Market Fee

例如：

```text
印花税
过户费
交易所费
清算费
平今手续费
Maker/Taker 交易所费
```

来源：

```text
Market Profile / Market Fee Schedule
```

### Broker Fee

例如：

```text
券商佣金
最低佣金
经纪服务费
```

来源：

```text
Broker Fee Schedule
```

Market Profile 不应该硬编码具体券商佣金。

Broker 插件也不应该重复计算印花税或交易所费用。

---

# 五、配置和装配链修复

## 5.1 配置必须真正生效

审计当前：

```yaml
market:
  fees: ...

broker:
  fees: ...
```

对应的 Config Domain。

确保配置经过：

```text
YAML
→ Config Parser
→ Validation
→ Runtime Assembly Plan
→ Runtime Factory
→ Fee Schedule Registry
→ FeeResolver
```

不能只完成 Config Model，却在 Runtime 中写：

```python
broker_schedule = None
broker_mode = NONE
broker_id = "runtime"
```

除非配置明确选择 NONE。

---

## 5.2 Schedule Registry

建立或完善正式 Registry：

```text
Market Fee Schedule Registry
Broker Fee Schedule Registry
```

要求：

```text
按 schedule_id 查找
按 version 查找
按 effective date 解析
禁止重叠有效期
稳定 Fingerprint
不可变
确定性排序
明确缺失错误
```

Unknown Schedule 必须在配置校验或 Runtime Build 阶段失败。

不能等到第一次成交时才因 `None` 随机失败。

---

## 5.3 Runtime Assembly

Runtime Factory 必须把：

```text
resolved market schedule
resolved broker schedule
broker reporting mode
broker identity
```

显式注入 `OnlyFeeResolver`。

禁止：

```text
从 Runtime 私有对象临时反查
动态 getattr
全局注册表
测试 monkeypatch
```

---

# 六、Estimated Fee 与 Reservation 修复

## 6.1 下单估算必须使用同一 Fee Engine

Order Service、Risk、Account Reservation 和 Strategy Ledger Reservation 不得单独计算固定佣金。

正确链：

```text
Order Intent
→ Estimated Fee Request
→ FeeResolver / FeeEngine
→ Estimated Fee Breakdown
→ Required Cash
→ Account Reservation
→ Ledger Reservation
```

---

## 6.2 成交后差额处理

成交费用与下单估算可能不同。

必须正确处理：

```text
estimated < actual
estimated = actual
estimated > actual
部分成交
多次成交
撤单
拒单
最低佣金累计
```

对于多 Fill 最低佣金，必须按订单累计处理：

```text
本次应收
=
当前累计应收
-
此前累计已收
```

不得每个 Fill 独立收取最低佣金。

---

## 6.3 Reservation 不变量

订单终态后必须满足：

```text
FILLED      → 未成交部分 Reservation 释放
CANCELED    → 剩余 Reservation 释放
REJECTED    → 全部 Reservation 释放
EXPIRED     → 全部 Reservation 释放
FAILED      → 全部 Reservation 释放
```

增加或修复测试：

```text
Account cash reservation
Strategy ledger reservation
Risk reservation
Margin reservation
Position reservation
Fee estimate reservation
```

不能因为 Fee 变化导致 Active Reservation 泄漏。

---

# 七、ExecutionProcessor 修复

## 7.1 成交应用顺序

ExecutionProcessor 中一次 Trade Update 应按明确顺序处理：

```text
1. Validate Scope
2. Deduplicate Update
3. Deduplicate Trade
4. Update Order
5. Build Trade Application Request
6. Resolve Position Scope
7. Resolve Fee Instruction
8. Build Position Trade
9. Apply Position
10. Apply Allocation
11. Apply Settlement
12. Apply Margin
13. Apply Account Cash Flow
14. Apply Strategy Ledger
15. Apply Fee Ledger
16. Consume/Release Reservations
17. Check Invariants
18. Publish Events
19. Commit Audit
```

顺序以当前正式事务模型为准，但必须统一且有测试证明。

---

## 7.2 禁止再使用 Broker 本地费用作为扣款真值

Broker Update 中的：

```text
reported_fee
```

只能作为费用解析和对账输入。

不能直接：

```python
account.apply_fee(update.reported_fee)
ledger.apply_fee(update.reported_fee)
```

除非 FeeResolver 已把它确定为权威 Fee Instruction。

---

## 7.3 幂等性

同一 Trade Update 重复到达时：

```text
Position 不重复
Account 不重复
Ledger 不重复
Fee 不重复
Reservation 不重复消耗
Adjustment 不重复
```

必须使用稳定：

```text
trade_id
fee instruction id
idempotency key
source sequence
```

证明。

---

# 八、Virtual Broker 修复

## 8.1 Virtual Broker 不计算本地权威费用

Virtual Broker 负责：

```text
订单接受
订单生命周期
撮合
成交价格
成交数量
延迟
Broker 侧 Snapshot
标准 Broker Update
```

它不负责：

```text
决定 Runtime Account 最终费用
根据 Market Profile 重算税费
维护另一套本地 Fee Ledger
```

如果 Virtual Broker 没有模拟外部费用回报：

```text
reported_fee = None
fee_reporting_mode = NONE
```

而不是用零费用伪装“外部已确认费用为零”。

必须区分：

```text
没有报告费用
报告费用为零
```

这两个语义不能相同。

---

## 8.2 Broker Account 的费用语义

必须明确：

```text
Virtual Broker Account
Runtime Account
```

谁是 Backtest 的权威账户。

推荐：

```text
Virtual Broker Account
    模拟外部 Broker Snapshot

Runtime Account
    OnlyAlpha 本地正式业务真值
```

如果 Virtual Broker Account 不包含 Runtime 解析费用：

* 文档必须明确；
* Query/Reconciliation 必须知道差异来源；
* 测试不能直接断言两边 Equity 完全相等。

或者让 Virtual Broker 使用同一个只读 Fee Instruction Port 更新外部快照。

只能选择一种明确方案，不能保留模糊状态。

---

# 九、真实 Broker reported fee 和 Reconciliation

## 9.1 MiniQMT 映射

审计 MiniQMT Broker Callback 和 Trade Snapshot。

如果 xtquant 对象能够提供费用字段，必须规范化为：

```text
reported_fee
fee_reporting_mode
fee_external_reference
```

如果 SDK 当前回调不提供费用：

```text
reported_fee = None
fee_reporting_mode = NONE 或 UNKNOWN
```

不能填 `0` 假装已报告。

---

## 9.2 Fee Reconciliation

接入正式：

```text
OnlyFeeReconciliationService
```

至少支持：

```text
本地 Provisional Fee
外部 Reported Fee
差异比较
Tolerance
Matched
Adjustment Required
Blocking Difference
```

---

## 9.3 Fee Adjustment

如果后续 Broker Reported Fee 与本地暂定费用不同：

```text
difference = reported - previously_applied
```

生成正式 Adjustment Instruction。

Adjustment 必须幂等更新：

```text
Account
Strategy Ledger
Fee Manager
Result Facts
Audit
```

不得重新应用整笔费用。

---

## 9.4 风险阻断

不可解释且超过阈值的费用差异必须进入正式状态：

```text
RECONCILIATION_REQUIRED
TRADING_BLOCKED
```

Risk 提交新订单前必须读取该状态。

不能只把 Blocking 状态返回给一个无人消费的 Service。

---

# 十、Account、Ledger、FeeManager 一致性

## 10.1 Account

Account 必须记录实际已应用费用。

至少保证：

```text
cash_balance
fees
equity
realized_pnl
```

与 Fee Adjustment 一致。

---

## 10.2 Strategy Ledger

禁止把所有 Fee Component 合并成错误的：

```text
COMMISSION
```

应保留各 Fee Component 类型，或者保存完整 Fee Breakdown 引用。

需要支持：

```text
commission
tax
stamp duty
transfer fee
exchange fee
broker fee
maker/taker
adjustment
```

---

## 10.3 FeeManager

FeeManager 是 Append-only 费用事实账本。

它必须记录：

```text
estimated
provisional
confirmed
adjusted
```

不能覆盖旧记录。

Adjustment 应追加新记录，而不是修改历史记录。

---

## 10.4 正式不变量

至少增加：

```text
ACCOUNT_FEE_EQUALS_APPLIED_FEE_TOTAL
LEDGER_FEE_EQUALS_CLUSTER_APPLIED_FEE_TOTAL
FEE_LEDGER_TOTAL_EQUALS_ACCOUNT_APPLIED_FEE_TOTAL
NO_DUPLICATE_FEE_INSTRUCTION
NO_DUPLICATE_FEE_ADJUSTMENT
NO_ACTIVE_FEE_RESERVATION_AFTER_FINAL_ORDER
```

对于多 Cluster，不能简单要求：

```text
一个 Ledger fees == Account fees
```

应按 Allocation 或 Cluster 归因后求和。

---

# 十一、Collector、Result 和 Artifact

## 11.1 Fee Facts

Collector 必须输出：

```text
fee_record_id
instruction_id
idempotency_key
account_id
cluster_id
strategy_id
broker_id
instrument_id
order_id
trade_id

authority
status
reporting_mode

schedule_id
schedule_version
schedule_fingerprint

currency
component_type
amount
total
adjustment_reference
external_reference

ts_event
ts_init
sequence
schema_version
```

字段以现有正式 Schema 为准，不要创建重复类型。

---

## 11.2 Artifact Schema 迁移

Fee Schema 变化时：

```text
明确提升 schema_version
更新稳定字段顺序
更新 Parquet Schema
更新 JSON Projection
更新 Fingerprint
更新空表 Schema
```

不得为了旧 Golden File 继续输出废弃字段。

---

## 11.3 Determinism

相同：

```text
Config
Market Schedule
Broker Schedule
Bars
Orders
Broker Reports
```

重复运行必须得到相同：

```text
Fee Instruction
Fee Breakdown
Account
Ledger
Fee Facts
Result Fingerprint
Artifact Hash
```

不得把：

```text
绝对路径
墙钟时间
随机 UUID
内存地址
```

加入确定性输入。

---

# 十二、37 项回归的处理要求

为每一个失败测试建立迁移表：

```text
test name
old assumption
new authoritative behavior
production change
test change
reason
```

输出：

```text
docs/reports/unified_fee_migration_regression_matrix.md
```

每个测试只能属于以下一种处理：

```text
A. 修复生产代码
B. 删除重复旧测试
C. 重写为新语义测试
D. 合并到更高层不变量测试
E. 删除已废弃产品路径
```

禁止：

```text
简单修改 expected number
增加 xfail
增加 skip
放宽精度
捕获异常后继续
删除断言但保留测试壳
```

---

# 十三、必须增加的测试

## 13.1 Fee Model 单元测试

覆盖：

```text
Schedule identity
Schedule effective date
Fee authority
Fee status
Fee reporting mode
Fee component total
Currency
Fingerprint
Unknown schedule
Overlapping versions
```

---

## 13.2 Fee Engine 测试

覆盖：

```text
Market-only fee
Broker-only fee
Market + Broker fee
Minimum commission
Buy-side fee
Sell-side fee
Stamp duty
Transfer fee
Maker fee
Taker fee
Close-today fee
Fractional quantity
Contract multiplier
Zero-fee mode
```

---

## 13.3 Reservation 测试

覆盖：

```text
estimated fee reservation
actual fee greater
actual fee smaller
partial fills
multi-fill minimum commission
cancel
reject
expired
duplicate fill
```

---

## 13.4 Broker Reporting 测试

覆盖：

```text
no reported fee
reported zero
reported provisional
reported confirmed
reported fee with external reference
```

---

## 13.5 Reconciliation 测试

覆盖：

```text
exact match
within tolerance
positive adjustment
negative adjustment
duplicate adjustment
blocking difference
Risk trading block
```

---

## 13.6 End-to-End Backtest

至少验证：

```text
GENERIC_T0_CASH
CN_A_SHARE_CASH
GENERIC_24X7_CRYPTO_SPOT
GENERIC_MARGIN_FUTURES
```

检查：

```text
Account fees
Ledger fees
Fee facts
Execution facts
Cash
Equity
Reservations
Fingerprint
```

---

## 13.7 Scenario 和 Conformance

所有内建 Required Scenario 必须更新到新 Fee Config。

Scenario Assertion 不得自己重算 Fee。

它只能比较正式 Fee Facts。

Conformance Coverage 必须来自正式 Scenario Runner。

---

# 十四、删除旧实现

必须检查并删除确认已经废弃的：

```text
OnlyFixedCommissionModel
Virtual Broker commission_model 参数
fixed_commission 配置
旧 Broker Fill fee 字段
旧 Trade fee 构造入口
旧 Product Backtest Assembler
旧 Product Runner 私有绑定
测试专用佣金旁路
旧 Fee JSON 字段
旧 Fee Parquet Schema
旧 Fee Golden Files
```

如果其中某个类型仍有不可替代职责，必须在审计报告中证明。

不能因为测试引用很多就保留旧类型。

---

# 十五、CI 和质量门禁

## 15.1 必须严格复现 CI

执行 `.github/workflows/ci.yml` 中全部逻辑。

至少保证：

```text
Metadata Validation       PASS

Core Linux                PASS
Core Windows              PASS
Core macOS                PASS

Tushare Linux             PASS
Tushare Windows           PASS
Tushare macOS             PASS

MiniQMT Windows           PASS

Integration               PASS
Scenario                  PASS
Conformance               PASS
Integration Demo          PASS

Core Build Smoke          PASS
Tushare Build Smoke       PASS
MiniQMT Build Smoke       PASS

Required CI               PASS
```

---

## 15.2 代码质量

必须执行：

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
git diff --check
```

MiniQMT Mypy 如果暂时无法启用：

* 必须列出具体错误；
* 修复属于本次 Fee 修改的错误；
* 不得用整包 ignore 掩盖 Fee API 错误。

---

## 15.3 禁止降低门禁

禁止修改 CI 以：

```text
删除失败测试
减少 testpaths
移除平台
关闭 mypy
关闭 ruff
添加 continue-on-error
添加 allow-failure
跳过 Scenario
跳过 Conformance
跳过 Build Smoke
```

当前代码必须适配门禁，而不是降低门禁适配当前代码。

---

# 十六、文档更新

任务完成后必须更新：

```text
README.md
AGENTS.md
HANDOFF.md
NEXT.md
docs/architecture.md
docs/runtime.md
docs/order.md
docs/risk.md
docs/virtual_broker.md
docs/execution_processor.md
docs/account.md
docs/results_framework.md
所有 Fee 相关文档
```

新增 ADR：

```text
docs/adr/00xx-unified-fee-authority-and-reconciliation.md
```

ADR 必须明确：

```text
费用唯一权威
Market Fee 与 Broker Fee 边界
Estimated/Provisional/Reported/Confirmed/Adjusted
Runtime 与 Broker 职责
Reconciliation
Adjustment
Risk Block
不兼容迁移策略
```

---

# 十七、HANDOFF 更新

最终更新 `HANDOFF.md`，必须记录：

```text
修复前 commit SHA
修复后 commit SHA
修复前失败总数
失败分类
删除的旧接口
新 Fee Authority 链
配置装配链
MiniQMT reporting 状态
Adjustment/Reconciliation 状态
Account/Ledger/Fee Facts 不变量
Scenario/Conformance 结果
真实 CI 命令
真实测试结果
明确未完成
```

不得把未执行的命令写成通过。

---

# 十八、执行阶段

严格按以下顺序执行：

## Stage 1：失败基线

```text
同步代码
执行完整门禁
输出失败矩阵
```

## Stage 2：领域审计

```text
确定唯一 Fee Authority
确定 Config/Schedule/Reporting 边界
确定需要删除的旧接口
```

## Stage 3：配置装配

```text
market.fees
broker.fees
→ Runtime Assembly
→ FeeResolver
```

## Stage 4：订单估算

```text
Estimated Fee
→ Risk
→ Account Reservation
→ Ledger Reservation
```

## Stage 5：成交应用

```text
Trade
→ Fee Instruction
→ Position
→ Account
→ Ledger
→ FeeManager
```

## Stage 6：Broker Reporting

```text
Virtual Broker NONE
MiniQMT Reported Fee
```

## Stage 7：Reconciliation 与 Adjustment

```text
Compare
→ Adjustment
→ Account / Ledger / Fact
→ Trading Block
```

## Stage 8：Result 和 Artifact

```text
Fee Facts
Schema
Fingerprint
```

## Stage 9：测试迁移

```text
处理全部失败测试
增加缺失不变量测试
```

## Stage 10：完整 CI

```text
所有平台和产品门禁通过
```

## Stage 11：文档和交接

```text
ADR
README
HANDOFF
报告
```

不得跳过阶段直接修改大量 Expected Values。

---

# 十九、完成标准

以下全部满足才算完成：

```text
旧 Fee/Commission 正式路径已删除
不存在 Legacy Fee 分支
不存在两套本地费用权威

market.fees 正式进入 Runtime
broker.fees 正式进入 Runtime
Market/Broker Schedule 均可按版本和日期解析

Estimated Fee 正确用于 Reservation
Provisional Fee 正确应用
Reported Fee 正确规范化
Confirmed/Adjusted Fee 正确入账

Account 使用唯一费用
Strategy Ledger 使用唯一费用
Position Trade 使用唯一费用
FeeManager 使用唯一费用
Collector 使用唯一费用
Result/Artifact 使用唯一费用

多 Fill 最低佣金正确
撤单/拒单 Reservation 无泄漏
重复 Trade 不重复收费
Adjustment 幂等
重大差异能阻断交易

37 项或最新实际数量的迁移回归全部处理
没有新增 xfail
没有新增 skip
没有放宽门禁

Core 三平台通过
Tushare 三平台通过
MiniQMT Windows 通过
Integration 通过
Scenario 通过
Conformance 通过
Integration Demo 通过
Build Smoke 通过
Required CI 通过

ruff check 通过
ruff format --check 通过
mypy 通过
git diff --check 通过

文档已更新
ADR 已新增
HANDOFF 已更新
```

---

# 二十、本任务明确不做

除非是修复 Fee 正式链所必需，本任务不实现：

```text
Paper Runtime
Live Runtime
Shadow Runtime
Research Runtime
每日盯市
强平
Web Server
新 DataSource
新 Broker
新 Indicator
完整 US/HK 规则
```

但不得以“Live 尚未实现”为理由跳过 Broker Reported Fee 和 Reconciliation 的接口设计与单元测试。

---

# 二十一、最终报告格式

完成后输出中文报告。

## 1. 基线

```text
commit
Python
uv
失败测试数量
CI 状态
```

## 2. 根因

按共享根因归类，而不是逐个罗列症状。

## 3. 删除内容

列出所有旧：

```text
Config
Field
Type
Assembler
Commission Model
Test Fixture
Artifact Schema
```

## 4. 新费用链

展示：

```text
Config/Schedule
→ Resolver
→ Instruction
→ Execution
→ Account/Ledger
→ Reconciliation
→ Result
```

## 5. 37 项回归处理

列出每项：

```text
测试名称
根因
生产修复
测试迁移
最终状态
```

## 6. 不变量

报告 Account、Ledger、FeeManager、Result 之间的一致性。

## 7. Scenario 与 Conformance

列出所有真实运行结果。

## 8. 插件

分别说明：

```text
Virtual Broker
Tushare
MiniQMT
```

的费用语义。

## 9. CI

列出真实命令、退出码和结果。

## 10. 文档

列出更新文件。

## 11. 明确未完成

任何门禁未通过时必须明确：

```text
本任务未完成
```

不得使用“主要完成”“基本完成”替代硬门禁。

---

# 二十二、最终架构原则

最终实现必须满足：

> OnlyAlpha 中费用是一等领域事实，不是 Broker Fill 上的附属数字。

> Market 负责市场和交易所费用，Broker 负责 Broker Schedule 或外部费用报告，OnlyFeeResolver 负责唯一权威决策。

> Account、Strategy Ledger、Position、Collector 和 Result 不计算费用，只应用或投影统一的 Fee Instruction。

> Estimated、Provisional、Reported、Confirmed 和 Adjusted 必须具有不同语义。

> 删除所有与新费用模型重复的旧佣金接口，不为旧测试保留兼容路径。

> 只有最新代码上的全平台、全 Scenario、全 Conformance 和全 Build 门禁真实通过，才能宣称迁移完成。
