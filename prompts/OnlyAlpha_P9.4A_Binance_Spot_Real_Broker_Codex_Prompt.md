# OnlyAlpha P9.4A — Binance Spot Real Broker / UNKNOWN / Reconciliation / Recovery

## Codex Implementation Prompt

> **任务性质：High-Risk Work Program**
>
> 本任务涉及 Broker、Order、Execution、External Identity、UNKNOWN、Reconciliation、Recovery、Public SPI、Persistence、Security Boundary 与部分 Quality Infrastructure。  
> 必须严格遵守仓库根目录 `PROJECT_CONSTITUTION.md` 与 `AGENTS.md`。  
> **不得把本提示词当成高于 Constitution / Architecture / Accepted ADR 的 Authority。**

---

# 0. 工作目标

本任务不是“把 Binance 下单 API 接进 OnlyAlpha”。

P9.4A 的真正目标是：

> 在真实外部交易 Venue、网络不可靠、响应可丢失、事件可重复/乱序、进程可 Crash 的前提下，使一个 OnlyAlpha Order Intent 始终保持唯一身份、唯一 Authority、确定的状态演进和可恢复性；通过稳定 Client Order Identity、Canonical Broker Facts、Durable Evidence、Reconciliation 与 Crash Recovery，使 OnlyAlpha 最终与 Binance Spot Venue 收敛到一个可证明的权威状态。

目标链路：

```text
OnlyAlpha Order Intent
        │
        ▼
Unique OnlyOrderId
        │
        ▼
Stable OnlyClientOrderId
        │
        ▼
Binance Spot Command
        │
        ├── Known protocol result
        ├── Known venue fact
        └── UNKNOWN outcome
                │
                ▼
        Venue Discovery / Reconciliation
                │
                ▼
        Canonical Broker Facts
                │
                ▼
        Existing Execution Pipeline
                │
                ▼
        OnlyOrderManager / Account / Fee / Runtime Projections
                │
                ▼
        Durable + Recoverable Convergence
```

必须始终保持：

```text
Uniqueness
Determinism
Market-Agnostic Core
Single Authority
Reproducibility
Fail-Closed
Explicit Boundaries
Recoverability
Traceability
```

---

# 1. 强制阅读顺序

开始任何 planning / implementation / refactor / test design 之前，必须按当前仓库内容完整阅读：

```text
1. PROJECT_CONSTITUTION.md
2. 相关 Architecture / public Contracts
3. 相关 Accepted ADRs
4. docs/p9_binance_spot_golden_vertical_execution_plan.md
5. AGENTS.md
6. 当前源码 + 当前测试 + 当前可执行行为
```

至少重点阅读：

```text
PROJECT_CONSTITUTION.md
AGENTS.md

docs/p9_production_trading_vertical_architecture.md
docs/p9_binance_spot_golden_vertical_execution_plan.md

docs/adr/0011-order-component-and-execution-port.md
docs/adr/0099-binance-spot-first-golden-vertical-and-provider-sequencing.md

src/onlyalpha/broker/
src/onlyalpha/order/
src/onlyalpha/order/execution/
src/onlyalpha/domain/
src/onlyalpha/runtime/
src/onlyalpha/execution/

packages/provider/onlyalpha-plugin-binance/

scripts/verify.py
scripts/test_suite.py
quality-policy.toml
pyproject.toml
.github/workflows/
```

如果当前 HEAD 中还有与 Broker / Reconciliation / Recovery / P9.4 直接相关的 Accepted ADR 或 Architecture，必须纳入。

首先记录当前 HEAD SHA，仅作为本次实现观察基线，不得创建或提交任何 Final-SHA / completion-status / audit-status 文件。

---

# 2. Authority 顺序

严格按照：

```text
PROJECT_CONSTITUTION.md        → L0
Architecture / public Contract → L1
Accepted ADR                  → L2
Roadmap / Work Program        → L3
Current Task Contract         → L4
Current Source / Tests        → Implementation Truth
```

如果低层内容和高层冲突：

```text
Constitution > Architecture > Accepted ADR > Roadmap > Prompt > Implementation
```

若当前任务本身要求违反 Constitution：

```text
STOP IMPLEMENTATION
REPORT: PLAN_CONFLICT
```

不得通过修改 `PROJECT_CONSTITUTION.md` 解决。

---

# 3. Constitution Impact

本任务开始前必须明确：

```text
Does P9.4A conflict with, weaken, reinterpret,
or require changing PROJECT_CONSTITUTION.md?

NO
```

如果实际分析无法得到 `NO`：

```text
PLAN_CONFLICT
STOP
```

---

# 4. 当前设计基线

## 4.1 Core 与 Provider 边界

必须贯彻：

```text
Will this change because an external market/provider rule changes?
```

若答案是 `YES`：

```text
Plugin / Adapter / Gateway
```

只有真正属于所有市场都成立的 universal canonical trading semantics，才允许进入 Core。

不得因为 Binance 当前 API 方便而向 Core 引入：

```text
Binance DTO
Binance error code
Binance endpoint
Binance listenKey/session token
Binance recvWindow
Binance symbol rule
Binance order status enum
Binance-specific retry semantics
```

---

## 4.2 已有 Broker Core 优先复用

当前工程已经存在 provider-neutral Broker Ports / Models / Updates / Execution integration。

默认原则：

> **P9.4A 不重建 Broker Core；只在真实证据证明缺失 universal canonical concept 时做最小 Core evolution。**

禁止为了 Binance 创建第二套：

```text
OrderManager
Execution state machine
Account authority
Position authority
Canonical Broker model
Runtime truth
```

---

## 4.3 Order Authority

`OnlyOrderManager` 必须继续是一个 Runtime 内唯一 Order state Authority。

ADR 0011 的核心约束继续成立：

```text
transport submit success != Accepted
cancel request success != Cancelled
EventBus does not own Order state
Gateway does not own Order state
```

所有 Binance 外部事实必须：

```text
Binance DTO
→ Provider normalization
→ Canonical Broker Update / Fact
→ Existing Execution Processor
→ OnlyOrderManager
```

禁止：

```text
Binance WebSocket callback
→ directly mutate OnlyOrderManager
```

禁止：

```text
Binance plugin
→ maintain official parallel order state
```

---

# 5. P9.4A Authority Model

必须保持下列 Authority：

| Semantic / Fact | Authority |
|---|---|
| Order Intent | OnlyAlpha Trading Kernel / Order Authority |
| `OnlyOrderId` | OnlyAlpha |
| `OnlyClientOrderId` | OnlyAlpha |
| Binance `clientOrderId` representation | OnlyAlpha-controlled correlation identity |
| Binance `orderId` | Binance Venue |
| Accepted / Rejected | Binance Venue |
| Partial Fill / Fill / Trade | Binance Venue |
| External commission fact | Binance Venue |
| External Account / Balance fact | Binance Venue |
| Local Order projection | `OnlyOrderManager` |
| Reconciliation semantic decision | OnlyAlpha |
| Market rules / reference | P9.1 Market Reference Authority |
| Binance transport/session state | Binance Broker Plugin |
| LIVE execution permission | P9.5 Runtime Safety Authority |

不得创造同一事实类别的第二 Authority。

---

# 6. External Identity Invariants

必须保证：

```text
OnlyOrderId
      │
      ▼
OnlyClientOrderId
      │
      ▼
Binance clientOrderId
      │
      ▼
Binance orderId
      │
      ▼
OnlyVenueOrderId
```

硬不变量：

```text
I1. Same OnlyOrderId → same OnlyClientOrderId

I2. One OnlyClientOrderId → at most one OnlyOrderId

I3. One OnlyVenueOrderId → at most one OnlyOrderId

I4. Same semantic submission must never silently obtain a new client identity

I5. Timeout / disconnect / crash must never turn O1/C1 into O1/C2 or O2/C2

I6. Restart must preserve the same semantic identity
```

不要为了 Binance 创建平行 `BinanceOrderIdentity` Authority。

Provider 可做 wire-safe encoding，但必须是稳定、确定、可逆/可关联的 `OnlyClientOrderId` provider representation。

---

# 7. UNKNOWN 是正式语义

当前实现中应重点检查：

```text
OnlyExecutionSubmissionOutcome
Broker operation/result models
Execution submission flow
Persistence / Recovery representation
```

Constitution 已经要求：

```text
UNKNOWN submit outcome is first-class
blind retry is forbidden
```

因此如果当前 Core Contract 不能正式表达：

```text
request may have reached Venue,
but outcome cannot be proven
```

这是一个已被 Constitution 证明的 universal semantic gap。

但不要直接假设最终类名或 enum 结构。

必须先检查完整 consumer graph，再实施 **最小正确 contract evolution**。

语义至少要能区分：

```text
NOT_DISPATCHED
DISPATCHED
KNOWN_RESULT
UNKNOWN
RECONCILING / RESOLVING
RESOLVED
```

名字可以根据现有工程语言调整，但必须满足：

```text
DISPATCHED != ACCEPTED
timeout != REJECTED
UNKNOWN != FAILED
UNKNOWN blocks blind new semantic submit
UNKNOWN is recoverable through reconciliation
```

---

# 8. 不要把 UNKNOWN 放进 Order Business Status

默认不要新增：

```text
OnlyOrderStatus.UNKNOWN
```

正确语义应允许：

```text
OrderStatus = SUBMITTED
SubmissionOutcomeKnowledge = UNKNOWN
```

原因：

```text
OrderStatus
→ business state

UNKNOWN
→ OnlyAlpha 对 external command outcome 的知识/确定性
```

这是两个正交维度。

只有经过完整 Architecture/Contract 分析并证明其他模型无法正确表达时，才允许不同设计。

---

# 9. Cancel 不提前扩展 Core

当前已有：

```text
PENDING_CANCEL
```

第一实现优先使用：

```text
PENDING_CANCEL
+ durable cancel-command evidence
+ Venue reconciliation
```

处理：

```text
cancel sent
→ timeout
→ reconciliation
→ CANCELLED / FILLED / EXPIRED / still open
```

不要为了对称性立即新增 `CancelResolution` public concept。

只有证明现有 canonical semantics 无法表达 market-independent cancel uncertainty，才允许最小 Core evolution。

---

# 10. Broker READY 语义

不得：

```text
CONNECTED → READY
```

真正的 Broker READY 至少要求：

```text
Transport usable
AND
Authentication verified
AND
Required account scope established
AND
Initial venue discovery complete
AND
Required reconciliation converged
AND
No unresolved blocking UNKNOWN
AND
No identity/authority conflict
AND
Required execution stream trust established
```

因此机械保证：

```text
CONNECTED != READY
AUTHENTICATION SUCCESS != READY
RECONNECTED != READY
```

stream interruption / unresolved reconciliation 必须撤销 Broker READY 或进入等价 fail-closed 状态。

注意：

```text
Broker READY
!=
LIVE execution permission
```

LIVE execution permission 属于 P9.5，不允许 P9.4A 偷渡实现第二 LIVE Authority。

---

# 11. Reconciliation 设计

Reconciliation 是正式协议，不是“后台定时同步脚本”。

Provider Plugin 回答：

```text
How to ask Binance?
```

例如：

```text
query account
query balances
query open orders
query order by stable client identity
query trades
```

OnlyAlpha canonical reconciliation 回答：

```text
What do discovered venue facts mean?
What local evidence is missing?
Are identities provably correlated?
Has authoritative convergence occurred?
Can Broker READY be granted?
```

推荐流程：

```text
LOAD LOCAL BASELINE
        ↓
DISCOVER VENUE FACTS
        ↓
CORRELATE IDENTITIES
        ↓
COMPARE
        ↓
APPEND MISSING CANONICAL FACTS
        ↓
PROCESS THROUGH EXISTING EXECUTION PIPELINE
        ↓
VERIFY
        ↓
CONVERGED
```

绝对禁止：

```text
query Binance
→ UPDATE local order projection directly
```

正确方式：

```text
Venue fact
→ canonical missing fact
→ durable evidence
→ existing execution state transition
→ projection convergence
```

Reconciliation 只能补充/重放真实事实，不能制造外部历史。

---

# 12. Durable Evidence

关键 truth 不能只存在进程内存。

至少必须能够恢复：

```text
Order Intent
OnlyOrderId
OnlyClientOrderId binding
submission dispatch evidence
submission UNKNOWN evidence
OnlyVenueOrderId association
canonical accepted/rejected facts
Trade / Fill facts
external fee evidence where applicable
reconciliation attempts/results
recovery frontier/checkpoint required facts
```

优先复用现有 Runtime persistence / audit / transaction / checkpoint / recovery 体系。

不要自然推导出一个全新的：

```text
Binance PostgreSQL order subsystem
```

数据库只是 persistence，不是新的 Broker/Order integration Authority。

Raw Binance payload 可以作为 diagnostics/provider evidence 存储，但不能成为第二 official Order truth。

---

# 13. Crash Boundaries

P9.4A 自身必须解决基本 Broker crash correctness，不得全部推迟到 P9.7。

至少覆盖：

```text
C1. crash before durable intent
    → no external order

C2. durable intent, before dispatch
    → deterministic recovery, no guessed external submit

C3. request may have been dispatched, response unknown
    → UNKNOWN, no blind retry

C4. Venue accepted, local response/fact lost
    → reconcile by same stable client identity
    → discover same external order

C5. Venue trade exists, realtime event missed
    → query/discover trade
    → canonical fact
    → one economic effect

C6. fact durable, local projection incomplete
    → deterministic replay
    → same state

C7. cancel/fill race
    → venue facts determine final convergence
```

必须使用：

```text
deterministic barrier
event
fake clock
fault injection
controlled fake venue
```

禁止用：

```text
sleep()
retry-until-green
oversized timeout
random timing
```

证明 correctness。

---

# 14. 测试分层

## Layer 1 — Pure Domain / Contract

Offline / hermetic：

```text
identity invariants
UNKNOWN semantics
state transition legality
conflict handling
deduplication
reconciliation planning
compatibility
```

## Layer 2 — Deterministic Fake Venue

这是 correctness 主证明层。

必须能控制：

```text
accept then response lost
known rejection
timeout before/after remote acceptance
duplicate event
out-of-order event
missing event
disconnect
reconnect
cancel/fill race
crash boundaries
stale local snapshot
identity conflict
```

## Layer 3 — Binance Adapter Contract Fixtures

使用 deterministic recorded payload：

```text
Binance request/response/event
↔
canonical OnlyAlpha request/fact
```

验证 provider DTO 在 adapter 边界终止。

## Layer 4 — Binance Spot Testnet

只证明 fake 无法证明的真实 provider contract：

```text
signature
credential validity
timestamp/recvWindow behavior
real private REST schema
clientOrderId behavior
real query/cancel behavior
real user-stream schema
real account/balance observations
```

Testnet 不得冒充 crash/determinism/idempotency correctness proof。

---

# 15. 第一版 Binance Spot Broker Scope

首轮 Golden Vertical 只要求最小充分能力：

```text
MARKET
LIMIT

BUY
SELL

required TIF:
GTC
以及 Market Reference 明确支持且当前流程需要的 IOC/FOK
```

BTCUSDT：

```text
primary path
```

ETHUSDT：

```text
non-hardcoding proof
```

不允许代码中写 BTCUSDT 专用业务分支。

Market rule 不得在 Broker 重新建立 Authority：

```text
tickSize
stepSize
minNotional
symbol status
supported order type / TIF
```

应继续由 P9.1 Market Reference Authority 决定。

Broker 只负责 protocol translation / final provider formatting。

Spot 不得为了满足通用接口而伪造 Futures-like Position semantics。

如果 Spot 的某 capability 不具备真正 canonical meaning：

```text
declare unsupported capability
```

优于制造错误语义。

---

# 16. P9.4A 工作拆分

本 Work Program 必须按顺序执行：

```text
P9.4A.0  Inherited P9.3 Deterministic Closure
        ↓
P9.4A.1  Real Broker Contract / UNKNOWN Closure
        ↓
P9.4A.2  Binance Spot Private REST Adapter
        ↓
P9.4A.3  Binance User Data Stream
        ↓
P9.4A.4  Reconciliation + Durable Recovery
        ↓
P9.4A.5  Binance Spot Testnet External Proof
        ↓
STOP P9.4A
```

不得将所有阶段揉成无法停止的持续重构。

每一阶段都建立独立 Task Contract：

```text
Goal
Modification Scope
Expected Impact Scope
Required Behavior
Acceptance Tests
Out of Scope
Stop Condition
Constitution Impact
```

达到当前阶段 Stop Condition 后立即停止当前阶段。

---

# 17. P9.4A.0 — 必须首先解决的遗留 P9.3 问题

## 17.1 硬前置规则

**P9.4A.0 未完成，不得进入 P9.4A.1 或任何 Binance Broker implementation。**

这是本任务中必须先显式关闭的四个遗留问题。

---

## 17.2 已知问题背景

当前已确认过的失败属于 PostgreSQL client tool selection nondeterminism：

```text
PostgreSQL 18 server/service available
PostgreSQL 18 client package installed
but generic `pg_dump` / `pg_restore` selected through ambient PATH
may resolve to another major version
```

已有 fail-closed guard 报：

```text
POSTGRES_CLIENT_MAJOR_UNSUPPORTED
pg_dump must be major 18
```

这说明 guard 本身正确。

**绝对禁止为了通过测试删除/弱化 major-version guard。**

---

## 17.3 遗留问题 1：Deterministic PostgreSQL 18 Client Resolution

必须使 production/operator code 的 client tool resolution 明确、确定、可配置、fail-closed。

优先方案：

```text
ONLYALPHA_POSTGRES_CLIENT_BIN_DIR=/usr/lib/postgresql/18/bin
```

或当前架构中已有的等价显式配置入口。

要求：

```text
pg_dump
pg_restore
psql（若同路径参与当前工作流）
```

从明确 client family 解析，而不是依赖 ambient PATH 的首个 executable。

不得偷偷 fallback 到错误 major。

---

## 17.4 遗留问题 2：CI 显式绑定 PG18 Binary Family

GitHub CI 安装 PostgreSQL 18 client 后，必须显式配置当前 test/runtime 使用：

```text
/usr/lib/postgresql/18/bin/pg_dump
/usr/lib/postgresql/18/bin/pg_restore
```

或等价确定性路径。

CI 必须验证：

```text
selected pg_dump major == 18
selected pg_restore major == 18
```

不要依赖 runner 默认 `/usr/bin/pg_dump`。

---

## 17.5 遗留问题 3：Multi-Version Host Regression

新增最小 regression，证明：

```text
Host has older PostgreSQL client on generic PATH
+
PG18 client in explicitly configured bin dir
```

结果仍然：

```text
OnlyAlpha selects PG18 deterministically
```

同时证明：

```text
configured required client unavailable
or
configured client major wrong
```

必须：

```text
FAIL CLOSED
```

不能自动降级到旧版本。

测试应复现旧错误：

```text
old generic PATH would pick wrong major
→ explicit configuration fixes root cause
```

---

## 17.6 遗留问题 4：P9.3 Closure / Applicable Phase Gate

修复完成后：

```text
targeted database/operator regression tests
affected static checks
affected DB-related canonical lane
quality-infrastructure-specific verification
```

全部通过。

因为这是已完成阶段的 inherited milestone closure，可以执行一次 **P9.3 final applicable Phase Gate**，但不得借此重新开启无限 P9.3 审计。

如果 Full Layered Quality 中出现失败：

```text
only classify whether it is a real regression / blocker attributable to current affected scope
```

历史无关失败不自动扩大当前修改范围。

---

## 17.7 P9.4A.0 Modification Scope

默认仅允许：

```text
scripts/database.py
directly related database operator/config modules
directly related tests
explicit PG client environment/config wiring
directly related CI PostgreSQL setup
```

如果必须修改 `.github/workflows/*`：

这是本 Task Contract 明确授权的 quality infrastructure change，但仍按高风险验证。

禁止顺手修改：

```text
test discovery
coverage threshold
unrelated quality rules
lint ignores
gate selection
unrelated workflow conditions
```

---

## 17.8 P9.4A.0 Stop Condition

```text
All four inherited issues are closed

PostgreSQL 18 client resolution deterministic
CI explicitly binds exact PG18 tools
multi-version-host regression PASS
wrong/missing major fails closed
major-version guard remains strict

targeted validation PASS
applicable P9.3 final Phase Gate PASS
bounded Independent Review complete
Constitution consistency PASS

current scope Critical = 0
current scope High = 0

→ STOP P9.4A.0
→ ONLY THEN proceed to P9.4A.1
```

---

# 18. P9.4A.1 — Real Broker Contract / UNKNOWN Closure

## Goal

在真实 Binance networking 之前，验证当前 canonical Broker/Execution Contract 是否足以表达真实 Broker。

只补齐已被真实需求和 Constitution 证明的 universal gap。

## Required Behavior

至少证明：

```text
known dispatch/result
known rejection
unknown external outcome

UNKNOWN cannot become blind retry
same OrderId retains same ClientOrderId
same semantic submit cannot create second external identity
venue identity conflict is detected
```

重点审查：

```text
src/onlyalpha/broker/
src/onlyalpha/order/execution/
src/onlyalpha/order/
recovery/persistence consumers
serialization/public exports
```

若 public contract 变化：

必须分析：

```text
backward/forward compatibility
consumer impact
serialization/checkpoint impact
plugin impact
migration if persistent format changes
```

不要接公网 Binance。

用 deterministic fake 完成 correctness proof。

## Stop Condition

```text
required universal semantics represented
no Binance-specific concept leaked into Core
UNKNOWN path deterministic
blind retry impossible
identity invariants PASS
affected compatibility PASS
affected architecture/recovery tests PASS
bounded Independent Review PASS
Critical = 0
High = 0
→ STOP P9.4A.1
```

---

# 19. P9.4A.2 — Binance Spot Private REST Adapter

## Goal

实现 provider-specific Binance Spot private REST transport，在不改变 Core Authority 的情况下实现真实命令和查询。

## Scope

建议职责：

```text
configuration
endpoint selection
credential handling
signature
timestamp / recvWindow
REST transport
canonical request → Binance parameters
Binance response/error → provider observation/canonical normalized result
```

最低能力：

```text
connect/auth proof as applicable
query account
query balances
submit MARKET
submit LIMIT
cancel
query order
query open orders
query trades
```

Testnet/Mainnet 是 configuration/environment，不创建两套 Broker implementation。

## Security

必须检查：

```text
secret never logged
signature input deterministic
external error payload sanitized appropriately
credential boundary explicit
no accidental credential persistence
```

## Stop Condition

```text
private REST adapter complete for required Spot scope
provider DTO leakage into Core = 0
BTC/ETH symbol handling not hardcoded
signing/timestamp tests PASS
recorded contract fixtures PASS
package/static/build checks PASS
bounded Independent Review PASS
Critical = 0
High = 0
→ STOP P9.4A.2
```

---

# 20. P9.4A.3 — Binance User Data Stream

## Goal

实现 Binance realtime external execution/account observations，并转换到 existing canonical Broker inbound contract。

## Required Behavior

至少：

```text
connect
receive
parse
normalize
duplicate handling
event ordering metadata where available
disconnect detection
reconnect lifecycle
stream trust invalidation
```

严禁：

```text
WebSocket callback
→ direct OrderManager mutation
```

必须：

```text
Binance event
→ normalize
→ OnlyBrokerInboundUpdate / existing canonical contract
→ existing processor
```

Reconnect 后：

```text
DO NOT set READY immediately
```

必须等待 P9.4A.4 reconciliation / verification。

## Stop Condition

```text
required User Data Stream payloads normalized
duplicate/replay behavior deterministic
stream loss revokes trust/READY path
reconnect alone cannot restore READY
no direct Core state mutation from provider callback
affected tests PASS
bounded Independent Review PASS
Critical = 0
High = 0
→ STOP P9.4A.3
```

---

# 21. P9.4A.4 — Reconciliation + Durable Recovery

## Goal

让：

```text
startup
UNKNOWN
disconnect
missed event
duplicate event
crash/restart
```

最终通过：

```text
durable local evidence
+
authoritative venue discovery
+
canonical facts
→ one authoritative state
```

## Required Behavior

启动路径至少：

```text
START
→ load durable state
→ connect
→ authenticate
→ discover venue
→ correlate identities
→ reconcile
→ establish required stream trust
→ verify
→ READY
```

Reconciliation 不允许直接 rewrite Order projection。

UNKNOWN 提交必须：

```text
reuse same stable client identity
→ query/discover
→ resolve by evidence
```

必须证明关键 crash boundaries C1-C7。

必须证明 external duplicate fact：

```text
N deliveries
→ one economic effect
```

必须证明：

```text
Venue fill missing locally
→ reconciliation discovers fill
→ append canonical fact
→ existing processor
→ local order converges
```

## Stop Condition

```text
startup reconciliation PASS
UNKNOWN reconciliation PASS
reconnect reconciliation PASS
identity conflict fails closed
missing fact recovery PASS
duplicate fact idempotency PASS
crash/restart convergence PASS
no duplicate external semantic order in deterministic fake tests
READY requires convergence
affected recovery/persistence tests PASS
bounded Independent Review PASS
Critical = 0
High = 0
→ STOP P9.4A.4
```

---

# 22. P9.4A.5 — Binance Spot Testnet External Proof

## Goal

只证明真实 Binance provider contract，不能用 Testnet 代替 deterministic correctness proof。

## Required External Proof

在可用 Binance Spot Testnet 环境中验证：

```text
credentials/signature
timestamp/recvWindow
account/balance query
MARKET order
LIMIT order
cancel
order query
trade query
clientOrderId behavior
User Data Stream
BTCUSDT path
ETHUSDT non-hardcoding path
```

若真实环境当前不可用：

```text
NOT PASS
```

不得用 mock 声称完成 external proof。

但不要因此改变正确实现或降低 Contract。

Mainnet 不属于 P9.4A completion requirement。

## Stop Condition

```text
required Testnet proof PASS
or explicit external-environment blocker reported truthfully

no correctness requirement weakened
no Mainnet automatic promotion
bounded external-integration review complete
```

只有真实外部证据满足 P9.4A Required Behavior 才能最终关闭 P9.4A。

---

# 23. 验收场景

至少建立以下确定性验收。

## A1 — READY

```text
connect
authenticate
baseline discovery
reconcile
stream trusted
→ READY
```

## A2 — LIMIT accepted → cancelled

证明 transport response 与 venue state 分离。

## A3 — accepted → partial fill → filled

最终 Order projection、fill evidence、fee evidence按现有 contract 收敛。

## A4 — duplicate trade/fill

```text
same external fact delivered twice
→ one economic effect
```

## A5 — submit timeout after venue accepted

```text
O1/C1 submit
Venue accepts
response lost
→ UNKNOWN
→ query using C1
→ discover same venue order
→ no C2
→ no second external order
```

## A6 — crash after uncertain dispatch

```text
restart
→ same O1/C1
→ reconciliation
→ discover or resolve
→ convergence
```

## A7 — cancel/fill race

不得因为 cancel command response 覆盖真实 fill。

## A8 — stream disconnect

```text
stream loss
→ revoke READY/trust
→ no new risk path
→ reconnect
→ reconciliation
→ verify
→ READY
```

## A9 — local missing fill

```text
Venue = FILLED
Local = ACCEPTED
→ discover trade/fill
→ append canonical fact
→ processor
→ FILLED
```

禁止直接 DB UPDATE projection。

## A10 — ETHUSDT

复用同一实现证明不存在 BTCUSDT hardcode。

---

# 24. 验收不变量

最终必须机械证明：

```text
one OnlyOrderId → exactly one OnlyClientOrderId binding

one semantic submit → at most one external Binance order

local execution state never outruns authoritative venue evidence

uncertainty != rejection

HTTP success != Accepted

reconciliation appends facts; it does not fabricate/rewrite external history

restart preserves semantic identities

duplicate/replay external facts are idempotent

CONNECTED != READY

authentication success != READY

reconnect != READY

stream loss revokes READY/trust

provider DTOs terminate at plugin boundary

Fill traceability reaches:
VenueOrderId
→ ClientOrderId
→ OrderId
→ Order Intent
→ upstream runtime/strategy causal context
```

如果不能唯一 correlate external fact：

```text
CONFLICT / UNPROVABLE
→ fail closed
```

不得猜测。

---

# 25. Impact-Aware Validation

严格使用 `AGENTS.md`。

每个阶段至少：

```text
targeted tests
affected ruff check
affected ruff format --check
affected mypy when typed/API code touched
nearest affected canonical lane
architecture consistency when boundary/contract touched
risk-specific tests
bounded Independent Review
Constitution consistency
```

不要因为“更保险”自动每个阶段执行：

```text
full repository tests
full Layered Quality
CodeQL
all build matrices
full coverage
release lane
```

完整 Phase Gate 仅在真正 Major Milestone closure 时按 `quality-policy.toml` / milestone contract 执行。

使用：

```text
scripts/verify.py
scripts/test_suite.py
quality-policy.toml
```

确定真实 affected canonical lanes。

不要修改这些工具来迁就业务实现。

---

# 26. Bounded Independent Review

P9.4A 每个高风险子任务完成后进行一次 bounded Independent Review。

范围仅：

```text
Modification Scope
+
real Impact Scope
+
directly relevant Constitution / architecture invariants
```

检查：

```text
Constitution violation
Authority duplication
illegal state
fail-open path
blind retry
identity mutation
recovery nondeterminism
public contract silent break
provider leakage
direct state mutation bypass
security boundary violation
test weakening
```

禁止：

```text
use Independent Review to restart full-repository audit
```

如果发现范围外问题：

默认记录但不修。

仅当其：

```text
blocks Required Behavior
or
proves original Impact Scope incomplete
```

才扩展到最近稳定工程边界。

---

# 27. Severity

```text
Critical → blocker
High     → blocker
Medium   → non-blocking by default
Low      → non-blocking
```

直接违反 Constitution 至少 High。

可能产生：

```text
duplicate external real order
unrecoverable execution truth
authority conflict
fund safety issue
```

按实际风险提升到 Critical。

---

# 28. 禁止事项

绝对禁止：

```text
修改 PROJECT_CONSTITUTION.md

为了过测试弱化 Required Behavior

删除 PostgreSQL version guard

用 PATH 偶然选择 pg_dump/pg_restore

retry-until-green

blind order retry

timeout → REJECTED

timeout → generate new ClientOrderId

HTTP 200 → Accepted

WebSocket callback direct mutate OrderManager

Binance plugin own parallel Order state

direct database mutation as reconciliation

provider DTO leak into Core

Binance market rules duplicated as Core truth

Spot balance fabricated as Futures position

sleep() correctness tests

skip/xfail real failures to close task

unrelated refactor

full-repository endless audit

implementation/completion/verification status files

Final-SHA certification files

historical Prompt committed as project Authority
```

---

# 29. Out of Scope

本任务不实现：

```text
Binance USD-M Futures
QMT
CTP
OKX

full P9.5 LIVE Runtime Composition
LIVE activation UI
LIVE strategy change authority
Kill Switch product UI

Mainnet certification
automatic Mainnet promotion

multi-account portfolio authority
smart order routing

full OCO / OTO / bracket
full stop/trailing order universe

L2/L3 HFT
latency optimization

Kafka
Redis
NATS
Kubernetes
distributed broker
HA consensus
```

不要因为这些“未来可能需要”扩展当前任务。

---

# 30. 总 Stop Condition

只有满足以下条件才允许声明 P9.4A 完成：

```text
Constitution Impact = NO

P9.4A.0:
    four inherited P9.3 issues closed
    deterministic PG18 client selection
    exact CI PG18 binding
    multi-version-host regression PASS
    strict major guard preserved
    applicable P9.3 Phase Gate PASS

Core:
    market-agnostic
    provider DTO leakage = 0
    unique Runtime Order Authority preserved

Identity:
    OrderId deterministic
    ClientOrderId deterministic
    VenueOrderId unique binding
    same semantic submit cannot silently obtain second identity

UNKNOWN:
    explicitly represented
    timeout != rejection
    blind retry impossible
    reconciliation path exists

Execution:
    REST response != venue execution truth
    User Data Stream normalized to canonical facts
    facts enter existing execution pipeline
    duplicate facts idempotent

Reconciliation:
    startup convergence PASS
    UNKNOWN convergence PASS
    reconnect convergence PASS
    missing-fact recovery PASS
    identity conflict fail-closed PASS

Readiness:
    CONNECTED != READY
    AUTHENTICATED != READY
    RECONNECT != READY
    stream loss revokes READY/trust

Recovery:
    deterministic crash boundaries PASS
    restart preserves same identities
    no duplicate semantic external order
    local state converges from durable evidence + venue facts

Provider proof:
    BTCUSDT Spot Testnet PASS
    ETHUSDT non-hardcode proof PASS

Validation:
    all required Impact-Aware validation PASS
    bounded Independent Review PASS
    Constitution consistency PASS

Current Scope:
    Critical = 0
    High = 0

→ STOP P9.4A
```

达到 Stop Condition 后立即停止。

不得因为：

```text
还能优化
还能抽象
还能支持更多订单
还能支持 Futures
还能重构
还能再审一次
```

继续扩大任务。

---

# 31. 实施输出要求

Codex 每完成一个子任务，只输出简洁、可验证的工程结果：

```text
1. Task Contract
2. Observed implementation truth
3. Exact changes made
4. Why each change is necessary
5. Why boundary/Authority placement is correct
6. Tests/validation actually run
7. Failures encountered and classification
8. Independent Review findings: Critical / High only as blockers
9. Constitution consistency result
10. Stop Condition result
```

不得在仓库生成：

```text
completion report
audit report
verification history
progress status
final SHA certification
task summary file
```

这些只出现在 Codex 会话输出。

---

# 32. 最终工程原则

如果实现过程中存在两个方案，优先选择满足：

```text
fewer authorities
fewer states
fewer provider-specific Core changes
smaller Modification Scope
explicit identities
explicit facts
deterministic recovery
fail-closed uncertainty
reusable provider boundary
```

的方案。

不要以“实现简单”为理由破坏：

```text
Uniqueness
Authority
Determinism
Recoverability
Traceability
Market-Agnostic Core
```

P9.4A 的成功标准不是代码量，也不是 Binance API 覆盖率。

最终只回答一个问题：

> **当一个 OnlyAlpha Order Intent 已经越过本地边界进入真实 Binance Spot 世界之后，无论网络、Venue response、stream 或进程在哪个边界失败，OnlyAlpha 是否仍然能够证明这笔订单是谁、外部实际发生了什么、为什么本地状态如此，并且恢复到唯一状态而不重复制造真实订单？**

只有答案可以被 deterministic evidence + real Testnet evidence 明确证明为 `YES`，P9.4A 才完成。

---

# 33. 时间输出要求

根据当前 `AGENTS.md`，本任务每次最终输出末尾必须打印：

```text
当前北京时间：YYYY-MM-DD HH:MM:SS
```

使用执行时真实北京时间，不要写固定时间。
