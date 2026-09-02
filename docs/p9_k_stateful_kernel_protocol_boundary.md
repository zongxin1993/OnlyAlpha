# Stateful Kernel & Protocol Boundary

本文件描述由 [ADR 0101](adr/0101-stateful-kernel-and-protocol-boundary.md) 派生的目标结构和永久边界，不记录阶段完成状态、Task Gate
结果、subject SHA 或下一任务授权。

## Product identity

OnlyAlpha 是长期运行的 Stateful Quant Kernel，不是由外部 Python、CLI 或配置文件控制的框架。

```text
Human → Web ───────────────┐
                          ├→ HTTPS / versioned OpenAPI → Product HTTP Adapter
Agent / Automation ───────┘                              │
                                                         ↓
                                              Command / Query Boundary
                                                         │
                                                         ↓
                                                Stateful Kernel Host
                                                         │
                         ┌───────────────────────────────┼───────────────────────────────┐
                         ↓                               ↓                               ↓
                  Domain authorities              Runtime supervision             Recovery/Reconciliation
                         │                               │                               │
                         └──────────────────── Kernel-defined Ports ────────────────────┘
                                                         │
                                                         ↓
                                            Plugins / Persistence / Gateways
```

External actors submit intent and exact references; Kernel authorities validate, transition and persist formal facts.

## Product Control Plane

Only one external product contract exists:

```text
HTTPS + JSON
→ governed OpenAPI
→ replaceable HTTP adapter
→ typed Command / Query
→ application/domain authority
```

HTTP DTO、domain model 和 persistence schema 是不同 schema worlds，必须显式 mapping。Command 请求合法状态转换；Query 只读，不得
隐藏 mutation。Externally retryable mutation 使用 durable command identity；same key + same canonical command 收敛到同一 outcome，
same key + different command fail closed。

仓内不提供 Product CLI 或 Python SDK。API failure 不得 fallback 到 local Engine/Runtime。`onlyalpha-http-server` 是 process entrypoint，
不是 Product CLI；Research Worker 和 provider doctor 同属 infrastructure/operator process/tooling。

## Internal Kernel protocol

Kernel 内部保持 strongly typed direct calls，不把 deterministic trading chain 改写为 HTTP 或 generic event bus：

```text
Observation
→ Strategy Decision
→ Portfolio / Risk
→ Order Intent
→ Execution
→ Position / Account / Runtime State
```

`OnlyEngine`、Runtime factories、Cluster composition 和 `OnlyClusterRunConfig` 是内部实现边界。Engine 不接受 config file path；正式
Runtime admission 必须来自版本化 Product API 产生的 canonical typed specification。

## Runtime specification and instance

```text
Runtime Specification
= immutable/canonical/fingerprintable semantic intent

admission / instantiate
        ↓

Runtime Instance
= distinct runtime/run identity + lifecycle + owner/worker
 + checkpoint/recovery state + result references
```

文件路径、HTTP metadata、idempotency key、actor、request ID 和 instance-specific state 不进入 specification semantic identity。Trading
semantic configuration 不从 ENV、YAML、JSON 或 mutable database lookup 隐式获得；deployment configuration 只配置 infrastructure。

## Lifecycle and state ownership

Kernel lifecycle：

```text
CREATED → BOOTING → VERIFYING → RECOVERING → READY → DRAINING → STOPPED
                                      failure → FAILED
```

Mutation 在 READY 前和 DRAINING 后 fail closed。一个 operational database 只有一个 unfenced mutation-capable Kernel authority。

State ownership：

```text
Immutable Semantic State → content-addressed semantic stores
Operational State        → transactional operational stores
Runtime Mutable State    → deterministic memory + explicit durable facts/checkpoints
External Execution State → Venue/Broker + local reconciliation evidence
```

Recovery 按 Authority 从 durable facts 重建，不序列化整个 Kernel object，也不从 projection 反向修复 semantic truth。

## Long-running operations

Research、Backtest、SIM 和 future Deployment 都是 durable lifecycle resources：

```text
POST command
→ durable admission
→ accepted resource identity
→ HTTP request ends
→ Kernel / Worker / Runtime continues
→ Query observes authoritative state
```

## Control Plane, Data Plane and Gateway Plane

- Product Control Plane：OpenAPI commands/queries。
- Trading Data Plane：bar、tick、trade、quote、execution report、fill，经 provider-neutral ports 进入 Kernel。
- Remote Infrastructure Plane：需要跨进程/OS 时使用 versioned Protobuf/gRPC contract；它不是第二 Product API。

Async infrastructure 只有出现真实 cross-process/multi-consumer delivery requirement 后才能引入。

## Scenario and diagnostics

Scenario parser、planner、runner、assertions 和 exact DataSource 只属于 tests/CI verification boundary。Scenario DataSource 不注册到默认
Product composition，也不暴露 CLI/API。

Operational diagnostic service 保留 canonical stale-worker、heartbeat、lease、stuck-run、failure 和 draining semantics。它不因 root CLI
退役而删除，也不得在 route 或 tooling 中复制成第二套判断逻辑。

## Mechanical gates

Architecture tests必须保证：

- root Product CLI、仓内 Python Product client、`examples/` 和 runtime file admission 不会重新出现；
- Web 只消费 governed Product API；
- API routes 不持有 raw Engine/Runtime/persistence/Strategy mutation capabilities；
- Scenario 不进入 default Product composition；
- Core 不依赖 FastAPI、provider SDK 或 concrete plugins；
- transport/audit identity 不污染 Strategy、Dataset、Calculation 或 trading fingerprints；
- one control-plane deployment 不产生多个 unfenced mutation-capable Kernel authorities。

## Non-goals

该边界不授权 provider-specific Core logic、第二 Trading Kernel、generic workflow engine、multi-master HA、Kafka/NATS/Redis 平台、
Kubernetes rewrite、LIVE permission shortcut 或整仓目录重排。
