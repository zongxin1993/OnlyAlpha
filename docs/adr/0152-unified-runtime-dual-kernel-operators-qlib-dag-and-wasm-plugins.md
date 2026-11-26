# ADR 0152：统一 Runtime 门面、双内核算子底座、Qlib 表达式 DAG 与 WASM/子进程插件架构

- 状态：Accepted（核心方向经架构讨论确认，仓库负责人于 2026-11-26 签收）
- 日期：2026-11-26
- 决策人：仓库负责人
- Constitution Impact：NO
- 相关：[PROJECT_CONSTITUTION.md](../../PROJECT_CONSTITUTION.md)、[ADR 0142](0142-library-product-boundaries-and-independent-releases.md)、[ADR 0149（扁平库布局）](0149-flat-rust-library-layout.md)、[ADR 0149（插件分类）](0149-market-integration-plugin-taxonomy.md)、[ADR 0150](0150-product-layout-and-programmable-quant-assets.md)、[ADR 0151](0151-postgresql-business-publication-and-memory-work.md)
- 所属架构文档：[仓库与产品架构](../repository-product-architecture.md)

---

## 1. 背景与动因

现有工程实现与产品长期目标之间存在四项结构性偏差，已开始增加维护成本并制约因子研究、实盘同构与插件扩展演进：

1. **Backend 与量化执行边界不清**：`packages/backend` 仍承担过多研究、回测及交易执行编排，未能收敛为只通过统一抽象 `Runtime` 门面驱动业务的薄产品外壳。
2. **Research 与策略信号图强耦合**：当前研究链路仍绑定策略版本与纯信号图（`strategy_revision` / `signal_graph`），而因子研究的核心对象是因子本身及其统计证据，不需要先构造完整策略。
3. **算子与指标缺乏双内核等价底座**：`crates/operators` 目前只覆盖极少数流式算子，`crates/indicators` 中大量指标各自维护手写状态，缺少“Op 定义与向量/事件双 Kernel 分离”的统一架构，难以从机制上保证研究侧向量计算与交易侧事件驱动逐点等价。
4. **因子表达与插件生命周期选型失配**：
   - 旧受限 Python AST 因子接口（`calculate(api, inputs, parameters)`）表达冗长、对 Agent 因子挖掘不够友好，且引入了 Backend Python 算法编译子进程的长期维护负担；
   - 另一方面，若为追求运行期自由加载/卸载而采用原生动态库（`.so` / `.dylib` + `dlopen`/`dlclose`），会直接撞上 Rust 缺乏稳定 ABI、`dlclose` 易引发宿主内存破坏与进程崩溃、进程内无沙箱隔离，以及跨 OS/CPU 二进制工件复现沉重等硬伤，威胁 7×24 实盘节点的故障域隔离。

本决策在严格遵守 [PROJECT_CONSTITUTION.md](../../PROJECT_CONSTITUTION.md) 的前提下，将上述四项议题收拢为一套统一、自洽、可长期演进的目标架构。

---

## 2. 核心决策

### 2.1 薄 Backend 与唯一抽象门面 `OnlyAlphaRuntime`

将所有量化计算与交易执行语义统一收拢至 `crates/`，对外暴露唯一抽象门面 `OnlyAlphaRuntime` 及显式端口 trait；`packages/backend` 收回薄产品外壳职责，只能通过 `OnlyAlphaRuntime` 与端口装配触发 Research、Backtest、SIM、LIVE。

| 组件 | 拥有（Owns） | 不拥有（Does Not Own） | 依赖方向 |
|---|---|---|---|
| `OnlyAlphaRuntime`（`crates/runtime` 及其组合内核库） | Research 向量引擎、Trading 统一事件引擎、因子/算子/指标计算语义、策略执行语义、风控与组合/账户/订单状态机、确定性快照与重放、统一错误与 `UNKNOWN` 语义 | HTTP/WS 协议、用户鉴权、SQL/CH 驱动细节、容器/进程编排、实盘人工审批 UI 流程 | 仅依赖市场无关内核库与抽象端口 trait，**严禁**依赖 `packages/backend`、Web 框架或具体存储驱动 |
| `packages/backend` | HTTP/WS 路由与 DTO 映射、认证鉴权与 Source grant、实盘人工授权门槛（LIVE Gate）、PG/ClickHouse 持久化端口实现、插件工件校验与宿主管理、作业认领/租约/调度与节点可观测性 | 量化计算逻辑、因子/策略语义、自建第二套回测或交易事件主循环、绕过 Runtime 的账户/仓位/订单状态改写 | 依赖 `OnlyAlphaRuntime` 与端口契约，负责装配端口与托管生命周期 |

### 2.2 Research 纯因子向量化 + Backtest / SIM / LIVE 统一事件主循环

`OnlyAlphaRuntime` 内部按“研究”与“交易”两类计算范式拆分为两条清晰且共享同一因子底座的执行路径：

1. **`ResearchEngine`（纯因子向量化）**
   - 彻底解除 Research 对策略修订和信号图的强绑定：Research 的核心输入是冻结行情切片、不可变因子集合（`FactorExpr` + 精确参数）与 Research 专用评估标签（`TargetExpr`）。
   - 直接消费来自 ClickHouse 的冻结列式切片，在内存按列批量执行因子 `VectorKernel`，计算标准化统计证据（如 IC、RankIC、分层收益、换手率、相关性等），经由 ADR 0151 的单事务机制原子发布至 PostgreSQL。
2. **`TradingEngine`（Backtest / SIM / LIVE 统一事件驱动）**
   - Backtest、SIM、LIVE 严格共用同一套事件驱动主循环与经济状态机：

```text
MarketEvent
  → Factor(EventKernel)
  → Strategy(factors, readonly_state)
  → OrderIntent
  → Risk
  → BrokerPort
  → VenueEvent
  → ExecutionState
```

   - 核心交易逻辑中禁止出现按运行模式分叉的业务分支（如 `if mode == Backtest`）。
   - 三种运行模式的全部差异仅由外部注入的端口组合表达：

| 端口 / 能力 | Backtest | SIM | LIVE |
|---|---|---|---|
| 行情与时钟端口 | ClickHouse 冻结切片回放 + 确定性虚拟时钟 | 实时行情流 + 显式记录事件时间 | 实时行情流 + 显式记录事件时间 |
| 券商端口（`BrokerPort`） | `onlyalpha-broker-virtual` | `onlyalpha-broker-virtual`（或显式准入模拟场所） | 真实券商网关子进程插件 |
| 持久化事实端口 | 内存计算过程态；结束校验后单事务原子发布至 PG | 订单/成交/资金/因果事实逐事件持久化 PG，支持重启对账 | 订单/成交/资金/因果事实逐事件持久化 PG，支持重启对账 |
| 实盘授权门槛 | 不适用 | 需满足资格准入政策，不可获取 LIVE 权限 | 强制要求人类经正式 Web/API 显式授权签发 `DispatchPermit` |

3. **跨模式因子严格等价**
   - Research 与 Backtest / SIM / LIVE 必须消费完全相同的因子定义与规范化精确参数绑定。
   - 所有因子必须同时支持向量化（`VectorKernel`）与事件驱动（`EventKernel`）两种求值模式，且在统一数值政策下逐点输出完全一致，**不得通过放宽容差掩盖差异**。

### 2.3 类 CUDA 双内核算子底座（`crates/operators`）与指标强制算子化（`crates/indicators`）

仿照 CUDA 算子“算子契约定义与底层 Kernel 实现分离”的架构模式重构 `crates/operators`：

1. **Op 契约与双 Kernel 分离**
   - 每个内置原子算子（如 `Ref`、`Delta`、`Mean`、`Std`、`Var`、`Sum`、`Max`、`Min`、`EMA`、`WMA`、`Rank`、`Corr`、`Cov`、`Slope`、`Log`、`Abs`、`Sign`、`Where` 等）在算子注册表中统一声明：唯一算子 ID、版本、输入/输出类型签名、warmup 规则、null/除零边界语义、资源预算系数与确定性数值规范（延续精确十进制/整数语义，禁止未约束浮点漂移）。
   - 每个原子算子必须成对实现两套 Kernel：
     - `VectorKernel`：面向连续列内存的批处理内核，支持 SIMD 与算子融合优化，并在接口层预留未来异构计算（如 GPU/CUDA）后端扩展能力；
     - `EventKernel`：增量流式状态机内核，提供确定性 `step` 推进及 `capture_state` / `restore_state` 快照能力。
2. **原子算子等价认证**
   - 每个原子算子必须通过独立数值 golden、`VectorKernel == EventKernel` 逐点等价、多前缀因果性、warmup/null 边界、以及检查点快照恢复后缀一致测试。
3. **指标与因子强制算子化**
   - `crates/indicators` 与所有内置/私有因子**必须且只能**通过组合 `crates/operators` 中已认证的算子构建，不得绕过算子底座各自维护手写滚动状态或私有数值逻辑。
   - 由此，任何由已认证原子算子组合而成的指标或因子，天然继承双模式等价性、因果性与快照可恢复性。

### 2.4 Qlib 风格表达式作为唯一因子表现形式，废弃旧受限 Python AST

全面采用 Qlib 风格声明式表达式作为 OnlyAlpha 的唯一因子表达形式，直接废弃旧的受限 Python AST 编写接口（[factor-program.md](../factor-program.md)）：

1. **表达式即算子 DAG**
   - 因子以声明式表达式编写（例如 `Mean($close, 20) / Std($close, 20)`、`Corr($close, Log($volume + 1), 10)`、`Rank(Delta($close, 5))`），解析后直接编译为基于 `operators` 注册表的类型化有向无环图（DAG）与紧凑内存指令流。
   - 表达式语言无任意循环、无副作用、无外部 IO，天然可指纹化、可静态计算资源上限与 warmup 长度，并极度契合 Agent 自动化因子挖掘、变异与组合。
2. **编译期静态封死未来函数**
   - 语法与静态类型校验器严格区分两类顶层表达式：
     - `FactorExpr`：通用于 Research、Backtest、SIM、LIVE。编译期强制拒绝任何前视偏移（例如 `Ref($x, n)` 仅允许 `n >= 0`），拒绝读取账户、仓位、资金、成交或外部非确定输入；
     - `TargetExpr`：仅限 Research 统计评估标签使用（允许显式声明的前瞻收益偏移 `n < 0`），类型系统严禁其进入交易引擎、策略输入或任何实盘/模拟路径。
3. **不可变版本与精确绑定**
   - 继续沿用 PostgreSQL 中的草稿与不可变版本模型：不可变因子版本绑定规范化表达式源码、算子注册表版本、解析后精确参数、数值规范与认证证书；任何语义修改均生成新版本，历史运行与证据保留原绑定。

### 2.5 四层热插拔与扩展承载模型（放弃原生 `.so/.dylib`）

按组件的变更频率、性能需求、安全隔离等级与 IO 特征，将扩展与插件统一划分为四层，全部纳入 Rust Runtime 生命周期管理：

| 层级 | 涵盖对象 | 承载形态 | 动态生命周期 | 隔离与复现保证 |
|---|---|---|---|---|
| **L1 核心内置算子** | `crates/operators` 基础算子双内核 | 静态编译进 Rust Kernel | 随 Rust 库统一发版（低变更率） | 零 FFI 开销、吃满内联与 SIMD；随 Kernel 版本精确绑定 |
| **L2 因子与组合指标** | Qlib 表达式因子、内置/私有组合指标 | 声明式表达式 → 内存算子 DAG / 紧凑指令流（数据即插件） | **运行期毫秒级自由热加载/热卸载**，零 `rustc` 编译等待 | 100% 内存安全、跨平台比特级复现；数据库仅存表达式与版本指纹 |
| **L3 扩展计算与规则插件** | 自定义扩展算子、市场交易规则（`onlyalpha-market-*`）、可编程策略模块 | **WASM 插件**（`wasmtime` + Component Model / WIT 契约） | **运行期安全自由热加载/热卸载**，可按需卸载并完整回收线性内存与实例 | 强内存沙箱与资源预算，绝不污染或拖垮宿主；单份 `.wasm` 跨 macOS/Linux 比特级一致 |
| **L4 外部 IO 网关插件** | 券商协议（`onlyalpha-broker-*`）、外部数据源（`onlyalpha-data-source-*`） | **独立子进程插件**（版本化 IPC / gRPC 契约） | 独立进程启动、健康检查、受控重启与升级 | 彻底隔离网络异常、第三方 SDK 崩溃与 OS 依赖，故障域独立 |

**明确拒绝原生动态库（`.so` / `.dylib`）热插拔的工程理由**：
- Rust 缺少稳定 ABI，强走 `cdylib` 必须降级为 `#[repr(C)]` FFI 并引入大量 `unsafe`，破坏类型安全与零成本抽象；
- 在 Rust 中对已加载动态库执行 `dlclose` 卸载极易因 `thread_local!`、全局分配器、静态引用、线程池或 panic unwind 触发宿主进程 `SIGSEGV`，与 7×24 实盘稳定性及故障域隔离原则冲突；
- 进程内动态库与交易内核共享地址空间，缺乏内存隔离，无法安全承载高频迭代或 Agent 辅助生成的扩展逻辑；
- 原生二进制强绑定 OS 与 CPU 架构，导致历史精确复现的工件归档成本大幅上升。

### 2.6 策略承载形态与 WASM 确定性红线

1. **策略（Strategy）的统一承载形态**
   - 为彻底告别 Backend Python 算法子进程，策略统一收拢为两档、均受同一 `Strategy` 契约约束：
     - **声明式规则策略**：结构化配置与受限组合表达式，读取因子值与只读仓位/账户视图产出标准 `OrderIntent`；
     - **WASM 策略模块**：编译为符合版本化 WIT 契约（概念签名 `on_event(factors, readonly_state) -> list<order_intent>`）的 `.wasm` 工件，支持运行期安全热加载与卸载。
   - 策略只能读取声明绑定的因子值与只读状态，只能产出规范化 `OrderIntent`；风控许可、资金/仓位权威、订单身份、场所提交与恢复继续由各自内核模块独占。
2. **WASM 确定性、安全与准入红线**
   - **纯计算确定性沙箱**：L3 层的算子、指标、策略与市场规则 WASM 插件**严禁**授予 WASI 时钟、随机数、网络、文件系统、进程与环境变量能力；所有影响结果的输入（时间、配置、规则版本、参数、行情、因子）必须由宿主经 WIT 接口显式传入。
   - **资源预算与 Fail-Closed**：宿主为每次 WASM 调用配置显式内存上限与指令燃料（fuel）配额；越界、trap 或耗尽燃料时立即中止该次调用并进入受控错误处理路径（阻止新增增险动作，保持观察/撤单/对账通道可用），绝不导致宿主进程异常退出或状态损坏。
   - **扩展算子 WASM 双内核准入认证**：自定义扩展算子 `.wasm` 必须成对导出 `eval_vector` 与 `step_event`（含 `capture_state` / `restore_state`），在准入阶段由 Runtime 自动运行与内置算子同等标准的 `Vector == Event` 逐点等价、因果性与快照恢复认证，认证通过后方可签发 READY 证书。
   - **可复现指纹绑定**：所有使用 WASM 插件的 Run 与冻结绑定，必须精确记录 `.wasm` 工件内容 SHA-256、WIT 契约版本、宿主运行时/Kernel 版本及规范化参数；历史回放严格校验精确工件，拒绝静默替换为最新版本。

---

## 3. 宪法合规性核对（`Constitution Impact: NO`）

对照 [PROJECT_CONSTITUTION.md](../../PROJECT_CONSTITUTION.md) 第 14 节九项宪法判定规则逐一核验：

| 宪法判定项 | 核验结论 | 说明 |
|---|---|---|
| 1. 是否保持唯一性（Uniqueness） | YES | 因子/策略/插件工件、算子版本与冻结绑定均采用单一规范身份，语义变化产生新版本 |
| 2. 权威归属是否显式（Single Authority） | YES | Runtime 独占计算与交易状态机语义，Backend 独占外部控制与人工授权装配，PG/CH 事实归属不变 |
| 3. 行为是否确定性（Determinism） | YES | 双内核等价认证 + 精确十进制/整数规范 + WASM 禁用非确定 WASI 能力，消除隐藏非确定性 |
| 4. 内核是否仍与具体市场无关（Market-Agnostic） | YES | 市场规则下沉至 L3 WASM 插件，券商与数据源下沉至 L4 子进程插件，内核无具体市场分支 |
| 5. 结果是否可复现（Reproducibility） | YES | Qlib 表达式文本 + 算子版本 + `.wasm` SHA-256 + 冻结 CH 切片完整锁定全部输入 |
| 6. 因果链是否可追溯（Traceability） | YES | 完整保留 `MarketFact → Factor → Strategy → OrderIntent → Risk → Broker → Fill → State` 因果链 |
| 7. 崩溃后是否可恢复（Recoverability） | YES | `EventKernel` 与 WASM 算子支持确定性快照恢复；SIM/LIVE 沿用 PG 逐步持久化与外部对账，有限作业沿用冻结输入重算 |
| 8. 不确定性是否 Fail-Closed | YES | WASM trap/超预算、插件缺失、认证未 READY 或提交结果 `UNKNOWN` 均拒绝新增增险动作并保持安全观察路径 |
| 9. 组件边界是否受尊重（Explicit Boundaries） | YES | 彻底收紧 Backend 边界，禁止绕过 `OnlyAlphaRuntime` 或数据库直写；Agent 与人类 Web 权限边界不变 |

本决策不修改 `PROJECT_CONSTITUTION.md` 及其指纹，不弱化任何宪法约束。

---

## 4. 替代范围、保留范围与清退清单

### 4.1 明确替代与修订

1. **修订 [ADR 0150](0150-product-layout-and-programmable-quant-assets.md)**：
   - 替代其中关于“受限 Python 因子与策略编写接口”及 Backend Python 算法隔离执行器的决定，改为本文的 **Qlib 表达式 DAG（因子/指标）+ 声明式/WASM 策略模块**。
   - 保留 `packages/` 仅含 `backend`/`frontend`、Agent 仅通过正式 API 工作、`crates/operators` 与 `crates/indicators` 纯 Rust 无 Python 接口、以及 PG 草稿与不可变版本模型。
2. **修订 [ADR 0151](0151-postgresql-business-publication-and-memory-work.md)**：
   - 修订第 9 条中“Research 与交易共用策略纯信号图”的条款：改为 **Research 面向纯因子（`FactorExpr`）与标签（`TargetExpr`）向量化执行，与交易层共用同一套因子定义与双内核算子语义**，不再要求 Research 绑定策略修订或信号图。
   - 完整保留 ADR 0151 的 PostgreSQL 业务发布与控制归属、ClickHouse K 线归属、Research/Backtest 内存计算与冻结输入重算、单事务原子发布、SIM/LIVE 逐步持久化、`UNKNOWN` 安全路径，以及开发阶段不做旧契约/旧数据兼容的准则。
3. **修订 [ADR 0142](0142-library-product-boundaries-and-independent-releases.md) 与 [插件能力文档](../plugin-capabilities.md)**：
   - 替代“Rust 插件仅静态链接、不引入动态加载或独立插件进程”的阶段性限制，升级为本文的 **L1 静态内置 + L2 表达式 DAG + L3 WASM 沙箱 + L4 独立子进程** 四层承载模型；继续明确禁止原生 `.so/.dylib` 动态库热卸载。
4. **清退范围（按当前唯一契约直接删除，不保留兼容分支或 fallback）**：
   - [docs/factor-program.md](../factor-program.md) 所定义的受限 Python AST 因子编写规范与编译器实现；
   - `packages/backend/python/algorithms/` 及相关 Python 因子编译/执行子进程包装；
   - `crates/calculation-bridge/` 中仅服务旧 Python 因子协议的桥接代码与旧协议绑定；
   - `packages/backend` 中自持的重复研究/回测/交易驱动循环与绕过 `OnlyAlphaRuntime` 的旧装配路径；
   - `crates/indicators` 中绕过 `crates/operators` 的手写重复滚动状态实现。

### 4.2 明确保留

- [ADR 0149（扁平库布局）](0149-flat-rust-library-layout.md) 的根 Cargo workspace 与 `crates/` 一级扁平库结构；
- [ADR 0149（插件分类）](0149-market-integration-plugin-taxonomy.md) 的 `plugs/` 三类插件目录与命名规范（`onlyalpha-market-*`、`onlyalpha-broker-*`、`onlyalpha-data-source-*`）；
- [ADR 0142](0142-library-product-boundaries-and-independent-releases.md) 与 [发行规则](../release-versioning.md) 的独立版本线（Rust 库统一版本、Backend/Frontend/独立插件各自发行）；
- Run/Attempt 身份与 lease/fence 控制模型、实盘人工授权门槛、Agent 权限红线、以及全部经济不变量与独立数值/故障回归测试的语义断言。

### 4.3 开发阶段兼容与数据重建原则

延续项目开发期唯一契约原则（见 `AGENTS.md` 第 5 节与 ADR 0151 2026-11-17 补充）：所有模块按本文与现行正式契约同步重构并更新全部调用方、测试与活动文档，**不保留旧接口、旧格式 reader、fallback 或迁移兼容层**。涉及数据库 schema 或冻结绑定结构变更时，按正式迁移机制演进并按 `AGENTS.md` 第 4.2 节成套重建已核实归属的 `onlyalpha-dev` 开发数据。

---

## 5. 分阶段落地路线与验收边界

> 本 ADR 仅定义目标架构与契约边界，不宣称以下任何阶段已经在当前代码中实现或通过验收。

| 阶段 | 核心交付范围 | 关键验收标准 |
|---|---|---|
| **阶段 0：规范定稿** | 本 ADR 签收生效；同步更新 `docs/repository-product-architecture.md`、`docs/plugin-capabilities.md` 与 `docs/job-execution-contract.md` | 架构文档、替代关系与术语全部对齐，无规范冲突 |
| **阶段 1：双内核算子与 Qlib DAG** | 重构 `crates/operators`（Op 注册表 + `VectorKernel` / `EventKernel`）与 `crates/indicators`；实现 Qlib 表达式解析器、静态因果校验（`FactorExpr` vs `TargetExpr`）及 DAG/指令流双模式执行器 | 全部内置算子与指标通过独立 golden、`Vector == Event` 逐点等价、多前缀因果、warmup/null 与快照恢复测试；编译期拒绝一切前视 `FactorExpr` |
| **阶段 2：WASM 宿主与 WIT 契约** | 引入 `wasmtime` 确定性宿主（禁用非确定 WASI、显式内存与燃料预算），定义扩展算子、市场规则与策略的正式版本化 WIT 契约与热加载/热卸载管理器 | 支持运行期加载/卸载与内存回收；扩展算子通过自动双内核等价认证；越界/超时 trap 按 Fail-Closed 隔离且宿主不受影响；跨平台校验工件 SHA-256 与确定输出 |
| **阶段 3：统一 `OnlyAlphaRuntime`** | 在 `crates/runtime` 落地纯因子向量化 `ResearchEngine` 与 Backtest/SIM/LIVE 统一事件主循环 `TradingEngine`，收拢全部外部端口 trait | Backtest/SIM/LIVE 运行完全同一核心事件循环；Research 与 Backtest 消费同一 Qlib 因子结果逐点一致；持续交易支持崩溃恢复与对账 |
| **阶段 4：Backend 瘦身与旧路径清退** | `packages/backend` 收拢为仅依赖 `OnlyAlphaRuntime` 的薄外壳；外部 IO 网关对接 L4 子进程插件边界；删除旧 Python AST 因子链路与重复驱动；重建 `onlyalpha-dev` 并跑通全链路 API/Web 回归 | Backend 无自持量化执行循环；旧 Python 算法目录与废弃文档清理完毕；API、权限、实盘门槛、故障恢复与全链路测试通过 |

---

## 6. 签收记录

仓库负责人于 2026-11-26 签收本 ADR，确认第 2 节四项决策作为目标架构：薄 Backend 与唯一抽象门面 `OnlyAlphaRuntime`；Research 纯因子向量化与 Backtest／SIM／LIVE 统一事件主循环；类 CUDA 双内核算子底座与 Qlib 表达式 DAG；L1–L4 四层插件承载模型并明确拒绝原生 `.so`／`.dylib` 热卸载。

签收同时执行阶段 0：同步更新 `docs/repository-product-architecture.md`、`docs/plugin-capabilities.md`、`docs/job-execution-contract.md` 与 `AGENTS.md`，并在 ADR 0142、0150、0151 标注替代范围。签收只使目标架构生效，不表示阶段 1–4 已实现或通过验收；当前实现状态仍以工作树源码和可执行证据为准。
