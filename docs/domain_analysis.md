# OnlyAlpha Domain 前置分析

## 1. 目标与范围

本分析面向未来十年以上的多市场金融 Domain，不以兼容 MyQuant API 或当前 A 股策略为目标。分析日期为 2026-07-13；MyQuant 仅只读审查，未运行实盘、未修改文件。

审查范围包括 `MyQuant/core/object.py`、`constant.py`、`order.py`、`position.py`、`broker.py`、`broker_sim.py`、`broker_xt.py` 及行情数据对象的产生路径。

## 2. MyQuant 领域对象现状

MyQuant 以 `PositionData`、`OrderData`、`TradeData`、`AccountData` 等可变 dataclass 作为跨 Broker 和 Strategy 的数据容器。标的由 `symbol: str + Exchange` 表达；价格、数量、金额、费用与 PnL 使用 `float`；时间使用不同格式的字符串；枚举主要覆盖 A 股与现有运行模式。

模拟 Broker 同时维护活动订单、历史订单、持仓、账户和撮合，XT Broker 将 SDK 查询/回调对象转为这些数据类。PositionManager 还根据 Broker 内部集合推断 FIFO、可卖量、超时和风险动作。因此数据对象虽存在，但状态所有权、领域规则与基础设施职责没有分离。

## 3. 值得保留的金融概念

以下是应保留的“概念”，不是应复制的实现：

- Order 与 Trade 分离：委托意图和实际成交是不同事实。
- total/available/frozen：账户余额和持仓都需要总量、可用量、锁定量。
- Order active/terminal 分类：订单生命周期必须可查询且受状态机约束。
- offset：期货等市场需要 OPEN/CLOSE/CLOSE_TODAY 等开平语义。
- 本地 Order ID 与场所 Order ID 分离：用于提交前身份和回报对账。
- Position 记录方向、数量、均价、市场价、PnL 和关联成交。
- 订单回报、成交回报、账户与持仓查询需要幂等对账；这将由未来执行域完成。

## 4. 必须重构的设计

| MyQuant 设计 | 长期问题 | OnlyAlpha Domain 决策 |
|---|---|---|
| 核心数值使用 float | 非确定、无精度/单位/币种 | Decimal 值对象，拒绝 float |
| `symbol + Exchange` | ID 可混用、Exchange 集合受限 | `OnlyInstrumentId(OnlySymbol, OnlyVenueId)` |
| 可变数据类 | 回调线程可产生隐式状态变化 | 默认 frozen dataclass，变更产生新快照 |
| 字符串时间 | 时区和格式含糊 | timezone-aware datetime |
| Broker 内订单/持仓/账户真值 | 基础设施与领域聚合耦合 | Domain 只定义事实/快照；管理器在外层 |
| A 股 Exchange/手数写入通用逻辑 | 无法自然支持多市场 | Instrument 规格 + 外部 Market Rule |
| `Direction.LONG/SHORT` 同时代表订单与持仓 | 买卖动作和持仓方向混淆 | `OnlyOrderSide` 与 `OnlyPositionDirection` 分离 |
| Account.total 隐式相加 | 多币种无法合法汇总 | 分币种 Balance；总权益必须指定报告币种 |
| 开放 dict/Any 配置和 remark | 约束、序列化不稳定 | 强字段模型；适配元数据留在 Gateway DTO |
| Position 中直接保存可变 market_price | 快照时点和估值来源不明 | Position 保存聚合状态，估值由显式价格输入产生 |

## 5. NautilusTrader 研究结论

参考官方 Value Types、Instruments、Orders、Positions、Portfolio 和 Order Book 文档。采用的思想：

- Price、Quantity、Money 是维度不同的不可变值类型；Money 绑定 Currency。
- precision 属于值的表达，increment 属于 Instrument 的场所约束；二者独立。
- Instrument ID 是 Symbol 与 Venue 的强组合，所有行情和执行事实引用它。
- Instrument 明确 base/quote/settlement、multiplier、数量/名义限额和有效时间。
- Order 是状态机实体；Trade/fill 是不可变事实；Position 从 fill 聚合。
- 标准、反向和 quanto 合约的名义价值/PnL 公式及币种不同。
- 多币种 Portfolio 汇总必须经显式 FX 转换。

不复制 NautilusTrader 源码、事件溯源实现、Rust 内存布局或 API。OnlyAlpha 初期用 Python Decimal；若将来切换缩放整数，必须保持公开语义并提供序列化迁移。

## 6. Domain 边界结论

Domain 可以依赖 Python 标准库，但不得依赖 Engine、Runtime、Cluster、Gateway、Broker SDK、Database、Web、Cache、EventBus、Backtest、Live 或 Research。Domain 定义金融事实、值对象、不变量和纯状态转换；时间获取、ID 生成、持久化、行情订阅、订单路由和状态管理均由外层注入或负责。

自动化测试 `test_dependency_boundary.py` 通过 AST 扫描保护该依赖方向。
