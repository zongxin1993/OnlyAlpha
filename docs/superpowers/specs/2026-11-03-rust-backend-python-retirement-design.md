# Rust 后端收敛与 Python 存量退役设计

## 意图与依据

Owner 选择以传统量化软件的数据、算法、策略与回测链路为本轮终点，按完整能力逐批完成 Rust 迁移与工程清理。内置 Agent 暂停开发；未来因子挖掘优先通过外置通用 Agent 使用正式 API，不在本轮建设新的 Agent 集成。

本文件描述设计，不记录完成状态，不替代 AGENTS.md、quality-policy.toml 或当前任务中的验收证据。各批 Task Contract 和审计结论仅保留在任务上下文。Constitution Impact: NO。不得修改 Constitution 或 fingerprint。

依据：[Repository architecture](../../repository-product-architecture.md)、[ADR 0139](../../adr/0139-linux-first-rust-trading-kernel-migration.md)、[ADR 0141](../../adr/0141-rust-product-backend-and-isolated-python-calculations.md)、[ADR 0142](../../adr/0142-library-product-boundaries-and-independent-releases.md)、[ADR 0146](../../adr/0146-independent-agent-product-and-python-langgraph.md) 及 [现有迁移顺序](../../repository-migration-work-program.md)。暂停 Agent 是当前 sequencing，不是取消 Constitution 的长期目标，也不自行废止 ADR 0146。

## 目标、保留内容与非目标

- 后端业务与 Trading Kernel 的唯一维护实现归 Rust；保持现有 crate、Product、Plugin 责任边界。
- 因子、指标及策略的 Python 算法编写与执行继续保留。策略数学计算和用户源代码不等于 Trading Authority；策略身份、Freeze、admission、交易语义、风控、订单、持久化、恢复与正式 Evidence 仍由 Rust owner 管理。
- 根目录 `src/` 最终删除；当前运行、安装、测试、构建、部署、发现和工程工具不再依赖它。不得把旧 Python 后端改名、搬到 SDK 或 worker 继续维护，也不得以 Python fallback、转发 facade 或动态旧源码 loader 代替迁移。
- 清理被替代的 Python 后端、Kernel、旧 worker/package、exports、entry points、依赖与 obsolete comparison 接线；保留必要算法 SDK、协议绑定、合适的算法插件和工程工具及其有效测试。
- 内置 Agent 不增加功能。现有独立 `packages/agent` 暂存冻结，其自身源码与测试不因“暂停”而自动删除；到回测的标准构建/启动/使用不得强制要求 Agent 服务、模型或凭据。旧 Agent 包仅在确认已被替代且消费者退役后删除；必要去耦不扩成 Agent 重构。
- 不新增 SIM/LIVE 能力，不进行 LIVE activation，不扩市场、不重写 UI、不添加依赖/服务/第二套 Compose，不自动发布、推送或删除业务数据和历史 artifacts。
- 不进行独立性能优化项目。仅处理阻止正常回测闭环或迁移验收的真实性能故障；其余定位结果留任务上下文，不能靠放宽超时或断言获得通过。

不可接受的结果：只删目录却保留隐式运行依赖；把大块 Python Core 搬进算法包；删掉有效断言使测试变绿；改变精确输入或身份以绕过恢复；用 API 或 fixture 代做业务步骤并宣称 Web 验收通过。

## Approaches

1. **按完整能力逐批退役（Owner 已选择）**：审计真实消费者 → 复用/补齐 Rust owner → 迁移有效断言与必要算法 SDK → 验证 → 原子删除旧实现和消费接线。每批保持可运行，问题范围可定位。
2. **先补全部 Rust，最后集中删除**：切换集中，但重复实现长期并存，消费者遗漏和回归定位成本更高；不采用。

技术选型沿用现有 Rust libraries/backend、Python 算法执行器/协议与 SDK、前端及唯一 dev 验证环境。这里是既有能力退役，不引入新功能或组件选型；发现必须新增功能或实质变更依赖、Authority、安全或部署条件时，先提出有依据的具体方案，由 owner 按 AGENTS.md §3.4.1 确认，不能以清理名义先做。

## 当前源码对设计的约束

当前 Rust 已有原生回测库，以及 backend 的准备、Run、worker、结果/Evidence 与正常 Web 回测页面。存在代码不等于已获得当前 checkout 的完整产品证据；设计不宣称回测或性能已经验收。

`scripts/build_algorithm_sdk.py` 仍从根目录 `src/onlyalpha` 选择数学/算法 SDK 文件构建安装包；算法资源及插件依赖 `onlyalpha` 包。根 `pyproject.toml` 仍将 `src/onlyalpha` 打包，并将旧 worker、Generation、Agent 包纳入开发依赖/测试发现。旧对照工具和部分基础设施工具也直接导入旧实现。这些真实消费者必须先解决，不能因已有 Rust crate 就删除。

原有普通 BTC 回测设计为本轮已实现功能的入口参考，见 [普通 BTC 回测计划](../plans/2026-11-02-normal-btc-backtest.md) 和 [owning contract](../../manual-backtest-strategy-validation.md)。不得把其中的单标的支持范围宣称为所有市场与策略均已迁移，也不得把本轮限制回测解释为删除 Rust Kernel 的共享 SIM/LIVE 语义。

## 分批收敛结构

### 1. 先断开必要 Python 算法对旧后端源码的依赖

审计已安装算法的真实 import/entry-point/动态加载闭包，逐文件区分纯算法、最小 authoring API、协议 DTO/codec 与后端业务。必要 SDK 的维护源码归入现有 `packages/backend/python/algorithms` 产品构成边界；保留仍必需的 Python import/API 与字节语义，不新增独立产品发布线，也不保留第二套同名源码来源。

构建器和包元数据必须消费同一源码与依赖闭包，更新锁、安装/构建、静态检查、插件及测试调用方。优先正常包构建与现有工具；不新建通用 SDK 平台。不复制 Rust 后端 authority 作为 Python helper。数学状态/算法 checkpoint 可跨协议传递，但正式提交、绑定及恢复决策仍归 Rust。

证明干净的非 editable 算法安装能够执行实际因子、指标和策略算法及必要 continuation；不借助宿主 `src/`、宽泛 `PYTHONPATH`、ambient site-packages 或完整旧 backend wheel。

### 2. 沿实际依赖逐批退役 Kernel 与适配器旧实现

优先处理消费者已迁出、Rust owner 已可覆盖的模块；按调用图确定批次，不按 Python 目录或类型数量机械切分。不重复迁移已有 Rust 能力。

每批同时处理旧代码、imports/exports、插件入口、SDK/脚本依赖及测试/对照工具。Provider/market 专属实现仍留 Plugin 边界；Python 算法例外不允许保留 Python Broker、Runtime 或后端编排。尚无当前产品消费者的旧 SIM/LIVE 实现不需要为删除而新建产品功能，但必须审计并保留对共享 Kernel 仍必要的独立语义与恢复断言；已有 admitted work 的历史 obligations 不能按“未使用”猜测取消。

### 3. 收敛正式 Product 与回测运行闭包

复核数据源/持久化读取、私有因子与策略资产、验证/Freeze/Qualification/Promotion、Generation、准备、Run admission、worker claim/cancel、数值算法子进程、交易重放与结果/Evidence 的实际 Rust owner 和正常 caller。

已有能力只做退役所需接线；真实缺口在正确 Rust owner 修复并同步 owning Contract 与有效断言。旧 calculation/authoring/Generation worker 只能在其实际算法部分保留到指定资源边界、业务消费者全部迁出后成套删除。不得保留 Python orchestrator 隐式承担 Rust 缺失工作。

### 4. 收敛测试、工程工具、打包与部署

逐项区分：旧实现专用断言、跨实现比较、独立 golden/adversarial/fault 向量、实际算法测试、工具测试、协议与 Product 回归。删除失去对象的测试与比较器，迁移有效语义断言到 Rust 或保留算法/工具 owner；不能把所有 `.py` 测试一起删除，也不能保留运行旧实现的对照器作为最终验证依赖。

更新根 Python 打包/workspace、锁文件、test discovery、Ruff/mypy、quality-policy、test_suite/verify 的真实受影响路径，及 SDK/release/build/deploy 消费者。保留持续质量要求并将检查归属转到新 owner，不因 Python 退役清空质量门禁。旧 umbrella backend distribution 不应继续包含旧业务实现；必要 SDK distribution 由其单一维护源码生成。

Python 工程脚本可保留，但不得导入已退役后端；必要操作使用现有正式基础设施能力或 Rust owning 工具，不创造绕过业务 API 的操作入口。当前事实文档只更新直接受影响的入口/路径和明确错误描述，不开展全仓文档改写。

## 验证与使用路径

产品范围是现有数据/算法/策略到普通回测，不要求 Research 报告、聊天或 Agent 前置流程。入口沿用当前 Shipping Web：普通导航 → 选择已有正式数据源/算法或通过现有编辑器创建所需资产 → 保存策略与条件 → 配置样本、资金和费用 → 确认准备 → READY 后明确开始 → 查看状态、净值/回撤、交易/持仓与结果 → 刷新/重启后查看原任务及原结果。User Goal 涉及的业务操作全部从正常 UI 完成，不能用直接 API/数据库/state injection 预先代做。

复用当前回测页面的信息层级和既有交互，不修改用户流程或新增 UI。本轮如发现必须改变用户可见行为，按 AGENTS.md 补充对应 Product Slice、实际界面参考与 owner 确认，不把迁移授权扩成产品设计授权。

每批验证只覆盖 Modification Scope、真实 Impact Scope 和直接消费者：affected package 的单一开发 profile 测试/静态检查；必要 Python Ruff/format/mypy；修改边界时的依赖约束与 Constitution consistency。新增有效 fault/regression 证明必须覆盖实际改变的 identity、错误、序列化、权限、确定性、取消、UNKNOWN、持久化/recovery 或历史读取；不能用 sleep、skip、弱断言、隐式重试或 latest 替代。

算法 SDK 提取验证真实安装闭包；Rust package 边界改变时验证对应隔离 source/dependency closure。高风险批次做 bounded Independent Review，所有非平凡 executable diff 在初始验证后做 bounded Simplicity Review。复用不受后续修改影响的通过证据，不每轮执行全仓测试或双 profile。

真实数据库和 Browser 验证复用唯一 `onlyalpha-dev` / `deploy/docker-compose.dev.yml` 及隔离测试 namespace。保留现有用户数据、模型设置、报告和精确历史 artifact，不因 Agent 暂停或清理代码而擦除。已有输入可以作前提；算法创建、策略配置、准备与提交若是本次验收目标，必须由 UI 完成。检查正常错误/取消与 UNKNOWN 原操作查询恢复，不制造重复任务；UI loading、unavailable、success、焦点/滚动等按真实受影响面验证。

交互/耗时依据先复用现有合同和受影响路径的实际测量；不得自行发明 SLA、放宽超时掩盖故障。技术检查、真实数据库、浏览器与平台证据分别报告；缺失证据明确保留为缺失，不能宣称完整产品通过。

## 停止边界与最终交付含义

本轮最终交付要求根 `src/` 不存在，且当前活跃与保留源码、安装、测试、发现、构建、部署和工程工具不再依赖该目录；根旧 Python backend/Kernel 和可退役包的消费接线清除。保留 Python 算法/SDK/协议/工具以及暂停的独立 Agent 属于明确边界，不称作“仓库零 Python”。不要求删除合法历史文档对旧路径的说明或不可变历史 artifact。

到回测的正式产品路径须有当前变更后的真实 Web 证据，并保持所需 Kernel 与 backend 技术回归。不能把清理完成等同于 SIM/LIVE 完成、跨平台认证或历史全兼容证明。

若真实消费者仍依赖旧实现，继续在本轮范围内迁移最小完整能力；若涉及新增 SIM/LIVE 产品功能、未决 historical/admission 权限或超出范围的产品/选型决定，保留当前数据与唯一 authority，报告具体阻塞并请求 scope 决策，不删消费者或伪造完成。Constitution 冲突报告 PLAN_CONFLICT 并停止实现。

实现者可决定：确切批次顺序、每批文件集合、现有 owner 内的模块划分，以及直接受影响测试选择；必须以实际调用/安装/发现图为证据，不新增状态账本或 speculative abstraction。设计批准后另按 writing-plans 制定可执行计划；本设计不授权自动进入发布或部署业务状态变更。
