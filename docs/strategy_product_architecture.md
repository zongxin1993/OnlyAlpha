# OnlyAlpha Target Strategy Product Architecture

> Status: **Target / Reference Architecture**
>
> 本文描述 OnlyAlpha 的长期策略产品语义、Research → Backtest → Sim → Live 晋升关系，以及 Web / LLM Agent 的目标操作边界。它不是当前实现完成声明，也不预先冻结 P8 之后的 milestone 编号。具体实现开始前仍必须重新读取当时 Repository truth，并通过 ADR 冻结最终类型、字段、状态机和 migration。

## 1. 产品目标

OnlyAlpha 的长期目标不是维护四套 Runtime-specific 策略，而是形成一条可以被研究、验证、晋升、审计和恢复的统一策略语义链：

```text
Human / LLM Agent
        ↓
Draft Indicator / Factor / Strategy Intent
        ↓
Research
        ↓
Research Evidence
        ↓
Freeze
        ↓
Immutable Strategy Revision
        ↓
Backtest
        ↓
Historical Trading Evidence
        ↓
Promotion Decision
        ↓
Sim
        ↓
Realtime Simulated Trading Evidence
        ↓
Promotion Decision
        ↓
Live
```

长期原则：

```text
Research discovers.
Strategy Revision defines.
Backtest verifies historically.
Sim verifies realtime trading behavior.
Live grants real execution permission.
```

Research、Backtest、Sim、Live 不重新解释策略含义。跨 Runtime 变化的是数据时态、Portfolio/Execution Profile、Broker、Lifecycle 与 Execution Permission，而不是策略语义本身。

## 2. Strategy 不是一段隐藏业务语义的 Python callback

策略长期应被定义为一组可序列化、可验证、可冻结的明确语义，而不是把核心决策隐藏在任意 Runtime callback 中。

参考结构：

```text
Strategy Semantic Definition
│
├── Universe Definition
├── Decision Mode
├── Calculations
│   ├── Indicators → Named Features
│   ├── Factors → Primary Score
│   └── Eligibility / Filter Calculations
├── Selection / Ranking
├── Decision Expressions
│   ├── Entry
│   └── Exit
└── Signal Contract
```

P9.0 已把 Trading Strategy 产品入口迁移为 immutable Strategy Revision：Runtime/Cluster 只按 `strategy_fingerprint` 从 Freeze-only
`frozen-revisions` Store 经 reader/Resolver 装配，Kernel callback 仅由内部 revision-backed adapter 承接。Freeze 从 Run-linked Research
Execution Evidence 读取 historical implementation，并要求 exact-node actual-backend Equivalence Evidence V2。任意 Python
`OnlyStrategy` subclass、动态 class/config path 与 raw Revision commit 不再是 Runtime Strategy authority；后续能力不得重建第二执行路径。

## 3. Universe 与 Decision Mode 必须正交

用户研究对象可以是：

```text
SINGLE_INSTRUMENT
STATIC_BASKET
MARKET_UNIVERSE
```

决策数学形态可以是：

```text
TIME_SERIES
CROSS_SECTIONAL
```

产品可以提供方便默认值：

```text
单票 → TIME_SERIES
多票 / 全市场 → CROSS_SECTIONAL
```

但 Domain 不得把“股票数量”与“策略类型”永久绑定。多票也可以执行彼此独立的 time-series rule；单一 Universe 选择与 Decision Mode 必须是两个显式事实。

Research 的用户友好 Universe 选择也不能代替正式数据 identity：

```text
Instrument / Universe Selection
        ↓
Dataset Materialization / Resolution
        ↓
Immutable Dataset Snapshot
        ↓
Dataset Snapshot Fingerprint
        ↓
Research Specification
```

正式 Research 执行始终消费 exact immutable Dataset Snapshot，而不是“当前数据库里这些股票的数据”。

## 4. Indicator、Feature、Factor、Eligibility 的角色

ADR 0110 refines this model into four layers: generic mathematical Operators (L1), financial Indicators (L2), hypothesis-bearing
Alpha Factors (L3), and canonical Strategy decisions (L4). L1/L2 are public reusable capabilities; production L3/L4 are private.
Calculation/Graph remain the sole engineering/DAG authorities and Feature remains an output port.

### 4.1 Indicator → Named Feature

Indicator 是无交易副作用的计算定义，可以输出一个或多个具有稳定名称和语义的 Feature，例如：

```text
MACD
├── macd
├── signal
├── histogram
├── golden_cross
└── dead_cross
```

用户选择 Indicator 时，可以进一步选择哪些 Feature 进入研究、可视化或最终 Decision Logic。

Feature 本身不是订单。Feature 与 operator / threshold 组合后形成 Predicate：

```text
RSI.rsi < 30
MACD.golden_cross == true
Close > MA20
```

### 4.2 Factor → Primary Score

第一阶段 Factor 的正式策略消费接口优先保持简单：每个 Factor 提供一个明确 primary score，并可以拥有其他可观察 Feature/Snapshot。

```text
MomentumFactor
→ primary_score
```

Decision Logic 可以显式引用：

```text
Momentum.score > 0.70
```

未来如增加 normalized score、rank、percentile 等，必须继续保持 exact semantic identity，不能由 Web 临时重算形成第二真值。

### 4.3 Eligibility / Filter 是独立 semantic role

市值、价格、流动性、交易状态等过滤条件可以复用统一 Calculation infrastructure，但在策略语义中应明确表示为 Eligibility，而不是与普通 Entry Feature 混淆：

```text
Original Universe
        ↓
Eligibility Expression
        ↓
Eligible Universe
        ↓
Factor / Ranking / Decision
```

例如：

```text
MarketCap > 5B
AND Price > 5
AND ADV20 > 50M
```

实现可以共享 Indicator/Calculation primitive；semantic role 必须保持不同。

## 5. Decision Logic 应是结构化表达式

第一阶段策略决策优先使用有限、可验证、可序列化的表达式树，而不是任意脚本：

```text
AND
OR
NOT
>
>=
<
<=
==
!=
```

例如：

```text
ENTRY
AND
├── RSI.rsi < 30
├── MACD.golden_cross == true
└── Momentum.score > 0.70

EXIT
OR
├── RSI.rsi > 75
└── MACD.dead_cross == true
```

后续只有被真实策略需求证明时，才增加 `crosses_above`、`held_for` 等 temporal operators。不要为了通用性一开始构造任意脚本语言。

Decision Expression 是策略语义的一部分，必须稳定序列化、fingerprint、测试和重放；Web graphical builder 与 LLM Agent 生成的都必须落到同一 canonical representation。

## 6. Signal 与 Portfolio/Execution 必须分离

策略语义首先产生确定性的 selection / signal，例如股票 Long-only 第一阶段可以使用：

```text
ENTRY
EXIT
NONE
```

而不是直接把资金规模、Broker order quantity 固化进 Strategy Revision。

长期组合关系：

```text
Strategy Revision
→ Signal / Candidate / Rank

Portfolio Profile
→ Capital Allocation / Max Positions / Weighting / Rebalance

Execution Profile
→ Order policy / execution constraints allowed above system mandatory rules
```

因此：

```text
Strategy Revision
!=
Portfolio Profile
!=
Execution Profile
!=
Runtime Permission
```

Backtest 也必须显式绑定 Portfolio/Execution Profile，才能计算 PnL、Drawdown、Turnover、Fee 等交易结果；不是只有 Live 才拥有仓位配置。Live 晋升时必须显式选择或确认 Live Deployment Profile，而不是隐式继承一个不透明的研究资金假设。

Mandatory Market Rule / Risk / Reservation / execution capability 仍属于系统和 Trading Runtime authority，Strategy Profile 不能删除或降级它们。

## 7. Immutable Strategy Revision

Research 允许大量实验、Sweep、代码和参数变化；真正进入 Trading verification 前必须执行一个明确的 Freeze / Promotion 动作。

本文使用 `StrategyRevision` 作为长期参考术语；最终 class/type 名称在实现阶段由 ADR 冻结。

一个 immutable Strategy Revision 至少需要能够精确证明：

```text
Strategy semantic identity
Universe definition
Decision mode
Calculation graph identities
Indicator exact code/type/version
Factor exact code/type/version
Resolved parameters
Selected named Features
Eligibility logic
Ranking / selection logic
Entry / Exit decision expressions
Signal semantics
Code/package/dependency evidence required for reproducibility
Origin Research Specification
Origin Research Run / Result / Artifact evidence
```

Strategy Revision 一旦冻结永远不可修改：

```text
S1
→ change code/parameter/logic
→ S2
```

禁止：

```text
same Strategy ID
+ silently changed code
```

`ResearchRunId`、`Research Specification fingerprint`、Dataset-bound Research Calculation fingerprint 都不能替代 Strategy Revision identity。Research Run 表示一次执行；Strategy Revision 表示被批准进入后续 Trading verification 的 immutable strategy semantics。

## 8. Research → Backtest → Sim → Live

### 8.1 Research

Research 负责高效探索：

```text
Universe / Dataset
→ Indicator / Feature
→ Factor / Score
→ Eligibility
→ Parameter Sweep
→ Decision / Signal
→ Target / Statistics
→ Scientific Analysis / Visualization
→ Research Result / Artifact
```

Research 不拥有 Account、Position、Broker、Order、Risk Reservation 或 Trading Transaction authority。

### 8.2 Freeze / Promote

用户或受控 Agent 从 Research Evidence 中选择候选后执行：

```text
Research Candidate
→ Freeze
→ Strategy Revision Sx
```

Freeze 必须把代码、参数、逻辑、依赖证据和 origin research evidence 一起固定。它不是把 mutable ResearchRun 改造成 Strategy，也不能删除或改写 Research history。

### 8.3 Backtest

Backtest 只允许执行 exact Strategy Revision：

```text
Strategy Revision Sx
+
Historical Evaluation Dataset
+
Backtest Portfolio Profile
+
Backtest Execution Profile
+
Market Product / Fee / Virtual Broker
→ Backtest Evidence
```

允许使用与 origin Research 不同的 out-of-sample historical Dataset，但 Strategy Revision 的代码、参数、Feature/Factor/Decision 语义必须不变。

### 8.4 Sim

通过 Backtest promotion gate 后，同一 Strategy Revision 进入 realtime simulated execution：

```text
Strategy Revision Sx
+
Realtime Data
+
Sim Portfolio/Execution Profile
+
Virtual Broker
+
Full Trading Kernel
→ Sim Evidence
```

Sim 不允许创建“Sim 专用策略版本”来修补语义差异。策略需要修改时必须产生新的 Strategy Revision，并重新获得要求的验证 evidence。

### 8.5 Live

Live 继续执行同一个 Strategy Revision，但额外要求显式真实执行权限：

```text
Strategy Revision Sx
+
Live Deployment Profile
+
Account / Capital Allocation
+
Resolved Market Product
+
Real Broker Capability
+
Authorization / Promotion Evidence
→ Live Runtime
```

`Runtime Type != Execution Permission` 继续成立。Strategy Revision 存在、Backtest/Sim 通过，都不自动等于允许真实资金执行。

## 9. Promotion 是 evidence-driven，不是状态名称驱动

长期 Promotion 不能等价于：

```text
if runtime == LIVE: enable trading
```

而应基于明确 evidence 与 permission：

```text
Research Evidence
→ Strategy Freeze Evidence
→ Backtest Evidence
→ Sim Evidence
→ Explicit Live Authorization
```

Promotion 只能向前增加证据和权限；历史 evidence 不被后续 Runtime 重写。

## 10. Web 最终产品形态

目标 Web 不只是 Result Viewer，而是 Strategy/Research 工作台。长期用户流程：

```text
Select Universe
→ Define / Select Indicator
→ Select Named Features
→ Define / Select Factor
→ Set Parameters / Sweep
→ Define Eligibility
→ Build Entry / Exit Expression
→ Preview canonical Research/Strategy intent
→ Submit Research
→ Monitor Run
→ Inspect K-line / Feature / Factor / Signal / Statistics
→ Freeze Strategy Revision
→ Launch Backtest
→ Promote to Sim
→ Explicitly deploy to Live
```

### 10.1 Research Studio

至少应支持：

- 单票、股票池、全市场 Universe 选择；
- Universe → exact Dataset Snapshot resolution；
- Indicator / Factor 选择与参数配置；
- Named Feature 选择；
- Factor primary score 选择/展示；
- Eligibility builder；
- Entry / Exit AND/OR expression builder；
- exact Specification / strategy intent preview；
- durable Research Run submission / cancellation / status；
- completed Result / Artifact navigation。

### 10.2 Scientific Visualization

Research 的核心不是只显示最终收益率，而是解释 Feature / Factor / Signal 与市场之间的关系。

Time-series / single-instrument 至少应支持：

```text
Historical K-line
+ Indicator overlay
+ Factor score panel
+ Selected Feature panel
+ ENTRY / EXIT marker
```

Cross-sectional 应支持基于 immutable Research facts 的科学分析，例如：

```text
Score vs Forward Return
IC / Rank IC time series
Quantile analysis
Distribution
Scatter
Heatmap
Coverage / Turnover
Candidate comparison
```

Web chart 只是 presentation projection。所有精确数据继续来自 Dataset / Calculation / Statistics / Result / Artifact authority，浏览器不得重新计算新的 semantic truth。

### 10.3 Embedded IDE

长期 Web 可以提供受控 embedded IDE，用于编写或修改 Indicator、Factor 和未来 Strategy extension code；本地 IDE 与 Web IDE 最终都必须进入同一 Code Admission Pipeline。

IDE 不是 production authority。保存草稿不等于注册新的正式 Calculation/Strategy revision。

## 11. LLM / Agent：Author，不是 Authority

本文统一使用 `LLM / Agent`。LLM 可以作为用户的研究与编码代理，但不能成为策略真值、测试真值或交易权限 authority。

目标流程：

```text
Human Prompt / Agent Goal
        ↓
LLM generates or edits Indicator / Factor / Decision draft
        ↓
Static validation
        ↓
Unit / Contract tests
        ↓
Determinism / identity checks
        ↓
Code Admission
        ↓
Exact version registered
        ↓
Research Specification
        ↓
Research Evidence
```

LLM / Agent 可以在用户授权下：

- 创建 Indicator / Factor 草稿；
- 修改代码并运行受控验证；
- 选择已注册 Indicator / Factor；
- 设置 parameters / Sweep；
- 选择 Feature；
- 构造 Eligibility 和 Entry / Exit expression；
- 提交 Research Run；
- 读取 Result / Artifact；
- 基于 evidence 提出 Strategy Freeze / Promotion 建议。

但不能：

- 绕过 Code Admission 把生成代码直接载入 Live；
- 自行修改 immutable Calculation / Strategy Revision；
- 伪造 Research/Backtest/Sim evidence；
- 根据自然语言模糊匹配 `latest` plugin 后直接执行；
- 绕过 Risk / Market Rule / Broker / Runtime permission；
- 未经明确授权自动晋升到 Live；
- 把自己的推理或聊天上下文当 durable strategy fact。

Human Author 与 LLM Author 必须经过同一验证、identity、freeze 和 promotion contract。

The Agent primarily creates and searches L3 Factors and L4 Strategies, while querying and composing admitted L1 Operators and L2
Indicators. If reusable mathematics or financial knowledge is missing, the Agent proposes a separate L1/L2 admission; it must not
hide that capability inside a Factor or Strategy.

ADR 0111 permits high-change private L3/L4 repositories to be consumed from an explicit source/editable path during controlled Agent
research, or from an installed uv/pip distribution. L3 source import and installed entry-point discovery expose the same registrations;
L4 explicit-root and package-resource reads expose the same authoring JSON. Paths remain pre-Freeze authoring inputs and are excluded from
Strategy identity and Runtime authority.

## 12. 代码与依赖证据

为了保证 Strategy Revision 能在未来重新验证，Freeze 必须保存足够的 reproducibility evidence，但不应把整个开发机镜像塞进 Strategy Domain。

需要在实现阶段从第一性原理决定最小证据，例如：

```text
canonical strategy representation
Calculation definition fingerprints
exact plugin type_id + semantic_version
source/package content fingerprint
resolved parameter values
decision AST fingerprint
relevant schema/version identities
origin Research references
```

代码 artifact、package artifact、Strategy Revision semantic record 应保持职责分离；一个巨大 JSON 不应成为所有 authority 的替代品。

## 13. 当前 P9.0 与长期 Strategy Product 的边界

P8 当前目标仍是完成 Web-native Research Control Plane，不预先扩张为完整 Strategy Promotion milestone。

P8 已留下 exact Candidate/Result/Artifact 输入边界；P9.0 已冻结并实现 Candidate Freeze、immutable Strategy Revision、唯一增量执行投影与 Promotion ledger foundation：

```text
Universe selection
Indicator / Factor selection
Named Feature / parameter configuration
Eligibility / decision / signal research representation
Scientific visualization
Durable Web Research execution
```

但完整以下能力默认属于 P8 之后、重新基于当时 Repository truth 规划的长期方向：

```text
immutable Strategy Revision authority
Research → Backtest Freeze / Promotion
Backtest → Sim promotion evidence
Sim → Live promotion evidence
Web embedded IDE code admission
LLM Agent strategy authoring automation
Backtest / Sim / Live full Web productization
```

这些更长期方向仍不等于 P9.0 已实现 Portfolio/Execution Profile、Live deployment permission 或完整 Production Trading Vertical。

## 14. 最终架构不变量

长期 Strategy Product 必须保持：

```text
One Strategy Semantic Truth
→ Immutable Strategy Revision

Research Run
!=
Strategy Revision

Universe
!=
Decision Mode

Indicator
→ Named Feature

Factor
→ Stable Score / Snapshot

Eligibility
!=
Entry / Exit

Strategy Revision
!=
Portfolio Profile
!=
Execution Profile
!=
Execution Permission

Same Strategy Revision
→ Backtest / Sim / Live

Runtime Type
!=
Strategy Semantics
!=
Execution Permission

LLM Agent
→ Author / Operator Client
→ Never Authority
```

任何实现如果需要为了 Runtime 差异修改策略代码、把 Web/Agent 变成 semantic authority、或者通过 mutable “当前策略”覆盖历史版本，都应视为架构错误并 fail closed / redesign，而不是通过兼容分支掩盖。
