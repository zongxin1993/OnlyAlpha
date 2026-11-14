# Repository and product architecture

This is the target architecture derived from the Constitution, [ADR 0142](adr/0142-library-product-boundaries-and-independent-releases.md) and [ADR 0150](adr/0150-product-layout-and-programmable-quant-assets.md), and retains the flat Rust layout from [ADR 0149](adr/0149-flat-rust-library-layout.md).
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
  fee/  settlement/  margin/  broker/  execution/
  integration-contract/  metadata-json/  calculation-bridge/  runtime/  backtest/
  operators/  indicators/              pure Rust libraries (target placement)
packages/
  backend/
    Cargo.toml
    src/
      main.rs  lib.rs
      application/                     Watchlist, Workspace, Integration, Research, Trading flows
      transport/                       HTTP/WebSocket and DTO mapping
      security/                        authentication, authorization and Source grants
      persistence/                     Product stores and schema migration integration
      execution/                       composition using reusable libraries
      runtime_generation/              exact environment/binding/activation lifecycle
      workers/                         task claim, supervision, shutdown and recovery
      bootstrap/                       explicit startup configuration and assembly
    python/
      algorithms/                      private bounded Python executor build constituent
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

插件职责、实际装配限制及发行单元对应关系见[插件能力与历史边界](plugin-capabilities.md)。

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
现有供集成测试复用的辅助文件保留原归属；仅供私有单元测试使用的文件一并集中，不能借辅助目录保留私有测试用例。`src/tests/` 是库内部单元测试，库根 `tests/` 是 Cargo 公开接口集成测试。

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

Permitted isolated algorithms and the minimum authoring SDK may remain Python under their existing
Product/plugin/tool boundaries. Their source must reside in the appropriate `packages/`, `plugs/` or `scripts/`, never back in root
`src/`. This creates no extra release line and does not transfer backend Authority or recovery into Python. Completion requires
root `src/` absent and no active runtime/install/test/build/deploy/discovery dependency on that tree. Exact archived artifacts remain
subject to their original contracts. AGENTS.md §2 governs execution and acceptance; this section owns target placement.

## Library and module boundaries

| Boundary | Responsibilities and allowed direction |
|---|---|
| Domain | Canonical values; no Runtime, backend, DB, network or concrete plugin dependency |
| Predicates, Clock, Event, Calculation, Strategy | Retain their owning semantic contracts and explicit lower-layer dependency closures |
| Market Data and Market Data Construction | Preserve construction/value reuse without forcing plugin/Strategy consumers to import Pipeline or process code |
| Order/Position/Account/Ledger/Risk/Fee/Settlement/Margin/Broker | Separate component owners; no direct mutation of another owner's private state |
| Execution | Pure planning and ordered commit/recovery coordination through owning ports; no concrete persistence/venue driver |
| Integration and metadata libraries | Shared SPI, exact normalization/fingerprints; never depend on Product business |
| Runtime | Concrete Trading store/replay implementation outside Kernel; not Product PostgreSQL ownership |
| Calculation bridge | Rust Gateway bindings, algorithm client and reusable Calculation/Strategy adapters; consumes an explicitly supplied process/transport boundary |
| Backtest | Immutable-input replay/run-loop using the same Kernel; no Product admission, user authorization or task queue ownership |
| Plugins | Concrete external rules and algorithms through public contracts; no backend-internal dependency |

Calculation parameters, graph, registry and recovery remain internal modules of Calculation. Allocation/reservations/valuation
remain with their appropriate Position/Account/Risk owners; performance remains with its owning Account/Ledger/Execution
contract. Do not extract generic reservation, checkpoint, recovery or worker-manager crates merely because names recur.

Backend's `transport` calls Application Commands/Queries; it does not bypass them to mutate DB/Kernel state. Product persistence
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
Backend Python runs as an explicitly managed algorithm child; process isolation alone is not authentication, authorization or a security sandbox.
Native process spawning/supervision belongs in backend; the reusable bridge accepts the supplied channel/lifecycle port.
Checkpoint candidate reconstruction uses an explicit caller-supplied connector, not a hidden interpreter or spawn policy
inside library adapters. Failed kill/wait retains the same child and capacity until a positive join; explicit drain recovers
that owner without retrying work. Technical diagnostic/reference executables belong to backend examples and confer no formal
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
| `calculation-worker` | `crates/calculation-bridge` 提供可复用协议与原生适配；后端 `workers/algorithm.rs`、`trading_nodes.rs`、`research_calculations.rs` 负责进程与节点调度；受限 Python 编写接口位于 `backend/python/algorithms` |
| `authoring-execution-worker` | 后端 `workers/research.rs`、`application/research_admission.rs` 和 `persistence/research_execution.rs` 负责准入证明、认领、执行与恢复 |
| `runtime-generation-manager` | 后端 `persistence/research_runtime.rs` 及其 `lifecycle.rs` / `contracts.rs` 负责原有 Generation 日志、工件验证与工作绑定 |
| `operators` | `crates/operators` 负责数值语义，`crates/calculation-bridge/src/native_operators.rs` 负责正式 Calculation 定义、实现清单、Provider 与检查点适配 |

Moving Python business into `backend/python` is not Rust migration. A retained interim implementation must be explicitly
classified in task context and follow the existing official-writer binding. No general compatibility re-export is added.

## Python resources, releases and retirement

Backend ships a platform-specific minimal interpreter/environment, executor, authoring SDK, bindings, licenses and exact
dependency artifacts/provenance. Internal wheels may be build constituents; they are not worker product release lines.
Use one authoritative dependency description per actual installation closure; package metadata, SDK builder and deployment
must agree. Do not resolve latest packages on startup or use the host venv/node_modules as container dependencies.

Algorithm plugins and materialized immutable private Revisions enter exact isolated environments through existing artifact,
Catalog and Runtime Generation contracts. Changing a private Factor need not rebuild backend. Changing bundled executor/SDK
content requires a backend release. Python algorithm children cannot own backend Product stores, Commands, trading state or
Generation selection.

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

## 内置算子与受限编写接口

内置算子的数值内核位于 `crates/operators`，完整 Calculation 定义、实现清单和检查点适配位于
`crates/calculation-bridge`。当前实现使用原有 `onlyalpha.operator.*` 名称和独立的语义版本 `2`。
每步十进制运算采用 28 位有效数字及半偶数舍入，输出量化到 12 位小数。平方根和自然对数的舍入
使用精确整数比较或可证明的上下界。零统一为正零。Delay 只依赖被移位的输入，Delta 同时依赖当前
输入和被移位的输入。截面的汇总顺序采用冻结平面的规范 Instrument 顺序。旧版本 `1` 的引用和摘要
不因此改变，当前编译入口不将旧引用自动解析为版本 `2`。

Research 的图拓扑与内置算子由 Rust 执行。Trading 和 Backtest 复用原 Strategy Executor、
Calculation 游标和收据，以独立节点实例执行原生算子。检查点绑定完整 Definition、实现、工作身份、
事件位置和窗口，恢复先构建并核对候选状态，再提交。截面算子需要其调用方证明同一事件时刻的完整
规范平面，时间序列不能冒充截面。受限 Python 编写接口和已明确隔离的算法不拥有图调度、Run、
Attempt、Generation、数据库或恢复权限。

Distribution Artifact Manifest `3` 将内置算子 Provider、24 项资产以及完整原生实现清单绑定到同一个
`BACKEND_RUNTIME` ELF。Provider 版本为 `7`。算子的 Research 和 Trading 实现身份分别绑定实际
入口及完整 ELF 摘要。该格式不再发布 Python 算子 wheel，也不把相同 ELF 包装成第二份发行工件。
Manifest `1`、`2` 仍按原字段和身份读取，历史引用不通过当前实现重写。

## Research／回测存储与信号边界演进

[ADR 0151](adr/0151-postgresql-business-publication-and-memory-work.md)及[有限作业契约](job-execution-contract.md)明确新框架：业务发布／控制／正式内容在PostgreSQL，K线实体在ClickHouse，有限作业未发布过程在内存；业务SQLite／文件Source退役。Runtime提供typed会话与纯持久化port，具体PostgreSQL接线属于Backend。原表中Runtime的store/replay职责不要求保留旧介质或逐Bar恢复。

Research与交易复用同一纯信号程序，信号只依赖行情／因子／显式参数；只读仓位、资金、风险和买卖意图属于后续交易环节。受限Python只承担因子编写／构建前端，实际typed程序与数值执行由Rust拥有。新框架不要求为旧接口／格式提供兼容；历史事实、工件及当前实际实现状态不得被文档声明重写。当前只完成第一阶段契约，后续实施与验证按各阶段进行。
