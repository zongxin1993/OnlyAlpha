# Codex Prompt — P4-0 Runtime Composition & Execution Hygiene Closure

## 任务名称

**P4-0 — Runtime Composition & Execution Hygiene Closure**

中文：

**P4-0：Runtime 组合 Authority 与 Execution 历史债务收口**

目标仓库：

```text
https://github.com/zongxin1993/OnlyAlpha
```

规划基线：

```text
7604b0a2e3cc36cfe581d7fcec263369471fdd66
Chore: Udpate 0.3.5
```

P3 业务基线：

```text
746d656a...
Feat: CN A-Share Production Fee Product
```

开始实现前，必须重新读取最新 `master`。

如果仓库已经前进：

1. 以最新 `master` 为唯一事实基线；
2. 重新审计本 Prompt 涉及的全部模块；
3. 已经被正确解决的问题不得重复实现；
4. 不得为了符合本 Prompt 而恢复已删除接口；
5. 如果最新实现与本 Prompt 提议的具体类名不同，但第一性原则已经满足，应保留更好的现有实现；
6. Implementation Report 必须记录：

   * Prompt baseline；
   * actual implementation baseline；
   * baseline differences；
   * 已提前完成的内容；
   * 因最新代码结构而调整的设计。

---

# 1. P4-0 的定位

P4-0 不是新的市场功能阶段。

P4-0 不负责：

```text
让 CN_A_SHARE_CASH 进入 DURABLE_TRADE
```

也不负责：

```text
实现新的 Trade Planner
实现新的 A-share Execution Path
Paper Recovery
Live Trading
```

P4-0 的根本目的是：

> **在正式进入 P4 CN A-Share Durable Execution 之前，把 Runtime 如何分组、共享资源如何判定、Mutable Authority 如何唯一、Component Registry 由谁拥有、Cluster Composition 如何原子提交，以及 Execution 生产代码中遗留的历史路径全部收口。**

当前 Kernel 已经具有较成熟的：

```text
Immutable Planning
        ↓
Prepared Runtime Transaction
        ↓
Durable Commit
        ↓
Ordered Projection
        ↓
Projection Ready
        ↓
Forward Recovery
```

P4-0 不重构这套 Kernel。

P4-0 解决的是它的上游：

```text
Config
   ↓
Environment Identity
   ↓
Runtime Planning
   ↓
Infrastructure Ownership
   ↓
Composition
   ↓
Runtime Assembly
```

---

# 2. 第一性原则

本阶段所有设计必须从以下原则推导。

---

## 2.1 一个 Mutable Identity 只能对应一个 Mutable Authority

例如：

```text
account_id = ACCOUNT-001
```

如果它在同一个 Engine 中出现：

```text
Broker Contract A
```

和：

```text
Broker Contract B
```

不能简单理解成：

```text
Runtime A 有一个 ACCOUNT-001
Runtime B 也有一个 ACCOUNT-001
```

这会形成：

```text
One Logical Identity
→ Multiple Mutable Authorities
```

违反 OnlyAlpha 的 Authority 原则。

正确语义必须是：

```text
Same Mutable Identity
+
Different Economic Authority
→ CONFIGURATION CONFLICT
```

除非未来显式引入：

```text
Account Namespace / Environment Scope
```

P4-0 不做这个扩展。

---

## 2.2 Runtime Compatibility 只能有一个事实来源

当前不能继续存在：

```text
RuntimePlanner
    自己定义一套 compatibility fingerprint

InfrastructureRegistry
    又定义一套 resource fingerprint
```

这必然随着功能增长发生漂移。

必须变成：

```text
Canonical Environment Authority
        │
        ├── Runtime Planner
        │
        └── Infrastructure Registry
```

二者消费同一个 Identity。

---

## 2.3 Runtime Planner 负责“分组”，不负责定义业务 Authority

Runtime Planner 的职责应该是：

```text
Environment Identity
        ↓
group equivalent configs
        ↓
build runtime plan
```

它不应该知道：

```text
Broker Fee Contract 哪些字段重要
Reconciliation Policy 哪些字段重要
A-share Reference 怎么 fingerprint
DataSource coverage 怎么 fingerprint
```

这些属于 Environment Identity Builder。

---

## 2.4 Infrastructure Registry 负责“冲突”，不负责重新解释 Config

Infrastructure Registry 应回答：

```text
Resource Key 已经存在吗？

如果存在：
    fingerprint 是否一致？
```

而不是重新回答：

```text
Account Contract 是否属于 identity？

DataSource Coverage 是否重要？
```

这些必须由 Canonical Resource Identity 决定。

---

## 2.5 Authority Definition 必须只有一个 Owner

如果：

```text
OnlyEngineServices
```

和：

```text
OnlyEngineRunAssembler
```

都能独立持有一套 Component Registries，

那么系统只是：

```text
“默认情况下恰好是同一对象”
```

而不是：

```text
“结构上只能有一个 Authority”
```

必须达到：

> **One Authority by Construction，不能只是 One Authority by Convention。**

---

## 2.6 Composition 修改必须具备事务语义

Cluster Load 不应该：

```text
先修改 Registry
↓
再验证后续配置
↓
失败
↓
Registry 留下残留 Authority
```

正确模型：

```text
Parse
↓
Normalize
↓
Resolve
↓
Validate
↓
Stage
↓
Commit
```

在 Commit 前不得修改正式 Engine Composition State。

---

## 2.7 Registry 应保持 append-only / immutable Authority 语义

不要为了补偿错误顺序新增：

```text
unregister()
rollback_register()
remove_authority()
```

作为常规路径。

正确方式是：

```text
先完成所有验证
最后一次提交
```

---

## 2.8 生产源码不是 Git 历史仓库

已经删除的 Execution 实现：

```text
不应该以三引号字符串
不应该以 commented-out code
不应该以 deprecated wrapper
```

继续存在。

Git 已经保存历史。

没有当前职责的旧接口应直接删除。

---

## 2.9 CI 也是工程反馈 Authority

如果：

```text
Recovery Lane
```

因为 dependency mirror 失败而根本没有运行测试，

不能描述成：

```text
Recovery failed
```

也不能认为：

```text
业务 Regression 已证明
```

CI 必须能区分：

```text
Environment/Dependency Failure

vs

Test Failure
```

并尽可能做到工具链确定性。

---

# 3. 当前需要解决的已知问题

开始修改前必须重新验证以下问题是否仍然存在。

---

## 3.1 RuntimeCompatibilityKey 与 InfrastructureRegistry 的 Account Identity 不一致

当前审计发现：

Runtime Compatibility Account Identity 包含：

```text
account_id
gateway_id
initial_cash
broker_fee_contract
```

但遗漏：

```text
fee_reconciliation_policy
```

而 Infrastructure Account fingerprint 包含：

```text
gateway_id
initial_cash
fee_reconciliation_policy
```

却遗漏：

```text
broker_fee_contract
```

这意味着同一个 Account Environment 被两个模块赋予了不同定义。

这是 P4-0 必须根治的问题。

---

## 3.2 DataSource Runtime Identity 过弱

当前 Runtime Compatibility 对 DataSource 主要依据：

```text
data_version
```

但 Infrastructure Registry 会考虑：

```text
plugin
enabled
version
coverage
extensions
```

因此理论上：

```text
DataSource A
DataSource B
```

只要 `data_version` 相同，就可能被 Runtime Planner 错误合并。

随后 Runtime Assembly 使用：

```text
first = configs[0]
```

作为 Runtime Shared Infrastructure 的来源。

这只有在：

```text
Compatibility Identity 已经完整证明 shared environment 相同
```

时才是合法的。

当前证明不足。

---

## 3.3 Component Registries 存在双重 Ownership

重新确认：

```text
OnlyEngineServices
```

是否仍单独持有：

```text
data_sources
brokers
market_fee_packs
broker_fee_contracts
fee_reconciliation_policies
...
```

同时：

```text
OnlyEngineRunAssembler
```

内部又持有：

```text
OnlyComponentFactoryRegistries
```

如果是：

必须收敛。

---

## 3.4 Broker Contract Provisioning 可能污染失败的 Cluster Load

确认：

```text
add_cluster()
```

是否仍然：

```text
register Broker Fee Contract
↓
acquire Infrastructure
↓
validate
↓
register Cluster
```

如果后续失败而 Contract 已进入 Registry：

这是 Authority Residue。

必须修复。

---

## 3.5 Execution 中存在已删除 Legacy Path 的死源码

审计：

```text
execution/processor.py
execution/*
```

是否仍存在：

```text
_unmigrated_trade
removed non-durable trade
triple-quoted legacy mutation body
_removed_fee_resolution_path
```

以及相关：

```text
dead helper
dead import
dead enum state
```

无职责的全部删除。

---

## 3.6 `LEGACY_UNMIGRATED` 是否还有真实语义

审计：

```text
OnlyExecutionCapability.LEGACY_UNMIGRATED
```

是否仍对应一条实际执行路径。

如果：

```text
不存在 Legacy execution implementation
```

那么这个状态不应该继续存在。

应该：

```text
UNSUPPORTED
+
structured reason
```

而不是保留一个描述历史开发阶段的 production enum。

---

## 3.7 CI Dependency Source / Toolchain 不够确定

重新检查：

```text
pyproject.toml
.github/workflows/*
uv.lock
```

当前是否仍：

```text
全局默认使用 TUNA mirror
```

以及：

```text
setup-uv 没有 pin uv version
```

如果 GitHub Actions 的某 Lane 因 mirror 403/timeout 而失败：

修复 CI 的依赖获取策略。

不要修改 Recovery 业务测试来掩盖 CI 基础设施失败。

---

## 3.8 Roadmap 当前事实与历史日志混合

如果：

```text
docs/roadmap.md
```

仍同时存在：

```text
P3 未完成
```

和：

```text
P3 已完成
```

等冲突描述：

必须重写为当前事实视图。

---

# 4. P4-0 的目标架构

最终希望形成：

```text
                            Cluster Config
                                 │
                                 ▼
                     Canonical Normalization
                                 │
                                 ▼
                    Runtime Environment Builder
                                 │
                                 ▼
                  OnlyRuntimeEnvironmentIdentity
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
              ▼                  ▼                  ▼
       Runtime Planner    Resource Registry   Composition Planner
              │                  │                  │
              │                  │                  ▼
              │                  │             Stage / Validate
              │                  │                  │
              └──────────────────┼──────────────────┘
                                 ▼
                              Commit
                                 │
                                 ▼
                         Runtime Assembly
```

最重要的变化：

```text
Environment Builder
```

成为：

> **“这些 Config 是否属于同一个 Runtime / Resource Authority”**

的唯一定义者。

---

# 5. 新增 Canonical Runtime Environment Model

建议新增：

```text
src/onlyalpha/runtime/environment.py
```

如果最新目录结构更适合：

```text
src/onlyalpha/composition/environment.py
```

也可以。

不要为了这次重构创建大型新的 package hierarchy。

该模块原则上只包含：

```text
immutable identity types

pure canonicalization

pure fingerprint builders
```

不得：

```text
创建 Runtime
修改 Registry
访问 Broker
访问 DataSource
产生 mutable state
```

---

# 6. Canonical Fingerprint Utility

开始建立 Environment Identity 前，先审计项目是否已经有统一的：

```text
canonical fingerprint
```

工具。

如果已有满足要求：

直接复用。

如果目前多个模块分别：

```text
json.dumps(default=str)
repr()
custom normalize
sorted tuple
```

则收敛成一个正式 utility。

建议语义：

```text
Decimal
    → canonical decimal string

Enum
    → stable value

date/datetime
    → normalized ISO representation

Mapping
    → keys sorted

set/frozenset
    → canonical sorted sequence

tuple/list
    → ordered sequence

dataclass/value object
    → explicit projection
```

最终：

```text
canonical payload
↓
canonical JSON
↓
SHA-256
```

不要依赖：

```text
repr()
object memory address
dict insertion order
Python hash()
```

---

# 7. DataSource Environment Identity

建议定义类似：

```python
@dataclass(frozen=True, slots=True)
class OnlyDataSourceEnvironmentIdentity:
    source_id: str
    plugin_id: str
    enabled: bool
    data_version: str
    coverage_fingerprint: str
    config_fingerprint: str
```

字段根据当前 Config 实际模型调整。

关键原则：

> 所有会改变 DataSource 实际输出或生命周期的共享配置都必须参与 Identity。

至少重新审计：

```text
source_id

plugin ID

enabled

data version

coverage

extensions/provider config
```

---

# 8. DataSource 的反例必须进入测试

以下不能因为 `data_version` 相同而被认为相同：

```text
Source A:
    plugin = Tushare
    data_version = V1
    coverage = SSE

Source B:
    plugin = MiniQMT
    data_version = V1
    coverage = SZSE
```

Environment Identity 必须不同。

---

# 9. Broker Environment Identity

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyBrokerEnvironmentIdentity:
    gateway_id: str
    plugin_id: str
    enabled: bool
    config_fingerprint: str
```

根据当前 Broker Config 纳入真正影响行为的字段，例如：

```text
plugin
gateway identity
extensions
execution mode
endpoint/environment
```

如果当前某些字段只属于 Cluster-local metadata：

不要纳入。

---

# 10. Account Environment Identity

这是 P4-0 的关键类型。

建议至少表达：

```python
@dataclass(frozen=True, slots=True)
class OnlyAccountEnvironmentIdentity:
    account_id: str
    gateway_id: str

    initial_currency: str
    initial_cash_fingerprint: str

    broker_fee_contract_id: str
    broker_fee_contract_version: str

    reconciliation_policy_id: str
    reconciliation_policy_version: str
    reconciliation_policy_currency: str

    fingerprint: str
```

具体字段使用项目现有强类型。

---

# 11. Account Identity 必须覆盖所有经济 Authority

至少：

```text
Broker Gateway

Initial Economic State

Broker Fee Contract Selection

Fee Reconciliation Policy Selection
```

都属于 Account Environment。

以后如果新增真正影响 Account mutable economics 的：

```text
Margin Agreement
Borrow Agreement
Tax Profile
Settlement Account
Base Currency Policy
```

必须从这个统一 Authority 模型扩展，而不是另一个模块自己加 fingerprint。

---

# 12. Selection Identity 与 Resolved Identity 的区别

P4-0 不要把这两个概念混淆。

Config 阶段只有：

```text
Broker Contract ID + Version

Reconciliation Policy ID + Version + Currency
```

而 Assembly 阶段可以得到：

```text
Resolved Contract Fingerprint

Resolved Policy Fingerprint
```

如果当前架构适合，可以建立两层：

```text
OnlyAccountEnvironmentSelection

OnlyResolvedAccountEnvironmentIdentity
```

但不要为了形式而增加无必要类型。

最重要的是：

```text
Runtime grouping
```

和：

```text
resource conflict
```

使用同一语义基础。

---

# 13. Reference Environment Identity

目前 A-share Reference 是明显的 Composition Leak。

P4-0 不要求完成 P5 的 Reference Provider 抽象。

但必须让：

```text
Reference Authority
```

成为通用 Runtime Environment Identity 的一个组成部分。

例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyReferenceEnvironmentIdentity:
    authority_kind: str
    authority_fingerprint: str
```

A 股可以暂时：

```text
authority_kind = CN_A_SHARE_REFERENCE
```

Generic 可以使用当前适合的通用 Identity。

不要再把：

```text
if profile == CN_A_SHARE_CASH
```

写进 Runtime Compatibility fingerprint 逻辑。

---

# 14. Market Environment Identity

建议表达：

```python
@dataclass(frozen=True, slots=True)
class OnlyMarketEnvironmentIdentity:
    profile_id: str
    profile_version: str | None

    overrides_fingerprint: str

    market_fee_pack_id: str
    market_fee_pack_version: str

    reference: OnlyReferenceEnvironmentIdentity

    fingerprint: str
```

根据当前真实 Config 调整。

---

# 15. 为什么 Market Fee Pack 必须属于 Runtime Environment

下面两个环境：

```text
CN_A_SHARE_CASH
+
Fee Pack v1
```

和：

```text
CN_A_SHARE_CASH
+
Fee Pack v2
```

会产生不同经济结果。

它们不能被 Runtime Compatibility 当成同一个环境。

---

# 16. Persistence Environment Identity

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyPersistenceEnvironmentIdentity:
    backend: str
    checkpoint_enabled: bool
    config_fingerprint: str
```

至少审计：

```text
MEMORY
SQLITE

checkpoint config

storage path / namespace
```

是否应该影响 Runtime Environment。

不要把：

```text
output formatting
```

这类非 Runtime semantic 配置混进去。

---

# 17. Clock / Replay Environment

当前已有：

```text
start_time
end_time
clock_policy
replay_policy
```

继续纳入 Runtime Identity。

如果当前已有正式 Value Object：

复用。

不要重新创建第二套 Clock Identity。

---

# 18. 最终 OnlyRuntimeEnvironmentIdentity

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyRuntimeEnvironmentIdentity:
    runtime_type: ...

    clock: ...
    replay: ...

    data_sources:
        tuple[OnlyDataSourceEnvironmentIdentity, ...]

    brokers:
        tuple[OnlyBrokerEnvironmentIdentity, ...]

    accounts:
        tuple[OnlyAccountEnvironmentIdentity, ...]

    market:
        OnlyMarketEnvironmentIdentity

    persistence:
        OnlyPersistenceEnvironmentIdentity

    fingerprint: str
```

所有集合必须 canonical sort。

排序必须使用：

```text
stable semantic key
```

不能依赖 Config 输入顺序。

---

# 19. Runtime ID 由 Environment Identity 派生

P4-0 后必须明确：

```text
Runtime ID
=
Runtime Type
+
Runtime Environment Fingerprint
```

RuntimePlanner 不再：

```text
临时拼字符串
临时 hash 某几个字段
```

---

# 20. Cluster-local 字段不能污染 Runtime Environment

必须明确区分：

```text
Runtime-shared Environment
```

与：

```text
Cluster-local Configuration
```

以下通常不应进入 Runtime Environment：

```text
cluster_id

strategy type/config

indicator config

factor config

cluster-local capital/allocation metadata
```

前提是这些字段没有改变共享 Runtime Resource。

必须有反向 Architecture/Unit Test：

```text
只改变 Strategy
→ same Runtime Environment Identity
```

---

# 21. RuntimePlanner 重构

当前 Planner 如果仍自己构造：

```text
source_versions
broker_environment
account_environment
market_environment
```

这些逻辑应删除。

目标：

```python
class OnlyRuntimePlanner:
    def plan(self, configs):
        groups = {}

        for config in configs:
            environment = self._environment_builder.build(config)

            groups.setdefault(environment, []).append(config)

        ...
```

Planner 只做：

```text
group
assign runtime id
build plan
```

---

# 22. Environment Builder 必须是 Pure

类似：

```python
class OnlyRuntimeEnvironmentBuilder:
    def build(
        self,
        config: OnlyClusterRunConfig,
    ) -> OnlyRuntimeEnvironmentIdentity:
        ...
```

禁止：

```text
修改 Registry

动态 install Contract

创建 Runtime

打开 Broker

读取 Market Data
```

它只从已存在的：

```text
Config / normalized selections / reference fingerprints
```

构造 Identity。

---

# 23. `first = configs[0]` 必须成为已证明安全的行为

如果 Planner Group 最终仍使用：

```python
representative = configs[0]
```

构造 shared Runtime Assembly：

必须先有 invariant：

```text
for every config in group:
    environment_builder.build(config)
        == group.environment
```

否则：

```text
INTERNAL_RUNTIME_GROUPING_INVARIANT_VIOLATION
```

Fail Closed。

---

# 24. 不要隐含依赖 first config

最好进一步把 Runtime Assembly 需要的 Shared Config：

```text
直接从 Environment / canonical group plan
```

生成。

如果当前改动会过大：

可以暂时保留 representative config，

但必须通过正式 invariant 证明：

```text
任何 representative 都得到同一 shared environment
```

---

# 25. InfrastructureRegistry 重构

当前如果存在：

```text
_source_projection()
_broker_projection()
_account_projection()
```

等自己定义语义的函数：

删除。

Infrastructure Registry 应消费 Canonical Resource Identity。

例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyResourceClaim:
    resource_type: OnlyResourceType
    resource_key: str
    fingerprint: str
```

然后：

```python
acquire(claim)
```

---

# 26. InfrastructureRegistry 的最终职责

只需要：

```text
Resource key 不存在
→ acquire

Resource key 已存在且 fingerprint 相同
→ refcount++

Resource key 已存在但 fingerprint 不同
→ RESOURCE_CONFIGURATION_CONFLICT
```

它不需要理解：

```text
Broker Fee Contract
Reconciliation Policy
DataSource Coverage
```

---

# 27. Runtime Compatibility 与 Global Resource Conflict 必须区分

这是 P4-0 非常重要的设计。

两个 Config Environment 不同：

```text
不一定表示系统非法
```

可能只是：

```text
分成两个 Runtime
```

但某些共享 Mutable Identity 冲突：

```text
必须全局 Fail Closed
```

所以必须分成两层：

```text
Runtime Environment Compatibility
```

和：

```text
Global Mutable Identity Conflict
```

---

# 28. 合法 Separate Runtime 示例

例如：

```text
Cluster A
    DataSource = Tushare
    Account = ACCOUNT-A

Cluster B
    DataSource = Synthetic
    Account = ACCOUNT-B
```

可以：

```text
Runtime A
Runtime B
```

---

# 29. 非法 Global Mutable Identity 示例

例如：

```text
Cluster A
    account_id = ACCOUNT-001
    Broker Contract = CONTRACT-A

Cluster B
    account_id = ACCOUNT-001
    Broker Contract = CONTRACT-B
```

不应该：

```text
Runtime A + Runtime B
```

应该：

```text
ACCOUNT_AUTHORITY_CONFLICT
```

同理：

```text
same Account
different reconciliation policy
```

应根据当前 Account Identity 原则 Fail Closed。

---

# 30. 建议建立 Global Mutable Resource Key

例如：

```text
ACCOUNT:<account-id>

BROKER:<gateway-id>

DATASOURCE:<source-id>
```

然后：

```text
key
+
canonical fingerprint
```

用于 Infrastructure Registry 冲突检查。

---

# 31. 同一 Account ID 的经济语义必须完整进入 fingerprint

Account Resource Fingerprint 至少包括：

```text
gateway

initial state/currency

broker fee contract selection

reconciliation policy selection
```

不要再出现：

```text
Runtime Planner 有 Contract

Infrastructure Registry 没 Contract
```

这种漂移。

---

# 32. EngineServices Registry Ownership 收口

重新审计：

```text
OnlyEngineServices
OnlyEngineRunAssembler
OnlyComponentFactoryRegistries
```

目标是：

```text
One Registry Object Graph
```

结构上只能有一套。

---

# 33. 推荐方案 A：EngineServices 只持有 Assembler

例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyEngineServices:
    assembler: OnlyEngineRunAssembler
    plugin_discovery: OnlyPluginDiscoveryReport
```

Assembler：

```python
class OnlyEngineRunAssembler:
    components: OnlyComponentFactoryRegistries
```

Engine 任何地方需要组件：

```text
services.assembler.components
```

---

# 34. 推荐方案 B：EngineServices 持有 Components，Assembler 引用同一个 Components

如果现有依赖关系更适合：

```python
@dataclass(frozen=True, slots=True)
class OnlyEngineServices:
    components: OnlyComponentFactoryRegistries
    assembler: OnlyEngineRunAssembler
```

则必须由 constructor invariant 保证：

```text
assembler.components is services.components
```

但这仍然比方案 A 弱。

优先选择：

> 结构上无法产生两套 Registry 的方案。

---

# 35. 禁止 Compatibility Property 保留旧字段

如果删除：

```text
services.broker_fee_contracts
services.market_fee_packs
services.brokers
...
```

不要保留：

```python
@property
def broker_fee_contracts(self):
    return self.components.broker_fee_contracts
```

仅为了旧调用兼容。

应该：

```text
修改所有调用点
删除旧 public surface
```

除非该 Property 本身有明确新的架构职责。

---

# 36. Composition Atomicity

建议新增：

```text
OnlyClusterCompositionPlan
```

或当前架构最匹配的不可变 Plan。

例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyClusterCompositionPlan:
    cluster_id: OnlyClusterId

    normalized_config: OnlyClusterRunConfig

    environment:
        OnlyRuntimeEnvironmentIdentity

    authority_installations:
        tuple[OnlyAuthorityInstallation, ...]

    resource_claims:
        tuple[OnlyResourceClaim, ...]

    fingerprint: str
```

---

# 37. Composition Phase

正式流程：

```text
Raw Config
    ↓
Validate Config
    ↓
Normalize
    ↓
Resolve existing authorities
    ↓
Parse new authority documents
    ↓
Validate all new authorities
    ↓
Build Environment Identity
    ↓
Build Resource Claims
    ↓
Check Global Conflicts
    ↓
Build immutable Composition Plan
```

这整个过程：

```text
NO ENGINE MUTATION
```

---

# 38. Commit Phase

只有：

```text
composition.commit(plan)
```

可以修改正式状态。

Commit 内容可能包括：

```text
install validated new authorities

acquire resource claims

register cluster config

publish cluster composition state
```

必须保证逻辑原子性。

---

# 39. Commit 前应完成所有可能失败的业务验证

尽可能把：

```text
plugin availability

broker contract validity

resource fingerprint conflicts

market pack compatibility

reference completeness

capital validation

extension contract validation
```

全部放在 staging/plan 阶段。

这样 Commit 本身尽量只剩：

```text
已验证对象的 deterministic insertion
```

---

# 40. 如果 Commit 内仍可能失败怎么办

如果仍有内存写入步骤可能抛异常：

应该：

1. 重新设计 commit order，使不可失败步骤靠后；
2. 或一次构造新的 immutable state 后 swap；
3. 不优先给每个 Registry 增加 rollback API。

例如可以：

```text
copy current registry state
+
apply staged changes to copy
+
validate
+
replace state
```

具体实现按当前 Registry 架构决定。

不要为了“事务”过度构造数据库框架。

---

# 41. Failed Composition 不得留下 Authority Residue

必须有测试：

```text
Cluster A config

contains:
    new Broker Contract X@1

later validation fails

assert:
    X@1 NOT installed
    Cluster NOT registered
    resource claim NOT acquired
```

然后修正 Contract：

```text
X@1
different fingerprint
```

重新提交：

```text
must succeed
```

不能因为第一次失败留下污染而发生 fingerprint conflict。

---

# 42. Execution Hygiene — 删除 dead legacy implementation

审计：

```text
src/onlyalpha/execution/
```

删除所有：

```text
triple-quoted old implementation

commented-out old mutation path

_removed_*
_unmigrated_* body

legacy fee-resolution code

dead helper

dead import
```

没有当前业务职责的一律删除。

---

# 43. `LEGACY_UNMIGRATED` 审计

如果当前：

```text
OnlyExecutionCapability.LEGACY_UNMIGRATED
```

仅表达：

```text
这条能力以前没迁移
```

但现在没有 Legacy Route：

删除该枚举值。

不要保留一个描述项目历史的生产状态。

---

# 44. Capability 更合理的长期结构

P4-0 不需要完成 P4 的 Capability Redesign。

但如果删除 `LEGACY_UNMIGRATED` 需要替代：

可以暂时保持：

```text
DURABLE_TRADE
DURABLE_TERMINAL
UNSUPPORTED
```

并使用现有错误码表达具体原因。

不要现在顺手建立完整：

```text
OnlyExecutionCapabilityDecision
```

除非现有代码已经需要。

P4 再正式处理 capability-driven execution。

---

# 45. P4-0 禁止修改 Generic Profile Gate 来支持 A 股

禁止：

```python
if profile in {
    "GENERIC_T0_CASH",
    "CN_A_SHARE_CASH",
}:
```

禁止删除 `_PROFILE_ID` 后顺手让所有 Profile 通过。

P4-0 完成时：

```text
CN_A_SHARE_CASH Durable Execution
仍然可以是 unsupported
```

这是正确状态。

---

# 46. P4-0 不重新设计 TradePlanner

除非为删除 dead code 必须做最小修改。

以下属于 P4：

```text
profile-neutral trade planning

capability-driven execution

CN A-share BUY OPEN

CN A-share SELL CLOSE

T+1 execution conformance
```

P4-0 不做。

---

# 47. CI Determinism Audit

检查：

```text
.github/workflows/quality.yml
pyproject.toml
uv.lock
```

特别确认：

```text
uv version
Python version
dependency index
parallel lane sync behavior
```

---

# 48. Pin uv

如果当前：

```yaml
uses: astral-sh/setup-uv@v7
```

未指定 uv version：

为 CI 固定一个明确版本。

使用最新 `master` 当前已经验证可工作的版本。

不要凭 Prompt 猜具体版本。

在实施时查询 CI 成功 Lane 中实际 uv version，选择正式 pinned value。

---

# 49. CI Dependency Index

如果项目全局：

```toml
[[tool.uv.index]]
url = "https://pypi.tuna.tsinghua.edu.cn/simple"
default = true
```

导致 GitHub Actions 外网环境出现：

```text
403
```

不要简单增加：

```text
retry 20 次
```

解决。

应重新定义：

```text
Project default dependency source
```

与：

```text
developer-local mirror preference
```

的边界。

---

# 50. 推荐原则

GitHub Actions：

```text
使用稳定公开源 / project canonical source
```

国内开发：

```text
通过用户本地 uv/pip 配置
或显式环境变量
使用 TUNA
```

不要把地域性 Mirror 作为：

```text
Repository Global Authority
```

除非它确实是项目正式制品源。

---

# 51. 不要修改 Lockfile 语义来绕过镜像问题

如果：

```text
uv.lock
```

本身正确：

不要通过：

```text
删除 frozen
```

绕开。

CI 必须继续：

```text
uv sync --frozen
```

---

# 52. Recovery Lane Failure Classification

CI/报告中必须明确：

```text
dependency sync failed
```

不等于：

```text
recovery test failed
```

Implementation Report 要记录：

```text
Recovery:
NOT RUN due to dependency infrastructure
```

或者真正修复后：

```text
Recovery:
xxx passed
```

不能模糊描述。

---

# 53. Roadmap Cleanup

`docs/roadmap.md` 应改造成当前真相，而不是累计历史日志。

建议结构：

```text
# Current Product Truth

# Completed Phases

# Current Phase

# Next Phase

# Later
```

---

# 54. Completed Phases

例如：

```text
P0 — Test Baseline & Feedback Loop Closure
P1 — Fee Authority Integrity Closure
P2 — Fee Reconciliation Semantic Closure
P2.1 — Reconciliation Composition Stabilization
P3 — CN A-Share Production Fee Product
```

---

# 55. Current Phase

P4-0：

```text
Runtime Composition & Execution Hygiene Closure
```

明确：

```text
CN A-share Durable Execution
still not enabled
```

---

# 56. Next Phase

```text
P4 — CN A-Share Durable Execution Product Closure
```

---

# 57. 历史阶段细节移出 Roadmap

之前的大量：

```text
当时问题
当时下一阶段
旧 status
```

应保留在：

```text
docs/reports/
docs/adr/
Git history
```

Roadmap 不重复。

---

# 58. Pre-Implementation Audit

开始写代码前必须生成：

```text
docs/reports/
p4_0_runtime_composition_pre_implementation_audit.md
```

至少包含：

```text
Baseline

Current Runtime Compatibility Model

Current Infrastructure Identity Model

Current Registry Ownership Graph

Current Cluster Add / Remove lifecycle

Current Broker Contract provisioning path

Current Runtime ID derivation

Current DataSource grouping semantics

Current Account grouping semantics

Current Market/reference grouping semantics

Current global resource conflict semantics

Current dead Execution paths

Current CI failure classification

Current roadmap drift

Exact interfaces to delete
```

---

# 59. 建议新增 ADR

新增：

```text
docs/adr/
<next>-runtime-environment-authority.md
```

ADR 必须回答：

```text
What is a Runtime Environment?

What is a shared resource?

What is a mutable global identity?

When do configs share a Runtime?

When do configs require separate Runtimes?

When is separate Runtime forbidden and conflict required?

Who owns resource identity semantics?

Who owns Component Registries?

Why Composition is staged before commit?

Why Registry rollback/unregister is not the chosen model?
```

---

# 60. Runtime Compatibility Test Matrix

必须建立矩阵，而不是零散补案例。

---

## DataSource

逐个变化：

```text
source_id

plugin_id

enabled

data_version

coverage

extensions
```

对于影响实际共享 DataSource 的字段：

```text
Environment fingerprint must change
```

---

## Broker

逐个变化：

```text
gateway_id

plugin_id

extensions/config

enabled state
```

同 logical Broker ID 不同 semantic config：

```text
resource conflict
```

---

## Account

逐个变化：

```text
account_id

gateway_id

initial currency

initial cash if part of initial authority

broker fee contract ID

broker fee contract version

reconciliation policy ID

reconciliation policy version

reconciliation policy currency
```

必须明确：

```text
same account_id
+
different mutable economic authority
→ conflict
```

---

## Market

逐个变化：

```text
profile ID

profile version

overrides

market fee pack ID

market fee pack version

reference authority fingerprint
```

相应 Runtime Environment Identity 必须变化。

---

## Persistence

逐个变化：

```text
MEMORY / SQLITE

checkpoint enabled

persistence path/namespace

other semantic config
```

---

# 61. Cluster-local Negative Tests

只改变：

```text
cluster_id

strategy config

factor config

indicator config
```

如果不影响 shared infrastructure：

```text
Runtime Environment Identity
must remain equal
```

否则说明 Runtime Identity 污染了 Cluster-local semantics。

---

# 62. Registration-order Determinism

配置：

```text
Cluster A
Cluster B
```

加载顺序：

```text
A → B
```

和：

```text
B → A
```

在 shared Runtime environment 相同情况下必须得到：

```text
same Runtime Environment Fingerprint

same Runtime ID

same final Runtime grouping
```

---

# 63. Collection Order Determinism

以下集合输入顺序变化：

```text
DataSources

Brokers

Accounts
```

如果语义相同：

Fingerprint 必须相同。

必须 canonical sort。

---

# 64. Account Global Authority Conflict Tests

至少：

### Case A

```text
ACCOUNT-001
Contract A
Policy X
```

和：

```text
ACCOUNT-001
Contract B
Policy X
```

→ conflict。

### Case B

```text
ACCOUNT-001
Contract A
Policy X
```

和：

```text
ACCOUNT-001
Contract A
Policy Y
```

→ conflict。

### Case C

完全相同：

→ resource sharing/refcount。

---

# 65. Runtime Grouping Test

如果：

```text
Market/DataSource/Persistence 不同
```

但没有 Global Mutable Identity Conflict：

允许产生两个 Runtime。

必须测试：

```text
different environment
→ different runtime IDs
```

---

# 66. `first = configs[0]` Invariant Test

如果当前实现保留 representative config：

构造错误 grouping 测试，证明任何 Environment 不一致都会在 assembly 前：

```text
fail closed
```

而不是：

```text
默默使用 first config
```

---

# 67. Registry Ownership Test

构造 Custom Engine Services。

必须在类型/constructor 层无法做到：

```text
Engine writes Registry A
Assembler reads Registry B
```

最好这种错误状态：

```text
cannot be constructed
```

而不是：

```text
运行时检测
```

---

# 68. Atomic Composition Tests

至少：

### Test 1

```text
new Broker Contract
+
later config validation failure
```

结果：

```text
no contract installed
no cluster registered
no resource acquired
```

### Test 2

第一次失败后：

```text
same contract ID/version
corrected fingerprint
```

第二次：

```text
success
```

证明没有 residue。

### Test 3

resource conflict：

```text
no partial authority installation
```

---

# 69. Remove Cluster / Refcount Regression

P4-0 改 Infrastructure Registry 后必须保证：

```text
Cluster A+B share resource

remove A
→ resource remains

remove B
→ resource released
```

不能破坏现有 refcount lifecycle。

---

# 70. Execution Dead Code Guard

新增 architecture/source guard：

禁止生产 `src/onlyalpha/execution/` 出现：

```text
removed non-durable
legacy mutation path
""" ... old implementation ...
_unmigrated_trade
_removed_fee_resolution_path
```

具体搜索词根据实际删除内容设置。

---

# 71. No Compatibility Layer Guard

禁止：

```text
LegacyRuntimeCompatibilityKey

OldInfrastructureFingerprint

CompatEnvironmentIdentity

DeprecatedEngineServiceRegistryAccess

LegacyUnmigratedExecutionAdapter
```

没有真实职责就不允许出现。

---

# 72. 不保留旧 RuntimeCompatibilityKey 包装层

如果：

```text
OnlyRuntimeCompatibilityKey
```

已经完全被：

```text
OnlyRuntimeEnvironmentIdentity
```

取代：

直接删除旧类型。

不要：

```python
OnlyRuntimeCompatibilityKey = OnlyRuntimeEnvironmentIdentity
```

不要 deprecated alias。

---

# 73. 但不要为了名字强制删除有新职责的类型

如果最新代码证明：

```text
OnlyRuntimeCompatibilityKey
```

本身非常适合作为 canonical Environment Identity 名称，

可以保留名字并重构其实现。

原则是：

```text
One semantic authority
```

不是：

```text
必须叫某个新名字
```

---

# 74. Error Codes

根据当前 Error System 增加最小必要错误。

建议语义：

```text
RUNTIME_ENVIRONMENT_CONFLICT

ACCOUNT_AUTHORITY_CONFLICT

DATASOURCE_RESOURCE_CONFLICT

BROKER_RESOURCE_CONFLICT

REFERENCE_AUTHORITY_CONFLICT

RUNTIME_GROUPING_INVARIANT_FAILED

COMPOSITION_PLAN_CONFLICT
```

如果已有：

```text
RESOURCE_CONFIGURATION_CONFLICT
```

足够表达，优先复用。

不要为 P4-0 重构全项目 Error System。

---

# 75. 错误信息必须包含可审计 identity

例如 Account Conflict 应至少包含：

```text
account_id

existing environment fingerprint

requested environment fingerprint
```

但不要把敏感 Broker config/token 写进错误。

---

# 76. Production Source Cleanup

P4-0 完成后执行：

```text
ruff
unused imports
dead helper scan
```

删除：

```text
旧 projection helper

旧 fingerprint helper

旧 Runtime key builder

旧 Registry aliases

dead execution helpers

stale comments
```

不要留下：

```text
TODO remove later
deprecated for compatibility
```

除非是真实未来工作，而不是已完成迁移。

---

# 77. 模块边界要求

完成后职责应该清晰为：

```text
runtime/environment.py
    defines canonical Runtime environment semantics

runtime/planning.py
    groups configs by environment

engine/infrastructure.py
    manages global resource claims/refcounts/conflicts

engine/composition.py
    plans and commits cluster composition

runtime/assembler.py
    instantiates already validated runtime objects

execution/*
    only contains current execution semantics
```

不要让：

```text
planning.py
```

知道 Broker Fee Contract 内部字段。

不要让：

```text
infrastructure.py
```

知道 Reconciliation Policy 内部字段。

---

# 78. P4-0 非目标：Reference Provider Neutralization

虽然 P4-0 会把：

```text
reference authority fingerprint
```

正式纳入 Runtime Environment，

但不要现在完整实现：

```text
OnlyReferenceAuthorityProviderRegistry
```

也不要删除所有：

```text
ashare_*
```

Config 字段。

这属于 P5。

P4-0 只建立正确 identity boundary。

---

# 79. P4-0 非目标：Execution Capability Redesign

不要在本阶段完成：

```text
Market Capability
∩
Engine Capability
→ Durable Trade
```

P4 再做。

P4-0 只删除遗留死路径。

---

# 80. P4-0 非目标：A-share Durable Execution

结束时必须保持：

```text
CN_A_SHARE_CASH Durable Execution
NOT ENABLED
```

如果测试为了方便需要：

```text
不要新增 test-only production bypass
```

---

# 81. P4-0 非目标：Multi-account Product

虽然 Environment Model 要能够正确描述多个 Account Config，

但不要因此开放：

```text
Backtest multiple Accounts
```

当前产品限制继续保留。

这里是在修：

```text
identity correctness
```

不是扩产品 Capability。

---

# 82. P4-0 非目标：Multi-broker / Multi-source Product

同理。

Environment Identity 应正确，但 Backtest Factory 仍可以继续要求：

```text
one enabled Broker
one enabled DataSource
```

不要混淆：

```text
Architecture can model
```

和：

```text
Product formally supports
```

---

# 83. P4-0 非目标：Paper / Live

不修改：

```text
Paper checkpoint unsupported
Live unsupported
```

除非 Composition API 改名导致机械调用点更新。

不得顺手开放能力。

---

# 84. 推荐 Commit 顺序

建议 P4-0 拆成清晰的提交。

---

## Commit 1 — Audit + ADR

建议：

```text
Docs: Freeze Runtime Environment Authority
```

内容：

```text
pre-implementation audit

ADR

compatibility matrix

authority ownership decisions
```

生产行为不改。

---

## Commit 2 — Canonical Environment Identity

建议：

```text
Refactor: Introduce Canonical Runtime Environment Authority
```

内容：

```text
canonical fingerprint utility

resource identity value objects

runtime environment identity

unit tests
```

暂时可与旧 Planner 并行用于验证。

不要 Compatibility Wrapper。

---

## Commit 3 — Runtime Planner Migration

建议：

```text
Refactor: Plan Runtimes from Canonical Environment Identity
```

完成：

```text
remove duplicated compatibility projections

Runtime ID derived from environment

group invariants

registration order tests
```

然后删除旧 compatibility implementation。

---

## Commit 4 — Infrastructure Identity Migration

建议：

```text
Refactor: Unify Infrastructure Resource Identity
```

完成：

```text
InfrastructureRegistry consumes canonical resource claims

remove duplicated _*_projection fingerprint logic

account economic authority conflicts
```

---

## Commit 5 — Registry Ownership Closure

建议：

```text
Refactor: Enforce Single Component Registry Ownership
```

完成：

```text
collapse EngineServices/Assembler duplicate registry surfaces

update all call sites

delete aliases
```

---

## Commit 6 — Atomic Cluster Composition

建议：

```text
Fix: Make Cluster Composition Authority-Atomic
```

完成：

```text
OnlyClusterCompositionPlan

stage / validate / commit

failed load leaves no residue

authority provisioning atomicity tests
```

---

## Commit 7 — Execution Hygiene

建议：

```text
Chore: Delete Removed Legacy Execution Paths
```

完成：

```text
remove dead mutation source

remove meaningless LEGACY_UNMIGRATED if appropriate

delete orphan helpers/imports

architecture guards
```

---

## Commit 8 — CI Determinism

建议：

```text
Chore: Stabilize Quality Toolchain
```

完成：

```text
pin uv

fix canonical dependency source for CI

retain frozen lock behavior

run all lanes
```

---

## Commit 9 — Roadmap + Final Report

建议：

```text
Docs: Close P4-0 Runtime Composition Authority
```

完成：

```text
rewrite roadmap current truth

implementation report

exact gate results

next phase P4
```

---

# 85. 每个 Commit 要求

不要：

```text
一个 8000 行 mega commit
```

也不要为了 commit 数量人为把：

```text
无法独立测试的半迁移状态
```

提交。

每个 Commit 应：

```text
有明确 invariant
有对应 tests
删除已经替代的旧代码
```

---

# 86. Static Gates

执行当前最新正式命令。

至少：

```bash
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages scripts

uv run ruff format --check src tests examples packages scripts

uv run mypy src/onlyalpha
```

以及当前所有正式 provider mypy。

---

# 87. Test Lanes

至少：

```bash
uv run python scripts/test_suite.py fast

uv run python scripts/test_suite.py integration

uv run python scripts/test_suite.py core-full

uv run python scripts/test_suite.py recovery

uv run python scripts/test_suite.py ashare

uv run python scripts/test_suite.py miniqmt-contract

uv run python scripts/test_suite.py exhaustive
```

如果当前 `master` 已更新 lane：

使用最新正式命令。

---

# 88. Build

```bash
uv build --all-packages
```

必须 PASS。

---

# 89. 不允许通过 Gate 的方式

禁止：

```text
skip

xfail

删 recovery test

降低 Environment identity assertion

允许 Account conflict fallback

保留两套 fingerprint 以兼容

允许 Registry fallback

删除 --frozen

把 CI retry 设置为无限

把 dependency failure 当业务测试通过
```

---

# 90. Recovery 回归

虽然 P4-0 不修改 Runtime Transaction Kernel，

仍必须完整跑 Recovery。

尤其检查：

```text
Runtime ID / Environment fingerprint
```

改变后是否影响：

```text
checkpoint restore

runtime identity validation

authority fingerprint restoration
```

如果 persisted Runtime Identity Schema 改变：

明确升级对应 Schema。

---

# 91. Schema 原则

不要机械升级所有 Schema。

如果：

```text
Runtime Compatibility Key
```

只是内部 planning object，不持久化：

不升级 persisted schema。

如果：

```text
Runtime Environment Fingerprint
```

进入 checkpoint/result/artifact persisted contract：

才升级对应 schema。

---

# 92. 不写旧 Schema 自动迁移

当前 Alpha 阶段：

如果旧 Runtime Environment persisted identity 已不正确：

```text
Fail Closed
```

不要：

```text
自动补 missing reconciliation policy
自动补 Broker Contract
```

这会重新引入隐式 Authority。

---

# 93. Architecture Guards

必须新增明确 Guard：

### Guard 1

生产代码只存在一个 Runtime shared-resource fingerprint Authority。

### Guard 2

`InfrastructureRegistry` 不重新解释 Account/Broker/DataSource config 字段。

### Guard 3

`RuntimePlanner` 不直接读取：

```text
broker_fee_contract fields
fee_reconciliation_policy fields
ashare registry internals
```

它只消费 Environment Identity。

### Guard 4

不存在 duplicated Engine Service Registry ownership。

### Guard 5

Execution 不保留 removed legacy source。

---

# 94. Runtime Identity Snapshot Tests

建议建立 human-readable snapshot：

```text
tests/reference_data/runtime_environment_identity/
```

或者普通 unit fixtures。

至少测试：

```text
canonical payload
fingerprint
runtime id
```

对于代表性环境：

```text
Generic T0 Memory

CN A-share Memory

CN A-share SQLite

different Broker Contract

different Reconciliation Policy
```

---

# 95. Fingerprint 不应该成为 opaque magic

测试失败时应该容易看出：

```text
哪个 Environment component changed
```

所以 Environment Identity 应保留 structured fields。

不要只在对象中保存：

```text
fingerprint: str
```

而丢弃组成部分。

---

# 96. Fingerprint 是 proof，不是 domain state

正式 Authority 应保存：

```text
structured semantic identity
+
fingerprint
```

而不是：

```text
只保存 hash
```

这样才能审计。

---

# 97. Implementation Report

最终新增：

```text
docs/reports/
p4_0_runtime_composition_execution_hygiene_closure.md
```

至少包括：

```text
Baseline

Root Problems

Before Architecture

Canonical Runtime Environment Model

Resource Identity Model

Global Mutable Identity Policy

Runtime Grouping Semantics

Registry Ownership Change

Atomic Composition Design

Deleted Interfaces / Dead Code

CI Determinism Changes

Schema Changes

Test Matrix

Exact Gate Results

Remaining P4 Scope
```

---

# 98. Deleted Interfaces 必须单列

报告必须明确列出：

```text
Removed Runtime Compatibility helpers

Removed Infrastructure projection helpers

Removed EngineServices registry fields

Removed legacy Execution method/body

Removed LEGACY_UNMIGRATED if applicable

Removed compatibility aliases
```

如果某一项没删除：

说明它当前仍承担什么职责。

---

# 99. Definition of Done — Runtime Environment

* [ ] Runtime shared environment 有唯一 canonical identity。
* [ ] RuntimePlanner 不再独立定义 compatibility semantics。
* [ ] InfrastructureRegistry 不再独立定义 resource semantics。
* [ ] DataSource identity 不再只依赖 data_version。
* [ ] Broker identity 覆盖影响实际行为的 config。
* [ ] Account identity 同时包含 Broker Fee Contract 与 Reconciliation Policy。
* [ ] Market identity 包含 Fee Pack 与 Reference Authority。
* [ ] Persistence identity 明确。
* [ ] Runtime ID 从 canonical Environment 派生。
* [ ] collection order 不影响 fingerprint。
* [ ] Cluster-local Strategy config 不污染 Runtime identity。

---

# 100. Definition of Done — Mutable Authority

* [ ] Same Account ID + same economic authority 可以共享。
* [ ] Same Account ID + different Broker Contract Fail Closed。
* [ ] Same Account ID + different Reconciliation Policy Fail Closed。
* [ ] 不允许通过建立两个 Runtime 绕过 Account Authority conflict。
* [ ] Resource conflict error 可审计且 deterministic。

---

# 101. Definition of Done — Registry Ownership

* [ ] Component Registries 只有一个结构性 Owner。
* [ ] Engine 不可能写 Registry A、Assembler 读 Registry B。
* [ ] 删除旧 Registry access surface。
* [ ] 不使用 compatibility properties 保留旧 API。
* [ ] Default 与 Custom Engine Services 使用同一 ownership model。

---

# 102. Definition of Done — Composition Atomicity

* [ ] Cluster Composition 有明确 plan/stage/commit。
* [ ] Commit 前不修改正式 Registry/Resource/Cluster state。
* [ ] Failed Cluster Load 不留下 Broker Contract residue。
* [ ] Failed resource conflict 不留下部分 state。
* [ ] 第二次 corrected submission 不受第一次失败污染。
* [ ] 不新增 unregister rollback hack。

---

# 103. Definition of Done — Execution Hygiene

* [ ] removed non-durable Trade implementation 已彻底删除。
* [ ] triple-quoted old implementation 不存在。
* [ ] dead fee-resolution path 不存在。
* [ ] orphan imports/helpers 已删除。
* [ ] `LEGACY_UNMIGRATED` 只有在存在真实 production semantics 时才能保留。
* [ ] 没有 compatibility legacy execution adapter。
* [ ] CN A-share Durable Execution 仍未提前开放。

---

# 104. Definition of Done — CI

* [ ] uv 版本明确固定。
* [ ] CI dependency source 在 GitHub Actions 环境稳定。
* [ ] `uv sync --frozen` 保留。
* [ ] Recovery Lane 真正执行 Recovery tests。
* [ ] dependency failure 与 test failure 在报告中明确区分。
* [ ] 所有正式 Quality Gates 绿色。

---

# 105. Definition of Done — Documentation

* [ ] Roadmap 不再同时陈述多个历史“当前状态”。
* [ ] P0–P3 位于 Completed。
* [ ] P4-0 位于 Current/Done。
* [ ] P4 是明确 Next。
* [ ] README 不宣称 CN A-share Durable Execution 已完成。
* [ ] Implementation Report 给出真实测试数字。

---

# 106. Definition of Done — Clean Architecture

* [ ] 一个 Identity 只有一个定义者。
* [ ] 一个 Registry graph 只有一个 owner。
* [ ] Runtime Planner 只做 grouping。
* [ ] Infrastructure Registry 只做 claim/refcount/conflict。
* [ ] Composition 只做 plan/validate/commit。
* [ ] Assembler 只实例化已经验证的对象。
* [ ] Runtime 只执行。
* [ ] Execution 只保留当前正式路径。
* [ ] 没有 Legacy wrapper。
* [ ] 没有 Deprecated alias。
* [ ] 没有 Dead Code。
* [ ] 没有临时 fallback。
* [ ] 没有 duplicated fingerprint logic。

---

# 107. 最终 Gate 结果必须精确记录

不要：

```text
all tests passed
```

必须写：

```text
commit SHA

ruff:
PASS

ruff format:
PASS

core mypy:
PASS

provider mypy:
...

fast:
xxx passed
x skipped

integration:
xxx passed

core-full:
xxxx passed
x skipped

recovery:
xxx passed

ashare:
xxx passed

miniqmt-contract:
xxx passed

exhaustive:
xxx passed

build:
PASS
```

同时记录 GitHub Actions 最终 Quality Gate。

---

# 108. P4-0 完成后仍明确未实现

Implementation Report 必须列出：

```text
NOT IMPLEMENTED IN P4-0
```

至少：

```text
CN A-share Durable Execution enablement

Capability-driven execution resolver

Profile-neutral Trade Planner

A-share BUY OPEN product slice

A-share SELL CLOSE product slice

T+1 durable product conformance

Market Reference Provider neutralization

Paper checkpoint/restart

Live Runtime

Durable Broker outbound command

Multi-account product

Multi-broker product

Multi-data-source product

Futures durable product

Vectorized backtest
```

---

# 109. P4-0 完成后的目标结构

完成后应达到：

```text
                        Config
                          │
                          ▼
              Canonical Runtime Environment
                          │
          ┌───────────────┼────────────────┐
          │               │                │
          ▼               ▼                ▼
     RuntimePlanner   ResourceRegistry  CompositionPlan
          │               │                │
          │               │           Validate / Stage
          │               │                │
          └───────────────┼────────────────┘
                          ▼
                     Atomic Commit
                          │
                          ▼
                    Runtime Assembly
                          │
                          ▼
                   Canonical Runtime
                          │
                          ▼
                  Durable Execution
```

---

# 110. P4-0 完成后 P4 应变得非常简单

P4-0 做正确后，P4 不应该再修：

```text
Runtime grouping

Account authority identity

Broker Contract provisioning atomicity

Component Registry ownership

legacy execution path

CI dependency source
```

P4 应只关注：

```text
Market semantics
        ∩
Canonical Durable Trading Shape
        ↓
Execution Capability
```

最终目标：

```text
GENERIC_T0_CASH
```

和：

```text
CN_A_SHARE_CASH
```

不是因为名字被允许，

而是因为：

```text
Market Instruction
Account Model
Position Model
Fee Authority
Settlement Authority
Reservation Authority
Durable Projection Capability
```

满足 Canonical Trade Kernel 的前置条件。

---

# 111. 最终工程原则

当：

```text
RuntimePlanner convenience
```

与：

```text
Canonical Environment Authority
```

冲突：

> 选择 Canonical Environment Authority。

当：

```text
两个模块各自算 fingerprint
```

与：

```text
一个语义定义
```

冲突：

> 删除重复实现。

当：

```text
same account id
```

与：

```text
different economic authority
```

冲突：

> Fail Closed。

当：

```text
先 register 再 rollback 比较方便
```

与：

```text
Stage → Validate → Commit
```

冲突：

> 选择后者。

当：

```text
保留 deprecated property 比较省调用点修改
```

与：

```text
Single Registry Ownership
```

冲突：

> 修改调用点并删除 deprecated property。

当：

```text
保留旧 Execution code 便于参考
```

与：

```text
生产代码干净
```

冲突：

> 删除旧代码，使用 Git history。

当：

```text
CI 镜像偶尔可用
```

与：

```text
Deterministic Feedback Loop
```

冲突：

> 修依赖来源和工具链。

当：

```text
现在顺手把 A 股跑起来
```

与：

```text
P4-0 Scope Boundary
```

冲突：

> 不提前开放 A 股 Durable Execution。

---

# 112. P4-0 最终定义

P4-0 不是：

> “给 RuntimePlanner 多加几个 fingerprint 字段。”

也不是：

> “修一个 CI timeout，再删点旧代码。”

P4-0 真正要完成的是：

> **建立 OnlyAlpha 唯一的 Runtime Environment Authority，使 Runtime 分组、共享资源冲突、Account Economic Identity 和 Runtime ID 全部来源于同一套 canonical semantics；同时让 Engine Composition 从易产生 Authority Residue 的顺序式 mutation 收口为 Stage/Validate/Commit，并删除 Execution 中已经失去职责的历史实现。**

最终必须成立：

```text
One mutable identity has one authority.

One runtime environment has one canonical identity.

One resource semantic has one fingerprint definition.

Runtime Planner groups; it does not redefine authority.

Infrastructure Registry detects conflicts; it does not reinterpret config.

Composition validates before it mutates.

Registries have one owner.

Failed composition leaves no residue.

Execution source contains only current execution semantics.

CI failures distinguish infrastructure from business failures.

Documentation states one current truth.

Unknown or conflicting state fails closed.
```

只有这些原则真正进入：

```text
代码
类型
Composition
Tests
CI
Architecture Guards
Documentation
```

P4-0 才算完成。

完成 P4-0 后：

> **冻结 Runtime Composition Authority，正式进入 P4 — CN A-Share Durable Execution Product Closure。P4 的工作应该只剩下把真实 A 股 Market Instruction、Production Fee、Settlement 和 Account/Position Shape 通过 capability-driven 方式接入现有 Canonical Durable Trading Kernel，而不再回头修 Runtime Composition 根架构。**
