# Codex Prompt — PR4.1 Stabilization / Market-Neutral Durable Fee Authority Stabilization

## 任务名称

**PR4.1 Stabilization — Market-Neutral Durable Fee Authority Stabilization**

基于当前 `master`：

```text
b4969e3bd8a4b7acb03552c273b8d71aaf2e1506
Feat: Market-Neutral Durable Fee Authority Kernel Closure
```

对 PR4.1 合并后的 OnlyAlpha 工程进行一次完整的稳定化、边界校正和测试基线恢复。

本任务不是新增业务功能。

本任务的核心目标是：

> **确保 PR4.1 已经确定的新 Fee Authority 架构成为整个仓库唯一合法架构，并彻底删除仍依赖旧 Fee Schema、旧 Fee Event、旧测试假设、旧 Scenario 格式和旧 Runtime 装配假设的残留。**

最终必须建立一个新的、严格的、无兼容包袱的工程基线：

```text
Static
Full
Recovery
A-share Conformance
Build
Nightly
```

全部通过。

---

# 0. 第一原则

开始修改代码前，必须从以下第一性问题重新判断所有失败，而不是机械修改测试：

1. 当前 PR4.1 后，Fee Authority 的唯一合法配置入口是什么？
2. 当前 Fee Policy Pack 是否已经取代旧的 `fees.mode` / `commission` / `schedule` 等配置？
3. 哪些旧测试只是历史接口残留，应删除或重写？
4. 哪些失败暴露的是生产代码真实缺陷？
5. 哪些 Scenario / Example / Fixture 已经违反当前正式配置 Schema？
6. 哪些事件名称已经被新 Fee Application Ledger 取代？
7. 哪些 Runtime 构造方式已经失效，不应继续支持？
8. 哪些测试正在以旧设计为“规范”，但实际已经不再代表产品语义？
9. 当前测试分层是否发生重复执行，导致质量门禁成本无意义增长？
10. 当前 `master` 能否作为下一阶段开发的可信基线？

本 PR 的优先级必须严格按照：

```text
1. 当前正式架构正确性
2. Authority 单一性
3. 配置边界一致性
4. Runtime 装配一致性
5. Durable Recovery 一致性
6. 测试语义正确性
7. CI 可维护性
8. 测试执行效率
9. 历史兼容性
```

其中：

> **历史兼容性不构成本任务约束。**

---

# 1. 明确禁止事项

严禁为了修复旧测试而新增以下设计：

```text
legacy_fee_mode
legacy_fee_config
allow_missing_fee_config
default_fee_pack
fallback_fee_pack
compat_fee_mode
deprecated_fee_schedule
legacy_commission
old_fee_event_alias
fee_schema_v1_compat
scenario_fee_compat
```

严禁：

* 因为旧 Scenario 没有 `market.fees` 而允许该字段省略。
* 因为旧测试使用 `mode: NONE` 而恢复 `fees.mode`。
* 因为旧测试使用 broker-level `fees.schedule` 而重新加入旧 Broker Fee 配置。
* 因为旧测试期待 `FEE_RECORDED` 而恢复已废弃 Event。
* 因为旧 Runtime 测试没有 Market Rule Engine 而在生产代码中添加隐式默认 Market Rule。
* 因为历史 Fixture 构造方便而让 Runtime 自动安装 Fee Pack。
* 因为旧测试失败而降低 Fail-Closed 约束。
* 修改新 Fee Authority 设计以适配旧测试。

正确做法必须是：

```text
新架构正确
    ↓
旧测试错误
    ↓
修改 / 删除旧测试
```

而不是：

```text
旧测试存在
    ↓
生产代码增加兼容
```

---

# 2. 本任务范围

本任务只做 Stabilization。

必须完成：

## 2.1 当前主分支失败清零

当前已知最新 Full Test 大约存在：

```text
1329 passed
1 skipped
20 failed
```

必须重新在最新 `master` 上执行并重新获取真实结果，不得直接使用该数字作为最终结果。

需要逐个分类失败：

```text
A. stale test
B. stale fixture
C. stale scenario
D. stale example
E. stale event expectation
F. stale Runtime assembly assumption
G. actual production defect
H. environment-coupled test defect
I. CI/test-lane defect
```

每个失败必须明确归类。

---

## 2.2 Fee Config Schema 完整迁移

当前正式 Schema 应要求显式 Fee Policy Pack，例如：

```yaml
market:
  profile: CN_A_SHARE_CASH
  fees:
    pack_id: ...
    pack_version: ...
```

检查：

```text
examples/
tests/
tests/fixtures/
tests/scenario/
tests/domain_conformance/
tests/integration/
packages/*/tests/
```

所有仍依赖旧 Fee 配置的内容。

重点搜索：

```text
fees:
  mode:

mode: NONE
mode: MODEL

commission
commission_rate
fixed_commission
minimum_commission

broker:
  fees:

brokers:
  - fees:

schedule:
broker_fee_schedule
default_fee
```

所有历史格式必须：

```text
删除
或
迁移到正式 Policy Pack 配置
```

不得在 Parser 中恢复旧字段。

---

# 3. Fee Policy Pack 是唯一配置 Authority

确认当前正式配置模型：

```text
OnlyMarketConfig
    profile
    fees: OnlyFeeConfig

OnlyFeeConfig
    pack_id
    pack_version
```

其设计原则：

> Fee Pack omission is invalid.

因此：

```text
market.fees 缺失
→ Config Error

pack_id 缺失
→ Config Error

pack_version 缺失
→ Config Error

Fee Pack 未安装
→ Runtime Assembly Fail Closed
```

不能：

```text
缺失 → 自动选择 GENERIC
```

必须增加或修复相应测试，证明以上行为。

---

# 4. 修复 Scenario 体系，而不是降低 Schema

当前大量 Scenario 测试可能仍生成：

```text
market:
  profile: ...
```

但不包含：

```text
fees:
```

这是 Scenario Fixture 落后于正式 Schema，而不是正式 Schema 错误。

必须统一修复：

```text
tests/scenario/
tests/fixtures/scenarios/
tests/domain_conformance/
tests/integration_demo/
```

要求 Scenario Builder / Fixture Builder 构造出来的配置天然满足当前正式 Schema。

不要在每个测试里临时 patch：

```python
payload["market"]["fees"] = ...
```

如果大量测试都需要相同 Fee Pack，应建立一个**新的正式测试 Fixture Factory**，例如：

```text
only_test_fee_pack_config(...)
only_generic_t0_market_config(...)
```

名称可以自行设计，但必须符合以下原则：

```text
Fixture 负责构造合法当前配置
Production Parser 不负责兼容旧测试
```

---

# 5. `NONE` Fee 语义必须重新审查

当前旧测试可能期待：

```yaml
fees:
  mode: NONE
```

PR4.1 已经删除旧 Mode 模型。

必须首先回答：

> 当前系统中“无费用市场”应该如何从第一性原则表达？

正确方向应是：

```text
显式 Fee Policy Pack
```

例如一个合法的：

```text
ZERO_FEE_CONFORMANCE
```

或者正式 Policy Pack 中没有适用于当前交易的 Fee Rule。

不要重新加入：

```text
mode = NONE
```

若当前 `OnlyFeePolicyPack` 要求 `market_schedules` 非空，则根据当前设计判断：

* 是应该允许显式 Zero-Fee Policy；
* 还是通过一条经济金额为零的显式 Fee Rule；
* 或通过正式 Empty-Applicable-Policy 语义。

必须选择一个单一设计，并写 ADR/测试说明。

不要为了测试方便创造第二套 Fee Pipeline。

---

# 6. Unknown Fee Pack / Schedule 必须 Fail Closed

当前已知有类似测试：

```text
unknown broker fee schedule should fail runtime build
```

但旧测试可能仍通过已经不存在的：

```yaml
brokers:
  fees:
    mode: MODEL
    schedule: UNKNOWN
```

这个测试语义已经过时。

必须重新定义真正应验证的错误：

```text
unknown Fee Policy Pack
unknown Fee Policy Pack version
Fee Pack incompatible with Market Profile
invalid schedule resolution
```

例如：

```text
pack_id = UNKNOWN
→ FEE_PACK_NOT_INSTALLED

known pack_id + unknown version
→ FEE_PACK_NOT_INSTALLED

pack incompatible with market
→ explicit compatibility failure
```

删除旧 Broker Fee Schedule 配置测试。

---

# 7. Fee Event 语义统一

当前旧 Recovery 测试可能仍期待：

```text
FEE_RECORDED
```

而 PR4.1 已经转向：

```text
Fee Assessment
Fee Accrual
Fee Application
Fee Application Ledger
```

必须检查当前正式 Durable Trade Outbox 中真正的 Fee Event 类型。

搜索：

```text
FEE_RECORDED
FEE_APPLIED
FEE_APPLICATION
FEE_ADJUSTED
```

确认：

1. 当前唯一正式 Fee Event 是什么。
2. 是否由 Durable Runtime Transaction 产生。
3. Recovery 是否重放同一 Event。
4. 是否不存在 Manager 直接再发一份旧 Event。
5. Tests 是否仍引用历史事件。

若 `FEE_RECORDED` 已正式删除：

> 删除所有旧 Event Expectation。

不得恢复 Alias Event。

---

# 8. Runtime 构造边界清理

当前有旧 Runtime Test 直接构造：

```python
OnlyRuntimeAssemblyConfig(
    ...
    market_rule_engine=None,
    fee_policy_pack=None,
)
```

然后期待 Runtime 正常运行。

PR4.1 之后若正式架构要求：

```text
Market Rule Engine
+
Fee Policy Pack
```

这是 Runtime 最低权威依赖，则旧测试应迁移。

不得为了旧测试在：

```text
OnlyBacktestRuntime
```

内部创建默认 Market Rule Engine 或 Fee Pack。

应该：

* 更新 Runtime Test Factory。
* 更新 Runtime Fixture。
* 更新测试 Helper。
* 保证所有 Product-level Runtime 都通过正式 Assembler 获得配置。

同时审查是否仍有大量测试绕过：

```text
OnlyEngine
OnlyRuntimeFactory
OnlyRuntimeAssembler
```

直接手工 new Runtime。

单元测试可以直接测试 Runtime，但必须构造完整合法依赖。

---

# 9. MiniQMT 测试环境隔离

当前一个已知失败来自：

```text
MiniQMT path not found:
C:\国金证券QMT交易端\userdata_mini
```

但测试本意使用 Fake/Patched MiniQMT。

必须定位：

```text
为什么测试已经 patch source/client
但 Plugin Lifecycle 仍然访问真实 Windows 路径
```

这是测试隔离或 Plugin Factory 边界问题。

正确修复目标：

```text
unit/integration test without external marker
    永远不能依赖真实 QMT 安装路径
```

必须保证：

```text
requires_local_qmt
requires_broker_account
external
```

才允许访问真实路径。

不能通过：

```text
CI 上创建假的 Windows 路径
```

来绕过。

也不能把真实 MiniQMT Path Validation 全局关闭。

应修复测试 Dependency Injection / Fake Plugin / Factory Boundary。

---

# 10. Fee Pack 与 Market Profile Compatibility 验证

检查 Runtime Assembly 当前是否真正验证：

```text
Fee Policy Pack.compatible_market_profiles
```

如果当前：

```text
require(pack_id, version)
```

成功后并未验证 Market Profile Compatibility，则这是 production defect，应在本任务直接修复。

要求：

```text
config.market.profile
        ↓
FeePolicyPack
        ↓
assert profile in compatible_market_profiles
```

否则：

```text
FEE_PACK_MARKET_PROFILE_INCOMPATIBLE
```

Fail Closed。

增加测试：

```text
GENERIC_MARGIN_FUTURES pack
+
GENERIC_T0_CASH market
→ fail
```

不能只靠“正确配置不会这样写”。

---

# 11. Fee Pack Registry 稳定性检查

审计：

```text
OnlyFeePolicyPackRegistry
```

必须保证：

### Duplicate identity + same fingerprint

明确语义：

```text
注册两次同一个版本
```

是：

```text
duplicate error
```

还是：

```text
idempotent no-op
```

只能有一个明确规则。

### Same identity + different fingerprint

必须：

```text
FEE_POLICY_PACK_FINGERPRINT_CONFLICT
```

### Unknown Pack

必须：

```text
FEE_PACK_NOT_INSTALLED
```

### Pack ordering

Registry 行为不允许依赖注册顺序。

增加 deterministic tests。

---

# 12. Runtime Fee Pack 注册来源审计

确认当前 Built-in Fee Pack 是在哪一层注册：

```text
runtime/defaults.py
assembler
component registry
```

检查是否存在：

```text
某些 Runtime Factory 隐式注册
某些 Test Fixture 再次注册
某些 Example 使用自己的 Fee Registry
```

最终要求：

```text
一个正式 Built-in Component Registry
```

由：

```text
Engine Assembly
```

统一使用。

Test 可以安装额外 Test Pack，但不能改变生产默认 Registry。

---

# 13. Generic Conformance Pack 边界检查

本任务不要求正式实现 CN A-share Fee Pack。

但必须检查当前：

```text
GENERIC_T0_CASH_CONFORMANCE
```

是否暂时兼容：

```text
CN_A_SHARE_CASH
```

若确实存在这种过渡设计：

* 不需要在 Stabilization 中强制拆除；
* 但必须明确记录为下一阶段 Technical Debt；
* 不得继续扩大其用途；
* Tests 必须清晰标记这是 Conformance Pack，不是正式 A 股 Fee Authority。

任何 Test 名称不得让它看起来像：

```text
official_cn_ashare_fee
```

---

# 14. Architecture Guard

增加明确架构测试，禁止旧 Fee 接口重新出现。

扫描生产代码：

```text
src/onlyalpha/
packages/
```

禁止以下模式：

```text
fixed_commission
default_commission_rate
legacy_fee
fee_mode
fees.mode
broker_fee_schedule config
commission_rate in Runtime config
fee calculation in Account
fee calculation in Strategy Ledger
fee calculation in Settlement
```

需要注意：

测试数据/ADR 中可以出现字符串说明，但 Architecture Guard 应针对生产模块和正式配置类。

---

# 15. Order Fee Authority 不允许退化

Stabilization 过程中必须确保以下 PR4.1 成果不被破坏。

Order Snapshot 仍正式包含：

```text
OnlyOrderFeePolicyBinding
OnlyOrderFeeEstimate
OnlyOrderFundingPlan
```

Order Submit 前必须安装 Fee Contract。

不能为了旧测试允许：

```text
Order without Fee Binding
→ Submitted
```

已有 Fail-Closed：

```text
ORDER_FEE_BINDING_REQUIRED
```

必须继续保持。

增加/保留对应测试。

---

# 16. Durable Fee Authority 不允许退化

确保 Trade Fill Durable Projection 仍包含：

```text
ORDER_FEE_ACCRUAL
FEE_LEDGER
ACCOUNT
STRATEGY_LEDGER
SETTLEMENT
```

检查 Projection Order 不因 Stabilization 修改而变化。

尤其禁止：

```text
为了旧测试方便
直接 FeeManager.record()
```

或者：

```text
AccountManager 重新计算 commission
```

Fee 必须仍通过：

```text
Fee Engine
→ Assessment
→ Accrual
→ Application
→ Durable Projection
```

进入经济状态。

---

# 17. Recovery 基线必须重新验证

完成 Full Test 修复后，必须单独运行：

```bash
uv run python scripts/test_suite.py recovery
```

验证至少：

```text
Fill commit before crash
Projection partial failure
Projection ready
Outbox pending
Restart
Checkpoint restore
Multiple fills
Partial fill
Long close
Fee accrual
Fee ledger
Account
Strategy ledger
Settlement
Risk
Valuation
```

全部仍保持：

```text
Forward Recovery
No rollback
No duplicate authority
No double fee
No duplicate outbox
```

Stabilization 不允许通过降低 Recovery Test 覆盖来获得绿色。

---

# 18. A-share Conformance 基线

单独运行：

```bash
uv run python scripts/test_suite.py ashare
```

检查 A 股相关测试因 Fee Schema 改动是否全部正式迁移。

必须保证：

```text
Reference Authority
Market Rules
Pre-trade Decision
Settlement
Fee Pack Selection
```

没有被 Generic Test Fixture 意外绕过。

---

# 19. Test Lane 重构

当前 `FULL` Lane 如果已经包含：

```text
recovery
conformance
```

而 Release 又再次运行：

```text
FULL
RECOVERY
ASHARE
```

则存在重复执行。

重新设计 Test Lane。

建议：

```text
FAST
INTEGRATION
CORE_FULL
RECOVERY
ASHARE
MINIQMT_CONTRACT
MINIQMT_LOCAL
RELEASE
```

可以保留命令名 `full`，但语义必须清晰。

推荐定义：

```text
FULL / CORE_FULL
=
所有非 external
非 network
非 performance
非 recovery
非 conformance
```

然后：

```text
RELEASE
=
Static
+ FULL
+ RECOVERY
+ ASHARE
+ Build
```

Nightly：

```text
FULL
+ RECOVERY
+ ASHARE
+ Determinism Exhaustive
+ Metrics
+ Build
```

必须确保：

> 同一高成本 Recovery Matrix 在同一个 workflow 中不重复执行。

---

# 20. 不要盲目把慢测试变成 `slow`

不要通过给所有慢 Recovery 测试加：

```text
@slow
```

然后从主质量门禁排除的方式解决执行时间。

首先分析慢的根源：

```text
大量 Runtime bootstrap
重复 plugin discovery
重复 SQLite schema creation
重复 fixture serialization
重复 recovery baseline construction
100-run determinism 进入普通 full suite
```

优先：

```text
减少重复初始化
合理 test lane
共享 immutable expensive fixtures
拆 exhaustive 与 normal correctness
```

而不是降低覆盖。

---

# 21. Determinism Test 分层

以下类型：

```text
100 fresh instances
100 deterministic replay
large failure matrix
all projection boundaries
```

不应全部作为普通每次 Full Gate 的最低反馈路径。

保留：

### Core Determinism

少量 2~5 次验证：

```text
same input
same authority hash
same payload
same transaction
same result
```

### Exhaustive Determinism

Nightly：

```text
100-run
all projection matrix
all restart matrix
```

必须保证语义覆盖不减少，只改变执行层级。

---

# 22. Performance Warning 体系检查

当前大量：

```text
PERFORMANCE WARNING:
unit test ... took > 1s
integration test ... took > 10s
```

需要区分：

```text
Correctness Gate
Performance Observation
Performance Regression Gate
```

不要把普通 correctness test 的机器噪声直接当稳定性能 Gate。

但需要输出统计：

```text
Top 20 slowest unit tests
Top 20 slowest integration tests
Top 20 slowest recovery tests
```

并识别 3~5 个最明显重复初始化热点。

本 PR 可以做低风险测试基础设施优化，但不要为了性能重构 Runtime Business Authority。

---

# 23. CI 基线

检查：

```text
.github/workflows/quality.yml
.github/workflows/nightly.yml
```

目标：

## Layered Quality

至少包含：

```text
Static
Core Full
Recovery Smoke / Full Recovery
A-share
Build
```

根据耗时合理并行。

## Nightly

包含：

```text
Exhaustive Recovery
Determinism
Full Conformance
Performance Metrics
Build
```

必须避免：

```text
main gate 第一阶段失败
→ 后续所有重要测试都 skipped
```

如果不同 Lane 逻辑独立，优先使用并行 Jobs，而不是串联导致一个普通失败完全遮蔽其他质量信息。

---

# 24. 测试失败必须分类报告

最终 Implementation Report 必须附表：

| Failure               | 分类                    | 原因                              | 修复                           |
| --------------------- | --------------------- | ------------------------------- | ---------------------------- |
| scenario fee missing  | stale fixture         | PR4.1 新 schema 强制 Fee Pack      | 更新 Scenario Factory          |
| FEE_RECORDED expected | stale test            | old Fee event removed           | 更新 Durable Event expectation |
| MiniQMT path          | test isolation defect | fake plugin仍走真实 path validation | 修复 DI                        |
| ...                   | ...                   | ...                             | ...                          |

不接受：

```text
updated tests
```

这种模糊总结。

---

# 25. 删除历史接口

搜索并删除本次稳定化确认已经不再有效的：

```text
legacy tests
legacy fixtures
old fee config examples
old event expectations
compat helper
deprecated comments
stale docs
```

特别注意名字含：

```text
legacy
compatibility
old_fee
fee_mode
commission_config
```

若文件实际只是历史测试而不代表现架构，直接删除。

不要保留：

```text
“以后可能有用”
```

的死接口。

---

# 26. 文档更新

至少更新：

```text
docs/adr/
docs/reports/
ROADMAP or equivalent project roadmap
```

增加一个：

```text
PR4.1 Stabilization Report
```

内容：

1. PR4.1 后正式 Fee Config Schema。
2. 当前唯一 Fee Authority Chain。
3. 被删除的旧 Schema。
4. 被删除的旧 Event。
5. Test Lane 新定义。
6. 当前 CI Baseline。
7. 下一阶段明确未解决事项。

不要在 Stabilization Report 中声称已经解决：

```text
formal CN A-share production Fee Pack
durable external fee reconciliation
Live Runtime
broker statement ingestion
multi-market durable execution
```

除非本 PR 实际做了。

---

# 27. 明确记录但不要在本 PR 扩 Scope 的问题

Stabilization 期间如果确认以下问题存在，只记录为下一阶段，不要偷偷扩成大重构：

```text
Market Fee Pack 与 Broker Fee Contract 尚未完全分离

Schedule applicability 尚未完整使用
market / venue / instrument_class / broker / account scope

Binding fingerprint authority proof 尚未完全闭合

External Fee Reconciliation 尚未完整 Runtime Projection

Generic T0 Fee Pack 暂时兼容 CN_A_SHARE_CASH

Futures fee basis provider 尚未正式产品化

Live Runtime unsupported

Paper restart unsupported
```

除非某项直接导致当前错误或违反当前 Authority Invariant，否则不要在 Stabilization 中大规模实现。

本 PR 的作用是：

> 建立干净基线，为下一 PR 提供可信起点。

---

# 28. 修改顺序

必须按以下阶段执行。

## Commit 1 — Pre-Stabilization Audit

只做审计和报告。

输出：

```text
current master SHA
current test status
failure classification
stale schema inventory
stale event inventory
runtime assembly inconsistencies
test lane duplication
```

不得先改代码再倒推审计。

---

## Commit 2 — Fee Config / Fixture Migration

完成：

```text
Scenario
Fixtures
Examples
Test Builders
Config Tests
```

统一迁移到：

```text
market.fees.pack_id
market.fees.pack_version
```

删除旧 Fee Mode 测试。

---

## Commit 3 — Runtime Assembly Stabilization

解决：

```text
missing formal MarketRule/FeePack dependencies
unknown pack fail-closed
pack compatibility validation
test Runtime builders
```

不要增加隐式默认。

---

## Commit 4 — Fee Event / Durable Expectation Stabilization

统一：

```text
Fee Application Ledger
Runtime Transaction Outbox
Recovery tests
Artifact expectations
```

删除历史 `FEE_RECORDED` 语义。

---

## Commit 5 — Plugin Test Isolation

解决 MiniQMT 等：

```text
non-external test
→ zero dependency on local installation
```

---

## Commit 6 — Test Lane Consolidation

重构：

```text
full
recovery
ashare
nightly
release
```

消除重复执行。

---

## Commit 7 — Architecture Guards + Documentation

增加：

```text
legacy Fee API guards
config schema guards
runtime dependency guards
final stabilization report
roadmap update
```

---

# 29. 验收测试

最终必须实际执行，不允许只根据单测推断。

```bash
uv sync --frozen --all-packages --all-groups
```

然后：

```bash
uv run ruff check src tests examples packages scripts
```

```bash
uv run ruff format --check src tests examples packages scripts
```

```bash
uv run mypy src/onlyalpha
```

```bash
uv run mypy \
  --config-file packages/provider/onlyalpha-plugin-tushare/pyproject.toml \
  packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare
```

```bash
uv run mypy \
  --config-file packages/provider/onlyalpha-plugin-miniqmt/pyproject.toml \
  packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt
```

然后：

```bash
uv run python scripts/test_suite.py fast
```

```bash
uv run python scripts/test_suite.py integration
```

```bash
uv run python scripts/test_suite.py full
```

```bash
uv run python scripts/test_suite.py recovery
```

```bash
uv run python scripts/test_suite.py ashare
```

```bash
uv build --all-packages
```

如果修改了 Lane 名称，则使用最终等价命令，并在报告中列出。

---

# 30. 必须达到的最终状态

最终不得存在：

```text
Full failures
Recovery failures
A-share failures
Static failures
Build failures
```

不得存在：

```text
market.fees omission fallback
fees.mode compatibility
old broker fee config
default implicit Fee Pack
old Fee Event aliases
Runtime auto-create Fee authority
non-external MiniQMT test requiring local QMT
```

---

# 31. 核心架构验收

最终必须证明：

### Config

```text
Every Runtime
→ explicit Market Profile
→ explicit Fee Policy Pack
```

### Order

```text
Order
→ explicit Fee Binding
→ explicit Estimate
→ explicit Funding Plan
```

### Fill

```text
Fill
→ Fee Engine
→ Assessment
→ Accrual
→ Application
```

### Durable

```text
Application
→ Runtime Transaction
→ FEE_LEDGER Projection
→ Account
→ Strategy Ledger
→ Settlement
```

### Recovery

```text
Committed Fee Authority
→ Forward Recovery
→ no duplicate fee
```

### Tests

```text
Tests represent current architecture
not historical architecture
```

---

# 32. Definition of Done

PR4.1 Stabilization 只有同时满足以下条件才算完成：

* [ ] 当前 `master` 真实失败全部重新确认。
* [ ] 所有失败逐个分类。
* [ ] 旧 Fee Config Schema 从正式测试和 Examples 中删除。
* [ ] `market.fees.pack_id/version` 成为唯一正式入口。
* [ ] Missing Fee Pack Fail Closed。
* [ ] Unknown Fee Pack Fail Closed。
* [ ] Fee Pack / Market Profile Compatibility Fail Closed。
* [ ] 不存在隐式默认 Fee Pack。
* [ ] 旧 Fee Event Expectation 删除。
* [ ] Durable Fee Projection 不退化。
* [ ] Order Fee Binding 不退化。
* [ ] MiniQMT 普通 CI 测试不访问真实安装路径。
* [ ] Scenario Fixtures 全部迁移。
* [ ] Runtime Fixtures 全部迁移。
* [ ] Full 通过。
* [ ] Recovery 通过。
* [ ] A-share 通过。
* [ ] Static 通过。
* [ ] Build 通过。
* [ ] Test Lane 不重复执行完整 Recovery/Conformance。
* [ ] Architecture Guards 阻止旧 Fee API 回归。
* [ ] Stabilization Report 完成。
* [ ] 下一阶段 Technical Debt 明确记录。
* [ ] 没有新增任何 Legacy/Compat Fee Path。

---

# 33. 最终实施报告格式

完成后必须输出：

## 1. Baseline

```text
Before SHA
After SHA
```

## 2. Pre-change Failures

逐项列出。

## 3. Root Cause Classification

分别统计：

```text
stale test
stale fixture
production defect
environment isolation defect
CI design defect
```

## 4. Deleted Legacy Surface

精确列出：

```text
old configs
old tests
old helpers
old events
old fixtures
```

## 5. Production Changes

列出所有实际生产代码变化及原因。

## 6. Test Infrastructure Changes

说明：

```text
Scenario Factory
Runtime Fixture
Test Lane
Plugin Fake
```

如何变化。

## 7. Final Architecture

画出：

```text
Config
→ Fee Pack
→ Order Binding
→ Fill Fee
→ Durable Projection
→ Recovery
```

## 8. Test Results

精确报告：

```text
Fast
Integration
Full
Recovery
A-share
Static
Build
```

实际 pass/fail 数量和耗时。

## 9. Remaining Technical Debt

明确写：

```text
NOT implemented in PR4.1 Stabilization
```

包括至少：

```text
Market Fee / Broker Contract split
Durable external fee reconciliation
formal CN A-share production fee pack
Live Runtime
Paper restart
multi-market durable execution
```

---

# 34. 最终原则

本任务不要优化：

```text
最少代码修改
旧测试继续不改
历史配置继续可用
旧 Fixture 继续复用
短期全部兼容
```

本任务只优化：

```text
一个正式 Fee Config Schema

一个正式 Fee Policy Pack Authority

一个正式 Order Fee Binding

一个正式 Fill Fee Calculation Chain

一个正式 Durable Fee Application Chain

一个正式 Recovery Path

一个当前架构一致的 Test Baseline

一个可信的绿色 master
```

当：

```text
历史测试
```

与：

```text
当前正确架构
```

冲突时，

**删除或重写历史测试。**

当：

```text
历史配置
```

与：

```text
当前正式 Schema
```

冲突时，

**删除历史配置。**

当：

```text
兼容性
```

与：

```text
清晰 Authority Boundary
```

冲突时，

**选择 Authority Boundary。**

PR4.1 Stabilization 的最终目的不是：

> “让 b4969e3 的测试重新变绿。”

而是：

> **证明 b4969e3 所建立的新 Fee Authority 架构已经完整接管整个仓库，并让 OnlyAlpha 重新拥有一个可以安全继续演进的可信 master。**
