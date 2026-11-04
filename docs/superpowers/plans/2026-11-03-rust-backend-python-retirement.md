# Rust Backend Python Retirement Implementation Plan

> For agentic workers: use `superpowers:executing-plans` for inline execution, or `superpowers:subagent-driven-development` if the owner selects delegation. Execute one complete capability at a time. Following AGENTS.md, this file contains future construction order only: do not check off steps or record completion, audit, quality or acceptance status here. Keep Task Contracts, deletion inventories and evidence in the active task context.

**Goal:** 在保留 Python 因子、策略、指标及最小算法 SDK 的前提下，完成到回测的 Rust 后端收敛，逐批删除旧 Python 后端/Kernel 及其消费者，最终移除根 `src/`。

**Architecture:** 复用当前 Rust Kernel、backend、Plugin 和受控 Python 算法执行边界。每个能力的 Rust 替代、消费者切换、必要断言和旧实现/接线删除成套交付。根目录 `src/` 的消失是源码及活动依赖退出条件，不是 SIM/LIVE 或全市场认证。

**Tech Stack:** 现有 Rust/Cargo、Python 3.12 最小算法环境、uv/Hatch、Protobuf/Arrow、PostgreSQL/现有事实存储、React/Ant Design/ECharts、Playwright；唯一 `onlyalpha-dev` 验证环境。

**Spec:** [已批准设计](../specs/2026-11-03-rust-backend-python-retirement-design.md)。先读 Constitution，再读设计、直接 owning Contracts/ADRs、AGENTS.md 与当前源码。这里不授权提交远端、发布、删除用户数据或激活交易。

## Global Constraints

- Constitution Impact: NO；Constitution 与 fingerprint 只读。
- 保留 Python 因子、策略及指标算法；既有结构化 Strategy Definition 与 Rust canonical 交易语义不变，不新增任意 Python callback 驱动的第二套策略引擎。
- 不在根 `src/` 新增文件、实现、函数或业务分支；只允许必要退役接线与删除。后端缺口直接落正确 Rust owner。
- 当前产品清退旧 Orchestrator 与独立 Agent 的现行代码及运行接线。保留已有数据、精确历史构件和恢复所需的读取能力。普通数据、策略和回测构建、启动和操作无需 Agent、模型或凭据。Constitution 的长期 Agent 边界继续适用。
- 本轮到现有普通回测为止；不新增 SIM/LIVE、市场、独立服务、第二套 Compose 或第三方依赖。新增能力/实质选型变更按 AGENTS.md §3.4.1 另行调研确认。
- 不重写旧事实、已绑定 Generation、Strategy Revision、精确历史 artifacts 或历史身份；不 fallback、不选择 latest、不 blind retry UNKNOWN。
- 本轮明确包含退役所需 quality-policy、test discovery、构建/安装/验证入口修改；这些修改是高风险基础设施工作，只替换退役对象的检查归属，不降低断言、阈值或质量要求。
- Task Contract、Required Behavior、Impact Scope、专项 Proof Matrix、审计与验收结果只留当前上下文，不新增仓库状态账本。各批开始前冻结具体修改/删除文件集。
- 所有正式验证使用 `python3 scripts/dev_verification.py run -- <command>`；Python 宿主检查仅为快速定位。Rust 选择受影响 package 的单一开发 profile，不默认执行整个 workspace、双 profile 或全量历史比较。
- 每批初始验证后做 bounded Simplicity Review；高风险批次再做 bounded Independent Review。Authority/proof 变化按 AGENTS.md 独立推导 state space、relation closure、missing/UNKNOWN 语义及 adversarial mutations。当前范围 High/Critical 未解决不得结束该批。
- 已有通过证据仅在源码/依赖/配置未再受影响时复用。正常用户步骤必须来自 Shipping Web；接口/库/受控外部输入 fixture 不能代替产品验收。

## Review Focus

1. SDK 被迁出但 dev/CI/release 仍从旧路径取文件：Task 1/8 用实际 wheel 安装、源码 bundle 和 frozen-input mutation 测试证明只消费同一份新源码。
2. 旧 Python 算法数值与 Rust backend 责任混在一起：Task 1/3/6 证明数学/算法 checkpoint 仍可用，Python 环境中后端业务模块不可导入，交易提交与恢复由 Rust 决定。
3. 任务/结果在源码退役后无法读取或被 current 版本替代：Task 6/9 证明原精确 Run/Generation/历史 Evidence 的读取和恢复；缺失/损坏 artifact 显式 unavailable。
4. Agent 暂停后标准构建/启动仍安装或启动它：Task 2 在 Agent 包安装器不可调用、模型凭据不存在的情况下完成标准构建/启动；不能删除存储或旧会话来绕过。
5. 删除测试导致验证空跑或安全 guard 消失：Task 3–8 逐项保留有效断言并执行真实收集；Task 7 验证 `_test` DSN、namespace fencing、UNKNOWN 与退出信号传播。

## 主要实现参考：NautilusTrader v2

Owner 选择以 NautilusTrader 为本轮迁移的主要工程参考。参考固定为 [develop@0afcf8bc30f18114a5147c09700460e949face50](https://github.com/nautechsystems/nautilus_trader/tree/0afcf8bc30f18114a5147c09700460e949face50)，不是旧版 `develop_v1` Cython 实现；版本区别见其 [v2 migration guide](https://github.com/nautechsystems/nautilus_trader/blob/0afcf8bc30f18114a5147c09700460e949face50/MIGRATION_V2.md)。以下是实现方向和未来验证要求，不是 OnlyAlpha 已完成状态。

| 当前任务 | 优先参考的 Nautilus 实现 | OnlyAlpha 落地与验证边界 |
|---|---|---|
| Task 1/5：Python 指标、因子及策略算法 | [EMA 策略示例](https://github.com/nautechsystems/nautilus_trader/blob/0afcf8bc30f18114a5147c09700460e949face50/docs/tutorials/ema_cross.py)、[Python 指标对象适配](https://github.com/nautechsystems/nautilus_trader/blob/0afcf8bc30f18114a5147c09700460e949face50/crates/common/src/python/indicators.rs)、`crates/common/src/actor/data_actor.rs` | 审计现有算法实例的创建、预热、增量更新、ready、结果与 checkpoint 生命周期；优先复用当前 worker/session，避免每条输入重新安装、启动或重算整个历史。保留 Python 自定义算法和现有有效 API；不为名称一致另造注册框架，不移入业务 Authority。验证真实安装后的连续输入、预热边界、实例隔离和恢复后数值一致。 |
| Task 6：Rust 回测循环与数据调度 | [Rust engine](https://github.com/nautechsystems/nautilus_trader/blob/0afcf8bc30f18114a5147c09700460e949face50/crates/backtest/src/engine.rs)、[有序多流 iterator](https://github.com/nautechsystems/nautilus_trader/blob/0afcf8bc30f18114a5147c09700460e949face50/crates/data/src/replay/iterator.rs)、`crates/backtest/src/exchange.rs` | 对照既有 RunLoop/Trading/worker 的实际调用图，检查游标推进、时钟、同时间排序、指标更新、策略决策、撮合与事件排空顺序。沿用当前 Rust owners；不复制第二套 engine。用独立顺序/费用/现金/成交向量及 fresh-process 故障恢复验证。 |
| Task 6/9：性能与产品闭环 | [同步 Python callback 边界](https://nautilustrader.io/docs/latest/concepts/python/)、上述 Rust 主循环 | 将输入读取、Rust 状态推进、算法计算、进程/协议边界和 journal/recovery 成本分开测量；先定位重复工作再改。库故障向量可用明确的小型完整输入，但不能缩短 Product admission 样本、变更身份或提高超时，并以此声称正常产品性能通过。 |

Nautilus 的内置指标通常由 Rust 实现并暴露 Python API，自定义指标则可保留 Python 对象；这不改变本轮保留 Python 因子、策略、指标算法的决定。其同进程 PyO3 回调不等于隔离执行，本轮仍遵守 ADR 0141 的受控算法边界，不引入 PyO3、依赖、任意 Python 交易 callback 或新的控制入口。

Nautilus 的 [Bar execution](https://nautilustrader.io/docs/latest/concepts/backtesting/bar-execution/) 包含 OHLC 模拟路径，零延迟下 `on_bar` 订单可在当前 Bar 收盘状态成交，并非原生 NEXT_OPEN。OnlyAlpha 保留现有 NEXT_OPEN、canonical identity、immutable inputs、Web/API、Risk、Evidence 与 durable recovery 语义；不照搬成交假设、风险 bypass 示例或内存对象地址身份。

每个后续能力批次在当前 Task Contract 中先列出相关 upstream 文件、可复用的本地实现、采用点与语义差异，再冻结修改集；没有缺口则仅迁消费者和删除旧接线。新增或实质改变选型仍遵守 Global Constraints，不借参考项目绕过 owning Contract。

## 工程文件与交付边界

| 边界 | 当前文件与计划责任 |
|---|---|
| 最小算法 SDK | `scripts/build_algorithm_sdk.py::build/install`；从根 `src/onlyalpha` 抽取的 SDK 源码移到 `packages/backend/python/algorithms/sdk/onlyalpha/`。现有 worker 源码仍在该算法资源的 `src/onlyalpha_backend_algorithms/` |
| Python 算法插件 | `packages/onlyalpha-indicators`、`operators`、`targets`；只保留算法/描述/必要 authoring，不容纳后端业务 |
| Kernel owner | `crates/onlyalpha-kernel/*`；按现有二十个 crate 和真实依赖划分能力，不按旧 Python 类/目录机械照搬 |
| 数据/Provider | Rust `plugs/onlyalpha-data-source-binance/rust`、`plugs/onlyalpha-data-source-tushare/rust`、`packages/backend/src/application/market_data*`、`persistence/market_data*`、`market_data_wal.rs` |
| 资产/准备/回测 | backend 的 `application/private_factor*`、`private_strategy*`、`strategy_validation`、`frozen_strategy.rs`、Qualification/Promotion、`backtest_*`、对应 persistence、`workers/backtest*`/`trading_*` 与 `crates/onlyalpha-backtest` |
| 工程/安全工具 | `scripts/database.py`、`compose_test.py`、`backtest_replay_check.py`、`*_reference_check.py`、`rust_kernel_check.py`、`verify.py`、`test_suite.py`；沿现有 owner 改接线，不新建通用迁移框架 |
| 构建与发布输入 | `pyproject.toml`、`uv.lock`、`hatch_build.py`、`scripts/embed_build_provenance.py`、`runtime_build.py`、`runtime_artifacts.py`、`native_workstation_build.py`、`release_sources.py`、版本/发布消费者、`.github/workflows/ci.yml`、`deploy/Dockerfile.dev` |
| 产品证明 | 现有前端策略/回测页面；新增 `packages/frontend/e2e/backtest.spec.ts` 只走正常 UI；通过现有 `scripts/native_web_e2e.py` 运行 |

## Task 1: 让实际算法安装包摆脱根 `src/` SDK 源码

**Files:** Modify `scripts/build_algorithm_sdk.py`、`scripts/release_sources.py`、`scripts/verify.py`、`pyproject.toml`、`deploy/Dockerfile.dev` 及其直接消费者；将 builder 的 `SDK` 清单中当前文件逐一迁入 `packages/backend/python/algorithms/sdk/onlyalpha/`，必要最小 package 初始文件也归该边界。Test `packages/backend/tests/transport/test_chart_algorithm_closure.py`、`test_trading_algorithm_session.py`、`test_trading_algorithm_transport.py`、`test_release_sources.py`；新增工具自身安装测试 `tests/tools/test_algorithm_sdk_installation.py`。

**Interfaces:** 保留 `build(output: Path) -> list[Path]`、`install(output: Path, destination: Path) -> str` 及现有 `onlyalpha.algorithm` / 数学 SDK imports、worker 模块入口、协议/安装 manifest 语义。源码位置变更必须改变相关构建输入记录；不伪造旧 artifact digest。

1. 审计当前 `SDK` 的完整 import、动态字符串、entry point、插件和安装闭包，尤其嵌套的 `packages/backend/python/**`；现有 `audit_src_semantic_surface.collect()` 只作线索，不能依靠其旧浅层目录枚举作删除证明。冻结本批数学/DTO 与业务的文件分类。
2. 先写 `test_sdk_wheel_build_uses_only_owning_algorithm_sources` 和 `test_installed_sdk_ignores_ambient_legacy_backend`：在只包含已声明算法构建资源的临时 source bundle 中调用实际 `build/install`；bundle 不含根 `src/`；实际安装以 `-B -I` 执行并拒绝从故意污染的 `PYTHONPATH` 加载旧业务模块。初始实现应因 builder 读取旧路径而失败；保留真实十四类指标、私有因子、交易/研究 framed transport 与 checkpoint 数值断言。
3. 用移动而非复制建立 SDK 单一维护源码。builder 仍构建现有内部 wheel，不新增产品发行线。为剩余 legacy Python 消费者保留正常打包途径：根旧 wheel 在退役期间通过显式 Hatch `force-include` 包含迁出的相同 SDK 叶文件，旧包自身初始文件保留到其消费者退出；验证环境将 root `onlyalpha` 改为非 editable 安装。不得修改 `sys.path`、动态导入旧源码或新增 namespace shim。Shipping 最小 wheel 仍只含算法 SDK，不包含旧后端。
4. 同批更新 SDK source bundle、frozen-input 哈希、根旧 wheel 与最小 wheel 的实际构建测试，证明两种安装闭包引用的是同一份 SDK 维护源码；旧 root wheel 仅服务尚未退役的 legacy 测试/消费者，不成为新的长期维护接口。已有 legacy 消费者路径测试随实际 source owner 更新，不能跳过。
5. 验证命令：`python3 scripts/dev_verification.py run -- python -m pytest -q tests/tools/test_algorithm_sdk_installation.py packages/backend/tests/transport/test_chart_algorithm_closure.py packages/backend/tests/transport/test_trading_algorithm_session.py packages/backend/tests/transport/test_trading_algorithm_transport.py tests/tools/test_release_sources.py`。再执行上述实际改动 Python 文件的 Ruff check、format --check、mypy 和对应构建输入测试。预期真实安装执行与禁止业务 imports 断言通过，无 editable/ambient 回填。审阅后形成一个可运行的完整 SDK 提取交付。

## Task 2: 普通工作站的构建与启动解除 Agent 强制依赖

**Files:** `scripts/native_workstation_build.py`、`runtime_artifacts.py`、`dev.py`、`dev_verification.py`、`runtime_build.py`、`deploy/Dockerfile.dev`、`deploy/docker-compose.dev.yml` 中真实强制依赖点；Test `tests/tools/test_native_workstation_artifacts.py`、`test_runtime_artifacts.py`、`test_dev.py`、`test_dev_native_startup.py`。现行 Agent 源码和专属构建、服务、Web 与 API 接线随清退移除。保留历史数据模型。

**Interfaces:** 保留 `native_workstation_build.build(directory: Path, *, release_input_path=None, release_input_sha256=None, source_bundles_path=None) -> dict[str, Any]`，默认产物为 backend/frontend/算法资源。`runtime_artifacts` 已允许无 Agent 记录，优先复用；显式包含 Agent 的已支持 artifact 仍按原精确 contract 验证，不静默丢弃它。

1. 写 `test_default_native_build_does_not_install_or_start_agent`：将 Agent 安装调用设为立即报错，标准 build 不应调用；独立 Agent 包目录暂不可用且无模型凭据时，标准 startup 参数和所需资源中不出现强制 Agent 项。保留现有含 Agent artifact 的 tamper/rejection 测试。
2. 通过 canonical wrapper 运行对应新增测试，确认目前强制 `install_agent` 路径导致失败。
3. 移除标准构建和启动中无条件 Agent 安装/监督依赖；优先使用已有可选资源语义，不新建配置平台。同步 Docker/输入选择及普通启动 attestation 的真实依赖，保留 backend 安全、namespace 和资源限制。移除现行 Agent 专属路由和交互入口。保留既有聊天数据及正式 Evidence 所需的历史读取。
4. 运行受影响工具测试；构建实际不含 Agent 的工作站资源并验证 seal。确认标准 backend 仍正常进入 READY；这只是基础设施证据，业务操作留到 Task 9。
5. 做 bounded review 后交付；不得以“Agent 暂停”为理由改写其工作流、预算或历史恢复。

## Task 3: 按真实消费者逐个退役已迁移 Kernel 能力

**Files:** 每次只选择对应 `src/onlyalpha/<owner>/`、`crates/onlyalpha-kernel/<owner>/`、`tests/<owner>/`、共享 vectors、相应 `scripts/*_reference_check.py` 与直接调用方。现有 Rust tests 与 `tests/tools/test_rust_<owner>_boundary.py` 为 owner 证据；不一次性删除整个 `tests/`。

**Interfaces:** 保留各 Rust crate 现有 public typed API、canonical bytes/error/identity 与回放语义；后续批次只消费这些已有接口。新增 Rust 函数仅用于当前缺口，签名在该能力 Task Contract 中从 owning Contract 推导，不新增统一迁移 facade。

1. 对每个能力建立上下文中的映射：旧公开 API/entry point → 当前 caller → Rust owner → 有效向量/故障断言 → 本批删除集。选择顺序按真正的依赖而非文件数量：先基础值/规范化、Clock/Event/Calculation/Strategy，随后 Market Data 能力，再 Order/Position/Account/Ledger/Risk/Fee/Settlement/Margin/Broker，最后 Execution。存在高层旧消费者时先迁消费者或将它们作为同一完整能力闭包处理；不得先删底层。
2. 从旧测试提取仍独立有效的预期值与错误，补到对应 crate 的现有 tests；对确定缺口先复现失败，再在 Rust owner 修复。旧 Python 只是参考，不是 oracle。测试至少保留该能力实际涉及的 canonical 序列化/identity、边界错误、determinism 和 recovery；没有缺口时复用已有向量，不造镜像测试。
3. 对照工具若仅为了运行 Python/Rust 两套实现，将有效预期值转为 Rust 直接读取的既有 `test-data/<domain>/` 向量，再删除旧 Python evaluator 与测试接线。生成器若依赖旧业务对象，改成无旧实现依赖的独立显式向量生成或 Rust owning test；保留生成物一致性守卫。
4. 迁完当前真实消费者后，在同一交付删除本批旧模块、exports、旧测试、comparison wiring 和不再需要的依赖。对剩余 caller 执行 imports/entry-point/实际测试收集检查；不存在消费者不是仅凭 rg 无结果推断，还要检查 discovery/安装。
5. 每个能力单独执行 `python3 scripts/dev_verification.py run -- python scripts/rust_kernel_check.py --package <实际受影响包名>` 及真实直接消费者的定向测试；命令中的包名必须在上下文展开，不能使用无参数全量模式。边界改变增加对应隔离构建。比较前后独立向量，完成 bounded Simplicity/Independent Review，随后才继续下一个能力。此 task 是重复执行的能力单元规则，不是一次二十包的门禁。

## Task 4: 数据源、行情存储与 Python Provider 存量退役

**Files:** 旧 `src/onlyalpha/data`、`collector`、`market_data`、对应 persistence；`plugs/onlyalpha-data-source-binance`、`tushare` 的旧 Python 分支/entry points 与 Rust owner；其余旧具体市场插件只处理真实消费者可安全退役的部分。直接 Rust owner 在 backend 的 `application/market_data*`、`persistence/market_data*`、`market_data_wal.rs` 与 Kernel Market Data crates。

**Interfaces:** 复用当前正式数据源/查询/历史准备 API、canonical Source/Instrument/Fact identities、WAL publication/recovery 和 Dataset 封存读取接口。API 不改成 browser 计算/直连 Store；具体规则留 Plugin。

1. 审计到回测所用数据源以及被 SDK、fixture 生成器、entry point 引用的旧 Provider；区分正式当前能力、仅参考实现和未获准外部 lane。旧股票/期货目录的存在不授权本轮新增这些市场。
2. 在现有 owning tests 保留/补齐 exact source、样本区间边界、缺失历史、重复/冲突事实、WAL 重启与 Dataset 读取断言；已有正确测试不重复造。若清理破坏真实 source consumer，先复现再修正确 Rust owner。
3. 迁移有效消费者；成套删除已被 Rust 替代的 Python Provider、旧 Store/采集编排及测试、entry points、依赖。纯算法插件继续保留；Python Provider 的市场规则若仍有本轮正式消费者，先补 Rust Plugin，不能塞进 Core 或 SDK。
4. 验证对应 Rust packages、真实数据库/文件存储回归和算法执行不受影响。数据源正常创建/选择/历史准备的业务步骤最终必须由 Task 9 的 UI 路径完成，直接 API checks 仅证明技术性质。
5. 审阅只覆盖本批 owner 与直接消费者；无法替代的外部环境证据明确 unavailable，不据此删除适用历史/身份义务，也不扩大到全部市场认证。

## Task 5: 私有算法资产、策略与 Generation/准备旧编排退役

**Files:** `src/onlyalpha/quant_assets`、`application`、`runtime/generation`、`research` 的直接相关部分；`packages/onlyalpha-authoring-execution-worker`、`onlyalpha-runtime-generation-manager`、`onlyalpha-calculation-worker` 中实际被替代的业务部分；对应 Rust application/persistence/worker owners。保留 Task 1 的算法执行资源，不把整个旧 worker 搬入其中。

**Interfaces:** 保留当前 DB-native Draft/Revision、精确算法 API、Provider/Catalog、Runtime Work binding、原准备 Command/receipt、Freeze/Qualification/Promotion。复用现有 `backtest_preparation::BacktestPrepareInput`、`BacktestOrigin` 及准备查询/确认 API，不创造另一套准备或 Generation 真相。

1. 审计算法保存/发布、策略保存、Generation materialization、验证、准备与取消的真实链路。原 Research 能力中仍被正式 caller 使用的部分也必须迁出旧 Python；不开发 Agent search，不重构暂停的独立 Agent。
2. 复用/补齐 `packages/backend/tests/application/test_manual_backtest_validation.py` 当前有效真实 producer 断言、`backtest_preparation.rs`、`strategy_validation/tests.rs`、相关持久化/route tests。Python harness 若只编译/驱动 Rust 可保留，若执行旧 backend 必须迁移其断言。
3. 迁移并测试相同 Strategy 重复准备复用原 admission、取消后已经发生的 Freeze 仍真实可见、READY 前没有 Run、失联保留原 Command/UNKNOWN、Generation 缺失/篡改拒绝、不同 Generation 不串用数学状态。不能把 optional downstream fact 缺失解释为原 occurrence 不存在。
4. 修改实际 consumer 到 Rust owner 后删除被替代旧 worker/package 的完整业务接线，更新 workspace/locks/entry points/测试发现和构建 provenance。`packages/onlyalpha-agent-orchestrator` 只在已被独立 Agent 或 Rust owner 替代、无正式 caller 后退役；不得删除 backend-owning Research/授权而把职责交给 Agent。
5. 定向验证该批 Rust tests、安装后的 Python 数学计算、受影响数据库/取消恢复与 Product API contract；高风险审阅从 Authority 状态空间独立推导后再比对实现。缺失则继续修 Rust，不回填根 `src/`。

## Task 6: 正式回测执行、结果与恢复旧实现退役

**Files:** `src/onlyalpha/backtest`、`runtime/trading`、`engine`、`execution` 等实际闭包；`crates/onlyalpha-backtest/rust`、`crates/onlyalpha-runtime-persistence`、backend 的 `workers/backtest_service.rs`、`backtest_worker.rs`、`backtest_terminal.rs`、`backtest_result.rs`、`trading_nodes.rs`、`trading_program.rs`、`persistence/backtest_*`、`transport/host_backtest*`；现有 tests/application/support/backtest_* 与 Rust tests。

**Interfaces:** `backtest_service::Produced::{Terminal(JoinedBacktest), Paused(PausedBacktest)}` 保持只有真实 terminal replay 和 positive child joins 才能获得 JoinedBacktest；沿用 `onlyalpha_backtest::{RunLoop, RunSpec, Trading}`，结果继续由原 Run 和 verified Evidence 推导。

1. 找出所有旧 Python replay、结果构造、性能对照和 Runtime 工具消费者；尤其 `scripts/backtest_replay_check.py::replay_environment(root: Path, artifacts: Path) -> dict[str, str]` 当前仍构造 Python domain/Dataset，是 Rust package 验证的间接旧依赖。
2. 将 replay 技术前提改为现有独立向量和 Rust owning composition：优先复用 backend 已安装算法的 trading fixture、`tests/application/support/backtest_native_host.rs`、回测服务/worker支持及 runtime-persistence fixtures，不新增对外产品入口。不再用旧 Python backend 生成预期值或正式 Evidence；受控输入仅作库/故障测试技术前提。库故障向量必须运行其完整声明输入及实际算法/Execution，保持经济效果和每个适用 cut/mutation；与正常 Product 的固定 admission、样本及性能证据分开，不为库测试伪造 Product preparation。
3. 复用 `crates/onlyalpha-backtest/tests/replay.rs`、`open_phases.rs`、runtime-persistence 的 `replay_journal.rs` 和 backend 现有 lifecycle/service/evidence tests；有缺口时补断言：pause/cancel/error/terminal 各自身份与 owner 保留、子进程未 join 不得释放容量或 mint success、crash/restart 不重复业务效果、损坏必需 fact 显式拒绝、相同初态和有序输入产生相同结果/bytes。
4. 旧结果与 performance comparison 中有效现金、费用、成交、持仓、净值/回撤和 traceability 断言迁入 Rust owning tests；删除只为 Python parity 存在的 evaluator 与路径。不能以数值看起来一致代替独立错误/recovery 断言。
5. 运行 `python3 scripts/dev_verification.py run -- python scripts/rust_kernel_check.py --package onlyalpha-backtest --package onlyalpha-runtime-persistence --package onlyalpha-backend`，仅在这三包均实际受影响时使用该组合，否则缩小。执行该批数据库 producer/lifecycle 测试；旧历史 work 所需 artifacts/readers 不可用时明确阻塞其删除，不引入新旧源码 loader。

## Task 7: 工程数据库工具与 canonical runner 消除旧后端导入

**Files:** `scripts/database.py`、`compose_test.py`、`market_data_database.py`、`dev_verification.py`、`native_web_e2e.py` 中真实 legacy 调用；Rust `packages/backend/src/main.rs`、`bootstrap/research_namespace.rs`、`bootstrap/research_namespace/manual_backtest.rs`、`persistence/schema.rs` 及需要承担现有基础设施操作的 backend owner。Test `tests/tools/test_browser_database.py`、`test_manual_namespace_operator.py`、`test_dev_verification.py`、`test_dev_native_startup.py` 与 Rust 对应 bootstrap/schema tests。

**Interfaces:** 复用 `--initialize-fresh-research-namespace`、`--verify-research-namespace`、`--extend-strategy-research-namespace`、`--extend-manual-backtest-namespace`。保留 `_extend_manual_backtest(dsn: str, user_data_root: Path, native_backend: Path | None = None) -> str` 等当前调用方已消费的工程函数签名，函数只调用原生 owner，不构造 Python business objects。

1. 枚举 scripts 的真实旧 imports、默认参数求值、provenance 读取和动态调用；尤其 `compose_test.py` 的 `_test` database guard 来自旧 persistence，`database.py` 的 namespace/schema/backup 验证仍有大量旧 store 类。仅无 callers 的旧工具可删除，活跃维护/备份恢复工具不能无声移除。
2. 在原 test 文件增加/复用拒绝错误 DSN、跨 namespace、busy/UNKNOWN fence、missing/corrupt schema 和异常退出信号传播断言。证明拒绝发生在连接/变更前；数据库名字从正式 parser 读取，不用字符串尾部猜测 authority。
3. Python 工具保留 stdlib/现有 psycopg 的连接与平台调用部分；namespace/schema/正式事实验证由现有 Rust owner 完成。必要基础设施 native 命令只补现有操作所需薄入口，在本批上下文冻结精确 CLI/错误输出和 owner，不创造业务 API 旁路。禁止把旧 Store/model 搬到 scripts。测试数据库安全 guard 可归工程工具局部 helper，保留原语义与负例，不成为第二份业务 authority。
4. 更新调用方与测试 fixture 后删除全部已被替代的旧 imports/工具。backup/restore 若有真实当前 consumer，使用已有原生 owner 验证和成熟 PostgreSQL 工具，保留耦合文件/数据库/key 的原恢复约束；不在本轮执行用户数据 restore/reset。
5. canonical wrapper 下运行上列受影响工具/真实隔离数据库 tests、必要 Rust tests，以及 affected Ruff/format/mypy。审阅必须证明 guard 没因 root 退出而消失；新工具入口仍只是明确基础设施管理，不成为正常业务操作入口。

## Task 8: 最后一批根源码、umbrella 打包与质量接线退役

**Files:** 根 `src/` 全部剩余内容，根 `pyproject.toml`、`uv.lock`、`hatch_build.py`、`quality-policy.toml`、`scripts/test_suite.py`、`verify.py`、`rust_kernel_check.py`、`runtime_build.py`、`release_sources.py`、`release_metadata.py`、`version_sync.py`、`embed_build_provenance.py`、`.github/workflows`、`deploy/Dockerfile.dev`、`tests/conftest.py` 及残留旧 test support/discovery；仅修改实际命中的消费者。

**Interfaces:** 根 Python 工程转为工具依赖/uv workspace；最小 SDK distribution 继续为算法提供 `onlyalpha` import，不再由 root legacy backend distribution 提供。新内部 manifest 放 `packages/backend/python/algorithms/sdk/pyproject.toml`，加入同一 uv workspace，SDK wheel 仅包含 `sdk/onlyalpha`，版本由现有 backend 发布输入派生/核验，不新增 SDK 产品/tag/release line。原有算法 worker/plugin 依赖仍指向这个最小 SDK。精确版本值按实施时 backend manifest，不写死当前版本。

1. 做全活动 consumer 的退出核对：维护源码、pyproject entry points、动态字符串/注册、SDK builder、release source bundles、CI、Docker COPY/RUN、test discovery、examples、fixture 生成器及暂停 Agent 都不再依赖根旧源码。历史 docs 和 immutable artifacts 的旧路径说明无需抹除；被误保留为当前 loader 的引用必须处理。不能仅按静态 import 无结果判定完成。
2. 建立 `tests/architecture/test_python_backend_retirement.py`（含 package 初始文件）验证根 `src/` 缺席、活动 manifests/build/discovery 不包含退役资源；为实际 source admission/安装增加负例，重新引入旧 backend module、旧打包资源或 editable root 依赖会拒绝。它是普通工程测试，不生成认证账本。
3. 删除 root legacy backend 的 project/build hook，SDK 内部 metadata 和 builder统一消费 Task 1 的维护源码；删除 Task 1 的临时 legacy wheel force-include/非 editable root 接线。`embed_build_provenance.py` 仍供 Rust资源构建使用时把 carrier 移到现有 build 产物边界并绑定 backend Cargo version，保留 exact provenance 字段/校验；不把 source files 写回已删除 `src/`，不改写旧 carrier。
4. 逐文件删除剩余已退出 Python 实现与专属 tests/support；有用的共享 golden/fault 断言必须已在正确 owner 运行。清理旧 packages、workspace members/dependencies/locks、version同步、安装/构建/部署/发现和 obsolete comparison lanes。coverage/mutation 原来针对旧 backend 的配置应由实际保留 owner 检查接替，不虚设低阈值或空目标；保留 CI 所要求的 Rust和Python算法检查。删除只剩本批产生缓存的已确认空壳目录，不递归清理未知 test-results 或用户文件。
5. 验证退役 guard、真实 uv lock/install/build、`tests/tools/test_release_sources.py`、`test_release_units.py`、`test_runtime_build.py`、`test_rust_kernel_check.py`、`test_chart_algorithm_closure.py` 的受影响部分及实际算法执行。检查 selector 选择的真实检查而非盲跑全部 `verify run`；若旧路径删除被粗粒度规则扩大为全仓，先正确更新 impact 映射和其 tests。Required Check 不可因路径没匹配而消失。
6. 构建不包含旧 `src/` 的正式 source bundle，并从这个 bundle 安装 SDK/插件、构建受影响 Rust backend 和 Shipping Web资源；验证 missing/drifted SDK/provenance/input 拒绝。做高风险基础设施 review；所有当前 legacy consumer 未退出则本批不能完成。

## Task 9: Agent 不可用时的真实 Shipping Web 回测闭环与重启验证

**Files:** Create `packages/frontend/e2e/backtest.spec.ts`；复用现有 `e2e/support` 普通 UI helpers 和 `scripts/native_web_e2e.py`，仅补本次所需 selection/restart evidence 接线，不新增测试页面/隐藏按钮。后端/前端产品代码仅修复阻塞本次迁移的实际回归。

**Interfaces:** 使用现有策略与回测页面、正式 Product API 和真实 canonical backend；`--restart-check` 下通过普通 UI URL/记录恢复同一任务。测试 evidence 只保存可从 UI 获得的导航/显示信息，不注入业务 state。Agent 进程/凭据缺席，模型解读不作为前置条件。

1. 编写 `test('normal backtest works without Agent and reopens the same run after restart', ...)`：从正常导航/编辑器选择或创建确切 Python 因子、指标和受支持策略条件，保存策略；选择真实正式 Source，配置样本、资金、费用；确认准备，等待真实 READY，再明确开始；等待终态，读取净值/回撤、费用、成交/持仓与原 Run。不得使用 `page.request`、route mocks、DB seed 或 JS state injection 代做上述业务步骤。对当前普通路径不支持的 Python authoring 形式不凭空新增支持。
2. 无当前产品步骤的 fixture 仅建立声明的既有外部数据前提，不能预建本次因子/策略/准备/Run。 空白测试部署可先通过原生基础设施入口建立空 Registry；不能预建 Generation、activation、work binding 或计算验证，也不能把已有业务历史当作空白。受控外部输入明确标为 hermetic input，不称作真实市场证据。复用现有事实来源与样本约束，不扩大到全市场回测。
3. 刷新/重启后从正常记录入口重新打开同一任务，核对 UI 可见样本/策略版本、指标、成交和原 URL；算法原 artifact 仍精确绑定。取消、UNKNOWN 原操作查询恢复的技术 fault tests 在 Task 5/6，Browser 按真实可见状态检验下一步，不能增加隐藏 fault 控件。
4. Run: `python3 scripts/dev_verification.py --controlled-source-https run -- python -m scripts.native_web_e2e --retained-market-input --controlled-source-https --backtest-market-input --restart-check e2e/backtest.spec.ts`。外层验证器与 runner 同时显式选择 controlled HTTPS；既有 retained input 建立 Source 前提，backtest input 只提供固定 20+720 分钟受控外部响应并声明近期 15m 图表历史缺席，不预建准备或 Run。不加 `--agent`。正常使用数据源不同而不需该受控输入时，在上下文说明并移除全部受控输入相关选项（含外层验证器选项），不能改用 mock backend。预期完整用户路径和相同原 Run 的 restart phase 均成功；环境不可用明确保留为未验收。
5. 同路径 dogfooding 检查必要输入/默认值、关键费用/样本、loading/empty/error/unavailable/success、焦点/键盘、窄屏与滚动；复用合同预算，记录实际耗时，不能提高 timeout 掩盖回归。普通错误可从 UI 恢复，结果尚未确认不能显示成可盲重试失败。
6. 执行只受实际产品修复影响的前端/后端回归，修复后重跑相应路径。最终 bounded review 核对各批保留断言与真实源码/安装闭包，报告技术、DB、Browser 与平台证据边界。达到设计与 AGENTS.md Stop Condition 后停止，不顺延 Agent/SIM/LIVE、发布或全仓性能优化。

## 每批验证与交接方式

步骤中的 `<实际受影响包名>` 由该批具体调用图展开；没有展开就不能开始执行。Python 标准检查形式为 `python3 scripts/dev_verification.py run -- python -m ruff check <affected files>`、`... ruff format --check <affected files>`、`... mypy <affected files/modules>`。对 Cargo 改动使用现有 package-selected runner；较大 package 中的 DB/harness 使用现有精确 pytest selector，不自动提升整条 lane。

每个可独立运行的完整能力形成一个本地审阅单元；若 owner 授权提交，使用明确文件列表提交，禁止 `git add .` 混入无关改动，不自动 push。设计/计划不写勾选状态或 PASS；具体文件、命令、结果、未决阻塞和剩余批次在当前上下文交接。发布 / Major Milestone 的全量门禁仅在对应明确授权中执行。

若一个能力需要突破回测 scope、另开新市场/Agent 功能或更改尚未决的历史 authority，保留当前唯一 owner 并报告具体阻塞；不删除仍有消费者的模块，也不能把 `src/` 尚存说成清理完成。发现 Constitution 冲突时报告 PLAN_CONFLICT 并停止实现。

## Relevant references and failure lessons

- [本地工程参考注册表](../../engineering/reference_registry.md)；[FP-RUNTIME-001](../../engineering/failure_patterns/FP-RUNTIME-001-generation-contamination-and-fallback.md)：版本相同不等于相同执行字节。Task 1 的真实安装/污染输入拒绝、Task 5/6 的 exact Generation/missing artifact tests 落实，不采用 reload/latest fallback。
- [Python 3.12 isolated mode](https://docs.python.org/3.12/using/cmdline.html#cmdoption-I)：`-I` 排除当前目录/用户 site 并忽略 `PYTHON*` 环境变量。Task 1 用实际解释器证明导入闭包；它不等于权限/操作系统 sandbox，现有算法隔离测试仍必须保留。
- [PyPA repeatable installs](https://pip.pypa.io/en/stable/topics/repeatable-installs/)：锁定版本、内容校验与明确安装包闭包有不同作用。Task 1/8 同时测试 manifest/source/bytes 和实际安装，不在运行时联网解析依赖，不新增 pip resolver。
- [FP-STORAGE-001](../../engineering/failure_patterns/FP-STORAGE-001-trading-projection-without-durable-history.md) 引用 [RQAlpha #479](https://github.com/ricequant/rqalpha/issues/479)：本次直接获取 upstream issue 未成功，因此该历史细节仅为本地整理的 advisory evidence，不宣称已实时复核。采用的通用故障是“当前投影正常但因果历史丢失”；Task 6 的丢必需 fact 拒绝、Task 9 重启后原交易/净值读取来自 OnlyAlpha 自身 Constitution/Contract，不复制 upstream 实现。

以上材料只帮助寻找失败模式；不拥有 OnlyAlpha 的语义、恢复、测试或发布 Authority。
