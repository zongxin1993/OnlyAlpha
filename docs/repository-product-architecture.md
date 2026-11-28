# Repository and product architecture

This is the target architecture derived from the Constitution, [ADR 0142](adr/0142-library-product-boundaries-and-independent-releases.md), [ADR 0150](adr/0150-product-layout-and-programmable-quant-assets.md) and [ADR 0152](adr/0152-unified-runtime-dual-kernel-operators-qlib-dag-and-wasm-plugins.md), and retains the flat Rust layout from [ADR 0149](adr/0149-flat-rust-library-layout.md).
It defines ownership, not implementation progress. Existing paths in development maps describe current source until their
atomic migration; this document does not claim that target paths or release guards already exist.

## Repository structure

```text
Cargo.toml / Cargo.lock                 one root workspace and development lock
crates/                                 one directory per reusable Rust library
  domain/  predicates/  clock/  event/  calculation/  strategy/
  market-data/                          pipeline, state and delivery
  market-data-construction/             independent construction rules
  order/  position/  account/  strategy-ledger/  risk/
  fee/  settlement/  margin/  broker/  broker-virtual/  execution/
  integration-contract/  metadata-json/  calculation-bridge/  runtime/  backtest/
  operators/  indicators/              pure Rust libraries (target placement)
packages/
  backend/
    Cargo.toml
    src/
      main.rs  lib.rs
      application/                     product commands/queries invoking the runtime facade
      transport/                       HTTP/WebSocket and DTO mapping
      security/                        authentication, authorization and Source grants
      persistence/                     Product stores and schema migration integration
      execution/                       composition using reusable libraries
      runtime_generation/              exact environment/binding/activation lifecycle
      workers/                         task claim, supervision, shutdown and recovery
      bootstrap/                       explicit startup configuration and assembly
    python/
      gateway_protocol/                generated bindings and infrastructure client constituent
    examples/                          technical conformance/diagnostics, not Product activation
    tests/
  frontend/                            official Web UI
plugs/                                 market rules, brokers, data sources (Rust preferred, Python second)
contracts/                             canonical versioned Product and cross-boundary protocols
deploy/  scripts/                       deployment and engineering tools
```

Each library directory uses its responsibility name, with a Cargo package name prefixed by `onlyalpha-` and Rust source in
`src/`. Kernel membership follows semantic ownership and dependency direction. SQLite, Python process/transport and
Provider dependencies stay outside the Kernel. Concrete Rust plugins use their own `src/` under `plugs/`. Each independently
deployable unit requires a distinct lifecycle, resource, fault or upgrade boundary.

仓内依赖从产品和插件指向基础库。`crates/` 中的库只依赖 `crates/` 成员提供的仓内实现。宿主和具体插件通过公开端口参与装配；涉及工件身份时，由装配方提供可核验的资源描述。各类 Cargo 目标和非 Cargo 引用的约束见[工程指南第 2 节](../AGENTS.md#2-架构边界与工程目录)。

BACKTEST 和 SIM 共用的确定性模拟场所由 [`broker-virtual`](../crates/broker-virtual/README.md) 提供，真实券商协议适配器由 `plugs/` 中的插件实现。插件职责、实际装配限制及发行单元对应关系见[插件能力与历史边界](plugin-capabilities.md)。

目标架构中 Backend 不再内嵌因子／策略算法编写与执行；`python/algorithms/`、旧 Python 因子编译／执行子进程及相关包装按 [ADR 0152](adr/0152-unified-runtime-dual-kernel-operators-qlib-dag-and-wasm-plugins.md) 清退。全部量化计算与交易执行语义收拢为 `crates/` 内的 `OnlyAlphaRuntime` 门面，Backend 只装配端口、托管生命周期并暴露正式 API。

### Rust 库的内部目录与说明

`crates/<lib>/` 只允许以下一级目录，按需创建，不要求空目录占位：

| 目录 | 职责 |
|---|---|
| `src/` | 库实现、随模块组织的单元测试及编译所需资源 |
| `tests/` | Cargo 集成测试及专用测试数据、辅助代码 |
| `examples/` | 使用公开接口的可运行示例 |
| `benches/` | Cargo 性能基准及专用数据 |

每个库的独立单元测试文件统一集中在 `src/tests/`，按被测职责命名；专用辅助文件放在
`src/tests/support/`，不再为每个业务模块创建物理测试目录。内联单元测试无需拆出。
测试文件仍由原业务模块挂载，保留原测试模块名与 `#[cfg(test)]`，通过精确 `#[path]` 引用保持逻辑模块归属和
私有访问能力；不得为移动测试而扩大公开接口，也不得改为统一从 `lib.rs` 挂载而改变所属模块。
现有供集成测试复用的辅助文件保留原归属；仅供私有单元测试使用的文件一并集中，不能借辅助目录保留私有测试用例。`src/tests/` 是库内部单元测试；库根 `tests/` 是 Cargo 集成测试目标，属于工程的功能测试。测试分类与入口见 [工程指南](../AGENTS.md#4-测试与验收)。

`Cargo.toml`、`README.md` 等必要文件位于库根目录。多个库或工程共享的参考数据仍位于根目录
`test-data/`，不因内部目录约束复制。Domain 的固定 TZif 资源及许可位于
`crates/domain/src/resources/tzdata/2026.3/`，随实际使用它的库编译。

每个库的中文 `README.md` 必须包含五个非空二级章节：目的与职责、边界与依赖、公开接口、状态与生命周期、
使用与验证。内容明确负责与不负责的范围、事实归属、输入输出、主要公开模块/类型/trait/函数、错误及约束、
直接依赖和适用的持久化恢复语义，并链接实际 Rust 公开入口。没有状态或持久化能力时明确说明。
README 是职责和调用导航，详细签名以源码及 Rust 文档为准，不创造另一份正式契约或验收 Authority。
修改公开接口时同步维护 README；目录白名单和必需章节由 `scripts/rust_kernel_check.py` 的源码检查入口校验。

Backend owns package/binary `onlyalpha-backend`. Frontend owns package `onlyalpha-frontend`.
These are the two runtime projects under `packages/`. Agent clients use the formal API. Quantitative asset authoring
and ownership follow [ADR 0150](adr/0150-product-layout-and-programmable-quant-assets.md). Release metadata is documented in [release versioning](release-versioning.md).

## Root Python source retirement

The owner freezes root `src/` as of 2026-10-29, including uncommitted changes. Its final state is deletion, not a permanent
Python reference/backend tree. This concerns root `src/`, not Rust `crates/**/src/` or Product `packages/**/src/` directories.
No new files or implementation/functionality may be added under the legacy root. Only deletion and the minimum consumer/import
rewiring required to retire existing implementations are allowed there. Backend gaps and fixes belong directly to their Rust owners.

For each complete capability, migrate real consumers and valid independent assertions, verify the affected closure, then remove
obsolete Python implementation, exports, dependencies, entry points and build/deployment wiring. Relocation alone is not migration;
Python business hidden behind an SDK, worker, plugin or forwarding facade does not satisfy the target. Still-required consumers
must migrate before deletion; they do not justify expanding legacy implementations.

Python remains permitted only for plugin or tooling implementations that retain their own boundary; factor and strategy
authoring is no longer a Python boundary (ADR 0152). Their source must reside in the appropriate `packages/`, `plugs/` or `scripts/`, never back in root
`src/`. This creates no extra release line and does not transfer backend Authority or recovery into Python. Completion requires
root `src/` absent and no active runtime/install/test/build/deploy/discovery dependency on that tree. Exact archived artifacts remain
subject to their original contracts. AGENTS.md §2 governs execution and acceptance; this section owns target placement.

## Library and module boundaries

| Boundary | Responsibilities and allowed direction |
|---|---|
| Domain | Canonical values; no Runtime, backend, DB, network or concrete plugin dependency |
| Predicates, Clock, Event, Calculation, Strategy | Retain their owning semantic contracts and explicit lower-layer dependency closures |
| Operators and Indicators | Dual-kernel operator registry (`VectorKernel` / `EventKernel`) with equivalence certification; indicators and factors compose certified operators only, with no hand-written rolling state or Python authoring |
| Market Data and Market Data Construction | Preserve construction/value reuse without forcing plugin/Strategy consumers to import Pipeline or process code |
| Order/Position/Account/Ledger/Risk/Fee/Settlement/Margin/Broker | Separate component owners; no direct mutation of another owner's private state |
| Execution | Pure planning and ordered commit/recovery coordination through owning ports; no concrete persistence/venue driver |
| Integration and metadata libraries | Shared SPI, exact normalization/fingerprints; never depend on Product business |
| Runtime | The sole abstract facade `OnlyAlphaRuntime`: research vector engine, unified Backtest/SIM/LIVE event engine, deterministic snapshot/replay and typed ports; no HTTP, authentication, storage driver or Product admission |
| Calculation bridge | Generated Gateway bindings and reusable adapters; the Python algorithm client and old protocol bindings retire with ADR 0152 |
| Backtest | Immutable-input replay/run-loop using the same Kernel; no Product admission, user authorization or task queue ownership |
| Plugins | Concrete external rules and algorithms through public contracts; no backend-internal dependency |

Calculation parameters, graph, registry and recovery remain internal modules of Calculation. Allocation/reservations/valuation
remain with their appropriate Position/Account/Risk owners; performance remains with its owning Account/Ledger/Execution
contract. Do not extract generic reservation, checkpoint, recovery or worker-manager crates merely because names recur.

Backend's `transport` calls Application Commands/Queries; it does not bypass them to mutate DB/Kernel state. Backend is a thin product shell: it assembles ports and supervises lifecycle but does not own quantitative calculation, factor/strategy semantics, a second research or backtest driver, or a second trading event loop (ADR 0152). Product persistence
implements owning business storage without exposing databases as cross-node integration APIs. `execution` assembles library
ports; `workers` coordinates existing Run/Attempt/Generation authorities rather than creating another status or binding store.
Bootstrap owns configuration and construction. Agent clients use the formal API, and client-side provenance does not grant
backend authority. Reusable libraries never import backend modules. Internal library targets for binary reuse do not create
separate release units or external control APIs.

## Processes and lifecycle

Default operator startup uses one `onlyalpha-backend` executable with `serve` and `worker` roles. Multiple processes are allowed
for actual fault/resource/security/lifecycle or exact Generation isolation; no package or service per worker. These startup
commands do not provide business operations around the Shipping UI/API. Deployment tools keep node/container lifecycle;
backend supervises its admitted workers/algorithm children without competing supervisors or duplicate Authority.

API/control remains responsive during bounded execution load. Execution workers claim only work admitted to their exact
implementation/Generation. Agent clients use the formal versioned API.
External IO plugins (broker and data source, L4 in ADR 0152) run as explicitly managed subprocesses under versioned
IPC contracts; process isolation alone is not authentication, authorization or a security sandbox.
Native process spawning/supervision belongs in backend; the reusable libraries accept the supplied channel/lifecycle port.
Checkpoint candidate reconstruction uses an explicit caller-supplied connector, not a hidden policy
inside library adapters. Failed kill/wait retains the same child and capacity until a positive join; explicit drain recovers
that owner without retrying work. The retired Python algorithm child is not a target execution path. Technical diagnostic/reference executables belong to backend examples and confer no formal
Product admission. The historical native Backtest artifact family and wire contract remain distinct from the Cargo target name;
new binaries bind their actual owning backend version and bytes, without rewriting old immutable artifacts.

Cross-process interactions use explicit contracts and owning durable admission/claim APIs, not arbitrary DB integration.
On crash, recover from existing durable facts/leases/reconciliation. Preserve cancellation, observation, UNKNOWN and risk
reduction; no blind retry, second order identity or inferred success. Deterministic fault tests cover API restart, worker
termination, child failures and interrupted durable boundaries. Role/permission checks precede claim and execution.

All backend roles and backend base Python resources ship under one backend version. Old backend/worker artifacts can remain for already-bound
work; new activation/rollback changes only new-work selection under ADR 0117. Version equality is not permission to claim work,
and a process restart is not a valid handover protocol. Keep required historical artifacts, readers, facts and keys.

## 原工程职责与当前实现归属

下表保留原工程名称用于定位历史职责；当前实现归属以右侧源码为准。

| 原 `packages/onlyalpha-*` 工程 | 当前职责归属 |
|---|---|
| `web-console` | `packages/frontend` |
| `http-server` | backend transport/security/bootstrap and program entry |
| `product-runtime` | backend Application, Product persistence and execution composition modules |
| `integration-contract`, `metadata-json` | `crates/integration-contract/` and `crates/metadata-json/` |
| `gateway-protocol` | Rust bindings in `crates/calculation-bridge/src/protocol/`, canonical definitions in `contracts/gateway/`, Python bindings in backend resources |
| `runtime-persistence` | reusable non-Kernel `crates/runtime/` library |
| `backtest-driver` | reusable `onlyalpha-backtest`; admission/task/process entry belongs in backend |
| `calculation-worker` | `crates/calculation-bridge` 保留生成的 Gateway 绑定与可复用适配；后端 `workers/algorithm.rs`、`trading_nodes.rs`、`research_calculations.rs` 的节点调度按 ADR 0152 收拢至统一 Runtime；`backend/python/algorithms` 与旧 Python 因子编译／执行子进程列入清退 |
| `authoring-execution-worker` | 后端 `workers/research.rs`、`application/research_admission.rs` 和 `persistence/research_execution.rs` 负责准入证明、认领、执行与恢复 |
| `runtime-generation-manager` | 后端 `persistence/research_runtime.rs` 及其 `lifecycle.rs` / `contracts.rs` 负责原有 Generation 日志、工件验证与工作绑定 |
| `operators` | `crates/operators` 目标为双内核算子注册表（`VectorKernel`／`EventKernel`）与等价认证；当前正式 Calculation 定义、实现清单与检查点适配仍在 `crates/calculation-bridge/src/native_operators.rs`，按 ADR 0152 阶段 1 迁移 |

Moving Python business into `backend/python` is not Rust migration. A retained interim implementation must be explicitly
classified in task context and follow the existing official-writer binding. No general compatibility re-export is added.

## Python resources, releases and retirement

Backend ships the exact artifacts of any Python runtime or bindings that retain a live owning boundary; the Python
algorithm executor and authoring SDK are retired under ADR 0152. Remaining Python implementations belong to their own
plugin or tool boundaries. Internal wheels may be build constituents; they are not worker product release lines.
Use one authoritative dependency description per actual installation closure; package metadata and deployment
must agree. Do not resolve latest packages on startup or use the host venv/node_modules as container dependencies.

不可变因子版本以声明式表达式加载，策略版本可采用声明式规则或 WASM 工件。正式运行通过工件、Catalog 和 Runtime Generation 契约绑定所用版本。使用已注册算子的表达式可以在同一进程加载。

Changing bundled
plugin or executor content requires the owning release. No algorithm child may own backend Product stores, Commands,
trading state or Generation selection.

The library set, backend and frontend release independently; plugins have their own distribution versions. Build inputs bind
exact library/plugin content, locks, toolchain, features, target and relevant non-secret configuration. Frontend/backend
compatibility requires API-contract evidence for declared
combinations, not matching version numbers. See
[release versioning](release-versioning.md) for metadata, tags and refusal rules.

Every selected Rust migration includes removal of obsolete Python code when its actual callers and semantic/product/recovery
gates permit. Preserve independent expected vectors and fault/replay assertions; delete obsolete dual-implementation-only
wiring after replacing its useful assertions. Retain the minimal Python algorithm API where still genuinely needed, not an
entire second Kernel. Exact historical artifact/readers remain under their owning contracts, without new legacy loaders or
source shims. [The work program](repository-migration-work-program.md) defines sequencing and required proofs; it does not
declare a module migrated or authorize deletion by directory name.

## 内置算子、指标与因子表达

目标架构（[ADR 0152](adr/0152-unified-runtime-dual-kernel-operators-qlib-dag-and-wasm-plugins.md)）中，`crates/operators`
是唯一算子底座。每个原子算子声明算子 ID、版本、输入／输出类型签名、warmup、null／除零边界、资源预算与确定性
数值规范，并成对实现 `VectorKernel`（列式批处理，可 SIMD 并预留异构后端）与 `EventKernel`（增量状态机，含
`capture_state`／`restore_state`）。每个算子必须通过独立数值 golden、`VectorKernel == EventKernel` 逐点等价、
多前缀因果性、warmup／null 边界及检查点恢复后缀一致认证。

`crates/indicators` 与所有因子只能组合已认证算子构建，不得各自维护手写滚动状态或私有数值逻辑。
因子与 Research 评估标签使用声明式因子表达式编写，解析为类型化算子 DAG 与紧凑指令流：`FactorExpr` 在编译期
拒绝前视偏移 `Ref($x, n)`（`n < 0`）及账户、仓位、资金、成交等非确定输入，通用于 Research、Backtest、SIM、LIVE；
`TargetExpr` 仅用于 Research 评估标签，禁止进入交易路径。不可变版本绑定规范化表达式、算子注册表版本、精确参数、
数值规范与认证证书。

数值规范沿用 `DECIMAL28_HALF_EVEN_Q12_V1`：每步十进制运算 28 位有效数字、HALF_EVEN 舍入，输出量化 12 位小数，
零统一为正零；平方根和自然对数使用精确整数比较或可证明的上下界；截面汇总采用冻结平面的规范 Instrument 顺序。
禁止以二进制浮点或运算重排改变结果，也不得据此修改资金、数量或 Ledger 的所属精度。截面算子要求调用方证明同一
事件时刻的完整规范平面，时间序列不能冒充截面。

当前实现状态：`crates/operators` 仍只包含少量流式算子，正式 Calculation 定义、实现清单与检查点适配位于
`crates/calculation-bridge/src/native_operators.rs`，`crates/indicators` 中仍有指标自持手写状态，发行 Manifest `3`
仍将内置算子 Provider 与原生实现清单绑定到同一个 `BACKEND_RUNTIME` ELF。旧受限 Python AST 因子接口见
[factor-program.md](factor-program.md)，已列入 ADR 0152 清退范围，不再是目标契约。双内核算子注册表、声明式因子表达式与
指标算子化按 ADR 0152 阶段 1 实施，完成前不得声称该架构已实现。

## Research／回测存储与信号边界演进

[ADR 0151](adr/0151-postgresql-business-publication-and-memory-work.md)及[有限作业契约](job-execution-contract.md)明确新框架：业务发布／控制／正式内容在PostgreSQL，K线实体在ClickHouse，有限作业未发布过程在内存；业务SQLite／文件Source退役。Runtime提供typed会话与纯持久化port，具体PostgreSQL接线属于Backend。原表中Runtime的store/replay职责不要求保留旧介质或逐Bar恢复。

Research 与交易共用同一套因子表达式定义与双内核算子语义：Research 以 `FactorExpr` 在冻结列式切片上向量化计算，Backtest／SIM／LIVE 以同一因子的 `EventKernel` 进入统一事件主循环，逐点结果一致。Research 不绑定策略修订或信号图；只读仓位、资金、风险和买卖意图属于后续交易环节。因子表达式解析、静态因果校验与数值执行均由 Rust 拥有，不再提供 Python 因子编写前端。开发阶段所有任务不提供历史代码、接口或开发数据兼容；不兼容开发状态直接成套删除并按当前契约初始化，不增加旧格式读取或迁移层。当前版本事实和恢复不变量仍须验证，不能用清空数据代替修复。实现与验证以当前源码和实际证据为准。
