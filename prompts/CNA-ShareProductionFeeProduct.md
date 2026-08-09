# Codex Prompt — P3 CN A-Share Production Fee Product

## 任务名称

**P3 — CN A-Share Production Fee Product**

中文：

**P3：中国 A 股生产级费用 Authority 产品化**

目标仓库：

```text
https://github.com/zongxin1993/OnlyAlpha
```

规划基线：

```text
0c0543765eeb124d3e87fdad5b3bfad2b38f69a1
Feat: Reconciliation Composition Stabilization
```

开始工作前必须重新读取最新 `master`。

如果 `master` 已经前进：

1. 以最新 `master` 为唯一实现基线；
2. 重新审计本 Prompt 涉及的代码；
3. 已经正确完成的内容不得重复实现；
4. 不得为了套用 Prompt 恢复已经删除的旧接口；
5. Implementation Report 必须记录：

   * Prompt baseline；
   * actual implementation baseline；
   * baseline differences；
   * 已被后续提交提前解决的内容。

---

# 1. P3 的根本目标

P0/P1/P2/P2.1 已经完成了：

```text
Test / CI Governance

Market Fee Authority
Broker Fee Contract Authority
Order Fee Binding
Fee Policy Resolution Proof
Fee Basis Provider
Fee Engine
Fee Accrual
Fee Application

External Fee Evidence
Fee Reconciliation
Forward Correction
Active Blocker
Reconciliation Policy Authority
Reconciliation Composition
```

因此 P3 **不是 Fee Kernel 重构 PR**。

P3 要解决的是：

> **把真实中国 A 股市场费用制度和真实账户 Broker Fee Contract，转换为 OnlyAlpha 已有 Authority 模型可以版本化、绑定、计算、持久化、恢复和对账的生产级经济事实。**

P3 前：

```text
CN A-share
    ↓
真实 Reference / Rule 基础
    ↓
CN_A_SHARE_TEST_MARKET_FEE_PACK
    ↓
Architecture / Conformance Fee
```

P3 后：

```text
Official Market Sources
        ↓
Versioned Production Market Fee Authority
        │
        │
Broker Account Contract Snapshot
        ↓
OnlyBrokerFeeContract
        │
        └───────────┐
                    ▼
             Order Fee Binding
                    ↓
             Policy Resolution
                    ↓
              Fee Assessment
                    ↓
          Order Fee Accrual
                    ↓
             Fee Application
                    ↓
          Durable Economic Facts
                    ↓
             Reconciliation
```

---

# 2. 第一性原则

所有实现必须从以下原则推导。

## 2.1 费用制度是 Authority Fact，不是代码分支

错误：

```python
if market == "CN_A_SHARE":
    stamp_duty = ...
    transfer_fee = ...
```

正确：

```text
Official Authority
        ↓
Normalized Fee Schedule
        ↓
OnlyMarketFeePack
        ↓
Generic Fee Resolution
        ↓
Generic Fee Engine
```

Fee Engine 不应该知道：

```text
印花税是什么
上交所是什么
深交所是什么
某年费率为什么调整
```

它只应该理解：

```text
Authority
Scope
Effective Period
Formula
Basis
Side
Offset
Calculation Scope
Resolution Policy
Rounding
Bounds
```

---

# 3. Market Fee 和 Broker Fee 必须继续严格分离

Market Authority：

```text
Market
Venue
Regulator
Clearing / Registration Authority
```

定义：

```text
制度性市场费用
```

Broker Authority：

```text
Broker
+
Account Contract
```

定义：

```text
佣金
最低佣金
账户折扣
特殊协议费率
Broker-specific commercial fees
```

严禁 P3 为了实现 A 股费用，把：

```text
Broker Commission
```

重新放入：

```text
OnlyMarketFeePack
```

P1 已经完成这个边界，P3 必须保持。

---

# 4. 历史 Authority 不可修改

当制度变化：

```text
Schedule v1
        ↓
Schedule v2
```

不得：

```text
修改 v1 的 rate
```

必须：

```text
保留 v1

新增 v2

设置准确 effective period
```

历史 Order / Fill 必须继续绑定和解析历史 Authority。

---

# 5. 不允许“最新费率”Fallback

任何：

```text
CURRENT
LATEST
DEFAULT_CURRENT
```

式费用选择都禁止。

例如 Backtest 日期：

```text
2024-xx-xx
```

如果系统只验证并安装了：

```text
2025-xx-xx 以后
```

正式 Schedule：

必须：

```text
FEE_SCHEDULE_NOT_FOUND
```

或一个更加明确的：

```text
MARKET_FEE_COVERAGE_NOT_AVAILABLE
```

Fail Closed。

禁止：

```text
拿 2026 年费率计算 2024 年交易
```

---

# 6. 官方事实优先于现有测试

如果当前：

```text
CN_A_SHARE_TEST_MARKET_FEE_PACK
```

与官方制度冲突：

> 官方制度优先。

如果当前测试验证的是 Test Pack：

> 重写测试。

不能为了保持旧测试：

```text
污染生产 A-share Market Fee Pack
```

---

# 7. Reference Expected Result 不得由生产 Fee Engine 自证

错误：

```python
expected = production_fee_engine.calculate(...)
assert production_fee_engine.calculate(...) == expected
```

正确：

```text
Official Source
        ↓
Independent manually reviewed reference vector
        ↓
Production Engine
        ↓
Compare
```

Reference Vector 必须是：

```text
外部于被测试实现的 oracle
```

---

# 8. 本阶段产品范围必须明确

P3 第一版优先定义为：

```text
CN A-share Cash Equity

Currency:
CNY

Venues:
SSE
SZSE

Account:
Cash

Position:
Long-only / Netting

普通人民币 A 股现金交易
```

开始编码前重新确认当前 `CN_A_SHARE_CASH` Product Scope。

除非仓库当前明确把以下内容列入第一阶段目标，否则默认 P3 不支持：

```text
BSE

B Share

ETF 特殊收费

Convertible Bond

Bond

Options

Margin Trading

Securities Lending

Hong Kong Stock Connect

Block Trade special fee regimes

Cross-border fees

Multi-currency
```

对于不支持的产品：

```text
明确 Unsupported / No Applicable Authority
```

不要用普通 A 股费率猜测。

---

# 9. P3 明确非目标

P3 不实现：

```text
CN_A_SHARE_CASH Durable Execution Enablement

Execution Capability redesign

Market Reference Provider SPI

Paper Streaming Recovery

Live Runtime

Durable Outbound Broker Command

Real MiniQMT fee evidence query

Real MiniQMT statement ingestion

Broker account automatic commission discovery

Multi-account Runtime

Multi-broker Runtime

Futures Production Execution

Crypto Production Execution

FX conversion

Vectorized Backtest
```

尤其严禁：

```python
if market_profile == "CN_A_SHARE_CASH":
    return DURABLE_TRADE
```

该工作属于 P4。

---

# 10. P3 开发前必须完成 Pre-Implementation Audit

首先只读审计：

```text
src/onlyalpha/fee/
src/onlyalpha/fee/packs/
src/onlyalpha/fee/market_pack.py
src/onlyalpha/fee/broker_contract.py
src/onlyalpha/fee/schedules.py
src/onlyalpha/fee/policy.py
src/onlyalpha/fee/formula.py
src/onlyalpha/fee/rounding.py
src/onlyalpha/fee/basis.py
src/onlyalpha/fee/accrual*
src/onlyalpha/fee/application*
src/onlyalpha/runtime/defaults.py
src/onlyalpha/runtime/assembler.py
src/onlyalpha/config/
src/onlyalpha/market/
src/onlyalpha/reference/
src/onlyalpha/artifact/
src/onlyalpha/result/

tests/fee/
tests/domain_conformance/
tests/integration/
tests/recovery/
tests/architecture/

examples/
docs/
```

重点搜索：

```text
CN_A_SHARE_TEST_MARKET_FEE_PACK
only_cn_a_share_conformance_fee_pack

OnlyMarketFeeSchedule
OnlyMarketFeePack

OnlyBrokerFeeContract
OnlyBrokerFeeSchedule

OnlyFeeRule
OnlyFeeFormula

OnlyFeeCalculationScope
OnlyFeeResolutionPolicy

minimum
maximum
rounding

ORDER_CUMULATIVE

source
source_id

CN_A_SHARE_CASH
```

输出：

```text
docs/reports/
p3_cn_ashare_production_fee_pre_implementation_audit.md
```

报告必须说明：

```text
Current A-share fee path

Current generic conformance path

Current Market Fee primitive capabilities

Current Broker Contract capabilities

Current source/provenance representation

Current partial/multi-fill accrual semantics

Current configuration selection

Current default composition

Current persistence/artifact coverage

Current A-share test assumptions

Potential model gaps
```

---

# 11. 官方数据研究是 P3 的硬性前置条件

P3 涉及真实费用制度。

**不得根据模型记忆、博客、券商文章、社区帖子或搜索摘要直接写费率。**

实施时必须重新联网核验官方来源。

优先使用：

```text
财政部

国家税务总局

中国证监会

上海证券交易所

深圳证券交易所

中国证券登记结算有限责任公司

以及具体制度中被明确授权的官方机构
```

第三方网页只能用于：

```text
找到官方文件线索
```

不能作为最终 Authority Source。

---

# 12. 如果开发环境不能访问官方资料

如果 Codex 无法访问互联网，或者官方页面无法获取：

**不要猜。**

必须：

```text
停止生产费率编码

完成可以安全完成的架构审计

列出缺失的官方 Authority Evidence

在报告中明确 BLOCKED
```

严禁：

```text
凭常识补数字
从旧博客复制
用 Generic 0.001 代替
```

---

# 13. 每个正式收费项必须建立 Source Record

每项生产 Fee Component 至少记录：

```text
source_id

issuer

official document identity

document title

publication date

effective date

official locator

scope

normalized interpretation
```

如果同一规则由多个官方文件共同确定：

```text
记录全部 load-bearing source
```

---

# 14. Source ID 必须稳定

当前 Schedule 已有：

```text
source / source_id
```

不要把随机 URL 直接作为稳定 Authority ID。

推荐定义稳定 canonical ID，例如：

```text
<ISSUER>:<DOCUMENT_ID>:<REVISION>
```

具体编码规则由实施审计决定。

URL 属于：

```text
locator
```

不是 Authority Identity。

---

# 15. 不要过度建设“法规管理平台”

P3 不需要：

```text
General Regulatory Document Database
Crawler
Web Archiver
Regulatory Workflow Engine
```

如果现有：

```text
source: str
```

配合一个独立：

```text
source manifest
```

已经足以审计，则保持简单。

例如：

```text
cn_a_share/
    market.py
    sources.py
```

或：

```text
cn_a_share/
    source_manifest.yaml
```

---

# 16. 只有现有 Source 表达确实不足时才增加类型

如果审计证明自由字符串已经不足以实现：

```text
稳定 source identity
审计追溯
source fingerprint
```

允许新增最小：

```python
OnlyFeeAuthoritySourceReference
```

但只能包含真正必要字段。

禁止创建新的大型 Source Framework。

---

# 17. 建立正式 Fee Authority Matrix

编码 Schedule 前先输出一份 Fee Matrix。

至少按以下维度组织：

```text
Fee Component

Authority

Official Source

Venue

Instrument Class

Currency

BUY / SELL applicability

Offset applicability

Basis

Rate / amount

Minimum

Maximum

Rounding

Calculation Scope

Resolution Policy

Effective From

Effective To
```

矩阵必须先通过内部一致性审查，再进入代码。

---

# 18. 不要在 Prompt 或旧测试中假设具体费率

所有：

```text
rate
minimum
rounding
effective date
```

必须来自 P3 当次官方研究。

如果不同官方 Authority 对同一费用解释不一致：

```text
停止该 Component 产品化
记录冲突
不要自行选择“看起来合理”的值
```

---

# 19. 正式建立 Production A-share Fee Pack

不要继续在：

```text
generic_t0_cash.py
```

里放生产 A 股规则。

推荐目录：

```text
src/onlyalpha/fee/packs/
├── generic_t0_cash.py
├── generic_margin_futures.py
├── generic_crypto_spot.py
└── cn_a_share/
    ├── __init__.py
    ├── market.py
    └── sources.py
```

具体文件可按项目风格调整。

核心原则：

```text
Generic Conformance
≠
Production CN A-share
```

---

# 20. Production Pack 命名

Pack ID 必须稳定，例如语义上：

```text
CN_A_SHARE_PRODUCTION_MARKET_FEES
```

具体命名按项目规范决定。

禁止：

```text
CURRENT_A_SHARE_FEES

LATEST_A_SHARE_FEES

NEW_A_SHARE_FEES
```

因为这些名字不可作为长期 Authority Identity。

---

# 21. Pack Version 与 Code Version 分离

Fee Pack Version 不得等于：

```text
OnlyAlpha package version
```

Pack Version 应代表：

> **一套经过验证的市场费用 Authority 集合版本。**

例如当任何正式 Schedule 集合发生改变：

```text
Pack Version
```

才变化。

---

# 22. Pack Version 与 Schedule Version 分离

例如：

```text
Market Fee Pack v3

contains:
    Schedule A v2
    Schedule B v5
    Schedule C v1
```

这是正确的。

禁止：

```text
Pack Version
==
所有 Schedule Version
```

这种耦合。

---

# 23. 每一种独立经济费用必须保留独立 Component

禁止：

```text
TOTAL_MARKET_FEE
```

一个 Rule 把所有市场费用汇总。

应该：

```text
Component A
Component B
Component C
...
```

独立。

原因：

```text
P2 Reconciliation
```

已经是 Component-by-Component。

生产本地费用也必须保留同等粒度。

---

# 24. Fee Type 必须复用现有 Domain Vocabulary

优先使用已有：

```text
STAMP_DUTY
TRANSFER_FEE
EXCHANGE_FEE
CLEARING_FEE
REGULATORY_FEE
BROKER_COMMISSION
...
```

如果官方制度存在一个现有 Vocabulary 无法准确表达的新经济 Component：

可以新增一个明确、市场中立的：

```text
OnlyFeeType
```

但必须：

```text
一个经济概念一个类型
```

禁止：

```text
CN_SPECIAL_FEE_1
CN_SPECIAL_FEE_2
```

这类临时名字。

---

# 25. Market Authority 不得包含 Broker Authority

`OnlyMarketFeeSchedule` 必须继续禁止：

```text
BROKER
PLATFORM
```

Authority。

P3 不得绕过。

---

# 26. Broker Schedule 不得包含 Market Authority

同样保持：

```text
OnlyBrokerFeeSchedule
```

只允许：

```text
BROKER
PLATFORM
```

相关 Authority。

---

# 27. Venue 差异必须通过 Scope 表达

如果 SSE 与 SZSE 的规则不同：

正确：

```text
SSE-specific schedule

SZSE-specific schedule
```

通过：

```text
venue
```

匹配。

禁止：

```python
if venue == "SSE":
```

写入 Fee Engine。

---

# 28. 相同 Schedule Family 不允许 Scope Drift

当前 Registry 已明确要求：

```text
same schedule_id
→ same scope fingerprint
```

P3 必须遵守。

例如：

```text
SSE_TRANSFER_FEE
```

不能下一版本突然变成：

```text
SZSE
```

如果 Scope 不同：

```text
使用不同 schedule_id
```

---

# 29. Version Change 只能代表同一 Family 的规则演进

同一：

```text
schedule_id
```

的新版本可以改变：

```text
rate
minimum
maximum
rounding
effective period
rules
```

但不能改变：

```text
Authority namespace
market
venue
instrument class
currency
```

这些属于 Family Scope。

---

# 30. Effective Period 必须准确

生产 Schedule 不允许：

```text
1970-01-01
```

作为“懒惰 catch-all”。

必须使用：

```text
能够被官方来源证明的最早有效日期
```

如果 P3 只验证了：

```text
某日期以后
```

则该日期之前：

```text
没有 Authority
```

Fail Closed。

---

# 31. 明确 Production Fee Coverage Window

P3 必须定义并文档化：

```text
production fee coverage begins at <verified date>
```

如果支持多个历史版本：

逐个列出。

不能让用户误以为：

```text
所有历史年份
```

都已验证。

---

# 32. Side-specific Fee 使用 Rule Applicability

如果某 Component：

```text
SELL only
```

使用：

```text
OnlyFeeRule.side
```

表达。

禁止 Fee Engine：

```python
if fee_type == ...:
    if side == ...
```

---

# 33. Offset-specific 规则同样使用 Domain Field

如果确实存在：

```text
OPEN
CLOSE
```

适用差异：

使用：

```text
OnlyFeeRule.offset
```

不要根据市场名做隐式推断。

---

# 34. Instrument Class 必须来自 Market / Reference Authority

Fee 模块不得自己维护第二套：

```text
A_SHARE_NORMAL
A_SHARE_SPECIAL
```

分类。

如果现有 Instrument Classification 不足：

```text
扩展 Reference / Market Domain
```

然后 Fee Applicability 只消费标准分类。

不要：

```text
根据 Symbol Prefix 猜类别
```

---

# 35. 禁止 Symbol Hardcode

生产 Fee 代码中禁止类似：

```python
if symbol.startswith("60"):
...
```

或：

```python
if symbol[:3] in ...
```

这种证券代码判断。

正确路径：

```text
Instrument Reference
        ↓
Normalized Market / Venue / Instrument Class
        ↓
Fee Applicability
```

---

# 36. Formula 优先复用现有 Generic Primitive

当前已有：

```text
Rate × Basis

PerUnit × Basis

Fixed
```

以及：

```text
Minimum

Maximum

Rounding

Calculation Pipeline
```

如果官方规则能由这些 primitive 表达：

> 不允许新增新 Formula 类型。

---

# 37. 不允许新增 A-share-specific Formula Class

禁止：

```text
AshareStampDutyFormula

AshareTransferFeeFormula

AshareCommissionFormula
```

如果真实制度确实无法表达：

首先证明：

```text
现有 market-neutral primitive 不足
```

然后增加最小 market-neutral primitive。

例如真正需要分层计费时，可以考虑：

```text
TieredRateTerm
```

而不是：

```text
AshareTieredTerm
```

---

# 38. Rounding 必须来自 Authority

不得统一假定：

```text
ROUND_HALF_UP
```

或：

```text
ROUND_HALF_EVEN
```

P3 必须按具体制度核验：

```text
rounding quantum
rounding mode
pipeline order
```

然后写入 Schedule Rule。

---

# 39. Minimum / Maximum 必须区分 Market 与 Broker

市场制度的：

```text
minimum/maximum
```

属于 Market Schedule。

Broker Contract 的：

```text
minimum commission
```

属于 Broker Schedule。

绝不能互相搬运。

---

# 40. Calculation Scope 必须逐项核验

每项规则必须明确：

```text
FILL
```

还是：

```text
ORDER_CUMULATIVE
```

不能一刀切。

---

# 41. Resolution Policy 必须逐项核验

每项 Schedule 必须决定：

```text
ORDER_FIXED
```

或：

```text
FILL_EFFECTIVE
```

如果制度以：

```text
实际成交日
```

决定适用版本，则通常应建模为：

```text
FILL_EFFECTIVE
```

如果在订单接受时必须冻结，则：

```text
ORDER_FIXED
```

但最终必须依据正式制度语义，而不是猜。

---

# 42. 必须测试跨制度生效日订单

必须有：

```text
Order created on D-1
Fill on D
```

其中 D 是新 Schedule 生效日。

验证：

```text
ORDER_FIXED
→ old exact version

FILL_EFFECTIVE
→ new effective version
```

这是 P1 Authority 设计的生产验证。

---

# 43. Broker Fee Contract Domain 不重构

当前：

```text
OnlyBrokerFeeContract
```

已有：

```text
contract_id
contract_version
broker_id
account_scope
schedules
fingerprint
```

P3 只解决：

> **真实合同如何 Provision 到 Registry。**

不要重写 Broker Contract Domain。

---

# 44. Broker Contract 真实 Provisioning 不得依赖“一账户一个 Python Plugin”

插件可以继续发布：

```text
simulation / static generic contract
```

但真实账户合同属于：

```text
data / authority snapshot
```

不是软件插件。

---

# 45. 新增最小 Broker Contract Provisioning Boundary

建议建立：

```text
Strict Contract Snapshot
        ↓
Parser / Validator
        ↓
OnlyBrokerFeeContract
        ↓
OnlyBrokerFeeContractRegistry
```

命名可以是：

```text
OnlyBrokerFeeContractDocumentLoader

OnlyBrokerFeeContractProvisioner
```

或与当前项目风格一致的名称。

---

# 46. Provisioning 属于 Composition，不属于 Runtime Factory

禁止：

```text
BacktestRuntimeFactory
    打开 YAML
    创建 Broker Contract
```

正确：

```text
Config / Authority Document
        ↓
Composition
        ↓
Registry Installation
        ↓
Runtime exact require
```

保持 P2.1 原则：

> **Runtime selects Authority; Runtime does not manufacture Authority.**

---

# 47. Contract Definition 与 Account Selection 必须分离

推荐配置概念：

```yaml
authorities:
  broker_fee_contracts:
    - <authority snapshot>

accounts:
  - account_id: ACCOUNT-001

    broker_fee_contract:
      contract_id: ...
      contract_version: ...
```

如果采用文件式：

```yaml
authorities:
  broker_fee_contract_documents:
    - contracts/account-001.yaml
```

同样可以。

关键原则：

```text
authorities
    → 定义并安装 Authority

account
    → 选择 Authority
```

---

# 48. 不要把费率直接塞入 Account Config

禁止：

```yaml
account:
  commission_rate: ...
  minimum_commission: ...
```

这会重新混合：

```text
Authority Definition
```

与：

```text
Authority Selection
```

---

# 49. Authority Document 路径必须 deterministic

如果选择 file-backed Contract Snapshot：

必须明确：

```text
相对哪个配置文件目录解析

绝对路径是否允许

重复 document 如何处理

文件不存在如何处理

内容 fingerprint 如何处理
```

不能依赖：

```text
current working directory
```

隐式变化。

---

# 50. 如果当前 Config 基础设施无法安全支持路径

不要临时使用：

```text
cwd-relative file open
```

可以优先采用：

```text
top-level inline authorities
```

作为 P3 第一版。

原则：

> 正确 deterministic provisioning 比“必须独立 YAML 文件”更重要。

---

# 51. Contract Snapshot 必须严格验证

至少：

```text
contract ID 非空

version 非空

broker ID 非空

account scope 合法

currency 合法

schedule identity 唯一

schedule scope stable

source 合法

fingerprint 正确
```

错误：

```text
Fail Closed
```

---

# 52. 不允许 Contract Fallback

如果 Account 配置：

```text
BROKER_ACCOUNT_A@2026.1
```

而 Registry 无此 Contract：

```text
BROKER_FEE_CONTRACT_NOT_INSTALLED
```

禁止：

```text
使用 simulation zero contract
```

生产配置不能默认 0 佣金。

---

# 53. Simulation Zero Contract 必须只服务明确模拟场景

现有：

```text
*_SIMULATION_ZERO_BROKER_FEES
```

可以继续存在于：

```text
test
simulation
shadow
```

场景。

但 Production A-share example 不得无意使用它并宣称：

```text
真实费用完成
```

---

# 54. Broker Commission Schedule 必须有稳定 Source

对于用户手工提供的真实 Account Contract：

source 应表达：

```text
contract snapshot identity
```

例如：

```text
BROKER_CONTRACT:<contract-id>:<version>
```

而不是：

```text
"manual"
```

---

# 55. Broker Contract Registry Key 不随意重构

当前 Registry 使用：

```text
(contract_id, contract_version)
```

P3 默认保持。

真实账户应使用足够唯一的：

```text
contract_id
```

如果审计证明必须支持：

```text
same contract_id/version
+
different account scopes
```

同时存在，才重新讨论 Registry Key。

不要为了理论未来提前改 P1 Authority Identity。

---

# 56. 最低佣金必须重点验证

如果 Broker Contract 存在：

```text
rate-based commission
+
minimum commission
```

必须使用现有：

```text
ORDER_CUMULATIVE
```

能力正确实现。

不能：

```text
每个 Fill 收一次 minimum
```

---

# 57. Partial Fill 最低佣金场景必须进入 P3 Gate

例如：

```text
Order
    Fill 1
    Fill 2
    Fill 3
```

每次：

```text
cumulative target
-
already applied
=
incremental fee
```

最终必须：

```text
sum(incremental applications)
==
final order-level commission
```

---

# 58. Reference Vectors 是 P3 的核心产品资产

新增独立目录，例如：

```text
tests/domain_conformance/cn_a_share_fee/
```

以及：

```text
tests/reference_data/
cn_a_share_fee_vectors.*
```

按照当前项目风格选择。

---

# 59. Vector 必须包含完整输入上下文

至少：

```text
vector_id

source references

trading_day

market profile

market

venue

instrument class

instrument identity if needed

broker contract identity

side

offset

price

quantity

expected fee components

expected total

expected schedule identities / versions
```

---

# 60. Reference Vector 不能由生产代码生成

生产代码不得提供：

```text
generate_cn_ashare_reference_vectors()
```

然后测试自己的输出。

Reference Vector 必须：

```text
独立维护
人工审核
来源可追溯
```

---

# 61. 可以用独立 arithmetic checker，但不能复用 Fee Engine

如果为了减少人工算术错误，需要一个测试侧小工具：

可以使用：

```text
Decimal arithmetic
```

验证固定 Expected Value。

但它不得 import：

```text
OnlyFeeEngine
OnlyFeeRule evaluation
production fee formula
```

否则不再独立。

---

# 62. Market Fee Reference Matrix 至少覆盖

```text
SSE BUY
SSE SELL

SZSE BUY
SZSE SELL

small notional
large notional

before effective boundary
on effective boundary
after effective boundary
```

根据正式制度增加必要情况。

---

# 63. Broker Commission Reference Matrix 至少覆盖

```text
BUY

SELL

below minimum threshold

exact minimum boundary

above minimum

single fill

two fills

multi-fill
```

---

# 64. Cross-Date Reference Matrix

至少一个场景：

```text
Order D-1
Fill D
```

D 为制度变化日。

分别验证：

```text
ORDER_FIXED
FILL_EFFECTIVE
```

---

# 65. Component Integrity

Reference Test 必须逐 Component 验证。

不能只：

```text
assert total == expected_total
```

还必须：

```text
assert component A
assert component B
assert component C
```

总额一致但 Component 错误：

```text
TEST FAIL
```

---

# 66. Test Pack 与 Production Pack 必须彻底隔离

当前：

```text
CN_A_SHARE_TEST_MARKET_FEE_PACK
```

不得继续作为 Production default。

P3 完成后：

```text
Production Runtime
→ Production A-share Pack
```

Test Pack 如果仍有价值：

```text
只能用于测试/Conformance
```

---

# 67. 如果 Test Pack 只剩测试用途，移出生产 package surface

优先考虑把：

```text
only_cn_a_share_conformance_fee_pack
```

从生产默认 Composition 移除。

如果它只为 tests 服务：

建议移入：

```text
tests fixture
```

或明确的 testing-only namespace。

删除：

```text
生产 public export
```

不要为了兼容旧测试把它留在正式用户路径。

---

# 68. 不允许 Compatibility Alias

例如禁止：

```python
only_cn_a_share_fee_pack =
    only_cn_a_share_conformance_fee_pack
```

Production 与 Test Authority 必须是两个明确不同对象。

---

# 69. Default Composition Root

P3 后：

```text
only_default_engine_services()
```

如果正式支持 A 股 Production Fee：

应安装：

```text
Production CN A-share Market Fee Pack
```

不再默认安装测试 Pack。

---

# 70. Test Composition 单独安装 Test Pack

如果架构测试仍需要 Generic A-share Fee：

通过：

```text
test fixture
test component registry
```

安装。

不要污染默认生产服务。

---

# 71. Config 示例必须迁移

所有正式 Example：

如果当前引用：

```text
CN_A_SHARE_TEST_MARKET_FEE_PACK
```

必须迁移。

测试 Fixture 可以继续使用明确 Test Pack。

---

# 72. P3 不开放 A-share Durable Execution

这是硬 Scope Guard。

即使 P3 完成：

```text
CN_A_SHARE_CASH
```

仍可以保持 Execution Capability 当前状态。

不要修改：

```text
OnlyExecutionCapability resolver
```

来允许正式 Durable Trade。

这属于 P4。

---

# 73. P3 Integration 测试应绕过 Product Gate 吗？

不要通过生产 Runtime hack 绕过。

可以在：

```text
Fee Domain Integration
```

层直接组装：

```text
Market Applicability Context
Market Pack
Broker Contract
Binding
Policy Resolution
Assessment
Accrual
Application
```

测试生产费用。

不要加：

```text
test-only runtime bypass
```

进生产代码。

---

# 74. Production Fee Binding 必须使用现有 P1 Authority Proof

P3 必须证明：

```text
Market Fee Pack Identity

Broker Contract Identity

Scope Fingerprint

Schedule Identity

Binding Fingerprint

Policy Resolution Fingerprint
```

全部正确。

不要创建第二条简化的 A-share Fee Path。

---

# 75. P3 只能有一条 Fee Path

禁止：

```text
Generic Fee Engine

+

A-share Production Fee Engine
```

只能：

```text
Existing Generic Fee Engine
+
Production A-share Authority Data
```

---

# 76. P2 Reconciliation 必须直接兼容 Production Components

至少增加测试：

```text
Production Local Fee Components
        +
Normalized External Evidence
        ↓
Component Reconciliation
```

应能：

```text
MATCHED
```

或产生精确 Component Adjustment。

---

# 77. 不接真实 Broker Evidence

该测试使用：

```text
Fake / normalized OnlyExternalFeeEvidence
```

不接：

```text
MiniQMT
network
statement API
```

P3 只验证 Product Semantic Compatibility。

---

# 78. Production Artifact 审计

审计现有 Artifact 是否已经可以追踪：

```text
Market Fee Pack Identity

Broker Contract Identity

Schedule Identity

Rule Identity

Source ID

Fee Component

Amount

Trading Day
```

如果已有：

```text
不要改
```

如果缺少关键 Authority：

```text
做最小 schema 增强
```

---

# 79. 不把整个 Source Document 复制进每个 Artifact Row

Trade Artifact 只需要：

```text
stable authority identity
fingerprint
source ID
```

完整 Source Metadata 可以存在：

```text
Authority Manifest
Report
```

避免重复和巨大 Artifact。

---

# 80. Recovery 不重构 Kernel

P3 继续复用：

```text
Prepared Transaction
Committed Transaction
Projection
Checkpoint
Forward Recovery
```

不要重新设计。

---

# 81. P3 Recovery 的核心问题是 Authority Stability

测试：

```text
Engine A
    Pack P1
    Contract C1
    Binding B1
    Fill 1
    checkpoint

Registry 后续新增：
    Pack P2
    Contract C2

Engine B restart
```

历史订单仍必须：

```text
使用原有已绑定 Authority
```

不能重新绑定新 Pack/Contract。

---

# 82. A→B→C Production Fee Recovery

必须有至少一条完整场景：

```text
Production A-share Market Fee
+
Broker minimum commission
+
partial multi-fill
```

然后：

```text
Engine A
Fill 1
checkpoint

Engine B
recover
Fill 2
crash

Engine C
recover
Fill 3
```

最终：

```text
Fee Components
Broker Commission
Order Accrual
Account Economics
Strategy Ledger Economics
```

与 uninterrupted baseline 等价。

---

# 83. Pack Version Update Test

安装：

```text
Pack v1
Pack v2
```

Config 明确选择：

```text
v1
```

必须：

```text
继续使用 v1
```

Registry 不允许：

```text
auto latest
```

---

# 84. Schedule Overlap 必须 Fail Closed

生产数据加载时：

如果同一 Schedule Family：

```text
effective ranges overlap
```

Runtime 最终可能产生：

```text
FEE_SCHEDULE_AMBIGUOUS
```

P3 应尽量在 authority validation/test 阶段发现。

不能依赖注册顺序。

---

# 85. 建议增加 Production Authority Validation

可以建立一个小的：

```text
validate_cn_a_share_market_fee_pack()
```

或者通用 Market Fee Pack validation。

验证：

```text
coverage
non-overlap
source presence
scope consistency
currency
component identities
```

如果能保持 market-neutral，优先做通用 validation。

不要做大型框架。

---

# 86. 真实制度不能表达时的扩展规则

只有满足以下全部条件，才允许改 Fee Kernel：

1. 官方制度明确存在该语义；
2. 当前 Fee primitive 无法无损表达；
3. 问题不是 A-share 特有命名问题；
4. 可以抽象成市场中立经济 primitive；
5. 新 primitive 有独立 Unit/Conformance tests；
6. 不破坏 P1/P2 Authority 边界。

否则：

```text
不修改 Kernel
```

---

# 87. 不允许的实现模式

生产代码禁止：

```python
if profile == "CN_A_SHARE_CASH":
    ...
```

出现在：

```text
Fee Engine
Fee Formula
Fee Accrual
Fee Reconciliation
```

---

# 88. 不允许证券代码前缀判断

禁止：

```python
if symbol.startswith(...)
```

用于费率选择。

---

# 89. 不允许默认零佣金

生产 Broker Contract 缺失：

```text
FAIL
```

不能：

```text
ZERO_BROKER_FEE_CONTRACT
```

fallback。

---

# 90. 不允许默认 Test Pack

Production A-share Config 缺 Market Pack：

```text
FAIL
```

不能：

```text
CN_A_SHARE_TEST_MARKET_FEE_PACK
```

fallback。

---

# 91. 不允许旧接口兼容层

如果 Production Pack 替代 Test Pack 的正式用户路径：

删除：

```text
旧 production-facing aliases
旧 example references
旧 config defaults
```

但仍有清晰 Test 职责的 Test Fixture 可以保留。

---

# 92. Architecture Guards

至少增加 Guard，防止：

```text
CN_A_SHARE_TEST_MARKET_FEE_PACK
```

重新出现在：

```text
runtime/defaults production registration
production examples
README production config
```

---

# 93. Guard：Broker Commission 不得进入 Market Pack

Architecture / Domain Test 扫描所有：

```text
CN A-share production market schedules
```

禁止：

```text
OnlyFeeAuthority.BROKER
OnlyFeeAuthority.PLATFORM
BROKER_COMMISSION
```

---

# 94. Guard：Market Fees 不得进入 Broker Contract

同理，Broker Contract 不得包含：

```text
MARKET
VENUE
REGULATOR
CLEARING
```

Authority。

---

# 95. Guard：Production Source 不得为空

生产 Schedule：

```text
source_id
```

必须属于：

```text
known production source manifest
```

不能：

```text
OnlyAlpha Generic Conformance
test
TODO
unknown
```

---

# 96. Guard：Production Pack 不得使用 1970 Catch-all

除非官方 Source 真的能够证明：

```text
1970-01-01
```

有效。

默认禁止。

---

# 97. Guard：No Current/Latest Authority IDs

禁止生产：

```text
LATEST
CURRENT
DEFAULT_CURRENT
```

出现在：

```text
pack ID
schedule ID
contract version
```

---

# 98. Test Structure

建议增加：

```text
tests/domain_conformance/cn_a_share_fee/

tests/fee/test_cn_a_share_production_market_pack.py

tests/fee/test_broker_contract_provisioning.py

tests/integration/test_cn_a_share_production_fee_binding.py

tests/integration/test_cn_a_share_production_fee_multifill.py

tests/recovery/test_cn_a_share_production_fee_recovery.py

tests/architecture/test_production_fee_authority_boundary.py
```

按当前项目布局调整。

---

# 99. Market Pack Unit Tests

至少覆盖：

```text
pack identity stable

fingerprint stable

compatible CN_A_SHARE_CASH

wrong profile rejected

all sources valid

all currencies CNY for P3 scope

scope stable

schedule family versioning valid
```

---

# 100. Venue Tests

至少：

```text
SSE instrument
→ only SSE applicable schedules

SZSE instrument
→ only SZSE applicable schedules

wrong venue
→ no incorrect fallback
```

---

# 101. Side Tests

对每一个 Side-specific Component：

```text
BUY
SELL
```

都独立验证。

不能只测总费用。

---

# 102. Effective Date Tests

每个历史 version boundary 至少：

```text
D-1
D
D+1
```

其中 D 为正式生效日期。

---

# 103. Missing Coverage Test

选择一个明确超出 Production Authority Coverage 的日期：

必须：

```text
Fail Closed
```

而不是使用最早或最新版本。

---

# 104. Broker Contract Provisioning Tests

至少：

```text
valid exact-account contract

valid all-account contract if supported

wrong broker

wrong account

unknown contract

duplicate version

fingerprint conflict

invalid source

invalid currency
```

---

# 105. Broker Minimum Commission Tests

至少：

```text
single fill below minimum

single fill exact minimum

single fill above minimum

two fills final below minimum

two fills crossing minimum

three fills

retry same fill
```

最终费用不得重复。

---

# 106. Reference Vector Tests

每个 Vector：

```text
load independently

run production fee path

assert schedule identity

assert rule identity

assert each component amount

assert aggregate amount
```

不能只 assert total。

---

# 107. Reference Data 必须人工可读

推荐 YAML/JSON/TOML 等稳定格式。

不要把所有 Reference Expected Values 隐藏在：

```python
复杂 fixture factory
```

里。

Review 时应能直接看到：

```text
Input → Expected Components
```

---

# 108. Reference Vector 需要 Source Traceability

每条 Vector 至少引用：

```text
source_id
```

或者：

```text
source_ids
```

这样 Review 可以直接追踪：

```text
为什么这个 Expected Value 正确
```

---

# 109. 不同官方 Authority 的 Expected Value 分开计算

不要先人为汇总：

```text
total_market_fee
```

再测试。

每个正式 Component 单独有 Expected Value。

---

# 110. Integration — Binding

验证：

```text
Production Market Pack
+
Production/Test Broker Contract Snapshot
+
CN A-share Applicability
        ↓
Binding
```

Binding 必须记录：

```text
Market Pack Identity
Broker Contract Identity
Scope
Schedule identities
```

---

# 111. Integration — Policy Resolution

验证：

```text
Binding
+
Fill Trading Day
```

得到正确：

```text
Market Schedule version
Broker Schedule version
```

---

# 112. Integration — Accrual

验证：

```text
partial fill
multi-fill
order cumulative
```

的经济结果。

---

# 113. Integration — Reconciliation

构造标准化 External Evidence：

```text
完全匹配
```

必须：

```text
MATCHED
```

Component 少量差异：

必须进入现有：

```text
P2 Reconciliation
```

路径。

不要建立第二套 A-share Reconciliation。

---

# 114. Recovery

至少执行：

```text
Production Fee Pack
+
Broker Contract
+
Multi Fill
+
Checkpoint / Restart
```

完整 Recovery。

---

# 115. Determinism

同样 Authority 数据：

即使 Schedule 注册输入顺序改变：

```text
Binding fingerprint
Resolution fingerprint
Assessment ID
Fee Applications
```

必须一致。

---

# 116. Source Manifest Ordering 不应影响 Fingerprint

如果 Source Manifest 本质上是 Map/Set：

不同文件顺序不得改变：

```text
Authority identity
```

除非顺序本身有业务含义。

---

# 117. Composition Root

P3 完成后审计：

```text
only_default_engine_services()
```

应该清晰体现：

```text
Generic conformance products

Production CN A-share Fee Product
```

但 Testing Authority 不应该伪装为 Production Authority。

---

# 118. 建议 Test Pack 处理方案

如果：

```text
CN_A_SHARE_TEST_MARKET_FEE_PACK
```

只被测试使用：

**移出 production defaults。**

如果没有 production API 价值：

**移出 production package exports。**

如果完全没有必要：

**删除。**

不要因为“以前有”而保留。

---

# 119. 文档

新增：

```text
docs/adr/
<P3-next-number>-cn-a-share-production-fee-authority.md
```

编号使用仓库最新实际序号。

ADR 必须解释：

```text
production product scope

official source policy

market/broker authority separation

fee coverage window

pack/version semantics

schedule/version semantics

source identity

broker contract provisioning

why Runtime does not define Authority

why Reference Vectors are independent

why Production Fee does not enable Durable Execution
```

---

# 120. Implementation Report

新增：

```text
docs/reports/
p3_cn_ashare_production_fee_product.md
```

至少包括：

```text
Baseline

Supported Product Scope

Official Sources

Coverage Window

Market Fee Matrix

Production Pack Identity

Schedule identities and versions

Broker Contract provisioning

Deleted test/legacy production surfaces

Reference Vectors

Partial/Multi-Fill Results

Recovery Results

Reconciliation Results

Quality Gates

Explicit Unsupported Scope

Remaining P4 work
```

---

# 121. 官方来源报告必须完整

Implementation Report 不能只写：

```text
根据交易所规则
```

必须写：

```text
issuer
document
publication date
effective date
source ID
locator
which rule it supports
```

---

# 122. README

更新 README，只声明真实已经实现的内容。

P3 后可以写：

```text
CN A-share Production Fee Authority
available for the supported fee coverage window
```

但必须同时明确：

```text
CN A-share Durable Execution Product
still not enabled until P4
```

---

# 123. Roadmap

更新：

```text
P0 DONE
P1 DONE
P2 DONE
P2.1 DONE
P3 DONE
```

下一阶段：

```text
P4 — CN A-Share Durable Execution Product Closure
```

---

# 124. 不允许 README 继续混淆 Test 与 Production

如果测试 Pack 仍存在：

README 应明确：

```text
Test / Conformance Fee Pack
≠
Production Fee Pack
```

---

# 125. 推荐 Commit 顺序

## Commit 1 — Production Fee Authority Audit

只做：

```text
official research

scope matrix

coverage definition

ADR draft

model-gap assessment
```

没有可靠官方数据前，不编码生产费率。

---

## Commit 2 — Production A-share Market Fee Authority

实现：

```text
source manifest

production schedules

production pack

unit tests
```

只使用已经验证的官方制度。

---

## Commit 3 — Broker Contract Static Provisioning

实现：

```text
strict authority document model

parser / validator

composition installation

config authority selection

tests
```

不实现 Broker 网络查询。

---

## Commit 4 — Independent Production Reference Vectors

提交：

```text
human-reviewable reference data

source linkage

market component expected values

broker expected values
```

---

## Commit 5 — Partial / Multi-Fill Fee Product Conformance

重点验证：

```text
minimum commission
ORDER_CUMULATIVE
partial fill
multi-fill
```

---

## Commit 6 — Integration / Reconciliation / Recovery

完成：

```text
binding

resolution

application

normalized external evidence

checkpoint/restart

A→B→C
```

---

## Commit 7 — Production Composition + Legacy Cleanup + Docs

完成：

```text
production default registration

test pack isolation/removal

example migration

architecture guards

README

roadmap

final report
```

---

# 126. 如果官方研究发现 Kernel Gap

不要偷偷在 Commit 2 修改大量 Kernel。

先在 Audit 报告明确：

```text
Official Rule X
cannot be represented because...
```

然后证明需要哪个：

```text
market-neutral primitive
```

最好独立提交：

```text
Generic Fee Primitive Extension
```

再继续 Production Pack。

---

# 127. Kernel Extension 的验收标准

新 primitive 必须：

```text
没有 CN_A_SHARE 名称

可以被其他市场复用

有独立 unit tests

不破坏旧 fee authorities

fingerprint deterministic

serialization deterministic

recovery unaffected
```

---

# 128. Schema 原则

不要机械升级 Schema。

只有真实 persisted contract 变化时：

```text
升级对应 schema
```

例如如果 Source Identity 从字符串升级成 typed identity：

```text
Schedule / Binding / Artifact
```

可能需要升级。

如果只是增加新的 Production Pack 数据：

```text
不升级 generic transaction schema
```

---

# 129. 不做旧 Schema Migration

当前 Alpha 阶段：

如果新的正式 Authority Schema 与旧错误 Schema 不兼容：

```text
旧 schema Fail Closed
```

不要写 Compatibility Layer。

---

# 130. 错误语义

优先复用现有：

```text
MARKET_FEE_PACK_NOT_INSTALLED

MARKET_FEE_PACK_PROFILE_INCOMPATIBLE

FEE_SCHEDULE_NOT_FOUND

FEE_SCHEDULE_AMBIGUOUS

FEE_SCHEDULE_SCOPE_DRIFT

BROKER_FEE_CONTRACT_NOT_INSTALLED

BROKER_FEE_CONTRACT_BROKER_INCOMPATIBLE

BROKER_FEE_CONTRACT_ACCOUNT_INCOMPATIBLE
```

必要时增加：

```text
MARKET_FEE_SOURCE_NOT_REGISTERED

MARKET_FEE_COVERAGE_NOT_AVAILABLE

BROKER_FEE_CONTRACT_DOCUMENT_INVALID
```

但不要为 P3 重构整个 Error System。

---

# 131. 代码质量要求

最终代码必须：

```text
Production market facts 与 generic algorithms 分离

Market Fee 与 Broker Fee 分离

Source data 与 calculation logic 分离

Authority definition 与 Authority selection 分离

Test authority 与 Production authority 分离

Runtime orchestration 与 fee economics 分离

Reference vectors 与 production engine 分离
```

---

# 132. 禁止 Dead Compatibility

完成后删除：

```text
无用 Test-Pack production exports

旧 production examples

旧 production config references

已失去职责的 aliases

无意义 wrappers

deprecated accessors

dead imports

stale docs
```

Git 已经保存历史，不需要把历史留在当前代码中。

---

# 133. 不要删除仍有明确测试职责的东西

“不要兼容旧设计”不等于：

```text
所有旧 test fixture 都删除
```

判断标准：

如果一个 Test Pack 仍明确承担：

```text
generic architecture conformance
```

可以保留。

但必须：

```text
隔离在 test/testing scope
不出现在 production default
不出现在 production docs
不被用户误选
```

---

# 134. Static Gates

执行当前正式 Static Gates。

至少：

```bash
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages scripts

uv run ruff format --check src tests examples packages scripts

uv run mypy src/onlyalpha
```

以及当前正式 Provider mypy。

---

# 135. Test Lanes

运行当前正式：

```bash
uv run python scripts/test_suite.py fast

uv run python scripts/test_suite.py integration

uv run python scripts/test_suite.py core-full

uv run python scripts/test_suite.py recovery

uv run python scripts/test_suite.py ashare

uv run python scripts/test_suite.py miniqmt-contract

uv run python scripts/test_suite.py exhaustive
```

如果最新 `master` 命令已改变：

```text
使用最新正式 Lane
```

不要恢复旧命令。

---

# 136. Build

```bash
uv build --all-packages
```

必须 PASS。

---

# 137. 不允许通过测试的方法

禁止：

```text
skip

xfail

降低 assertion

删除历史 fee recovery tests

删除 P1/P2 authority tests

hardcode expected from actual result

fallback Test Pack

fallback zero commission

fallback latest rate

unsupported date fallback current rate
```

---

# 138. P3 Definition of Done — Official Authority

* [ ] 所有 Production Market Fee Components 都有正式官方 Source。
* [ ] Source 记录 issuer/document/publication/effective information。
* [ ] 没有使用第三方文章作为最终 Authority。
* [ ] 无法验证的费用没有被猜测实现。
* [ ] Production Fee Coverage Window 明确。
* [ ] Coverage 之外 Fail Closed。
* [ ] 没有 1970 catch-all production schedule，除非官方事实确实如此。
* [ ] 没有 `CURRENT` / `LATEST` Authority Identity。

---

# 139. Definition of Done — Market Pack

* [ ] Production CN A-share Market Fee Pack 存在。
* [ ] Production Pack 与 Test Pack 分离。
* [ ] Market Pack 不含 Broker Commission。
* [ ] 每个经济 Component 独立。
* [ ] SSE/SZSE Applicability 正确。
* [ ] Instrument Class Applicability 正确。
* [ ] Side Applicability 正确。
* [ ] Effective periods 正确。
* [ ] Schedule Scope 无 drift。
* [ ] 0 match Fail Closed。
* [ ] >1 match Fail Closed。
* [ ] Pack/Rule/Schedule fingerprints deterministic。

---

# 140. Definition of Done — Formula

* [ ] 优先复用现有 Fee Formula primitive。
* [ ] 没有 A-share-specific Formula class。
* [ ] Basis 正确。
* [ ] Rounding 正确。
* [ ] Pipeline 顺序正确。
* [ ] Minimum/Maximum 正确。
* [ ] Calculation Scope 正确。
* [ ] Resolution Policy 正确。
* [ ] 如果增加新 primitive，它是 market-neutral。

---

# 141. Definition of Done — Broker Contract

* [ ] Production Broker Contract 不定义在 Market Pack。
* [ ] Static Contract Snapshot 可以被严格 Provision。
* [ ] Provisioning 发生在 Composition 阶段。
* [ ] Runtime Factory 不读取 Contract Document。
* [ ] Account 只选择 Contract Identity。
* [ ] Wrong Broker Fail Closed。
* [ ] Wrong Account Fail Closed。
* [ ] Missing Contract Fail Closed。
* [ ] 没有 Zero Commission fallback。
* [ ] Contract Source 可追溯。

---

# 142. Definition of Done — Reference Vectors

* [ ] Reference Vectors 独立于 Production Fee Engine。
* [ ] 每条 Vector 有 Source Reference。
* [ ] SSE BUY/SELL 覆盖。
* [ ] SZSE BUY/SELL 覆盖。
* [ ] Effective Date Boundary 覆盖。
* [ ] Component Expected Values 单独验证。
* [ ] Total 相同但 Component 错误会 FAIL。
* [ ] Broker minimum commission boundary 覆盖。
* [ ] Partial/Multi-Fill 覆盖。

---

# 143. Definition of Done — Durable Semantics

* [ ] Order Binding 继续使用 P1 Authority Proof。
* [ ] ORDER_FIXED 生产规则行为正确。
* [ ] FILL_EFFECTIVE 生产规则行为正确。
* [ ] Historical Authority 不因新版本安装而改变。
* [ ] Partial/Multi-Fill accrual deterministic。
* [ ] Minimum commission 不重复。
* [ ] Production Fee Application 可 Recovery。
* [ ] A→B→C 等价于 uninterrupted baseline。

---

# 144. Definition of Done — Reconciliation

* [ ] Production Local Fee Components 可以进入 P2 Reconciliation。
* [ ] Exact component match 正确。
* [ ] Broker Commission difference 能形成正确 adjustment。
* [ ] 不新增 A-share-specific reconciliation path。
* [ ] 不接真实 MiniQMT 网络。

---

# 145. Definition of Done — Clean Architecture

* [ ] Fee Engine 不存在 `if CN_A_SHARE`。
* [ ] Fee Formula 不存在 `if CN_A_SHARE`。
* [ ] Fee Accrual 不存在 `if CN_A_SHARE`。
* [ ] Fee Reconciliation 不存在 `if CN_A_SHARE`。
* [ ] 不通过 Symbol Prefix 决定 Fee。
* [ ] 不存在 Test Pack production fallback。
* [ ] 不存在 Broker zero-fee production fallback。
* [ ] Test Authority 与 Production Authority 清楚隔离。
* [ ] 无 Compatibility Alias。
* [ ] 无 Dead Code。
* [ ] 无 Deprecated Wrapper。
* [ ] 模块边界比 P3 前更清楚，而不是更复杂。

---

# 146. Definition of Done — P4 Boundary

P3 结束后必须仍明确：

```text
CN A-share Production Fee Product:
READY

CN A-share Durable Execution Product:
NOT YET READY
```

P3 不修改：

```text
Execution Capability Resolver
```

来开放 A 股 Durable Trade。

---

# 147. Definition of Done — Quality

* [ ] Ruff PASS。
* [ ] Ruff Format PASS。
* [ ] Core mypy PASS。
* [ ] Provider mypy PASS。
* [ ] Fast PASS。
* [ ] Integration PASS。
* [ ] Core Full PASS。
* [ ] Recovery PASS。
* [ ] A-share PASS。
* [ ] MiniQMT Contract PASS。
* [ ] Exhaustive PASS。
* [ ] Build PASS。
* [ ] 最新 Quality Gate PASS。

---

# 148. 最终 Implementation Report 必须给出真实数字

不能只写：

```text
All tests passed
```

必须记录：

```text
actual commit SHA

static status

fast:
xxx passed
xx.xx s

integration:
xxx passed
xx.xx s

core-full:
xxxx passed
x skipped
xx.xx s

recovery:
xxx passed
xx.xx s

ashare:
...

miniqmt-contract:
...

exhaustive:
...

build:
PASS
```

---

# 149. 最终报告必须列出 Production Scope

明确：

```text
SUPPORTED IN P3
```

以及：

```text
UNSUPPORTED IN P3
```

例如不支持的：

```text
BSE
ETF special fee rules
Convertible Bonds
Margin Trading
Stock Connect
Options
Multi-currency
```

必须按实际最终结果填写，不能用本 Prompt 示例代替审计结论。

---

# 150. P3 完成后明确仍未实现

Implementation Report 必须有：

```text
NOT IMPLEMENTED IN P3
```

至少包括：

```text
CN A-share Durable Execution enablement

Capability-driven execution resolver

Market Reference Composition Neutralization

Real MiniQMT fee evidence ingestion

Real Broker commission query

Paper streaming recovery

Durable outbound Broker commands

Live Runtime

Multi-account Runtime

Multi-broker Runtime

Vectorized Backtest
```

---

# 151. P3 最终成功标准

P3 的成功不是：

```text
代码里出现“印花税”“佣金”几个数字
```

而是：

> **现实世界的一项 A 股费用制度变更，只需要增加或更新版本化 Authority Data、Schedule/Pack Version 和独立 Reference Vectors，而不需要修改 Fee Engine、Order、Position、Account、Runtime Transaction 或 Reconciliation Kernel。**

正确的长期维护流程应该是：

```text
Official Institution publishes change
        ↓
Create new Source Record
        ↓
Create new Schedule Version
        ↓
Create new Pack Version if required
        ↓
Add independent Reference Vectors
        ↓
Run Conformance / Recovery Gates
        ↓
Deploy
```

而不是：

```text
Official Institution publishes change
        ↓
edit if/else
        ↓
hope tests pass
```

---

# 152. 最终工程原则

当：

```text
测试费率
```

与：

```text
官方费率
```

冲突：

> 官方 Authority 优先。

当：

```text
旧测试
```

与：

```text
正确 Production Semantics
```

冲突：

> 重写旧测试。

当：

```text
方便使用最新费率
```

与：

```text
历史 Accuracy
```

冲突：

> Fail Closed。

当：

```text
Broker Commission
```

与：

```text
Market Fee Pack convenience
```

冲突：

> 保持 Broker Contract Authority。

当：

```text
少写一个 Schedule
```

与：

```text
准确 Venue / Scope
```

冲突：

> 建立准确 Schedule。

当：

```text
A-share-specific code
```

与：

```text
market-neutral primitive
```

冲突：

> 使用 market-neutral primitive。

当：

```text
Runtime 动态造 Authority
```

与：

```text
Composition 安装 Authority
```

冲突：

> Composition owns Authority installation。

当：

```text
保留旧 production-facing Test API
```

与：

```text
代码边界清晰
```

冲突：

> 删除旧 API。

当：

```text
猜一个费率先跑起来
```

与：

```text
官方来源不可确认
```

冲突：

> 不实现该规则，并明确报告 BLOCKED。

---

# 153. P3 最终定义

P3 不是：

> “给 OnlyAlpha 加一个 A 股手续费函数。”

P3 是：

> **把中国 A 股真实费用制度，从外部官方 Authority 转换成一套具有明确 Source、Scope、Effective Period、Version、Fingerprint、Calculation Semantics 和 Independent Reference Evidence 的生产级 Market Fee Product；同时建立真实 Broker Account Contract 的静态 Authority Provisioning，使本地应收费用第一次真正具有现实市场意义。**

最终必须满足：

```text
Market facts are official and versioned.

Broker commercial terms remain separate.

Sources are traceable.

Historical authority is immutable.

Coverage is explicit.

Unknown periods fail closed.

Rules are data-driven.

Algorithms remain market-neutral.

Partial fills remain correct.

Minimum commission remains order-cumulative.

Reference vectors are independent.

Runtime selects authorities; it does not create them.

Test authorities never masquerade as production authorities.

Recovery changes nothing.

Reconciliation works on production components.

No compatibility layer remains without a real responsibility.
```

只有这些原则真正进入：

```text
代码
Authority Data
Configuration
Tests
Artifacts
Recovery
Documentation
```

P3 才算完成。

完成 P3 后：

> **冻结 Production Fee Product，下一阶段进入 P4 — CN A-Share Durable Execution Product Closure，把 `CN_A_SHARE_CASH` 通过 capability-driven 方式正式接入现有 Durable Trading Kernel。**
