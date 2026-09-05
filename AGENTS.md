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

---

## 4. 验收模型：Risk-Tiered + Impact-Aware

验证范围由 **真实 Impact Scope** 决定，不由任务编号决定。

### 4.1 普通任务 Baseline Validation

涉及代码的普通任务默认至少执行：

1. 与修改直接相关的 targeted tests；
2. affected Ruff `check`；
3. affected Ruff `format --check`；
4. 涉及 Python 类型或 API 时，对 affected scope 执行 mypy；
5. 触碰已有 subsystem 时，执行最近的 affected canonical lane；
6. 若触碰 architecture / contract / boundary，检查 Constitution consistency。

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

数据库 migration 必须明确 precondition、deterministic transformation、failure semantics、transaction/atomicity、compatibility window、restart/retry semantics 和 data integrity。能安全回滚时提供 rollback；不能安全回滚时使用 fail-closed + backup/snapshot/forward-fix。

修改 package metadata、dependencies、entry points、public exports、plugin discovery、frontend build inputs、Docker image contents 或 release/build scripts 时，执行对应 build/package 验证。

认证授权、secret handling、外部输入、网络协议、SQL/persistence、命令执行、文件系统、Web security、Broker/LIVE 外部接口等修改按真实风险增加专项 security 验证。

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
→ implement smallest correct solution
→ correct Impact Scope from real dependencies
→ targeted tests + Baseline Validation
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
`plugs/onlyalpha-plugin-<NAME>/`. Any independently buildable, versioned, deployable
non-plugin component MUST live under `packages/onlyalpha-<FUNC>-<NAME>/`. Stable,
market-agnostic canonical semantics and the Plugin SPI belong under `src/onlyalpha/`.

Do not add `apps/<...>` or category-first wrappers such as `packages/provider`,
`packages/market`, `packages/api`, `packages/protocol`, `packages/factor`,
`packages/indicator`, `packages/target`, or `packages/fake`. Do not place a non-plugin
component under `plugs/`, and do not place a concrete plugin under `packages/`.
If a new architecture requires a different boundary, record an explicit architecture
decision before adding the path. Web and HTTP transport are components, not plugins;
the OpenAPI Product Contract remains a first-class contract under `contracts/`.

## Quantitative asset placement

Classify each new quantitative capability under ADR 0110:

1. Generic mathematics without financial context is an L1 Operator.
2. Stable financial meaning without a predictive Target hypothesis is an L2 Indicator.
3. A testable predictive or explanatory Alpha hypothesis is an L3 Factor.
4. Composition of admitted Features/Factors into eligibility, selection, entry or exit decisions is an L4 Strategy.

L1/L2 are public reusable capabilities. Production L3/L4 assets are private; the main repository's only L3/L4 assets are the
non-production reference libraries explicitly authorized by ADR 0110 under `examples/onlyalpha-example-alpha/` and
`examples/onlyalpha-example-strategies/`. The Agent primarily creates/searches L3/L4. Missing reusable L1/L2 capability must be
proposed and admitted separately, never hidden inside a Factor or Strategy.

Under ADR 0111, high-change private L3/L4 repositories may be consumed from an explicit source path or editable path installation only in
development, testing and controlled Agent research. Production L3 discovery requires installed distribution metadata and the public
Calculation entry point. L4 package/path resources are pre-Freeze authoring inputs only; their path never becomes Strategy identity or
Runtime authority.

All L1/L2/L3/L4 libraries expose versioned management providers through `onlyalpha.quant_assets` under ADR 0112. L1/L2/L3 continue to
execute only through `onlyalpha.calculations`; L4 remains authoring data. Any content change requires a new provider version, and any semantic
change additionally requires a new Calculation or Strategy-asset semantic version. Hot plug switches an immutable catalog generation only
for new work; never reload modules in place or rebind an active Run/StrategyRevision.

## Public example / private asset contract parity

When a public Core change affects an L3/L4 authoring, discovery, execution, Research, Evidence or Freeze contract, the implementer must
inspect the corresponding public example, update it in the same public change when behavior changes, run the public example conformance
lane, and assess both `OnlyAlpha-alpha` and `OnlyAlpha-strategies` against the exact Core revision. If private execution is unavailable,
report `PRIVATE_ASSET_COMPATIBILITY_CERTIFICATION_PENDING`; never claim compatibility without evidence.

When a private repository needs a new Core capability, it must first be expressible through a public OnlyAlpha contract, demonstrated by
the corresponding public example, and consumed by the private repository through that same contract. Hidden private-only Core integration
paths are forbidden and must fail closed as `EXAMPLE_CONTRACT_COVERAGE_REQUIRED` until public contract/example coverage exists.
