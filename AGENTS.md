# OnlyAlpha Agent 工程指南

本文件定义 OnlyAlpha 每个工程任务的唯一验收规则。它只规定 **如何开发、如何验证、何时停止**，不记录任何任务、阶段或版本的完成状态。

当前工程事实只能从当前源码、当前测试和当前可执行行为判断；长期设计约束由 ADR、Architecture 与 Contract 定义。任何历史报告、历史 CI、旧 Prompt、旧提交结论都不能代替对当前工程的判断。

---

## 1. Authority 模型

OnlyAlpha 固定使用以下 Authority 分工：

```text
当前源码 + 当前测试
→ 当前工程实际实现了什么

ADR / Architecture / Contract
→ 已冻结的长期设计约束是什么

AGENTS.md
→ 每个任务如何验收

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

源码与长期设计文档冲突时，不能静默选择一边：若源码违反冻结设计，则修实现；若设计确实改变，则在同一任务内明确更新对应 ADR / Architecture / Contract、实现和测试。

---

## 2. 永久架构不变量

OnlyAlpha 是多市场量化平台，不为单个市场复制第二套 Engine、Runtime 或经济 Manager。

必须保持：

- `onlyalpha.domain` 是跨市场 canonical domain language；
- 市场差异只通过 versioned Market Product、DataSource、Broker 等插件边界进入；
- Core 不依赖具体 Provider / Broker 实现；
- RESEARCH / BACKTEST / SIM / LIVE 是正式 Runtime vocabulary；
- Backtest / SIM / LIVE 共享 Trading Kernel 与交易语义；
- 一个 Trading Runtime 只有一个 Account authority、一个 resolved Market Product 与一个 Account currency；
- UI / Web 永远不是 Trading authority；
- Strategy fingerprint 是策略身份；Freeze 后产生 immutable Strategy Revision；
- 同一 Strategy Revision 进入 Backtest / SIM / LIVE，Runtime 不重新定义策略语义；
- 外部 venue 是 execution fact authority；OnlyAlpha 是 intent、policy、promotion、reconciliation 与本地可恢复状态 authority；
- UNKNOWN submit outcome 是一等状态，禁止 blind retry 创建第二订单身份；
- 市场与执行事实 append-only；修正产生 revision，不静默重写历史事实；
- LIVE 对新的 risk-increasing execution fail closed，但进程继续处理观察、成交、撤单、持久化、reconciliation 与 recovery；
- correctness 测试使用 deterministic barrier、event、fake clock 或 fault injection，禁止用 `sleep()` 证明正确性。

任何任务若触碰这些不变量，都必须把对应约束纳入真实 Impact Scope。

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
```

Task Contract 只存在于当前任务上下文，不提交仓库，不生成模板实例、完成报告、验收报告或状态文件。

### 3.1 Required Behavior

Required Behavior 在任务开始时冻结。实现困难不能反向降低 Required Behavior。

开发中若证明确实需要改变长期 Contract 或设计，必须显式做设计变更，并在同一任务中同步对应 ADR / Architecture / Contract、实现和测试。

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
5. 触碰已有 subsystem 时，执行最近的 affected canonical lane。

随后只按真实 Impact Scope 增量扩展。不得因为“更保险”自动执行全仓测试、完整 Layered Quality、CodeQL、全 build matrix 或全量 coverage。

纯文档修改不需要无关 Python 测试；但修改 ADR / Contract 时必须检查其直接依赖和架构一致性。

### 4.2 高风险任务判定

只要修改失败可能破坏以下任一性质，就按高风险任务处理：

- 资金安全；
- execution correctness；
- 持久事实完整性；
- recovery / reconciliation 能力；
- 唯一 Authority；
- 公共兼容性；
- 安全边界；
- 工程质量基础设施。

典型高风险范围包括但不限于：

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
Quality infrastructure
```

该列表不是封闭枚举。也不得仅因为“安全起见”把所有任务升级为高风险；必须有具体风险依据。

### 4.3 高风险任务额外要求

高风险任务在普通 Baseline Validation 基础上增加实际相关的专项验证，例如 recovery、persistence、contract、consumer、migration、security、build、external integration。

并且必须进行一次 **bounded Independent Review**。

Independent Review 必须提供独立第二视角，重点检查：

- Authority 是否唯一；
- 状态机是否存在非法状态；
- fail-closed 是否成立；
- recovery / retry 是否确定；
- public contract 是否被静默改变；
- 跨模块边界是否被穿透；
- 是否存在绕过测试或正式入口的隐式路径。

Review 范围严格限制为：

```text
Modification Scope
+ 真实 Impact Scope
+ 直接相关架构不变量
```

禁止借 Independent Review 重新启动全仓审计。

---

## 5. Severity 与阻塞规则

```text
Critical → 阻塞
High     → 阻塞
Medium   → 默认不阻塞
Low      → 不阻塞
```

Medium 只有在直接违反当前 Required Behavior、Acceptance Tests 或明确架构不变量时，才升级为 blocker。

Medium / Low 可以在当前会话中指出，但不得自动写入仓库质量报告、自动创建 backlog 或自动扩展成下一任务。

---

## 6. Scope Expansion 与范围外问题

当前任务只修改：

```text
Modification Scope
+ 因真实依赖关系证明必须扩展的 Impact Scope
```

发现范围外真实问题时，默认不修。只有以下两种情况才纳入当前任务：

1. 它实际阻止 Required Behavior 正确实现；
2. 它证明原先的 Impact Scope 判断不完整。

否则只在当前会话中简要说明，不修改、不生成报告、不自动创建后续任务。

Impact Scope 扩展只扩到最近的稳定工程边界，禁止“发现一个问题 → 顺手重构旁边模块 → 再发现问题 → 无限审计”。

---

## 7. Hard Stop Condition

普通任务满足以下全部条件后必须停止：

```text
Required Behavior 已实现
+ Acceptance Tests PASS
+ Baseline Validation PASS
+ 真实 Impact Scope 所需验证 PASS
+ 当前范围不存在 Critical / High blocker
= STOP
```

高风险任务额外要求：

```text
bounded Independent Review 完成
+ Critical = 0
+ High = 0
= STOP
```

达到 Stop Condition 后，不得因为 speculative risk、Medium/Low、无关技术债、“还能优化”或“还能重构”继续扩大当前任务。

只有出现新的真实失败、当前修改引入 regression、当前范围 Critical/High 或新证据证明架构不变量被破坏时，才允许重新打开当前范围。

---

## 8. CI 的地位

GitHub CI 是持续质量探针，不是每一步任务的默认完成 Authority。

```text
CI pending → 不阻塞普通任务
CI PASS    → 附加质量信号
CI FAIL    → 判断是否为当前修改导致的真实 regression
```

只有以下情况 CI 成为当前任务阻塞条件：

1. 已确认当前修改引入真实 regression；
2. 某项验证只能在 CI / 特殊环境完成，且它是当前 Required Behavior 不可替代的证明。

普通任务不得等待所有 Layered Quality、CodeQL 或所有 GitHub jobs 才能停止。

### 8.1 Major Milestone Phase Gate

完整 Phase Gate 只在 Major Milestone 真正结束时执行一次，用于证明各任务组合后的整体一致性。

Phase Gate 按 `quality-policy.toml` 与实际 milestone contract 执行适用的：

- repository-wide static；
- canonical regression lanes；
- architecture；
- recovery / conformance / persistence；
- build；
- 必要 E2E；
- 必要 security checks。

Phase Gate 失败时只修真实失败和对应 Impact Scope，不重新展开无边界审计。

---

## 9. Determinism、Hermetic Tests 与外部环境

默认 Task Acceptance 测试必须 deterministic、hermetic、offline-first。

普通验收不得隐式依赖：

- 公网；
- 实时市场数据；
- 真实时间推进；
- 第三方账户状态；
- 不可控执行顺序。

优先使用 fixture、recorded deterministic payload、fake clock、contract fake、local ephemeral DB、deterministic barrier 与 controlled fault injection。

### 9.1 Flaky / nondeterministic failure

当前 Impact Scope 内，同一代码、输入和受控环境必须得到确定结果。

禁止通过以下方式“跑绿”：

- retry-until-green；
- 增加 `sleep()`；
- 无依据扩大 timeout；
- 吞掉异常；
- 依赖随机执行顺序。

若 flaky 明确是历史问题、不在 Modification/Impact Scope 且当前修改没有使其恶化，则不阻塞当前任务。

### 9.2 真实外部环境

真实 Binance、QMT、CTP、数据库部署、Docker 等环境只有在它们本身是 Required Behavior 的不可替代证明时，才是当前任务的强制验收项。

环境不可用不等于代码失败，但也不能被描述为 PASS；真实环境测试失败则是有效失败证据。Mock/fake 不得冒充必须由真实环境证明的集成行为。

---

## 10. Tests 与 Regression Protection

测试是当前行为的可执行证据，可以随真实 Contract 演进，但不能为了让实现通过而被洗白。

禁止：

- 删除有效断言；
- 降低断言强度；
- 无依据扩大 tolerance；
- 删除有效边界测试；
- skip/xfail 当前真实失败；
- 通过 sleep/retry 掩盖 race；
- 修改测试以适配一个违反现有 Contract 的实现。

### 10.1 Bug Fix

确认的真实 Bug 原则上必须增加最小 Regression Test：

```text
复现旧错误
→ 修复根因
→ 在最近稳定边界证明错误不会复发
```

如果因为真实硬件、第三方环境或构建平台原因无法稳定自动复现，必须提供另一种可重复的最小验证；“难写测试”不是跳过 Regression Test 的理由。

### 10.2 Coverage

Coverage 是诊断与专项验证工具，不是普通任务默认 Gate。

只有以下情况按需使用：

- Task Contract 明确以 coverage 为目标；
- 关键算法/状态机需要分支覆盖证明；
- 某模块已有长期 coverage contract；
- Major Milestone Phase Gate 需要整体观察。

不得为了固定百分比制造低价值测试。

---

## 11. Pre-existing Failures 与 Evidence Sufficiency

历史已有失败不自动阻塞当前任务。

若能够证明失败：

- 修改前已经存在；
- 不属于当前 Required Behavior；
- 不属于当前真实 Impact Scope；
- 当前修改没有扩大或恶化它；

则不修、不扩 Scope。

若历史失败阻止当前任务建立必要证据，它就成为当前真实 Impact Scope 的依赖问题。

无法确认是否 pre-existing 时，只做最小必要确认，不启动全仓审计。

**缺少充分证据不能等价为验收满足。** 未执行、环境不可用、无法证明都不是 PASS。补证据时只补当前 Contract 所需的最小充分证据。

---

## 12. Compatibility、Persistence 与 Migration

任何公共 Contract 或持久格式兼容性变化都属于高风险任务，包括：

- public Python API；
- Provider / Broker / DataSource SPI；
- wire protocol；
- persistent schema；
- checkpoint / recovery format；
- event serialization；
- plugin contract；
- public CLI behavior。

必须判断 backward/forward compatibility、migration 与 affected consumers，并按需执行 contract、consumer、migration tests 与 bounded Independent Review。

Breaking change 可以存在，但必须是明确设计决定，不能因为实现方便而静默发生。

### 12.1 Database Schema / Migration

数据库迁移追求真实可恢复性，不形式主义地要求所有 migration 都提供伪 downgrade。

必须明确并验证：

- precondition；
- deterministic transformation；
- failure semantics；
- transaction / atomicity；
- compatibility window；
- restart / retry semantics；
- data integrity。

能安全回滚时提供 rollback；不能安全回滚时使用 fail-closed + backup/snapshot/forward-fix。

按实际影响覆盖 fresh DB、previous schema、success、repeat/restart、partial/invalid state、integrity 与 affected application compatibility。真实数据库仅在不可替代时成为任务强制证据。

---

## 13. Build、Package 与 Security

### 13.1 Build / Package / Distribution

普通内部实现不默认执行完整 build。

修改以下可分发边界时，必须执行对应 build/package 验证：

```text
pyproject / package metadata
dependencies
entry points
public exports
package layout
plugin discovery
generated artifacts
frontend build inputs
Docker image contents
release/build scripts
```

Major Milestone Phase Gate 再执行完整适用的 build 集合。

### 13.2 Security

Semgrep、dependency audit、CodeQL 与其他 security checks 同样由风险和 Impact Scope 驱动。

普通内部修改不默认执行全量安全工具。修改依赖、认证授权、secret handling、外部输入、网络协议、SQL/persistence、命令执行、文件系统、Web security、Broker/LIVE 外部接口等边界时，增加对应专项安全验证。

持续 CI 负责广泛扫描；Major Milestone Phase Gate 执行完整适用的安全检查。

---

## 14. Quality Infrastructure Protection

以下属于质量基础设施：

```text
AGENTS.md
quality-policy.toml
scripts/verify.py
scripts/test_suite.py
CI workflows
architecture rules
lint / mypy / test discovery configuration
```

业务/功能任务不得为了让当前实现通过而修改质量规则、ignore、allowlist、threshold、test discovery、gate selection 或 workflow condition。

只有以下情况允许修改质量基础设施：

1. 当前 Task Contract 本身就是质量基础设施改造；
2. 有明确工程证据证明现有规则本身错误或与冻结架构冲突。

质量基础设施修改本身按高风险任务处理：targeted infra tests + consistency checks + bounded Independent Review。

---

## 15. `scripts/verify.py` 的职责

`verify.py` 是 **当前工作区修改的 Impact-Aware Verification Selector**，不是任务状态机或认证系统。

它只负责：

```text
读取当前 working tree / staged / unstaged / untracked / rename / delete
→ 根据当前规则推导 Impact Scope 候选
→ 选择 canonical lanes / checks
→ 执行或输出当前结果
```

它不得要求 Task Base SHA，不得生成长期 verification manifest，不得维护历史 PASS evidence，不得宣布任务、Increment 或 Phase 状态。

Agent 仍需根据 Task Contract 和实际依赖判断 selector 是否覆盖真实 Impact Scope；工具输出不是完成 Authority。

---

## 16. 文档与仓库卫生

仓库只保存系统长期需要的信息：

- 源码；
- 测试；
- ADR；
- Architecture；
- Contract / protocol；
- 必要用户、开发、部署说明；
- Roadmap / execution plan 中的未来建设顺序和依赖关系。

仓库不得保存：

- 每步完成状态；
- 工程进度状态文件；
- 质量/审计/验收/closure 报告；
- CI PASS 快照；
- verification manifest/history；
- Final-SHA / Exact-SHA 工程认证记录作为当前规则；
- task implementation/validation/completion summary；
- 自动生成的下一步授权状态。

Roadmap 只能描述未来建设地图，不记录 completed/current/pending/ready/verified/progress percentage 等工程进度。

任务结束后的实现说明与测试结果只存在于当前开发会话，不提交为任务总结文件。

真实长期设计变化必须更新对应长期文档；普通实现不得为了“记录完成”修改 ADR 或 Architecture。

---

## 17. Versioning

Task / Increment 编号与 Release Version 完全解耦。

```text
P9.x / P10.x
→ 工程规划标识

0.x.y / 1.x.y
→ 软件发布与兼容性版本
```

普通任务验收不要求根据任务编号修改版本号，也不存在 `Pn.m -> 0.n.m` 映射。

只有真实发布、package/API compatibility release 或明确 release contract 要求时才修改版本，并使用现有版本同步工具保证需要同步的 package metadata 一致。

---

## 18. 明确退役的工程机制

以下机制不得重新成为 OnlyAlpha 工程推进条件：

- Exact-SHA / Final-SHA engineering certification；
- 每个 Increment 的持久化 VERIFIED/READY/COMPLETE 状态；
- project-state authority；
- 每步质量报告；
- 每步完整 Layered Quality 等待；
- 每步全仓 coverage；
- 无边界重复审计。

历史 Git commit、旧 Prompt、旧 ADR 中可能出现这些术语，它们只能解释历史，不得覆盖本文件定义的当前工程验收规则。

---

## 19. 默认执行原则

面对任何工程任务，按以下顺序工作：

```text
读取当前代码与长期设计约束
→ 建立当前上下文 Task Contract
→ 冻结 Required Behavior
→ 实现最小正确方案
→ 根据真实依赖校正 Impact Scope
→ targeted tests + Baseline Validation
→ 按风险增加专项验证
→ 高风险执行 bounded Independent Review
→ 确认当前范围 Critical=0 / High=0
→ 达到 Stop Condition
→ STOP
```

核心原则：

> **代码工程本身是当前事实；验收必须充分，但必须有边界。**
