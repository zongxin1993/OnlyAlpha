# OnlyAlpha Agent 工程指南

本文件定义 OnlyAlpha 每个工程任务的强制执行与验收规则。它规定 **开始前必须理解什么、如何开发、如何验证、何时停止**，不记录任何任务、阶段或版本的完成状态。

---

## 0. 首要规则：必须先读 Project Constitution

任何 Codex / Agent 在执行以下工作之前：

```text
architecture analysis
planning
audit
implementation
refactor
bug fix
review
test design
ADR drafting
roadmap interpretation
```

**MUST 首先完整阅读并理解根目录 `PROJECT_CONSTITUTION.md`。**

然后按以下顺序获取上下文：

```text
1. PROJECT_CONSTITUTION.md
2. 相关 Architecture / public Contracts
3. 相关 Accepted ADRs
4. Roadmap / 当前任务上下文
5. 本 AGENTS.md 的工程执行规则
6. 当前源码 + 当前测试 + 当前可执行行为
```

其中：

```text
PROJECT_CONSTITUTION.md
→ L0 最高规范性 Authority：OnlyAlpha 为什么存在、最终是什么、不可牺牲原则和永久边界

Architecture / Contract
→ L1：如何实现 Constitution 定义的目标

Accepted ADR
→ L2：局部设计决定，只能在 L0/L1 之下生效

Roadmap / Work Program
→ L3：建设顺序与任务分解，不拥有改变产品目标的 Authority

Task Contract / Prompt
→ L4：当前授权实现范围

当前源码 + 当前测试
→ observational truth：当前工程实际上实现了什么
```

### 0.1 Constitution 不可由普通工程任务修改

Codex / Agent / 普通实现任务 **MUST NOT**：

- 修改、删除或重写 `PROJECT_CONSTITUTION.md`；
- 修改其 pinned fingerprint；
- 通过 ADR supersede Constitution；
- 因实现困难降低 Constitution 中的 Required Principle；
- 把“当前还没实现”解释成“长期目标已取消”；
- 把局部 sequencing 优化解释成产品 scope 缩减；
- 通过 Prompt、测试或实现重新定义 OnlyAlpha 的产品身份。

若任务、现有 ADR、Roadmap、代码或测试与 Constitution 冲突：

```text
STOP IMPLEMENTATION
REPORT: PLAN_CONFLICT
```

Agent 必须说明冲突来自哪里、违反哪一条 Constitution、需要什么 owner-level 决策；不得自行通过修改 Constitution 解决冲突。

### 0.2 Normative Truth 与 Implementation Truth 必须分离

```text
Constitution / Architecture / Contract
→ OnlyAlpha 应当成为什么

Current source / tests / executable behavior
→ OnlyAlpha 当前已经实现了什么
```

源码可以证明 Futures、某插件、某节点“当前没有实现”；源码不能证明它“不是长期目标”。

---

## 1. OnlyAlpha 永久架构不变量

以下规则必须与 `PROJECT_CONSTITUTION.md` 一致，并在每个相关任务中保持：

- OnlyAlpha 是长期运行的个人 Stateful Quant System，而不是以 Python callback 为正式产品边界的量化脚本框架；
- Trading Kernel 只拥有不会因具体市场规则变化而变化的 canonical trading semantics；
- Core 必须 Market-Agnostic，不依赖具体 Provider / Broker / Exchange / Market 实现；
- 任何会随市场、交易所、Broker、Provider、监管、协议版本变化的内容，必须停留在 Plugin / Adapter / Gateway 边界；
- `onlyalpha.domain` 是跨市场 canonical domain language；
- RESEARCH / BACKTEST / SIM / LIVE 是正式 Runtime vocabulary；
- Backtest / SIM / LIVE 共享 Trading Kernel 与同一交易语义；
- Strategy fingerprint 是策略身份；Freeze 后产生 immutable Strategy Revision；
- 同一 Strategy Revision 进入 Backtest / SIM / LIVE，Runtime 不重新定义策略语义；
- 一个正式语义事实只有一个 canonical identity 和一个 Authority，不得维护平行真相；
- 外部 venue 是 execution fact authority；OnlyAlpha 拥有 intent、policy、strategy identity、promotion、reconciliation 与本地可恢复状态 authority；
- 相同 Kernel version + canonical configuration + Strategy Revision + initial state + ordered facts 必须得到相同 state transition 和 output；
- 所有影响结果的时间、随机性、模型版本、外部结果、人或 Agent 决策必须成为显式输入、版本配置或正式事实；
- 市场与执行事实 append-only；修正产生 revision，不静默重写历史事实；
- Research / Backtest 正式 Evidence 必须绑定 immutable inputs，不能依赖 mutable database query 作为唯一数据定义；
- 所有正式链路必须可 Trace：能够从 Fill 追溯到 Order Intent、Risk/Portfolio/Strategy Decision、Strategy Revision 和输入事实，也能够正向追踪影响；
- Crash / Restart 是正常生命周期；关键 Truth 不能只存在内存，必须能从 durable facts + reconciliation 恢复到唯一状态；
- UNKNOWN submit outcome 是一等状态，禁止 blind retry 创建第二订单身份；
- LIVE 对新的 risk-increasing execution fail closed，但必须继续观察、成交、撤单、持久化、reconciliation、recovery 和风险降低链路；
- Web 只负责 Display、Input/Management、Command Submission；UI/Web 永远不是 Trading Authority；
- 正常 Human 操作通过 Web → versioned API → OnlyAlpha，不通过直接 Python Core 调用或数据库修改；
- Agent 只能通过正式 API 使用 OnlyAlpha，职责限定于 Factor 实现/挖掘/管理、Research、Backtest、SIM 与 Evidence 分析；
- Agent 永远不拥有 LIVE Authority；LIVE activation、LIVE strategy change、material LIVE risk authorization 必须人工明确操作；
- Infrastructure 负责 node identity、deployment boundaries、interfaces、compatibility、health、upgrade、rollback、persistence topology、observability、failure domains 与 lifecycle；具体 Docker/Kubernetes/DB/Web 技术不是 Constitution；
- 跨节点通信使用明确、版本化 Contract；Database 不是默认 integration API；
- correctness 测试使用 deterministic barrier、event、fake clock 或 fault injection，禁止用 `sleep()` 证明正确性；
- Convenience、性能和交付速度不能作为越过 Authority / Boundary / Determinism / Recoverability 的理由。

### 1.1 代码归属第一判断

新增能力先问：

```text
Will this change because an external market/provider rule changes?
```

如果 `YES`，默认属于 Plugin / Adapter / Gateway。

如果 `NO`，继续判断它是否属于 universal canonical trading semantics；只有属于时才考虑进入 Core。

Human interaction → Web。

Factor discovery / research automation → Agent / Research。

Node / deployment / compatibility / lifecycle → Infrastructure。

若新市场能力无法表达，必须先判断是 provider-specific difference，还是 Core 确实缺失 universal concept。只有后者才构成 Core 演进理由。

---

## 2. Authority 模型

OnlyAlpha 固定使用以下工程 Authority 分工：

```text
PROJECT_CONSTITUTION.md
→ 最高规范性 Authority，不可由普通任务 supersede

Architecture / public Contract
→ 由 Constitution 派生的长期结构与接口约束

Accepted ADR
→ 局部设计决策；与上层冲突时无效

当前源码 + 当前测试
→ 当前工程实际实现事实

AGENTS.md
→ 每个任务如何执行、验证、何时停止

quality-policy.toml
→ 持续 CI 与 Major Milestone Phase Gate 的机器检查集合

scripts/test_suite.py
→ canonical lane 的实际执行定义

scripts/verify.py
→ 当前工作区修改的 Impact-Aware 验证选择器

pyproject.toml
→ Python 测试、静态检查与包配置的机器事实
```

不得创建第二份任务验收 Authority、工程进度 Authority、质量结论 Authority 或认证状态 Authority。

源码与长期设计冲突时不得静默选择一边。首先检查 Constitution：

- 若源码违反 Constitution/冻结设计，修实现；
- 若低层文档违反 Constitution，修低层文档；
- 若任务本身要求违反 Constitution，`PLAN_CONFLICT` 并停止；
- 普通任务无权通过“设计变化”修改 Constitution。

---

## 3. 每个正式任务的最小 Task Contract

开始实现前，当前开发/Codex 上下文必须明确：

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

其中 `Constitution Impact` 必须回答：

```text
Does this task conflict with, weaken, reinterpret, or require changing PROJECT_CONSTITUTION.md?
```

合法普通任务答案必须是：

```text
NO
```

若为 `YES` 或无法确定，停止实现并报告 `PLAN_CONFLICT`。

Task Contract 只存在于当前任务上下文，不提交仓库，不生成模板实例、完成报告、验收报告或状态文件。

### 3.1 Required Behavior

Required Behavior 在任务开始时冻结。实现困难不能反向降低 Required Behavior。

开发中发现现有设计不足时，只能在 Constitution 允许范围内显式更新对应 Architecture / Contract / proposed ADR，并同步实现和测试。

Codex 可以起草 `PROPOSED` ADR，但不得把与 Constitution 冲突的 ADR 当作有效决策，也不得仅因自身实现选择把产品 scope 缩小。

### 3.2 Acceptance Tests

Acceptance Tests 可以因为真实发现而增强或纠正，例如：

- 新发现的真实边界条件；
- 实际依赖使 Impact Scope 扩大；
- 原测试不足以证明 Required Behavior；
- 原测试本身被证明错误；
- 需要新增 determinism、recovery、compatibility 或 migration 证明。

不得因为实现无法满足要求而删除测试、弱化断言、放宽语义、增加无意义 retry/sleep、skip/xfail 当前真实失败或吞掉异常。

### 3.3 Web / Product Vertical Slice Tasks

Web 产品化任务除通用 Task Contract 外，必须遵守 ADR 0135 与 `docs/web-product-development-mode.md`。

在开始实现之前，当前上下文必须额外明确：

~~~text
Product Slice
Reference Interaction
User Goal
Primary User Flow
Visible States
Existing Product API
Missing Product API / Authority Capability
E2E Acceptance
~~~

默认开发链必须是：

~~~text
用户可见工作流
→ UI / Product Slice
→ 当前 Product API / Authority Gap Analysis
→ 优先复用已有能力
→ 只补当前 Slice 所需的最小完整 canonical capability
→ formal Product API
→ Web integration
→ Browser E2E
→ dogfooding / review
→ closure
~~~

禁止把 Web 产品化重新退化成“先横向完成大量后端模块，最后再给它们加页面”。若当前 Product Slice 不需要某个后端能力，
默认不为假设未来需求提前增加 API、Authority、abstraction、configuration 或 persistence surface。

上述约束不阻止独立必要的 correctness、安全、数据完整性、recovery/reconciliation、quality infrastructure 或 owner 明确批准的
非 Web roadmap 工作。

TradingView 只作为 chart-centric interaction reference。它不拥有 OnlyAlpha 产品语义、Domain、API 或 Authority，也不自动授权
替换现有 renderer。ADR 0094 的 renderer boundary 在被新的 Accepted ADR 显式 supersede 之前保持有效。

Web 仍然只能是 Control + Presentation。若页面需求不能通过当前正式 API 表达，必须先判断是 PRESENTATION_GAP、QUERY_GAP、
COMMAND_GAP、DOMAIN_GAP、AUTHORITY_GAP 还是 INFRASTRUCTURE_GAP，再修改 canonical boundary；禁止通过 React 直连数据库、
Store、internal Core 或浏览器重算 Research/Trading truth 规避缺口。

Web Slice 的默认 closure 不是“endpoint 已存在”或“component 能 render”，而是主用户路径通过 formal Product API 端到端可用，
并有与风险相匹配的 Browser E2E / targeted evidence。

#### 3.3.1 业务产品验收：唯一 Web UI 路径

所有业务产品能力的测试、验证与验收，MUST 以正式 Shipping Web UI 为唯一用户操作入口，走与普通用户完全一致的流程：
真实产品入口 → 正常导航/输入/操作 → versioned Product API → owning Authority → 正常 UI 结果与反馈。
不能通过 curl、SDK、Python、直接 API Command、数据库/Store 修改、浏览器脚本注入 state 或内部对象调用替代用户步骤。
业务目标包含的创建、配置、选择、提交、查看、修改、取消或恢复操作，必须由用户可发现的正常 UI 完成。

禁止为了验收制造普通用户不可用的特供页面、隐藏按钮、测试模式、捷径、特供响应或不同业务流程。公开的正式深链接、
产品配置模式与辅助功能定位符可以使用，但不得改变正常用户行为、认证授权、Authority 或执行语义。
若正常 UI 无法完成业务目标，必须报告具体 Product/API/Authority Gap，产品验收保持未完成；禁止绕过 UI 记为 PASS。

Browser 测试必须使用正常用户行为和 UI 可见状态组织断言，而不是以内部实现步骤定义产品流程。
正式业务验收必须连接真实 canonical application/Authority；mock API、预计算结果、测试专用 backend/renderer fixture、
组件测试和接口测试只能证明各自的技术性质，不能单独或合并替代真实产品验收。
hermetic 测试可以使用受控外部输入与正式、隔离的测试数据；前提准备只能建立任务明确的既有条件，不得预先代做当前
User Goal 包含的业务步骤，也不得把 fixture 说成真实市场、真实账户或真实部署证据。
Infrastructure 初始化/兼容性/隔离检查不是正常业务用户流程，也不能替代业务验收。

Kernel 的开发和验证标准保持不变：确定性、唯一 identity/Authority、数据完整性、traceability、recovery/reconciliation、
fail-closed 及所需 unit/contract/property/fault tests 继续执行。前端 unit、API contract、renderer 与 security 等技术回归也
继续保留；“业务验收唯一 Web UI”不授权删除、弱化或绕过这些工程检查，更不把 Web 升级为 Trading Authority。

前端以用户使用便捷性为核心验收点：入口和下一步可发现；默认值合理且无隐式越权；术语能被用户理解；不要求复制内部
ID、查询数据库或切换调试工具；loading/empty/invalid/denied/unavailable/degraded/success 清楚可见；正常错误后的恢复仍
可从 UI 完成，UNKNOWN 不被包装成失败或盲重试；保留相关 keyboard/focus/responsive 行为。每个 Slice 必须明确用户
步骤、必要输入、预期可见反馈与有依据的交互/耗时预算，并进行同路径 dogfooding，不用单一点击数或测试变绿代替可用性。

#### 3.3.2 界面调研、信息层级与用户语言

任何新增或修改用户可见界面，在实现前 MUST 调研与当前用户任务相符的成熟量化 / 金融产品界面，查看实际界面、官方截图或
官方交互演示；只凭印象、阅读 API 文档或列出竞品名称不算界面调研。TradingView 可用于行情与图表，QuantConnect 等可用于
研究与回测；对话式研究还应结合 owner 指定的对话产品参考。复用仍适用的已有调研，范围限于当前 Slice，不扩成全产品审计。
当前任务上下文必须给出参考来源、观察到的布局 / 操作路径 / 信息层级、采用或不采用的理由，以及对应 OnlyAlpha 用户步骤。
无法取得界面证据时应说明缺口，不得把推测称作已完成调研。外部产品不拥有 OnlyAlpha Domain、API、权限或执行 Authority。

- 默认界面只展示完成当前任务所需的输入、关键金融 / 量化信息、当前状态与下一步。配置归入可发现的设置入口；
  高级选项、代码、日志与诊断按需展开，不把工程说明、完整 schema 或安全契约整段堆在主界面。
- 用户文案采用普通金融量化用户熟悉的词汇与自然中文，例如因子、收益率、回撤、样本区间、数据源、研究条件、模型。
  `Fingerprint`、`Reducer`、`DTO`、`Lease`、`Revision Hash`、内部 ID、哈希、类名、原始错误码等实现概念不得作为默认标签、
  必填输入、操作指引或错误说明；也不得只是机械翻译成同样难懂的中文。必要精确信息可放在诊断详情中。
- 操作文案说清动作及对象；错误反馈优先说明发生了什么、是否已生效以及用户能如何继续。未知结果必须明确表示“结果尚未确认”，
  保留查询原操作的恢复路径，不能用“失败，请重试”掩盖 UNKNOWN。不得泄露凭据或把原始异常直接当作用户提示。
- 简洁不能隐藏用户决策必需的信息：实际数据来源、样本边界、费用 / 资源限制、权限范围、关键风险、不可逆效果及确认对象仍须在
  相关操作处清楚呈现。精确身份和完整 provenance 继续由 owning Authority 保留，简化显示不修改契约或降低任何安全检查。
- 实现前明确主次操作、默认 / 展开信息和空白 / 加载 / 错误状态；验收必须在真实 Shipping Web 中检查视觉层级、字号 / 间距、
  对齐、滚动、窄屏与 keyboard / focus，以及文案能否让用户无需内部知识完成任务。组件渲染或测试通过不等于界面易用。

### 3.4 Simplicity / Accidental Complexity Control

OnlyAlpha 使用 bounded Simplicity Review 消除 accidental complexity；它不删除 Constitution、Architecture / Contract、Accepted ADR、冻结 Required Behavior、correctness、security、reproducibility、data integrity、recovery、traceability、observability 或 required tests 所要求的 essential complexity。

对涉及 executable code 的非平凡实现、重构或 Bug 修复，Agent 在理解真实调用链和边界之后，按以下顺序选择实现：

```text
1. 当前 Required Behavior 是否真的需要新增实现？若不需要，不新增。
2. 当前代码库是否已经有可复用实现？优先复用。
3. Python / JavaScript / 平台标准能力是否已经覆盖？优先 stdlib / native。
4. 已安装依赖是否已经可靠覆盖？优先复用，不为同类能力新增 dependency。
5. 只有以上都不成立时，新增满足当前 Required Behavior 的最小正确实现。
```

默认禁止仅为了假设未来需求新增 abstraction、interface、factory、adapter、wrapper、configuration switch、extension point 或 dependency。第二个真实实现、明确 Contract、已接受 Architecture/ADR 或当前 Required Behavior 可以构成新增抽象的证据。

“最小”指最小必要复杂度，不是 code golf。不得用更短代码换取更差的可读性、边界正确性、类型安全、错误语义或确定性。

若当前 Codex 环境已安装 Ponytail，默认使用 Full semantics；实现阶段可调用 `@ponytail`，在代码修改完成并通过初始 Baseline Validation 后调用 `@ponytail-review`。若 Ponytail 不可用，Agent 仍必须直接执行同等 bounded Simplicity Review；第三方插件可用性不得改变 Required Behavior、验证范围或 Stop Condition。

Simplicity Review 只检查当前 Modification Scope + 真实 Impact Scope 内的 diff，重点寻找：

- 可删除的 dead/speculative code；
- 已存在项目实现却重复实现的逻辑；
- stdlib/native 已覆盖的手写实现；
- 为单一实现/单一调用方提前建立的抽象层；
- 没有当前消费者的配置、扩展点和 dependency；
- 保持相同语义时可以明显缩小的实现。

每个 finding 必须在当前开发上下文中二选一：

```text
APPLY
→ 简化实现，并重新执行受影响的 targeted tests / static checks

REJECT_AS_ESSENTIAL
→ 说明它由哪条 Required Behavior / Architecture / correctness / safety / reproducibility / recovery 约束要求保留
```

不得把 Ponytail finding、`@ponytail-audit` 输出、debt ledger、PASS 结果或 review summary 提交成第二份仓库质量/进度 Authority。`@ponytail-audit` 也不得把普通任务扩展成全仓 cleanup；只有当前 Task Contract 或 Major Milestone contract 明确把 repository-wide complexity audit 纳入 Scope 时才能执行。

Ponytail 不拥有任务验收 Authority，不替代 Baseline Validation、risk-specific evidence、bounded Independent Review、Constitution consistency 或现有 CI/quality gates。

#### 3.4.1 成熟组件优先与新增功能选型确认

工程精力优先投入 OnlyAlpha 的 canonical semantics、唯一 Authority、确定性、数据完整性、可恢复性及正式产品链路。
UI 与通用配套能力 MUST 优先复用满足当前需求的成熟第三方组件 / 项目，不重复建设成熟生态已可靠解决的能力。
UI 的表单、表格、对话框、菜单、布局与可访问性交互等，先复用项目已有组件体系，再评估成熟第三方方案；
用户管理、通用身份认证、发行版本管理、部署、升级及类似非 OnlyAlpha 特有的能力，也必须先评估成熟项目、平台或标准工具。
不得仅因“代码可控”“方便定制”或个人偏好就从零实现；已有实现、native / stdlib 或成熟依赖已满足需求时不得另造同类实现。

每次新增功能，在选型及实现前 MUST 进行与当前功能相关的全网调研，并由 owner 明确确认方案：

1. 先明确用户目标、现有可复用能力及真正属于 OnlyAlpha 的约束，再联网检索相关成熟项目 / 组件、官方文档、维护与发布情况、
   适用案例及直接相关的已知问题；UI 同时遵守 §3.3.2 的实际界面调研要求。不能只凭模型记忆、过往偏好或一个候选直接定案。
2. 在当前任务上下文给出有来源的候选比较、推荐方案及理由，说明需求覆盖、项目边界适配、维护成熟度、许可证、
   安全 / 隐私、现有技术栈兼容性、接入与长期维护成本；调查深度按真实风险与 Impact Scope 确定。
   “全网调研”要求主动跨相关来源查找与比较，不意味着无限穷举网站或扩大为全仓审计。
3. 提交具体可审阅方案供 owner 确认，明确复用什么、OnlyAlpha 必须自行实现什么、依赖 / 服务 / 部署变化及主要取舍。
   已明确批准的功能范围和选型不重复询问；新功能或实质改变已批准选型、边界、成本与安全条件时须重新确认。
   未获确认或调研来源不可用时，不得先实现、安装依赖或引入服务，再补做确认；说明缺口并保留未决状态。
4. 只有经调研证明现有能力与成熟方案不能满足当前必要需求时，才可提出自研；必须说明具体缺口、排除方案及理由，
   经 owner 确认后实现最小必要部分。不得以假设未来需求扩大自研范围，也不得为单个小能力引入不必要的大型平台。

本节补充 §3.4 的复用选择顺序；引入依赖必须有当前功能的实际消费者和已确认的必要性。第三方方案必须服从 Constitution、
Architecture / Contract 与 Accepted ADR，不得取得 OnlyAlpha 的 Trading / Research / Risk / LIVE Authority，
不得绕过 versioned API、权限、identity、确定性、审计、recovery 或 fail-closed。通用用户认证不代替 OnlyAlpha 的业务授权；
发行 / 部署工具不定义 Strategy Revision、事实身份、Runtime Generation 或人工 LIVE 授权，也不自动授权第二套本地 Compose 拓扑。
只实现当前边界所需的最小集成，不复制成熟项目内部实现、不新建平行状态真相，也不为本规则一次性替换全仓已有能力。
调研与方案确认保留在当前任务上下文，不新增进度、选型认证或质量状态 Authority；长期设计决定按既有 Architecture / ADR 规则记录。

---

### 3.5 Python / Rust 模块迁移

按 ADR 0139，以完整功能模块作为迁移交付和隔离单位。每个模块 MUST 先审计对应 Python 实现的职责、公开接口、依赖、
边界、确定性、identity、序列化、错误及适用恢复语义，识别真实缺陷、职责混杂和不合理的模块划分；不得直接翻译源码。
Constitution / owning Contract 是语义 Authority，Python 实现仅是迁移期的行为与交叉验证参考，不是正确性 oracle。

Rust 是选定迁移范围内最终唯一维护的 Kernel 实现。Rust 的模块、目录与依赖应按经审计的合理职责设计，不要求复制 Python
的文件、类、目录层级或历史包边界。发现 Python 划分不合理时，应在当前 Rust 实现中修正，并同步 owning Contract、职责映射
和独立参考向量；不得为了外观一致而复制设计缺陷，也不为未来需求创建空目录或无实际作用的抽象。

不以 Rust 迁移为由全面整理或修复即将退役的 Python 实现。Python 修改仅限当前仍在运行的正式链路所需 correctness / safety
修复，或建立可信验证参考所必需的最小修改；单纯历史结构问题留在参考实现中，不要求先重构 Python 才能实现 Rust。
发现缺陷必须在正确的 owning boundary 固化正确语义并增加回归；Python 与正确契约的已知差异必须显式分类，不能伪造两种实现
全部一致、弱化断言或照搬 Bug。未决数值、身份、历史或 Authority 设计仍阻塞依赖它的移植。

迁移期间当前获准的 Python Runtime 不因“参考实现”称呼而丧失其正式执行 Authority；Rust 验证也不自动获得正式写入权。
按 ADR 0142，每个已迁移模块都必须审计并在实际 caller、admission、Product、recovery 与适用历史门槛满足后，成套删除
被替代的 Python 实现及 imports/exports、dependencies、entry points、build/deployment 和 obsolete comparison wiring。
仍被正式 Python caller 或算法 SDK 使用时，先迁移消费者或提取最小合法 SDK；不能因 Rust crate 存在就删除，也不能把
可安全清理的模块无限推迟到最后。R8 是最终聚合退役门槛，不承诺永久双内核。保留必要的 exact artifacts、
immutable facts 和历史恢复能力；不得提前删除现行实现、绕过 admission 或自动 fallback。Python 指标、因子、研究编写和
适合 Python 的插件不属于 Kernel 退役的当然删除范围。

主要 Rust 功能模块在有实际独立构建与依赖隔离要求时使用独立 library crate，内部对齐经审计的 canonical 职责，
不要求对应 Python 的历史包边界。
独立构建 / 测试必须只需要本模块及声明的下层依赖，不依赖整个应用、数据库、行情或 Broker 环境；同时证明 package-selected
和隔离 source/dependency closure 构建。机械检查允许依赖方向、禁止反向引用及环；编译器拒绝环不等于已禁止所有反向依赖。
不得为每个源文件建立 crate / 服务，不得为隔离新增逐节点 RPC。Python 当前统一打包事实与模块隔离目标必须分开描述。

共享独立向量及 adversarial cases 验证两种实现的值、错误、规范化、序列化和适用状态/恢复语义。模块内小任务、类型数量或
局部向量通过不能替代完整功能模块验收。审计结论和执行状态只留当前 Task / Review 上下文，不新增仓库质量或进度 Authority。


### 3.6 根目录 `src/` 冻结与最终退役

Owner 决定（2026-10-29）：仓库根目录 `src/` 是待退役的 Python 存量区，最终必须完整删除；不再是任何能力的长期归属。
本规则只指根目录 `src/`，不指 `crates/**/src/` 或 `packages/**/src/`。

- MUST NOT 在根目录 `src/` 下新增文件、Python 实现、函数、类、业务分支、公开能力或功能；不得以修复、过渡、兼容、
  Reference、SDK 或“先补 Python 再移植”为由回填实现。新增后端能力及现有后端缺陷的正确实现直接落在 owning Rust 模块。
- 存量 `src/` 只允许退役所需的删除和最小调用/导入/出口接线调整；这种调整必须实际缩小旧实现及其消费者闭包，不能增加
  新实现、新功能、转发 facade、compatibility shim、动态加载旧代码或 Python backend fallback。
- 每批迁移先审计真实职责与消费者，复用已有 Rust 能力，在正确 Rust owner 补齐缺口，迁移有效的独立断言并完成定向验收，
  然后成套删除被替代的 Python 实现、导入/出口、依赖、entry points、打包、构建、部署及过时比较接线。不得只移动目录、
  把旧后端改名为 SDK/worker/plugin 继续维护，或因 Rust crate 存在就提前删除仍有正式消费者的代码。
- ADR 0146 的独立 Python Agent 和 ADR 0141/0142 允许的隔离算法、最小 authoring SDK、合适的插件及工程工具仍遵守其原有
  职责边界，但当前维护源码必须归入相应 `packages/`、`plugs/` 或 `scripts/`；这些例外不允许在根目录 `src/` 继续开发，
  也不允许把后端 Authority、编排、持久化、权限或恢复逻辑移入 Python 算法包来规避 Rust 目标。
- 当前未提交改动同样适用；新增到 `src/` 的内容必须按真实职责撤回或完成正确迁移，不能将其当作冻结前存量。
- 最终退役验收：根目录 `src/` 不存在；当前运行、安装、测试、构建、部署、发现及 entry-point 链路不再依赖它；必要的
  数值/身份/序列化/权限/恢复断言在正确 owner 保留并通过。精确历史 artifact 的保留不等于保留当前源码或新增旧路径 loader。

此规则不修改 Constitution，不降低 guard、确定性、唯一 Authority、UNKNOWN 或退役验收，也不扩大日常验证到全仓。

---

## 4. 验收模型：Risk-Tiered + Impact-Aware

验证范围由 **真实 Impact Scope** 决定，不由任务编号决定。

### 4.1 普通任务 Baseline Validation

涉及代码的普通任务默认至少执行：

1. 与修改直接相关的 targeted tests；
2. affected Ruff `check`；
3. affected Ruff `format --check`；
4. 涉及 Python 类型或 API 时，对 affected scope 执行 mypy；
5. 复用 canonical lane 中覆盖受影响模块的测试和正式执行方式；lane 粒度过大时选择其受影响测试集，不自动执行整个 lane；
6. 若触碰 architecture / contract / boundary，检查 Constitution consistency。

本地日常开发必须按“修改了什么模块，就验证什么模块”执行，只增加有真实调用、依赖或 Contract 变化证据的直接受影响消费者。
禁止每轮本地开发自动执行完整测试流程；“阶段验收”“高风险”或工具只有粗粒度 lane 均不能作为自动扩大到全仓的理由。
Rust 默认选择受影响 package 的单一开发 profile；双 profile、全 workspace、全部 crate 隔离闭包和跨实现全量比较，仅在
当前修改确实需要对应证明时选择相关模块，或在明确要求的发布 / Major Milestone / CI 全量门禁执行。
已有通过结果在对应源码、依赖和配置未受后续修改影响时复用；只重跑新修改真实影响的检查。

随后只按真实 Impact Scope 增量扩展。不得因为“更保险”自动执行全仓测试、完整 Layered Quality、CodeQL、全 build matrix 或全量 coverage。

纯文档修改不需要无关 Python 测试；但修改 ADR / Contract / governance 时必须检查其直接依赖和架构一致性。

### 4.2 高风险任务判定

只要修改失败可能破坏以下任一性质，就按高风险任务处理：

- 资金安全；
- execution correctness；
- 持久事实完整性；
- recovery / reconciliation 能力；
- 唯一 Authority；
- determinism / identity；
- public compatibility；
- security boundary；
- Constitution / architecture governance；
- quality infrastructure。

典型高风险范围包括：

```text
Authority / ownership
Trading state machine
Persistence / Schema / Migration
Checkpoint / Recovery / Reconciliation
Order / Execution
Broker
Risk
LIVE safety
Public Core Contract / SPI
Wire / serialization contract
Compatibility boundary
Security boundary
Governance / quality infrastructure
```

### 4.3 高风险任务额外要求

高风险任务在 Baseline Validation 基础上增加真实相关专项验证，并进行一次 bounded Independent Review。

Independent Review 重点检查：

- Constitution 是否被违反或弱化；
- Authority 是否唯一；
- 状态机是否存在非法状态；
- fail-closed 是否成立；
- recovery / retry 是否确定；
- public contract 是否被静默改变；
- 跨模块边界是否被穿透；
- 是否存在绕过 API、测试或正式入口的隐式路径。

Review 范围严格限制为：

```text
Modification Scope
+ 真实 Impact Scope
+ 直接相关 Constitution / architecture invariants
```

禁止借 Independent Review 重新启动全仓审计。

---

## 5. Scope、Severity 与 Hard Stop

Severity：

```text
Critical → 阻塞
High     → 阻塞
Medium   → 默认不阻塞
Low      → 不阻塞
```

任何直接违反 Constitution 的问题至少是 High；涉及资金安全、Authority 冲突或可能产生不可恢复真实交易状态时按实际风险提升到 Critical。

当前任务只修改：

```text
Modification Scope
+ 因真实依赖关系证明必须扩展的 Impact Scope
```

发现范围外真实问题默认不修，除非它阻止 Required Behavior 或证明原 Impact Scope 判断不完整。Impact Scope 只扩到最近稳定工程边界，禁止无限审计。

普通任务满足：

```text
Required Behavior 已实现
+ Acceptance Tests PASS
+ Baseline Validation PASS
+ 真实 Impact Scope 所需验证 PASS
+ bounded Simplicity Review 已完成（涉及非平凡 executable code 时）
+ Constitution consistency PASS
+ 当前范围 Critical = 0
+ 当前范围 High = 0
= STOP
```

高风险任务额外要求：

```text
bounded Independent Review 完成
= STOP
```

达到 Stop Condition 后，不得因为 speculative risk、Medium/Low、无关技术债、“还能优化”或“还能重构”继续扩大当前任务。

---

## 6. Determinism、Tests 与 Evidence

默认 Task Acceptance 测试必须 deterministic、hermetic、offline-first。

普通验收不得隐式依赖公网、实时市场数据、真实时间推进、第三方账户状态或不可控执行顺序。

优先使用 fixture、recorded deterministic payload、fake clock、contract fake、local ephemeral DB、deterministic barrier 与 controlled fault injection。

禁止通过以下方式“跑绿”：

- retry-until-green；
- 增加 `sleep()`；
- 无依据扩大 timeout；
- 吞掉异常；
- 依赖随机执行顺序；
- 删除有效断言；
- 降低断言强度；
- 无依据扩大 tolerance；
- 删除有效边界测试；
- skip/xfail 当前真实失败；
- 修改测试去适配违反 Contract/Constitution 的实现。

确认真实 Bug 原则上必须增加最小 Regression Test：

```text
复现旧错误
→ 修复根因
→ 在最近稳定边界证明不会复发
```

真实 Binance、QMT、CTP、数据库部署、Docker 等环境只有在它们本身是 Required Behavior 的不可替代证明时才是当前任务强制验收项。环境不可用不是 PASS；Mock/fake 不得冒充必须由真实环境证明的集成行为。

历史已有失败不自动阻塞当前任务，但缺少充分证据也不能等价为 PASS。

Coverage 是诊断与专项验证工具，不是普通任务默认 Gate，不得为了固定百分比制造低价值测试。

本地正式验证必须在唯一 `onlyalpha-dev` project 中通过 `deploy/docker-compose.dev.yml` 的正式验证入口执行，复用 dev
服务和固定 dev 镜像集合，并遵守下述 §6.1；宿主 `.venv` 只允许用于快速 inner-loop 定位，其结果不得替代正式验收。
验证必须绑定当前工作树，并在验证、review 与远端提交核验完成前保留 `test-results/`；成功 push 后按 §9.2 清理本次过程数据。
CI 可以使用独立 job namespace 和测试资源；这种 CI 生命周期不得默认搬到
本地开发。明确依赖公网、Windows、硬件或真实账户的 external lane 在对应受控目标环境执行，不得伪装成容器 PASS。

本地 PostgreSQL 测试必须通过唯一 canonical `deploy/docker-compose.dev.yml` 的 `test` profile 执行；
不得在宿主机手工启动 PostgreSQL 或为测试引入第二套 PostgreSQL DSN 变量。Compose
容器只使用正式连接配置 `ONLYALPHA_POSTGRES_DSN`，并必须保留 `_test` 数据库后缀安全校验。

当前开发阶段，`deploy/docker-compose.dev.yml` 是 OnlyAlpha 唯一授权的 Docker Compose 拓扑。
新增第二个 OnlyAlpha-owned Compose topology 必须先取得明确的 owner approval，并同步更新本治理规则与架构测试。

### 6.1 本地开发、验证与调试：单一 dev 环境

本地开发只使用一套 dev 环境，而不是每个 commit、worktree、任务、验证轮次或 PID 创建一套 Docker 环境：

- 唯一 Compose project 为 `onlyalpha-dev`，唯一拓扑为 `deploy/docker-compose.dev.yml`。禁止为普通本地验证创建
  `onlyalpha-test-*`、`onlyalpha-web-e2e-*`、`onlyalpha-operator-*` 或其他平行 project/network/store；独立部署边界测试
  若确实需要例外，必须先取得针对本次资源、风险、数据保留和清理范围的明确 owner approval。
- OnlyAlpha 自建镜像按必要服务角色复用固定 `:dev` 标签；相同 build target 的服务共享镜像，不按 service、commit SHA、
  日期、任务或验证轮次新增标签。必要的 Python、Web、验证工具及 pinned PostgreSQL/ClickHouse 镜像构成**同一套镜像集合**，
  不要求把数据库、Web 和 Python 强行合成一个镜像。CI/release 的不可变发布镜像不受本地标签规则替代。
- 开发阶段优先将当前工作树 source 挂载到固定 dev 工具镜像中执行验证；普通 source 修改不触发环境镜像重建。
  正式验证使用每轮冻结的只读 source view；该 view 仍通过同一固定 dev 服务挂载，不把普通源码变更烘焙进镜像。
  只比较实时挂载 source 的前后 hash 不能证明期间未变更；执行相关隐藏配置必须纳入 input，credential 不得纳入。
  容器依赖必须与宿主依赖隔离；不得把宿主 macOS 的 `.venv` / `node_modules` 当作 Linux 验证依赖。
  只有 Dockerfile、dependency、工具链或环境不兼容时才更新对应固定 dev 标签。必须证明当前工作树被实际验证，不能把旧
  镜像的结果归给新源码。固定标签不替代 image content identity、build provenance、Provider version 或 Runtime Generation。
- 优先复用 dev 中已有容器，通过正式入口执行必要命令。需要验证工具容器时复用同一 project 下的固定服务；不得以
  `compose run`、随机容器名或 build-only project 每次再生一批容器。不得在 dev 旁边启动平行的 PostgreSQL/ClickHouse/
  产品 API Compose stack。固定验证服务内部、无对外端口、隔离测试数据的短生命周期 HTTP fixture 不等于第二套业务部署；
  它只能提供 hermetic 测试事实，不能控制 dev 业务状态或替代真实产品/部署验收。
- 测试隔离必须保留：复用数据库**服务**不等于共享业务**数据库/semantic store**。PostgreSQL 继续使用正式
  `ONLYALPHA_POSTGRES_DSN` 及 `_test` 后缀校验；ClickHouse 和 immutable test roots 必须使用明确的测试 namespace。
  测试不得清空、迁移、重绑定或导入 fixture 到 dev 业务数据库、user-data、生产 Private Assets 或实际采集事实。
- 同一 dev/test namespace 的破坏性 fixture 和验证过程必须串行或由确定性锁/barrier 隔离；不得同时运行会共享可变测试
  状态的多个 suite。普通本地 Python、Vitest 和 Playwright 验证默认单 worker。提高并发需要当前机器资源与状态隔离证据，
  不能把框架按 CPU 自动推算的默认并发当作安全证明。
- 资源压力、连续异常超时、Docker 控制失去响应或 owner 要求停止时，终止当前验证，不自动重试，不加大 timeout，不弱化
  断言，不标记 PASS。保留已有日志；对未能取得的状态/trace/产物明确记录证据不可用。
- 开发阶段，Owner 已授权在必要时完整停止、删除并重建确认为 `onlyalpha-dev` 所属的 dev 容器，无需为这些容器的
  清理重复申请授权。执行前仍须盘点精确 container/image/network/volume 身份及引用关系，确认当前工作可停止、持有
  对应生命周期锁并保留已有日志；不得删除未知归属或其他项目的容器。这不是每个任务、commit 或验证轮次自动重建
  的许可，正常开发仍优先复用唯一 dev 环境。
- 开发阶段，本地历史数据卷及源码运行的本地 `user_data` 均为可丢弃开发数据，不属于兼容性、迁移或升级保留目标。
  Owner 已授权在实现、升级或持久格式演进需要时直接删除并重建已确认归属的本地 dev 数据，无需重复询问；
  不得为这些旧数据新增 compatibility shim、历史格式 loader、离线历史重建工具或历史保留验收，也不要求先备份旧开发数据。
  执行前仍须盘点精确资源与引用关系，持有生命周期锁、协调当前工作并保留日志；数据库、文件数据、密钥和 namespace
  必须成套清理并重新初始化，禁止只删 user-data 后重绑未清理的数据库。普通启动不隐式清库，不因每轮验证自动重建。
  清理仅限明确归属本项目的开发资源；仍禁止 `down -v`、全局 `system/image/volume/builder prune` 或删除未知归属资源。
  保留固定 dev 镜像集合与其他项目。Docker Desktop 全局停启及其对其他服务的影响必须单独明确授权。
- Owner 补充授权（2026-10-30）：开发阶段更新部署时，可直接删除已确认归属 `onlyalpha-dev` 的旧 dev 容器和本地开发数据卷，
  成套重新初始化并部署当前工作树验证构建的最新版本；无需为旧开发数据保留、备份、格式兼容或该开发环境的重建重复申请授权。
  仍须先盘点精确资源与引用、协调正在运行的工作并持有生命周期锁，使用唯一拓扑、固定 dev 镜像集合及正式构建 / 部署入口。
  本授权不涉及其他项目、生产 / 真实账户数据、全局 Docker 清理或 Trading / LIVE 授权。
  开发构建 / 部署失败留下待恢复标记时，Agent 可在持锁核对原操作身份、进程终止、实际镜像 / 容器 / 卷及命令结果后，
  保留诊断日志并恢复该 dev 生命周期，按上述授权清理重建，无需再次向 owner 申请；不能只删除标记，把尚未核对的 UNKNOWN 当作未发生。
- 不满足上述约束的旧 runner/命令不能作为本地开发入口。特别是会创建临时 project 并 `down -v` 的
  `deploy/run-tests.sh`、`deploy/run-web-e2e.sh` 调用模式只能用于其受控 CI 场景，不能因脚本已存在就继续在本地执行。
  未完成安全的共享 dev 入口时应报告入口缺口，不得偷偷退回平行部署或把文档约束宣称为已实现的机械保护。

单一 dev 约束不授权降低 authentication、Source grant、authority、determinism、immutable history、hermetic tests、
recovery 或 accepted deployment/semantic-store boundary。需要重置可丢弃本地开发数据时按上述授权执行，不能通过清库取消安全约束。

### 6.2 运行数据位置、历史保留与升级验证

- 源码运行通过正式配置指定本机 `user_data` 目录；Docker 运行使用独立于容器生命周期的数据卷。路径与挂载是部署配置，
  不是 canonical identity，也不得创建第二份事实 Authority。复用现有 `--user-data-root` 和 `OnlyUserDataLayout`。
- 运行数据、密钥与凭据不得进入源码、Git、镜像或冻结的源码验证副本；验证数据与业务数据继续隔离。
- 开发阶段不考虑本地旧数据卷的内容或格式兼容，不要求跨开发版本保留历史或验证旧数据升级读取；需要时直接按 §6.1
  删除并重建本地 dev 数据，优先实现当前正确的 canonical contract。fresh 初始化可作为开发版本切换路径，必须如实标明
  数据已重置，不能称为历史迁移成功。当前版本新产生的数据仍须满足 exact identity、引用完整性、持久化和正常停机重启、
  crash recovery/reconciliation 的产品语义与必要测试；可丢弃旧开发数据不授权绕过当前运行的 Authority 或 UNKNOWN。
- 正式部署默认保护历史数据。删除/重置必须有精确范围、明确人工授权、受保护的配对备份、已验证的恢复路径和保留策略；
  开发期的清空许可不能扩展到正式部署。缺失或不匹配的历史、密钥、namespace 必须 fail closed，不能静默采用新存储。
- 测试必须区分 fresh reader/process restart、真实服务停机重启、格式迁移和真实部署升级；前者不能冒充后者的证据。

---

## 7. Compatibility、Persistence、Build 与 Security

任何公共 Contract 或持久格式兼容性变化都属于高风险任务，包括：

- public Python API；
- Provider / Broker / DataSource SPI；
- versioned external API；
- wire protocol；
- persistent schema；
- checkpoint / recovery format；
- event serialization；
- plugin contract；
- public CLI behavior。

必须判断 backward/forward compatibility、migration 与 affected consumers，并按需执行 contract、consumer、migration tests 与 bounded Independent Review。

Breaking change 可以存在，但必须是 Constitution 允许范围内的明确设计决定，不能因为实现方便静默发生。

开发阶段不保留旧版本兼容处理：直接演进当前 canonical contract，并原子更新仓内 consumers、测试与文档；不得仅为
兼容已淘汰开发版本而新增或保留 compatibility shim、version-family duplication、legacy loader、旧 schema/DTO fallback
或平行旧版本分支。Breaking-change detection、分类及仓内 consumer 原子迁移仍然必须执行。
开发期本地旧数据卷按 §6.1 / §6.2 作为可丢弃数据处理，不要求为其实现 migration 或跨版本历史读取。
当前规范对正式产品事实要求的 exact identity、immutable history、replay、recovery 与完整性仍必须保留；正式部署需要的 migration 不得删除或放宽。若已有 Contract 明确标记 compatibility-frozen / externally supported，不得静默解除承诺；须先取得 Owner 对该
Contract 的明确变更决策。仅记录本规则不授权范围外全仓删除或 cleanup。

数据库 migration 必须明确 precondition、deterministic transformation、failure semantics、transaction/atomicity、compatibility window、restart/retry semantics 和 data integrity。能安全回滚时提供 rollback；不能安全回滚时使用 fail-closed + backup/snapshot/forward-fix。

修改 package metadata、dependencies、entry points、public exports、plugin discovery、frontend build inputs、Docker image contents 或 release/build scripts 时，执行对应 build/package 验证。

认证授权、secret handling、外部输入、网络协议、SQL/persistence、命令执行、文件系统、Web security、Broker/LIVE 外部接口等修改按真实风险增加专项 security 验证。

### 7.1 发行单元与组件兼容性

按 Owner 确认的 ADR 0142，目标是三条主要独立 SemVer 发行线：Rust libraries 统一版本，backend 和 frontend 各自版本；
插件按各自 distribution 独立版本。只为本次选择发行的变更单元升版，不因普通 PR、纯文档或无关单元变化强制全仓升版。
正式 tag 使用 `libs-vX.Y.Z`、`backend-vX.Y.Z`、`frontend-vX.Y.Z` 及无歧义的插件名 tag；已发布版本/tag/内容不可覆盖。
每个发行单元只有一个机器可读 metadata Authority，不创建第二份版本台账；目标 metadata 归属见 `docs/release-versioning.md`。

发行规则的机械保护必须由当前源码与实际执行证明，不能仅凭文档宣称已实现。`scripts/version_sync.py`、metadata、locks、
transition checks、publisher、tests 与 workflows 必须成套演进；不混用全局同步与独立发行规则，不关闭有效保护。
目标目录搬迁前使用当前 HTTP manifest / Web package metadata 作为 backend / frontend Authority，搬迁时原子更新消费者。
具体 CLI 与路径映射见 `docs/release-versioning.md`；文档或迁移计划本身不授权升版、tag、merge、push 或发布。

开发可用 workspace path；正式 backend 发行必须验证选定 libraries/插件的实际 source closure 与不可变发行内容一致，
并绑定 lockfile、工具链、features、target、相关非 secret 构建输入及实际 artifact。版本断言与 Cargo.lock 不代替源码校验。
默认 frontend/backend 组合必须有真实验收证据；不同版本只承诺明确验证的 API-compatible 组合，不承诺任意混用，
不为已淘汰开发版本增加 shim、fallback 或滚动升级保证。SemVer 级别遵循实际声明的支持边界与 ADR 0130 breaking 分类；
初始开发阶段不免除 canonical identity、fact integrity、authentication 和 recovery 要求。

Product API、Plugin SPI、Provider/content、Calculation semantic version、Private Asset Revision、schema/checkpoint、
Catalog/Runtime Generation 和 image content identity 均保持各自 owning Authority；不得随发行号自动升版、放宽 admission、
重绑定工作或猜测兼容。发行、部署、Generation activation 与人工 LIVE authorization 分离。操作说明见 `docs/release-versioning.md`。

---

## 8. Quality / Governance Infrastructure Protection

以下属于质量或治理基础设施：

```text
PROJECT_CONSTITUTION.md
docs/governance/*
AGENTS.md
quality-policy.toml
scripts/verify.py
scripts/test_suite.py
scripts/check_constitution.py
.github/workflows/* governance/quality rules
architecture rules
lint / mypy / test discovery configuration
```

业务/功能任务不得为了让当前实现通过而修改质量规则、ignore、allowlist、threshold、test discovery、gate selection 或 workflow condition。

`PROJECT_CONSTITUTION.md` 与其 fingerprint 对普通任务绝对只读。

其他质量/治理基础设施只有在 Task Contract 本身明确以该基础设施为修改目标，或有工程证据证明现有规则本身错误且修改不违反 Constitution 时才能修改，并按高风险任务验收。

`verify.py` 是当前工作区修改的 Impact-Aware Verification Selector，不是任务状态机、长期认证系统或产品规划 Authority。

---

## 9. 文档与仓库卫生

### 9.1 Repository Semantic Identity

永久仓库 identifier 必须描述稳定的 domain semantics、responsibility、observable behavior、schema change 或 invariant，
不得描述它来自哪个 roadmap phase、implementation task、closure round、milestone、temporary migration stage、PR 或 issue。

本规则适用于 `src/`、`packages/`、`plugs/`、`database/`、`tests/`、`test-data/`、`scripts/`、`examples/`、
`contracts/` 与 deployment / CI 资产中的路径、模块、类型、函数、fixture、helper、test name、parametrize ID、
golden/case ID、migration suffix、SQL object、error code、runtime resource 和长期配置名。

例如：

```text
test_b3_registry.py                  → test_factor_registry.py
test_p9_case_2()                    → test_unknown_order_is_reconciled_without_duplicate_submission()
0010_p9_0_authority_hardening.sql   → 0010_strategy_revision_authority.sql
a0_binance_golden                   → binance_spot_price_filter
```

Migration 的数字顺序前缀、正式 schema/API version、稳定 domain 编号以及 exact replay / immutable identity 所要求的
既有序列化身份不是开发过程标签。此类例外必须由当前 Architecture / Contract / Accepted ADR 明确要求，并在机械 Gate 中
使用精确 token 或精确 path 记录原因；禁止目录级、glob 或模糊 allowlist。

过程文档（`docs/tasks/`、`docs/plans/`、`docs/audits/`、`docs/handoffs/`、Roadmap、Prompt）可以保留过程身份，
因为其职责就是记录开发历史。Git 记录何时发生；源码、测试、迁移与 fixture 描述当前产品事实。

仓库只保存系统长期需要的信息：

- Project Constitution；
- 源码；
- 测试；
- ADR；
- Architecture；
- Contract / protocol；
- 必要用户、开发、部署说明；
- Roadmap / execution plan 中的未来建设顺序和依赖关系。

仓库不得把以下内容作为当前 Authority：

- 每步完成状态；
- 工程进度状态文件；
- 质量/审计/验收/closure 报告；
- CI PASS 快照；
- verification manifest/history；
- Final-SHA / Exact-SHA 工程认证记录；
- task implementation/validation/completion summary；
- 自动生成的下一步授权状态；
- 历史 Prompt。

Roadmap 只能描述建设地图和依赖关系，不得通过 completed/current/pending/ready/verified/progress percentage 取代当前源码事实。

历史 Prompt 只能解释历史任务，不拥有产品目标、当前状态或下一步工作 Authority。

---

### 9.2 远端分支提交后的过程数据清理

每次成功向远端分支提交（`git push`）后，MUST 先核实目标远端分支已包含本次提交，再清理本次工作产生且已不再使用的本地过程数据；
适用于开发分支及主分支，不以 merge 或发布为前提。清理属于本次工作的收尾步骤，不得留作下一次任务的默认负担。

- 执行前盘点精确路径、归属与使用状态，只清理已确认属于本项目、本次工作且不再被验证、review 或其他任务使用的产物。
- 清理范围包括根目录及组件内的 `test-results/`（以及遗留 `test-result/`）、临时测试报告、日志、截图、录像、trace、
  临时验证源码副本、测试缓存和临时构建产物；不得仅因目录被 gitignore 忽略就递归清空所有未跟踪文件。
- 不删除源码、未提交改动、正式 fixture / golden / reference vectors、必要的 exact artifacts、immutable facts、运行数据、
  密钥或凭据；不得把本规则当作删除 dev 容器、镜像、network、volume 或重置数据库的授权，相关资源仍遵守 §6.1。
- push 失败、远端状态未核实或当前验证 / review 尚未结束时，保留对应证据。仍被使用或有明确保留要求的产物应暂缓清理，
  在当前任务上下文说明精确路径、原因和清理时机；这不是永久豁免，也不得通过复制到其他目录规避清理。
- 清理后核查目标产物已移除且工作区源码改动未受影响；在当前任务回复中简述清理范围与暂留项，不新增仓库清理报告或状态文件。

---

## 10. CI、Phase Gate 与默认执行顺序

GitHub CI 是持续质量探针，不是每一步任务的默认完成 Authority。

```text
CI pending → 不阻塞普通任务
CI PASS    → 附加质量信号
CI FAIL    → 判断是否为当前修改导致的真实 regression
```

只有已确认当前修改引入真实 regression，或某项验证只能在 CI/特殊环境完成且是 Required Behavior 不可替代证明时，CI 才成为当前任务阻塞条件。

完整 Phase Gate 只在 Major Milestone 真正结束时执行一次，并按 `quality-policy.toml` 和 milestone contract 执行适用的 repository-wide static、canonical regression、architecture、recovery、conformance、persistence、build、E2E 与 security 检查。

面对任何工程任务，默认顺序：

```text
READ PROJECT_CONSTITUTION.md
→ READ relevant Architecture / Contracts / Accepted ADRs
→ READ AGENTS.md
→ inspect current source/tests
→ Constitution Impact check
→ if conflict: PLAN_CONFLICT + STOP
→ establish Task Contract
→ freeze Required Behavior
→ implement smallest correct solution under Simplicity Discipline
→ correct Impact Scope from real dependencies
→ targeted tests + Baseline Validation
→ bounded Simplicity Review when non-trivial executable code changed
→ if simplicity changes code: rerun affected validation
→ add risk-specific evidence
→ bounded Independent Review when high-risk
→ Constitution consistency check
→ Critical = 0 / High = 0
→ STOP
```

核心原则：

> **Constitution 定义 OnlyAlpha 必须成为什么；代码工程定义 OnlyAlpha 当前做到了什么。实现必须充分，但永远无权通过局部实现重新定义项目愿景。**
> 每次读到这里，要求在当前在任务的最后，输出现在的北京时间

## Repository placement and naming

Any concrete implementation loaded through the OnlyAlpha Plugin SPI MUST live under
`plugs/onlyalpha-plugin-<NAME>/`. Stable canonical semantics and reusable public libraries belong under `crates/`;
Kernel libraries use the `crates/onlyalpha-kernel/` grouping, including `predicates/` rather than former `core/`.
Product units are `packages/backend`, `packages/frontend` and `packages/agent`, under ADRs 0142/0146.
Backend business and lifecycle are Rust. Existing Python `src/onlyalpha/` and legacy worker/manager package paths are
migration observations, not authorization to add implementations there or create another product per worker.
Root `src/` is frozen and must ultimately disappear under §3.6. Do not put Application, DB, process or provider rules in Kernel.

Do not add `apps/<...>` or category-first wrappers such as `packages/provider`,
`packages/market`, `packages/api`, `packages/protocol`, `packages/factor`,
`packages/indicator`, `packages/target`, or `packages/fake`. Do not place a non-plugin
component under `plugs/`, and do not place a concrete plugin under `packages/`.
If a new architecture requires a different boundary, record an explicit architecture
decision before adding the path. Web and HTTP transport are components, not plugins;
the OpenAPI Product Contract remains a first-class contract under `contracts/`.

## Quantitative asset placement

Classify each new quantitative capability under ADR 0110:

1. Generic mathematics without financial context is an Operator.
2. Stable financial meaning without a predictive Target hypothesis is an Indicator.
3. A testable predictive or explanatory hypothesis is a Factor.
4. Composition of admitted Features/Factor into eligibility, selection, entry or exit decisions is a Strategy.

Operator/Indicator are public reusable capabilities. Production Factor/Strategy assets are private; the main repository's examples are
non-production DB import seeds under `examples/private-assets/factor/` and `examples/private-assets/strategy/`. The Agent primarily
creates/searches Factor/Strategy. Missing reusable Operator/Indicator capability must be
proposed and admitted separately, never hidden inside a Factor or Strategy.

Under ADR 0129, ADR 0131 and ADR 0132, production Private Factor/Strategy authoring is PostgreSQL-backed and uses mutable Drafts plus immutable
Revisions. Private Factor V1 is one canonical UTF-8 Python source unit bound to one exact stable Factor API Contract; Private Strategy is a canonical structured Strategy
Definition. Git repositories, source paths, editable installs, wheels and packages are optional interoperability/provenance paths, not
production authoring Authority. The database source is never direct execution permission; exact API/adapter, validation, Provider,
Catalog and Runtime Generation boundaries remain mandatory.

ADR 0111's source/distribution loading remains valid for optional import/export and executable materialization. Do not reintroduce
mandatory per-asset Git/package authoring workflows without a new ADR; private Factor/Strategy planning must follow ADR 0129–0132.

Operator/Indicator distributions and snapshot-backed Factor providers use `onlyalpha.quant_assets` under ADR 0112. Operator/Indicator/Factor
execute only through `onlyalpha.calculations`; Strategy remains authoring data. Any content change requires a new provider version, and any semantic
change additionally requires a new Calculation or Strategy-asset semantic version. Hot plug switches an immutable catalog generation only
for new work; never reload modules in place or rebind an active Run/StrategyRevision.

## Public example / private asset contract parity

When a public Core change affects a Factor/Strategy authoring, discovery, execution, Research, Evidence or Freeze contract, the
implementer must inspect the corresponding DB-native seed, update it in the same public change when behavior changes, and run the seed
import/native execution conformance lane.

When a private asset needs a new Core capability, it must first be expressible through a public OnlyAlpha contract, demonstrated by the
corresponding public example, and consumed through that same contract. Hidden private-only Core integration paths are forbidden and
must fail closed as `EXAMPLE_CONTRACT_COVERAGE_REQUIRED` until public contract/example coverage exists.

## Test placement standard（测试目录与测试数据标准）

`tests/` 采用单一分类法：**按被测模块区域分目录，测试目的用 pytest marker 与区域子目录表达**，禁止用平行目录表达目的。

### 测试代码归属

1. `src/onlyalpha/<area>/` 的测试默认落 `tests/<area>/`；同一模块的测试 MUST NOT 分散到多个历史平行目录（如 `tests/unit/<area>`、`tests/<area>_conformance` 与 `tests/<area>` 并存）。合并时保留 git 历史（`git mv`）。
2. `scripts/` 工具自身的测试落 `tests/tools/`；`packages/<component>/` 与 `plugs/<plugin>/` 的测试只落各自组件目录内的 `tests/`，根 `tests/` 不接受组件专属测试。
3. 跨切验证区域（architecture、conformance、contracts、integration、scenario、performance、property、formal、certification、examples、deploy、cli 等）各自承载一种验证视角，不得为同一模块再造目的重复目录；新增跨切区域必须在节内登记。
4. unit / contract / recovery / scenario 等目的区分使用 `pyproject.toml` 已注册的 pytest markers，不用目录层级复制。
5. 每个测试包目录 MUST 含 `__init__.py`；共享测试辅助代码统一放 `tests/support/`（可按职责建子包）；被 subprocess 以模块方式拉起的测试入口脚本统一放 `tests/runtime_support/`。tests 根目录 MUST NOT 存放非测试模块的散文件。
6. 空壳目录（无受跟踪测试文件的目录，含仅存 `__pycache__`）属于遗留垃圾，发现即删除；`tests/` 内 MUST NOT 出现 `.DS_Store` 等系统文件被跟踪。

### 测试数据归属

测试数据只允许两个落点：

1. **`tests/<area>/fixtures/`**：唯一消费者是某区域的场景绑定数据，与该区域 co-locate，随场景在同一 commit 原子更新。
2. **`test-data/`**：跨多个区域消费的数据、golden 基线（如 recovery baselines）、共享参考向量包与生成型工件（如 `test-durations.json`）。子目录按 owning domain 命名并保留 `README` 级可发现性，MUST NOT 倾倒为无结构散件。

禁止新增第三类测试数据目录（如 `tests/fixtures/`、`tests/reference_data/` 式的根内异构数据树）。与代码原子演进的 golden 数据必须由再生脚本 + 一致性守卫（fail closed）绑定，路径变更 MUST 同步更新守卫与再生脚本。生成物与测试产物缓存（`test-results/`、`.test-cache/`）保持 gitignored，不入 `test-data/`。

存量迁移按上述两规则执行；每次触碰某数据目录时按本标准收敛，不做无验证范围的全仓一次性搬迁。

## External engineering evidence and upstream failure research

External projects, upstream documentation, issues, pull requests and incident reports are engineering evidence only; they never supersede `PROJECT_CONSTITUTION.md`, OnlyAlpha Architecture / Contracts / Accepted ADRs, current Task Contract or current implementation truth.

Before freezing architecture or a repository-aware plan, Codex / Agent MUST use first-principles reasoning first and then consult relevant curated material under `docs/engineering/` when mature external references exist for the affected domain.

For high-risk work, a new domain, provider/venue semantics, unresolved correctness defects, or a new certification boundary, planning MUST inspect relevant upstream issue/bug history when such evidence is available. The research is bounded by the real Impact Scope and MUST NOT become an open-ended ecosystem audit.

The required transformation is:

```text
external design / issue / incident evidence
→ applicable generalized lesson or failure pattern
→ OnlyAlpha invariant / failure semantic
→ regression, differential or fault-injection test
```

Borrow failure modes and invariants, not patches. A third-party retry, timeout, sleep, mutable status model, evaluator, runtime choice or component graph is never adopted merely because a mature project uses it.

When external evidence materially affects a high-risk plan, the plan should explicitly record:

```text
Relevant references
Applicable design lessons
Applicable historical failure patterns
Rejected reference approaches
OnlyAlpha invariants / tests derived from the evidence
```

Routine planning SHOULD consult `docs/engineering/reference_registry.md` and `docs/engineering/failure_patterns/` before live upstream research. Live research is required only when risk, novelty, provider change or unresolved defects justify it.

A confirmed applicable external failure SHOULD become an executable OnlyAlpha regression/fault test when deterministic reproduction is practical. Documentation such as "be careful with reconnect" is not an adequate substitute for a test when the failure can be mechanically proved.

The detailed method is defined in `docs/engineering/open_source_engineering_evidence.md`. These reference documents remain advisory engineering knowledge and MUST NOT become a second architecture, quality, Research, execution or certification Authority.

## Formal proof / Authority-bound audit

以下规则补充第 4.3 节的高风险 Independent Review 与第 5 节 Stop Condition。它们适用于会影响正式 **Authority、canonical identity、immutable fact/history、projection、Evidence/provenance、state machine、recovery/replay、exact query/certified absence、fail-closed、admission/reuse/suppression/decision witness** 的 proof-bearing / Authority-bound 任务。

这类任务在冻结实现前，MUST 从 owning Authority 与 Accepted Contract/ADR 重新推导，而不是只从本次 bug、当前代码分支或实现 checklist 出发。至少完成：

```text
Authority State-Space
→ 枚举真实 Impact Scope 内所有合法 state / outcome / terminal variant

Proof Matrix
→ 对每个 mandatory dimension 明确 Authority、canonical identity、representation、validation、missing semantics

Relation Closure
→ 明确 occurrence / ownership / lineage 的 authoritative relation chain；共享 Result/ref/时间戳不得替代关系证明

Predicate Truth Table
→ 区分 proved match、proved non-match、incomplete proof、unavailable proof

Negative Invariants
→ 明确哪些结论绝不能从缺失、UNKNOWN、共享 identity、cancel/stop/failure 等事实推导

Structural Mutation
→ 至少覆盖 whole-context、owner identity、nested relation、source ref、leaf identity、duplicate owner、wrong family、complete-different identity
```

若 formal predicate 内部使用 `True / False / None`，语义 MUST 为：

```text
True  → 已完整证明 exact match
False → 已完整证明 exact non-match
None  → 缺少完成判断所需的 mandatory proof
```

因此：

> **每一个 `False` 都必须有完整的 non-match 证明；missing evidence / malformed relevant proof 不得作为 False，也不得被升级为 certified absence。**

对 typed owner / exact predicate，默认按以下三阶段推导：

```text
Applicability
→ record 是否属于该 predicate / owner family？

Completeness
→ 若适用，mandatory proof 是否完整？

Equality
→ proof 完整后 exact identity / context 是否匹配？
```

对于状态机，必须同时审计 success / failure / cancellation / incomplete / UNKNOWN 等合法状态，不能只覆盖 happy path；optional downstream fact 不得成为 occurrence 存在的隐式前提。

高风险 proof-bearing 任务的 bounded Independent Review MUST **独立重推导**相关 Authority state space、relation closure、negative invariants、predicate truth table 和 adversarial mutations，再与实现比较；不得仅复读实现 Prompt 的 checklist。

此类任务在第 5 节原 Stop Condition 之外，适用项还必须在当前任务上下文证明：

```text
Authority State-Space       PASS
Entity Completeness         PASS
Relation Closure            PASS
Predicate Proof Sufficiency PASS
Negative Invariants         PASS
Structural Mutation         PASS
Recovery / Replay           PASS（涉及 durable history / recovery 时）
Independent Re-Derivation   PASS
```

并保持当前范围：

```text
Critical = 0
High = 0
```

不适用项可以 `N/A`，但必须说明为什么不在真实 Impact Scope；不得用 `N/A` 跳过实际 proof obligation。上述 PASS/N/A 只存在于当前 Task / Review 上下文，禁止提交成仓库质量状态、closure 报告或第二份验收 Authority。

详细执行方法见 `docs/engineering/formal_proof_audit_method.md`。该文档解释如何执行本节规则，不拥有独立的 Task Acceptance Authority。
