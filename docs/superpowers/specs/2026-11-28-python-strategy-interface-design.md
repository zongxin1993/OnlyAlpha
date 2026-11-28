# 单股与截面策略的 Python 接口设计草案

**状态：待评审。** 文中的 Python 名称、返回类型和调用时序是拟议接口。现行架构只接受声明式规则或 WASM 策略；新增 Python 编写入口、扩展策略 WIT 和组合决策能力需要架构决定。本稿供讨论，不改变现行契约或准入条件。[现行策略架构](../../adr/0152-unified-runtime-dual-kernel-operators-qlib-dag-and-wasm-plugins.md) · [策略身份与准入](../../strategy.md)

## 1. 作者写什么

人在 Web 写 Python，或由 Agent 经正式 API 创建同样的策略草稿。作者声明决策范围、触发条件、所需因子、精确参数，然后实现一个函数。依赖绑定在冻结时解析到不可变版本。因子继续由 Rust 从声明式表达式计算；同一因子可以供多种策略使用。

**范围由谁一起做决策决定。** 全市场排名可以作为单股策略的一个输入。反过来，即使输入全是逐股收益率，只要多只股票需要竞争同一笔预算、共享换仓名额，就应对整个组合调用一次。

| 接口 | `instrument` 单股决策 | `portfolio` 截面决策 |
| --- | --- | --- |
| 调用单位 | 一个触发事件中的一个标的 | 一个调仓事件中的整个策略投资域 |
| 作者入口 | `on_bar(ctx: InstrumentContext) -> InstrumentDecision` | `on_rebalance(ctx: PortfolioContext) -> PortfolioDecision` |
| 因子视图 | `ctx.factors[别名]`，当前标的在该时点的值 | `ctx.universe`，按标的身份有序的只读表，每行含标的和全部已绑定因子 |
| 交易视图 | 当前标的、该标的的策略持仓与未完结订单、只读账户摘要 | 策略组合的持仓、未完结订单、只读账户摘要，包括已调出投资域但仍持有的标的 |
| 一次返回 | 维持或设置该标的目标数量 | 维持或提交一份组合目标权重表 |

两类上下文都提供事件时间 `ctx.as_of`、不可变参数 `ctx.params` 和稳定的标的身份。上下文只在本次调用有效。持仓与在途订单按运行绑定的策略组合归属读取，账户摘要反映绑定账户；策略不能把同账户其他策略的仓位当作自己的仓位。跨标的预算由组合策略和经济端处理。

## 2. 单股示例：双均线，目标持仓 100

以下两个代码块各代表一份独立策略源文件。`onlyalpha_strategy` 是拟议 SDK。装饰器声明因子别名，Web 草稿绑定页或同一正式 API 将别名映射到精确因子版本。示例中 `fast`、`slow` 分别绑定收盘价的 5 期和 20 期均线，标的与 Bar 周期来自冻结的投资域和行情契约。

```python
from onlyalpha_strategy import InstrumentContext, InstrumentDecision, strategy


@strategy(scope="instrument", trigger="bar_close", factors=("fast", "slow"))
def on_bar(ctx: InstrumentContext) -> InstrumentDecision:
    fast = ctx.factors["fast"]
    slow = ctx.factors["slow"]
    if fast is None or slow is None:
        return ctx.hold(reason="WARMUP_OR_MISSING")
    if fast > slow:
        return ctx.target_quantity(100, reason="FAST_ABOVE_SLOW")
    if fast < slow:
        return ctx.target_quantity(0, reason="FAST_BELOW_SLOW")
    return ctx.hold(reason="EQUAL_AVERAGES")
```

这里的 `100` 是目标总持仓。已有 60、另有已确认仍有效的买单 40 时，目标已被覆盖，本次新增量为 0。原派单结果未知时，经济与执行端按原命令对账，暂停依赖该未知数量的新增风险。目标仅在本次决策生效；`hold` 不新增命令，也不补发上一次被拒订单。`target_quantity(0)` 遇到相反方向的在途买单时，执行端须关联原单撤单，等待最终撤单和途中成交确证。例如原有 60、撤单期间又成交 10，重新核对后按 70 计算可卖量。结果未知时保持观察、撤单和对账，缺证的新增派发暂停。现有 `OrderIntent` 只表达新单；支撑这个目标语义还需要执行端的撤单协调与可恢复记录。

## 3. 截面示例：每周选 20 只，等权，最多替换 3 只

示例采用多头股票组合，`momentum` 绑定一个确定版本的动量因子。每周最后一个交易日收盘后触发。候选少于 20、已有超过 20 个多头，或调仓时尚有未完结订单，本例选择整批维持。非投资域持仓、因子缺值的持仓仍计入原持仓数和替换预算。首次从空仓建仓、给未满 20 只的组合补足空位，不计入“替换”。

```python
from onlyalpha_strategy import PortfolioContext, PortfolioDecision, decimal, strategy


@strategy(scope="portfolio", trigger="weekly_close", factors=("momentum",))
def on_rebalance(ctx: PortfolioContext) -> PortfolioDecision:
    k, max_replacements = 20, 3
    if ctx.portfolio.has_unresolved_orders:
        return ctx.hold_portfolio(reason="ORDERS_PENDING")

    # 返回有值的标的 ID；同分按规范标的 ID 升序。
    ranked = ctx.universe.rank_by("momentum", descending=True,
                                  missing="exclude", tie_break="instrument_id")
    held = ctx.portfolio.long_instrument_ids  # 稳定排序，包含已离开投资域的持仓
    if len(ranked) < k or len(held) > k:
        return ctx.hold_portfolio(reason="PORTFOLIO_OR_COVERAGE_LIMIT")

    rank = {symbol: i for i, symbol in enumerate(ranked)}
    preferred = ranked[:k]
    # 先替换无排名持仓，再替换排名靠后的持仓，同级按标的 ID。
    outsiders = sorted((s for s in held if s not in preferred),
                       key=lambda s: (-rank.get(s, len(ranked)), s))
    removed = outsiders[:max_replacements]
    selected = [s for s in held if s not in removed]
    additions = [s for s in preferred if s not in selected]
    selected.extend(additions[:k - len(selected)])

    weights = {s: decimal("0.05") for s in sorted(selected)}
    return ctx.target_weights(weights, unlisted="target_zero", reason="WEEKLY_ROTATION")
```

例如原组合已满，前 20 名有 8 只新股票，本周提出移出优先级最低的 3 只、移入排名最靠前的 3 只的目标，另外 17 只保留在目标名单内。部分成交、拒绝或冻结可能让实际持仓偏离目标；若需将实际持股数硬性限制在 20 以内，经济端必须等相应退出获得确证才能准入占用该名额的新买单。**最多替换 3 只约束的是成员更换次数。** 保留标的回到 5% 也可能产生交易；金额换手率上限是另外一种约束。若持仓已离开投资域但受替换上限影响而暂时保留，目标换算只能使用有效的估值和交易资格。首版建议对域外或不可增持的保留标的禁止新增敞口，记录目标与可执行量的差异；是否能减持交给市场规则与风控。

## 4. 输入、时间与返回值

- **时点与截面。** 冻结交易日历、时区、周期和可见性截止规则。`weekly_close` 指该日历每周最后一个交易日的收盘决策。首版沿用固定行情标的全集和因子状态宽度，准入时覆盖候选及全部需管理的原持仓；运行中可变的候选资格来自截至当时可见的冻结成分规则与生效记录。排名集合按该期资格筛选，行情全集继续推进和估值，包括被调出的持仓。新成分必须已在全集内预热，重新入选沿用同一因子历史；全集外新增标的需重新绑定运行。截面算子的排名／标准化也须按相应声明的有效成员掩码处理，此能力需要实现并验证。无有效估值时阻止依赖该估值的整批权重换算，保留风险处置路径。
- **周触发。** 用交易日历版本、逻辑交易周和决策范围定位唯一的计划收盘事件。宿主记录事件时间截止和交付水位，即使末根 Bar 缺失也按冻结缺值政策处理；全周无交易日不触发，截止证据不足则记录阻塞。之后收到的补数不产生第二次周调仓。宿主在同一截止点生成因子表、交易状态和估值。横截面因子也完成后才调用单股策略。多市场若没有已定义的联合日历和对齐规则，不接受该运行配置。
- **缺数与迟到。** 投资域内的标的即使缺观测也保留行，可空因子以 `None` 呈现。因子缺值、无持仓和未知账户状态分别表示。缺少必需的账户或组合归属证据时阻止本次风险增加。迟到或修订数据不得静默改写已封闭决策。回测用相同可见性规则；缺乏到达顺序或截止证据时，须标明可提供的重放证据范围。
- **类型。** 价格、数量、权重和参与决策的非整数参数采用确定性的精确十进制；示例的 `decimal("0.05")` 表示精确的 5%。声明外的因子、参数或上下文字段返回契约错误。SDK 冻结精度、除法与舍入政策，禁止依赖本机浮点或可变的进程级数值上下文。跨 WIT 按规范十进制字符串无损转换；溢出、除零和超出领域精度的输出拒绝整次决策。标的 ID 跨 Python 与 Rust 按同一规范顺序比较。
- **维持、清仓和失败。** `hold_portfolio()` 与单股 `hold` 相同，保留现有在途订单，本次不发新命令，也不补发已拒订单。`target_weights` 的 `unlisted` 必须显式指定；本例的 `target_zero` 只覆盖本策略组合，包含此前持有或尚有相关在途命令的标的。空表加 `target_zero` 表示全部目标为零。函数异常、超预算和非法返回是失败，不能解释成维持、空表或清仓。
- **目标换算。** 首版建议只接受多头、无杠杆目标，权重和小于等于 1，余量为现金。组合／账户和执行模块分别提供有归属的权益、估值与在途事实。策略适配层核对整批目标的结构、归属和权重上限，按冻结的估值、取整和订单政策生成规范化 `OrderIntent`。具体市场数量规则由对应插件给出。[经济端口](../../../crates/runtime/src/trading/execution.rs) 拥有资金预留与逐单准入；不同策略共享账户时按已生效的预留计算可用资金。依赖卖出所得的买单只使用已确证可用的资金，卖单拒绝、部分成交或结果未知时，记录相应买单的未准入或受限数量。

## 5. 身份、确定性与 Rust 执行

同一个正式 Strategy Revision 在三种模式下使用同一决策语义。建议修订的语义绑定包括精确 WASM 摘要、WIT 版本、因子别名到不可变版本的映射、参数、范围、投资域定义、Bar 构造语义、日历与触发／可见性规则、数值与目标解释版本。`fast` 改绑或周触发规则变化均产生新修订。构建清单将 Python 源码摘要、SDK、依赖和工具链关联到已核验工件；作者与编辑时间属于溯源。运行绑定另记具体行情快照、账户、经济政策和输入序列。换账户或快照可以复用同一修订；正式指纹编码由策略身份所属模块经 ADR 定稿。人工编写和 Agent 生成走同一校验路径，LIVE 启用和重大风险授权由人经正式入口操作。[不可变修订](../../adr/0097-strategy-revision-freeze-and-promotion-authority.md) · [宪法关于确定性、恢复和 LIVE 的规定](../../../PROJECT_CONSTITUTION.md)

1. 构建服务在隔离环境把冻结源码构建为策略 WIT 组件。策略可见能力采用显式白名单，不授予系统时钟、随机、文件、网络或环境变量。首版只接受经验证能确定执行的 SDK 和依赖；哈希种子、集合迭代、浮点以及数值转换不得改变可观察结果。编译工件能否满足大小、内存和逐事件时延预算尚待验证。
2. Rust 按修订加载工件，先推进事件因子，再按 `scope` 传入一行或完整截面。首版回调无私有跨事件状态，因子窗口由 Rust 持有。组合矩阵在 WIT 边界须限制标的数、格数、字节数和输出数。检查完整性后再调用，超预算拒绝整次决策，截断前若干行会改变排名。
3. 决策按原运行身份、修订、触发事件和作用域关联，单股另含标的身份。输入证据记录实际可见的行情、因子、账户与在途状态前缀。Rust 对目标按规范顺序归一化，整批校验后才交给执行层。同一运行、修订、逻辑触发和作用域实例只有一份决策。单股实例按标的区分，组合实例按策略组合归属区分。同键同正文复用原决策，同键异文阻断。独立运行保留各自的身份，跨模式比较规范化输入与输出。
4. SIM／LIVE 在首笔派发前持久绑定原输入截止点、规范目标、已生成意图的有序身份和准入状态。后续准入或撤单产生的命令沿用原决策因果链，在派发前先持久绑定。崩溃后分别处理已确认、确证未派发、未知及证据不可读的状态；缺证不能断言未派发。观察、对账、风险降低继续走原执行端口。有限回测丢失过程状态时使用新 attempt 从原冻结输入重算。

## 6. 工程落点与待评审决定

| 已有能力 | 拟议改动及仍缺少的证据 |
| --- | --- |
| [`TradingEngine` 与逐标的 `StrategyPort`](../../../crates/runtime/src/trading.rs) 已持有截面因子矩阵，每个截面读取一次账户快照 | 在相同矩阵与快照上按范围派发；补充组合归属、在途命令、可分配权益和时点证据，确认由对应事实 owner 提供。 |
| [策略 WIT v1](../../../contracts/wasm/v1/onlyalpha-plugin.wit) 接收命名因子、只读账户和参数；[WASM 宿主](../../../crates/wasm-host/src/strategy_plugin.rs) 每次隔离调用 | 设计版本化 WIT，显式传入当前标的或整个组合截面；明确目标到意图的适配和证据归属。验证 Python 构建产物与真实预算。 |
| [端口回测](../../../crates/runtime/src/trading/backtest.rs)、[SIM](../../../crates/runtime/src/trading/sim.rs)、[LIVE](../../../crates/runtime/src/trading/live.rs) 支持注入策略；[默认有限回测](../../../crates/runtime/src/trading/backtest/playback.rs) 核对冻结 `Executor` 且限定单标的 | 统一不可变修订的加载路径。组合回测还需多标的估值、批次准入、信号回执与结果复核；逐点因子一致只证明因子计算。 |

建议评审优先决定三件事：是否将 Python 正式纳入策略编写入口；首版是否接受上述无私有状态、只做多、目标数量／权重的范围；是否将两种范围共同纳入默认有限回测。若接受，再在正式 ADR 与对应公开契约中定稿。

评审时可用以下场景核对语义：同根行情重复投递、买单未成交时连续触发、双均线预热缺值、周末遇休市、排名第 20/21 名同分、原持仓调出投资域、候选不足时整批维持、空表显式清仓，以及部分派单后重启。各模式对相同事实前缀应产生相同的规范化决策；场所成交不同应作为新的外部输入保留。
