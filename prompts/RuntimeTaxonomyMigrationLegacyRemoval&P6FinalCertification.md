# OnlyAlpha P6.6 — Runtime Taxonomy Migration, Legacy Removal & P6 Final Certification

## 0. 任务身份

你正在实现 OnlyAlpha 的：

**P6.6 — Runtime Taxonomy Migration, Legacy Removal & P6 Final Certification**

Repository:

```text
https://github.com/zongxin1993/OnlyAlpha
```

P6.6 不是新的交易功能阶段，也不是普通的代码清理任务。

它是：

> **P6 Runtime Architecture Migration 的最终迁移、删除、事实统一与认证阶段。**

P6.0–P6.5 已经逐步建立了：

- Runtime Control Plane 与 Trading Semantic Plane 边界；
- canonical `SIM` Runtime；
- realtime MarketData streaming lifecycle；
- Live Clock；
- Virtual Broker；
- full Trading Kernel；
- realtime continuity；
- historical bootstrap / historical-to-realtime handoff；
- gap detection / gap recovery；
- reconnect；
- durable checkpoint；
- same-process recovery；
- new-process restart；
- Runtime State Lease；
- post-recovery authority validation；
- verified checkpoint finalization；
- dedicated `recovery` / `sim-recovery` verification lanes。

P6.6 的任务不是重新设计这些能力。

P6.6 的任务是：

> 在不改变已经建立的 Backtest / SIM canonical trading semantics、不破坏现有 SIM durable recovery contract、不提前实现 Research 或 Live 的前提下，完成 Runtime Product Taxonomy 的 one-shot cutover，彻底删除 `PAPER` 与 standalone `SHADOW` 的 active product path，完成配置、Factory、测试、文档和架构门禁迁移，并以同一 final SHA 完成整个 P6 的最终认证。

---

# 1. 最重要原则：Repository Is Source of Truth

开始实现前必须重新完整阅读当前 Repository。

**禁止假设本 Prompt 描述的代码状态仍然完全准确。**

当前 HEAD、当前源码、正式测试、active docs、ADR、CI workflow 才是事实来源。

历史 Prompt、旧讨论和本 Prompt 本身只能作为设计背景。

首先执行：

```bash
git status
git rev-parse HEAD
git log --oneline -20
```

记录：

```text
STARTING_SHA=<current HEAD>
```

如果 working tree 不是 clean：

1. 不得覆盖用户已有修改；
2. 必须先识别已有变更；
3. 将它们与 P6.6 修改区分；
4. 不得擅自 reset / checkout / clean 用户工作。

---

# 2. Mandatory Repository Refresh

开始任何代码修改前，至少重新阅读：

```text
README.md

docs/roadmap.md
docs/architecture.md
docs/runtime.md
docs/engineering/quality-system.md

docs/adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md

src/onlyalpha/domain/enums.py

src/onlyalpha/runtime/
src/onlyalpha/runtime/defaults.py
src/onlyalpha/runtime/factory.py
src/onlyalpha/runtime/planning.py
src/onlyalpha/runtime/runtime.py

src/onlyalpha/runtime/backtest/
src/onlyalpha/runtime/sim/
src/onlyalpha/runtime/streaming/
src/onlyalpha/runtime/paper/
src/onlyalpha/runtime/shadow/
src/onlyalpha/runtime/live/
src/onlyalpha/runtime/research/

src/onlyalpha/runtime/trading/
src/onlyalpha/runtime/checkpoint/
src/onlyalpha/runtime/recovery/
src/onlyalpha/runtime/persistence/

src/onlyalpha/transaction/

src/onlyalpha/scenario/

tests/architecture/
tests/runtime/
tests/integration/
tests/scenario/
tests/execution/
tests/transaction/

scripts/test_suite.py

pyproject.toml

.github/workflows/
```

同时检查：

```text
examples/
packages/
```

中是否存在 active Runtime vocabulary 或 legacy config。

---

# 3. Mandatory Legacy Search

在修改前执行全仓搜索：

```bash
rg -n "\bPAPER\b|\bPaper\b|\bpaper\b" .
rg -n "\bSHADOW\b|\bShadow\b|\bshadow\b" .

rg -n "OnlyRuntimeMode" src tests
rg -n "OnlyPaperRuntime|OnlyPaperRuntimeFactory" .
rg -n "OnlyShadowRuntime|OnlyShadowRuntimeFactory" .
rg -n "OnlySimRuntime|OnlySimRuntimeFactory" .

rg -n "runtime\.paper|runtime/paper" .
rg -n "runtime\.shadow|runtime/shadow" .
```

将每个结果分类为：

1. production source；
2. active config/schema；
3. active tests；
4. active fixtures；
5. active examples；
6. active documentation；
7. historical ADR；
8. historical report；
9. historical prompt / migration record；
10. unrelated English word usage。

不得把所有搜索结果机械替换。

尤其禁止：

```text
全仓 PAPER → SIM
全仓 Paper → Sim
全仓 SHADOW → 删除
```

历史 ADR 和历史报告必须保留真实历史语义。

---

# 4. Engineering Priority

所有决策按以下优先级执行：

```text
正确性
>
架构一致性
>
可验证性
>
可恢复性
>
可维护性
>
性能
>
自动化程度
```

当两个目标冲突时，严格按照这个顺序选择。

例如：

```text
旧 API compatibility
```

不能高于：

```text
正确 Runtime taxonomy
```

---

# 5. P6.6 的目标 Runtime Product Taxonomy

重新确认当前 ADR 和 Repository Truth。

如果当前 Accepted ADR 没有发生新的正式变更，则目标 Runtime Product Taxonomy 必须是：

```text
RESEARCH
BACKTEST
SIM
LIVE
```

目标产品边界：

```text
RESEARCH
    Historical
    Vectorized / Batch
    Research Job lifecycle
    No formal Trading Broker/Account authority
    P7 implementation target

BACKTEST
    Historical
    Event-driven
    Backtest Clock
    Virtual Broker
    Full Trading Kernel
    Finite lifecycle

SIM
    Realtime
    Event-driven
    Live Clock
    Virtual Broker
    Full Trading Kernel
    Streaming lifecycle
    Continuity / Recovery
    Durable Checkpoint

LIVE
    Realtime
    Event-driven
    Live Clock
    Real Broker
    Full Trading Kernel
    Future P8/P9 implementation target
```

`PAPER` 是历史 migration source，不是目标长期产品。

Standalone `SHADOW` 不是目标 Runtime Product。

P6.6 完成后：

```text
PAPER Runtime Product = removed
SHADOW Runtime Product = removed
```

---

# 6. P6.6 的本质

不要把 P6.6 理解为：

```text
rename PAPER to SIM
```

正确理解是：

```text
P6.0–P6.5:
建立 canonical SIM architecture

P6.6:
确认 legacy capability ownership
→ 迁移仍有价值的通用基础设施
→ 删除旧产品 identity
→ 删除旧产品 path
→ 删除 compatibility debt
→ 固化唯一 Runtime taxonomy
→ 同步 Repository Truth
→ 加 architecture guards
→ 最终认证整个 P6
```

---

# 7. Core Architecture Invariants

以下 invariant 在整个实现过程中都必须保持。

---

## INV-001 — Single Economic Authority

不得因为 P6.6 创建新的 Runtime-specific economic manager。

禁止新增：

```text
SimOrderManager
SimPositionManager
SimAccountManager
SimRiskManager
SimReservationManager
SimExecutionProcessor
SimFeeManager
SimSettlementManager
SimTransactionManager
```

Backtest / Sim / future Live 必须继续共享 canonical Trading Kernel。

---

## INV-002 — Runtime Type != Execution Permission

Runtime Product Type 只能用于：

```text
product identity
composition
planning
grouping
driver selection
runtime lifecycle
operational configuration
```

不能用于：

```text
market legality
risk authority
economic permission
order validity
position semantics
account semantics
fee semantics
settlement semantics
```

禁止在经济语义模块中增加：

```python
if runtime_mode is OnlyRuntimeMode.SIM:
    ...
```

---

## INV-003 — Strategy Must Remain Runtime Neutral

Strategy 和 Strategy-facing Context 不得获得：

```text
runtime_mode
runtime_type
is_sim
is_backtest
is_live
is_paper
is_shadow
```

不得通过 Runtime 类型分支交易策略。

---

## INV-004 — Backtest / Sim / Live Semantic Equivalence

Backtest / Sim / future Live 的差异应主要存在于外围：

```text
MarketData Driver
Clock Driver
Broker Adapter
Lifecycle Driver
Operational Boundary
```

三者必须共享 canonical：

```text
Strategy
Market Rule
Risk
Reservation
Order
Execution Support
Execution Processor
Transaction
Projection
Position
Allocation
Account
Strategy Ledger
Fee
Settlement
Result
Recovery semantics
```

---

## INV-005 — Commit Fact First

不得破坏 canonical transaction model：

```text
Normalized Broker Fact
→ Durable Transaction
→ Ordered Projection
→ Economic State
```

P6.6 原则上不得修改 transaction/projection economic semantics。

若发现当前 HEAD 存在真实 Critical bug，只有当该问题阻塞 P6.6 correctness 时才允许最小修复，并必须明确报告。

---

## INV-006 — Forward Recovery Only

不得修改 committed history 来“迁移” Runtime taxonomy。

Recovery 应继续基于：

```text
durable facts
checkpoint
transaction tail
continuity evidence
broker deterministic state
```

向前恢复。

---

## INV-007 — Lifecycle Command != Domain Fact

以下 control-plane command：

```text
initialize
start
stop
reconnect
subscribe
unsubscribe
worker shutdown
```

不能自行创建：

```text
Market Fact
Broker Fact
Trade
Fill
Cancel
Terminal Order Fact
```

---

## INV-008 — No PAPER Compatibility Layer

严格禁止：

```python
PAPER = SIM
```

严格禁止：

```python
if value == "PAPER":
    value = "SIM"
```

严格禁止：

```text
PaperRuntime wrapper
PaperRuntime alias
deprecated PaperRuntime
PaperFactory forwarding to SIM
Paper config transparent migration
```

P6.6 是 one-shot migration。

---

## INV-009 — No Standalone SHADOW Compatibility Layer

严格禁止：

```text
ShadowRuntime alias
ShadowRuntime wrapper
Shadow Factory forwarding
OnlyRuntimeMode.SHADOW deprecated alias
```

如果未来需要：

```text
dry-run
execution suppression
observation-only
approval mode
```

应该作为明确 capability / policy 设计，而不是 standalone Runtime Product。

P6.6 不需要实现这些新 feature。

---

## INV-010 — Existing SIM Durable State Must Not Be Broken Without Cause

P6.6 是 taxonomy migration，不是 checkpoint schema redesign。

如果当前 P6.5 已经定义合法 SIM durable contract，则应保护：

```text
Runtime identity
checkpoint schema
checkpoint participant identity
persistence schema
transaction identity
projection readiness
market composition fingerprint
config fingerprint
continuity state
Virtual Broker deterministic state
```

除非当前 Repository Truth 证明 schema migration 确实不可避免，否则：

```text
不要 bump checkpoint schema
不要 bump persistence schema
不要无理由修改 serialization
不要无理由修改 runtime identity derivation
```

---

## INV-011 — Legacy PAPER Durable State Is Not SIM State

明确：

```text
legacy PAPER durable state
!=
canonical SIM durable state
```

禁止实现：

```text
Paper checkpoint → SIM checkpoint
Paper database → automatic SIM database migration
Shadow execution history → synthetic SIM transaction history
```

两者经济语义不同。

必须 fail closed，而不是猜测转换。

---

## INV-012 — Historical Truth Must Remain Historical Truth

历史 ADR、reports、migration records 中可以继续出现：

```text
PAPER
SHADOW
Paper migration
Shadow migration
```

这是合法的。

不得为了“零搜索结果”修改历史记录，让仓库看起来像从未存在过 Paper/Shadow。

---

# 8. Workstream A — Pre-Removal Capability Ownership Audit

这是 P6.6 最重要的前置工作。

**禁止先删除 `runtime/paper` 然后根据测试失败猜测缺少什么。**

必须先详细阅读：

```text
src/onlyalpha/runtime/paper/
src/onlyalpha/runtime/shadow/
src/onlyalpha/runtime/sim/
src/onlyalpha/runtime/streaming/
```

特别检查：

```text
src/onlyalpha/runtime/paper/factory.py
```

对 Paper Factory / Runtime 中每个 capability 进行 ownership 分类。

分类必须至少包括：

```text
A. 已经正式存在于 runtime/streaming/
B. 已经正式存在于 runtime/sim/
C. 属于通用 Streaming capability，但仍错误留在 paper/
D. 属于 legacy Shadow execution，应删除
E. 已无 caller / dead code，应删除
```

重点审计：

```text
LiveClock creation
MarketData source creation
historical bootstrap
historical-to-realtime handoff
subscription wiring
realtime inbound queue
aggregation
watermark
continuity
gap detection
gap recovery
reconnect
observation
streaming phase
worker lifecycle
timer lifecycle
checkpoint wiring
persistence wiring
broker wiring
Virtual Broker wiring
Shadow suppression
diagnostics
resource lifecycle
```

输出一个内部 audit matrix，例如：

```text
Capability                    Current Owner        Final Owner       Action
LiveClock                     paper/sim/...        streaming/sim     migrate/retain
Gap Recovery                  streaming            streaming         retain
Shadow suppression            paper                none              delete
Virtual Broker                sim                  sim/shared        retain
...
```

只有完成 capability ownership audit 后才能进行正式删除。

---

# 9. Workstream B — Streaming Ownership Closure

P6.6 必须最终建立：

```text
Streaming != Paper
```

`streaming/` 应代表：

> product-neutral long-running runtime control infrastructure

Streaming 可以拥有：

```text
subscription lifecycle
worker lifecycle
streaming phase
semantic lane
market continuity
watermark
gap detection
gap recovery
reconnect orchestration
timer coordination
checkpoint coordination
recovery orchestration
driver lifecycle
runtime diagnostics
processing admission
```

Streaming 不应拥有：

```text
PAPER product semantics
SHADOW product semantics
SIM-specific economic semantics
Real Broker economic semantics
Runtime-specific Trading authorities
```

目标概念结构：

```text
                     Streaming Control Plane
                              |
                   +----------+----------+
                   |                     |
                  SIM                future LIVE
                   |                     |
           Virtual Broker         Real Broker / P8
                   |                     |
                   +----------+----------+
                              |
                       Trading Kernel
```

如果 Paper Factory 中仍有 shared streaming wiring：

```text
先迁移到 neutral shared owner
再删除 Paper Factory
```

禁止复制一份进入 Sim Factory。

---

# 10. Workstream C — Runtime Taxonomy One-Shot Cutover

在 ownership audit 完成后执行正式 cutover。

最终：

```python
class OnlyRuntimeMode(StrEnum):
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    SIM = "SIM"
    LIVE = "LIVE"
```

顺序不是重要 contract，集合才是。

删除：

```text
OnlyRuntimeMode.PAPER
OnlyRuntimeMode.SHADOW
```

删除 production package：

```text
src/onlyalpha/runtime/paper/
src/onlyalpha/runtime/shadow/
```

删除：

```text
OnlyPaperRuntime
OnlyPaperRuntimeFactory

OnlyShadowRuntime
OnlyShadowRuntimeFactory
```

删除 active exports。

删除 default composition root 中：

```text
Paper Factory registration
Shadow Factory registration
```

默认 Runtime Factory Registry 最终应只包含目标产品：

```text
OnlyBacktestRuntimeFactory
OnlySimRuntimeFactory
OnlyLiveRuntimeFactory
OnlyResearchRuntimeFactory
```

其中当前实际能力可以是：

```text
BACKTEST = supported
SIM      = supported
LIVE     = explicit unsupported
RESEARCH = explicit unsupported
```

不要因为 Live / Research 尚未实现而删除它们的 target product identity。

---

# 11. Workstream D — Config / Schema / Public Contract Migration

全面审计：

```text
runtime mode
runtime type
environment identity
runtime grouping
runtime planning
config validation
schema
YAML
JSON
CLI
examples
fixtures
scenario models
public exports
serialized config snapshot
```

Active contract 中不再接受：

```text
PAPER
SHADOW
```

应 fail closed。

正确：

```text
"PAPER"
→ invalid RuntimeMode
```

错误：

```text
"PAPER"
→ warning
→ SIM
```

禁止 silent compatibility。

---

# 12. Config Migration Must Be Semantic, Not Textual

旧 Paper config 不得机械转换为 SIM。

例如旧配置：

```yaml
runtime:
  type: PAPER
```

不能仅改成：

```yaml
runtime:
  type: SIM
```

就视为迁移完成。

必须判断旧 config 的真实 workload。

---

## Case A — Realtime Simulated Trading

如果旧 Paper config 的真实用途是：

```text
Realtime MarketData
+
Strategy
+
simulated execution
```

则应迁移为完整合法 SIM composition：

```text
SIM Runtime
+ Live Clock
+ required realtime/historical DataSource capability
+ Virtual Broker
+ simulated execution capability
+ Market Product
+ persistence contract
+ full Trading Kernel
```

---

## Case B — Observation Only

如果旧 config 只用于：

```text
realtime observation
feed validation
market diagnostics
```

不要为了保留 fixture 把它伪装成 Trading SIM。

应根据当前架构：

```text
迁移到 observation/diagnostic surface
```

或者：

```text
删除 obsolete fixture
```

---

## Case C — Shadow Execution

如果旧 config 依赖：

```text
order intent creation
+
execution suppression
+
no canonical Virtual Broker facts
```

则不能直接迁移为 SIM 并保留旧 assertion。

应该：

```text
删除 legacy Shadow product test
```

或者：

```text
改造成验证 canonical SIM Virtual Broker path
```

---

# 13. Workstream E — Durable State Boundary

P6.6 必须显式保持两条边界。

第一条：

```text
Legacy PAPER durable state
!=
SIM durable state
```

不支持自动迁移。

第二条：

```text
Existing valid SIM durable state
→ P6.6
→ remains recoverable
```

如果当前正式 contract 允许，应增加 regression：

```text
create valid SIM durable state
→ close process/runtime
→ construct fresh runtime under P6.6 code
→ recover
→ verify canonical world equivalence
```

至少覆盖当前正式 recovery contract 中的重要 authority：

```text
Orders
Positions
Allocations
Accounts
Strategy Ledgers
Reservations
Risk state
Fee records
Settlement records
Runtime Transactions
Continuity state
Virtual Broker deterministic state
```

---

# 14. Workstream F — Test Migration

测试必须迁移到目标 architecture。

不能为了保持旧测试绿色而维持旧产品。

将所有 Paper/Shadow tests 分类。

---

## Category 1 — Shared Streaming Behavior

例如：

```text
continuity
watermark
subscription
reconnect
worker lifecycle
```

应迁移到：

```text
streaming-neutral test
```

或者：

```text
SIM test
```

视实际 ownership 决定。

---

## Category 2 — Useful SIM Product Behavior

迁移到正式 SIM product path。

例如：

```text
Realtime Bar
→ Strategy
→ Order
→ Virtual Broker
→ Accepted
→ Trade
→ Transaction
→ Projection
```

---

## Category 3 — Shadow Suppression Behavior

如果仅验证 legacy Shadow execution：

```text
删除
```

或者替换成正式 SIM semantics。

---

## Category 4 — Legacy Product Contract

例如：

```text
Paper Runtime can be created
Shadow Runtime can be created
```

产品本身被删除后，这类测试也应删除。

不得改成 wrapper assertion。

---

## Category 5 — Architecture Tests

重写为：

```text
target Runtime taxonomy
no legacy product
no alias
no duplicate semantic authority
```

---

# 15. Workstream G — Scenario / Product Certification

重新检查 Scenario 当前 abstraction。

如果当前 `Scenario Runner` 是 finite Backtest runner：

**不要为了形式统一强行让它承担 streaming SIM lifecycle。**

生命周期是不同的：

```text
BACKTEST
finite

initialize
→ run/replay
→ complete
```

```text
SIM
streaming

initialize
→ start
→ wait/process
→ stop
→ close
```

推荐结构：

```text
Scenario / Certification Semantic Specification
                  |
        +---------+---------+
        |                   |
 finite certification   streaming certification
      BACKTEST                   SIM
```

不要求为了 P6.6 设计复杂的新统一 Runner。

P6.6 至少要保证：

> SIM 拥有正式、deterministic、通过 public product path 的 certification coverage。

优先复用当前 P6.5 已存在的 integration/recovery tests，而不是重新实现测试框架。

---

# 16. Required SIM Certification Cases

确保当前正式测试继续证明或补充证明：

```text
SIM basic startup
SIM realtime processing
SIM Virtual Broker Accepted
SIM next-bar Fill
SIM durable transaction
SIM ordered projection

SIM stop does not create synthetic trading fact

SIM gap detection
SIM gap recovery
SIM reconnect

SIM checkpoint
SIM same-process recovery
SIM new-instance recovery
SIM new-process recovery

SIM corrupt checkpoint fail-closed

SIM state lease rejects simultaneous writer

SIM recovery checkpoint supports second restart

SIM canonical trading world remains equivalent after restart
```

---

# 17. Workstream H — Repository Truth Reconciliation

P6.6 必须把文档更新作为正式 deliverable。

重新检查：

```text
README.md
docs/roadmap.md
docs/architecture.md
docs/runtime.md
docs/engineering/quality-system.md
```

目标：

```text
active documentation
=
current production source
=
formal tests
```

任何 active docs 如果仍声称：

```text
SIM does not exist
SIM factory unavailable
SIM durable checkpoint not implemented
SIM new-process restart not implemented
PAPER is a target product
SHADOW is a target product
```

必须根据 current truth 更新。

---

# 18. ADR Handling

不要重写 ADR 历史。

特别是：

```text
docs/adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md
```

原来的 Context / Decision / Rejected Alternatives 是历史事实。

如果 P6.6 完成该 ADR 的 implementation closure，可以追加：

```text
Implementation Update
```

记录：

```text
P6.6 completion date
final SHA
PAPER Runtime removed
standalone SHADOW Runtime removed
production Runtime taxonomy reduced to RESEARCH/BACKTEST/SIM/LIVE
no compatibility alias retained
SIM remains canonical realtime Virtual Broker product
Streaming infrastructure is product-neutral
P6 final certification result
```

不要把历史 migration description 删除。

---

# 19. Roadmap Update

只有达到真实 Acceptance Criteria 后才更新 Roadmap。

Roadmap 必须区分：

```text
implemented
locally verified
remotely certified
accepted
```

不要因为代码看起来完成就提前写：

```text
DONE / CERTIFIED
```

P6 最终退出条件必须重新根据 current Roadmap 验证。

如果目标仍然包括：

```text
SIM available through formal config/factory/engine lifecycle
Shadow suppression replaced by Virtual Broker + full Trading Kernel
gap/reconnect/checkpoint/restart closed
PAPER source/config/tests/public spelling deleted
standalone SHADOW source/config/tests/public spelling deleted
no alias/deprecated spelling/compat wrapper
```

则必须全部满足。

---

# 20. Quality-System Documentation

检查：

```text
docs/engineering/quality-system.md
```

是否仍使用旧产品词，例如：

```text
Backtest / Paper / Live Semantic Consistency
```

如果 current target 已经是：

```text
Backtest / Sim / Live Trading Semantic Equivalence
```

则 active quality docs 应同步。

---

# 21. Permanent Architecture Guards

P6.6 不能只删除旧代码。

必须增加永久 architecture gate，防止未来重新引入 legacy product。

建议新增或扩展：

```text
tests/architecture/test_runtime_taxonomy_closure.py
```

具体路径遵循当前测试结构。

---

## Guard A — Exact Runtime Taxonomy

必须验证：

```python
set(OnlyRuntimeMode) == {
    OnlyRuntimeMode.RESEARCH,
    OnlyRuntimeMode.BACKTEST,
    OnlyRuntimeMode.SIM,
    OnlyRuntimeMode.LIVE,
}
```

---

## Guard B — No Legacy Runtime Production Module

确保 production 中不存在：

```text
onlyalpha.runtime.paper
onlyalpha.runtime.shadow
```

---

## Guard C — No Legacy Factory Registration

Default Runtime Registry 不得注册：

```text
Paper
Shadow
```

---

## Guard D — No Legacy Production Import

Production source 不能 import：

```text
onlyalpha.runtime.paper
onlyalpha.runtime.shadow
```

---

## Guard E — No Compatibility Alias

禁止：

```text
PAPER = SIM
PaperRuntime = SimRuntime
PaperFactory = SimFactory
ShadowRuntime wrapper
deprecated Paper config converter
```

Architecture gate 应关注：

```text
active production source
active public config
active API
```

而不是历史 ADR。

---

## Guard F — Trading Semantic Plane Remains Runtime Neutral

现有 architecture tests 中关于：

```text
Strategy Context
Trading Facade
fee
market
position
risk
order
execution
settlement
account
strategy ledger
trading kernel
```

不得读取 `OnlyRuntimeMode` 的 invariant 必须继续通过。

不要弱化这些测试。

---

## Guard G — SIM Cannot Use Real Broker

保留或强化：

```text
SIM
→ Virtual Broker / simulated execution
→ never Real Broker submission
```

---

# 22. Compatibility Cleanup Outside PAPER/SHADOW

允许处理与 P6 migration **直接相关** 的 compatibility debt。

例如：

```text
migration-only Runtime exports
legacy internal Runtime names
Paper-specific helper
Shadow-specific helper
obsolete config parser
```

但必须先搜索 caller。

对于类似：

```text
OnlyRuntimeServices = OnlyTradingKernelServices
```

这样的兼容 alias：

1. 搜索全部 caller；
2. 判断是否属于 P6 migration debt；
3. 若安全且 scope 很小，可以删除；
4. 若与 P6.6 无直接关系，记录 technical debt；
5. 不要为了“顺便整洁”扩大任务范围。

---

# 23. Forbidden Shortcuts

以下实现严格禁止。

---

## Forbidden 1 — Mechanical Rename

禁止：

```text
PAPER → SIM
```

机械全仓替换。

---

## Forbidden 2 — Delete First, Understand Later

禁止：

```text
rm runtime/paper
rm runtime/shadow
```

然后通过 broken tests 猜 architecture。

必须先完成 ownership audit。

---

## Forbidden 3 — PAPER Alias

禁止：

```python
PAPER = SIM
```

---

## Forbidden 4 — Deprecated PAPER Wrapper

禁止：

```text
OnlyPaperRuntime(...)
→ internally OnlySimRuntime(...)
```

---

## Forbidden 5 — SHADOW Alias

禁止：

```text
ShadowRuntime → SimRuntime
```

---

## Forbidden 6 — Copy Paper Factory Into Sim

禁止复制旧 Factory。

通用能力必须进入正确 shared owner。

---

## Forbidden 7 — Parallel Streaming Kernel

禁止创建：

```text
SimStreamingRuntime
SimStreamingRecovery
SimStreamingContinuity
```

作为第二套 parallel infrastructure，除非 current architecture 已经明确要求且有正式设计依据。

---

## Forbidden 8 — Runtime-Specific Economic Branch

禁止在：

```text
risk
order
position
account
fee
settlement
execution
transaction
strategy
```

加入 SIM/PAPER-specific economic branch。

---

## Forbidden 9 — Unnecessary Persistence Migration

禁止因为 taxonomy cleanup 修改：

```text
checkpoint schema
transaction schema
projection schema
persistence schema
```

除非确有必要。

---

## Forbidden 10 — PAPER State Conversion

禁止：

```text
Paper checkpoint → SIM checkpoint
```

---

## Forbidden 11 — Implement P7

不要实现：

```text
Research Job Engine
Vectorized Research
Research Artifact
Research Query API
```

---

## Forbidden 12 — Implement P8/P9

不要实现：

```text
Real Broker durable outbound command
ACK / Reject / Unknown
Broker synchronization
reconciliation
production Live Runtime
```

---

## Forbidden 13 — Large Purity Refactor

不要借 P6.6 大规模重写：

```text
OnlyRuntime
OnlyStreamingRuntime
Trading Kernel
Recovery
Transaction
Checkpoint
```

除非当前 architecture correctness 明确要求。

---

## Forbidden 14 — Weaken Tests

不得：

```text
删除关键 assertion
放宽 expected behavior
skip failing recovery test
mark xfail
扩大 exception handling
```

来掩盖 regression。

---

## Forbidden 15 — Fake Certification

禁止伪造：

```text
CI passed
coverage passed
remote certified
P6 DONE
```

必须基于真实证据。

---

# 24. Implementation Order

严格按照以下顺序工作。

---

## Phase 1 — Repository Refresh

完成：

```text
HEAD
git status
docs
ADR
runtime source
tests
CI
```

重新阅读。

---

## Phase 2 — Legacy Inventory

建立 Paper/Shadow occurrence inventory。

---

## Phase 3 — Capability Ownership Audit

确认旧 Paper Factory 中每个 useful capability 的最终 owner。

---

## Phase 4 — Shared Ownership Migration

如有必要，只迁移：

```text
仍错误归属于 Paper 的通用 streaming capability
```

不要做额外重构。

---

## Phase 5 — One-Shot Product Cutover

删除：

```text
PAPER enum
SHADOW enum
Paper Runtime
Paper Factory
Shadow Runtime
Shadow Factory
registry registration
public exports
```

---

## Phase 6 — Config / Fixture / Example Migration

语义迁移，而不是字符串替换。

---

## Phase 7 — Test Migration

迁移 shared/SIM tests，删除 obsolete product tests。

---

## Phase 8 — Architecture Guards

增加不可回退的 taxonomy gates。

---

## Phase 9 — Repository Truth Reconciliation

更新 active docs / Roadmap / ADR implementation note。

---

## Phase 10 — Full Verification

执行完整 local verification。

---

## Phase 11 — Same-SHA Remote Certification

如果有权限访问 GitHub CI，确认 final SHA 上 required checks。

---

# 25. Required Local Tests

修改过程中采用由小到大的测试策略。

首先运行受影响测试，例如：

```text
Runtime enum tests
Runtime factory tests
Runtime planner tests
SIM factory tests
Streaming tests
Scenario tests
Architecture tests
```

然后运行正式 test lanes。

不要假设命令，先读取：

```text
scripts/test_suite.py
pyproject.toml
.github/workflows/
```

根据 current repository truth 确定真实命令。

至少覆盖 current equivalent：

```text
static
format/lint
mypy/type-check
import-linter
architecture tests

build

core-full
recovery
sim-recovery

ashare
miniqmt-contract

security/static gates
```

如果当前仓库正式要求：

```text
fast
integration
coverage
release
semgrep
codeql
```

也需要获取对应证据。

---

# 26. Backtest Regression Requirements

必须证明 P6.6 没有破坏 Backtest：

```text
Historical event-driven lifecycle still works
Virtual Broker semantics unchanged
Order semantics unchanged
Transaction semantics unchanged
Projection semantics unchanged
Position/Account semantics unchanged
Fee/Settlement semantics unchanged
```

P6.6 不应该改变 Backtest canonical world。

---

# 27. SIM Normal-Path Regression Requirements

必须证明：

```text
MarketData
→ Strategy
→ Market Rule
→ Risk
→ Reservation
→ Order
→ Virtual Broker
→ Broker Fact
→ Durable Transaction
→ Ordered Projection
→ Position / Allocation / Account / Ledger / Fee / Settlement
```

保持不变。

重点验证：

```text
Bar N:
order accepted

Bar N+1:
trade/fill

transaction sequence:
deterministic

projection:
ordered

reservations:
correctly consumed/released
```

---

# 28. SIM Stop Semantics

确保：

```text
Runtime stop
```

不等于：

```text
cancel all orders
fill remaining orders
create synthetic trade
close partial live bar as market fact
mutate account arbitrarily
```

Lifecycle command 不能成为 economic fact。

---

# 29. SIM Recovery Regression Requirements

必须保留当前正式 P6.5 recovery guarantees。

至少验证：

```text
checkpoint creation
checkpoint verification
same-instance/same-process recovery where applicable
new Runtime instance recovery
new-process recovery
corrupt checkpoint fail-closed
Runtime State Lease
repeated restart
post-recovery authority validation
```

---

# 30. SIM Canonical World Equivalence

restart 前后必须验证 canonical world equivalence。

根据当前测试 contract，至少包括：

```text
Orders
Positions
Allocations
Accounts
Strategy Ledgers
Reservations
Risk state
Fee records
Settlement records
Runtime Transactions
Continuity checkpoint state
Virtual Broker checkpoint state
```

如果当前 formal contract 还包含更多 authority，也必须继续验证。

---

# 31. Legacy Source Search Acceptance

实现完成后再次运行：

```bash
rg -n "\bPAPER\b|\bPaper\b|\bpaper\b" .
rg -n "\bSHADOW\b|\bShadow\b|\bshadow\b" .
rg -n "OnlyPaperRuntime|OnlyPaperRuntimeFactory" .
rg -n "OnlyShadowRuntime|OnlyShadowRuntimeFactory" .
rg -n "OnlyRuntimeMode\.PAPER|OnlyRuntimeMode\.SHADOW" .
```

每个剩余结果必须人工解释。

Active production source / config / public API 中不得继续存在 legacy Runtime Product dependency。

剩余合法位置可以包括：

```text
historical ADR
historical report
migration documentation
explicit architecture rejection test
release history
```

---

# 32. Documentation Acceptance

P6.6 后 active docs 必须统一表达：

```text
Target Runtime Products:
RESEARCH
BACKTEST
SIM
LIVE
```

并清楚区分当前实现完成度：

```text
BACKTEST: implemented/certified according to current repository evidence
SIM: implemented/certified according to current repository evidence
RESEARCH: future P7 unless already implemented by newer HEAD
LIVE: future P8/P9 unless already implemented by newer HEAD
```

绝对不能把：

```text
target architecture
```

写成：

```text
currently implemented capability
```

---

# 33. P6 Final Certification Report

如果当前 Repository 没有合适的最终认证报告，新增一个符合现有命名习惯的报告。

建议概念名称：

```text
docs/reports/p6_runtime_architecture_final_certification.md
```

具体路径和文件名以当前仓库惯例为准。

报告至少包含：

```markdown
# P6 Runtime Architecture Final Certification

## Final SHA

## Scope

## Runtime Product Taxonomy

## Legacy Products Removed

## Streaming Ownership

## Backtest Certification

## SIM Normal-Path Certification

## SIM Continuity Certification

## SIM Durable Recovery Certification

## Existing SIM Durable Compatibility

## Legacy PAPER Durable-State Policy

## Architecture Invariants

## Config / Public API Migration

## Scenario / Product Certification

## Documentation Reconciliation

## Test Evidence

## CI Evidence

## Explicit Non-Goals

## Remaining Known Limitations

## P7 Readiness

## Final Decision
```

---

# 34. Definition of Done

P6.6 只有以下所有条件同时成立才能标记 `ACCEPTED`。

---

## Runtime Taxonomy

- [ ] Production Runtime vocabulary 只有 `RESEARCH / BACKTEST / SIM / LIVE`
- [ ] `OnlyRuntimeMode.PAPER` 已删除
- [ ] `OnlyRuntimeMode.SHADOW` 已删除

---

## Legacy Product Removal

- [ ] `runtime/paper` active production package 已删除
- [ ] `OnlyPaperRuntime` 已删除
- [ ] `OnlyPaperRuntimeFactory` 已删除
- [ ] `runtime/shadow` active production package 已删除
- [ ] `OnlyShadowRuntime` 已删除
- [ ] `OnlyShadowRuntimeFactory` 已删除
- [ ] Default Runtime Registry 不再注册 Paper/Shadow
- [ ] Public exports 不再暴露 Paper/Shadow

---

## No Compatibility Layer

- [ ] 无 `PAPER -> SIM` alias
- [ ] 无 deprecated PaperRuntime
- [ ] 无 PaperFactory forwarding
- [ ] 无 Paper config auto-conversion
- [ ] 无 ShadowRuntime wrapper
- [ ] 无 Shadow deprecated alias

---

## Streaming Ownership

- [ ] useful streaming infrastructure 有明确 neutral owner
- [ ] shared streaming code 未复制到 SIM
- [ ] Streaming 不再拥有 PAPER product semantics
- [ ] legacy Shadow execution 不再属于 SIM normal path

---

## Semantic Integrity

- [ ] Trading Kernel 未新增 Runtime-specific economic branch
- [ ] Strategy Context 仍 Runtime neutral
- [ ] Backtest semantic regression tests pass
- [ ] SIM normal-path tests pass
- [ ] SIM 使用 Virtual Broker
- [ ] SIM 不能进入 Real Broker submission path

---

## Persistence / Recovery

- [ ] current valid SIM durable contract 仍可恢复
- [ ] no automatic Paper→SIM durable migration
- [ ] corrupt checkpoint still fail-closed
- [ ] Runtime State Lease behavior unchanged
- [ ] new-process recovery still valid
- [ ] repeated restart still valid

---

## Config / Public Contract

- [ ] active config 不再接受 PAPER
- [ ] active config 不再接受 SHADOW
- [ ] legacy fixtures 已语义迁移或删除
- [ ] observation-only workload 未错误伪装成 SIM

---

## Scenario / Certification

- [ ] Scenario active vocabulary 不再依赖 PAPER/SHADOW
- [ ] finite BACKTEST lifecycle 没有被错误扩展成 streaming abstraction
- [ ] SIM 有正式 deterministic product certification coverage

---

## Documentation

- [ ] README 与实现一致
- [ ] architecture docs 与实现一致
- [ ] runtime docs 与实现一致
- [ ] quality-system 与 target taxonomy 一致
- [ ] roadmap 与真实 status 一致
- [ ] ADR implementation update 已补充（如适用）
- [ ] historical records 未被篡改

---

## Architecture Guards

- [ ] exact Runtime taxonomy guard
- [ ] no legacy Runtime package guard
- [ ] no legacy Factory registration guard
- [ ] no compatibility alias guard
- [ ] existing semantic-neutrality guards pass
- [ ] SIM real-broker isolation guard pass

---

## Quality

- [ ] formatting pass
- [ ] lint pass
- [ ] type checking pass
- [ ] architecture/import checks pass
- [ ] build pass
- [ ] core test lanes pass
- [ ] recovery pass
- [ ] sim-recovery pass
- [ ] security/static gates pass
- [ ] no known Critical issue
- [ ] no known High issue
- [ ] Independent Review completed

---

# 35. Acceptance Status Rules

阶段状态只允许：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```

只有所有 P6.6 Acceptance Criteria 和 P6 exit criteria 都满足时，才允许：

```text
ACCEPTED
```

如果代码已经完成，但 remote same-SHA certification 尚不可确认：

```text
CONDITIONALLY_ACCEPTED
```

并明确原因。

如果存在：

```text
Critical/High architecture issue
economic semantics regression
durable recovery regression
legacy compatibility path
parallel product path
```

则：

```text
REJECTED
```

---

# 36. Same-SHA Certification

不要在本地测试通过后直接宣布 P6 DONE。

完成实现后：

1. 获取 final commit SHA；
2. 确认 working tree 状态；
3. 检查 final diff；
4. 执行完整 local gates；
5. 检查 current GitHub CI workflow；
6. 确认 final SHA 的 remote CI；
7. 确认 required jobs 实际 green；
8. 再决定最终 Acceptance Status。

如果没有权限访问 remote CI：

明确写：

```text
Remote same-SHA certification unavailable / pending.
```

不得写：

```text
Remote CI passed.
```

---

# 37. Scope Control

P6.6 理想 diff 应体现：

```text
大量 legacy deletion
+
少量 ownership migration
+
config/test migration
+
architecture guards
+
documentation reconciliation
```

而不是：

```text
大量新 Trading code
```

如果发现需要新增大量：

```text
Order
Position
Account
Risk
Execution
Transaction
Settlement
Recovery
```

实现，应立即暂停并重新检查是否偏离 P6.6 scope。

---

# 38. Explicit Non-Goals

P6.6 不实现：

```text
Vectorized Research Runtime
Research Job
Research Dataset Engine
Research Factor Engine
Research Result/Artifact API

Durable Real Broker outbound command
Broker ACK / Reject / Unknown
Broker query
Broker reconciliation
Live synchronization
Production Live Runtime

Multi-account
Multi-broker
Multi-data-source expansion
Futures
Margin
Crypto
Distributed Research
Distributed Event-driven Backtest
```

这些属于未来阶段。

---

# 39. Expected Final Architecture

P6.6 完成后概念结构应为：

```text
OnlyEngine
│
├── RESEARCH
│   └── future P7
│
├── BACKTEST
│   ├── Historical Driver
│   ├── Backtest Clock
│   ├── Virtual Broker
│   └── Shared Trading Kernel
│
├── SIM
│   ├── Streaming Control Plane
│   ├── Live Clock
│   ├── Realtime MarketData
│   ├── Continuity
│   ├── Gap Recovery
│   ├── Reconnect
│   ├── Durable Checkpoint
│   ├── Recovery
│   ├── Virtual Broker
│   └── Shared Trading Kernel
│
└── LIVE
    └── future P8/P9
```

不存在：

```text
PAPER Runtime Product
SHADOW Runtime Product
Paper compatibility path
Shadow compatibility path
```

---

# 40. Expected Repository Truth

最终应满足：

```text
Target Architecture
=
Production Source
=
Runtime Enum
=
Factory Registry
=
Config Vocabulary
=
Formal Tests
=
Active Documentation
=
Architecture Guards
```

也就是：

```text
Repository == Executable Architecture Truth
```

---

# 41. Independent Review

实现完成后，不要只以作者视角检查。

重新以独立 Reviewer 身份审查整个 diff。

主动寻找以下 REJECT 证据：

```text
是否仍存在第二个 Runtime product path？

是否仍有 PAPER alias？

是否 Paper Factory 只是复制进入 SIM？

是否 shared Streaming code 仍然依赖 PAPER identity？

是否 legacy Shadow execution 偷偷保留？

是否 SIM durable state 被无理由破坏？

是否 Strategy / Trading Kernel 出现新的 Runtime mode branch？

是否 active config 仍接受 PAPER / SHADOW？

是否测试通过是因为 assertion 被削弱？

是否删除了重要 recovery regression test？

是否历史 ADR 被错误改写？

是否 Roadmap status 超过真实 CI evidence？

是否 P6.6 偷偷实现了 P7 / P8 / P9 scope？

是否产生了新的 duplicate authoritative state？
```

如果发现 Critical / High：

```text
不得 ACCEPTED
```

---

# 42. Final Output Requirements

任务完成后，不要只输出：

```text
Done.
```

必须输出完整结构化 implementation report。

格式如下。

---

## A. Repository Baseline

提供：

```text
Starting SHA:
Final SHA:
Working tree status:
```

---

## B. Pre-Removal Capability Audit

用表格列出：

| Capability | Previous Owner | Final Owner | Decision |
|---|---|---|---|
| ... | ... | ... | retain/migrate/delete |

重点说明 Paper Factory 中每个 useful capability 如何处理。

---

## C. Runtime Taxonomy Changes

列出：

```text
removed enum values
removed Runtime classes
removed factories
removed packages
removed public exports
registry changes
```

---

## D. Streaming Ownership Result

说明：

```text
哪些能力属于 streaming
哪些属于 sim
哪些 legacy 能力被删除
```

---

## E. Config / Public API Migration

列出所有 breaking changes。

明确说明：

```text
PAPER config no longer accepted
SHADOW config no longer accepted
No aliases retained
```

---

## F. Persistence / Recovery Compatibility

明确回答：

```text
Existing SIM durable compatibility:
PASS / FAIL

Legacy PAPER durable migration:
INTENTIONALLY UNSUPPORTED
```

并说明验证方式。

---

## G. Tests Added / Updated / Removed

分类列出：

```text
architecture
runtime
integration
recovery
sim-recovery
scenario
config
```

不要只给文件数量。

---

## H. Documentation Updated

列出：

```text
README
roadmap
architecture
runtime
quality-system
ADR
certification report
```

实际修改哪些就列哪些。

---

## I. Local Verification

逐条报告真实命令和结果。

例如：

```text
uv run ruff check ...
PASS

uv run mypy ...
PASS

uv run python scripts/test_suite.py core-full
PASS

uv run python scripts/test_suite.py recovery
PASS

uv run python scripts/test_suite.py sim-recovery
PASS
```

必须基于真实执行。

不要写模糊的：

```text
all tests passed
```

---

## J. Remote CI Certification

报告：

```text
Final SHA:
Workflow/check:
Result:
```

如果无法访问：

```text
UNAVAILABLE
```

不要猜。

---

## K. Remaining Known Issues

列出所有已知：

```text
Critical
High
Medium
Low
```

如果没有 Critical/High，明确写：

```text
No known Critical/High issues found in P6.6 scope.
```

前提是真实 review 后得出的结论。

---

## L. Final Acceptance Decision

只能选择：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```

并明确解释。

---

## M. P7 Readiness

最后回答：

```text
Can P7 start?
YES / NO
```

只有 P6 最终：

```text
ACCEPTED
```

后才默认回答：

```text
YES
```

否则说明 blocker。

---

# 43. Final Success Criterion

P6.6 的成功标准不是：

```text
旧测试重新变绿
```

也不是：

```text
PAPER 被重命名成 SIM
```

真正的成功标准是：

> OnlyAlpha 的 active production architecture 中，`RESEARCH / BACKTEST / SIM / LIVE` 成为唯一可表达的 Runtime Product Taxonomy；PAPER 与 standalone SHADOW 从生产产品模型、Factory、配置和 public contract 中彻底消失；没有 alias、deprecated wrapper 或 hidden compatibility path；有价值的 streaming capability 都拥有正确且唯一的 owner；Backtest 与 SIM canonical Trading Kernel 语义保持不变；SIM durable checkpoint/new-process recovery contract 保持有效；源码、测试、配置、active docs 与 CI 对这一架构形成一致、可执行、不可回退的证明。

最终目标：

```text
P6.0–P6.5
    Build the canonical runtime architecture

P6.6
    Remove the legacy architecture
    Freeze the product taxonomy
    Protect the boundary
    Reconcile repository truth
    Certify P6

Result:

RESEARCH / BACKTEST / SIM / LIVE
             |
             +-- only Runtime product taxonomy

BACKTEST / SIM / future LIVE
             |
             +-- one canonical Trading Semantic Core

PAPER
    → gone from active product architecture

standalone SHADOW
    → gone from active product architecture

Repository
    =
Architecture
    =
Executable Truth
```