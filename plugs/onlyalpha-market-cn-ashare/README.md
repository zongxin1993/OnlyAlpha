# OnlyAlpha CN A-share Market Product

同路径 Rust 库拥有冻结版本的普通人民币 A 股 Reference、政策编译和市场费包，消费公开 Domain、Fee、Settlement API。
不拥有可变交易状态、行情或 Broker 接口，不授予 A 股 Runtime、SIM 或 LIVE 运行许可。

`Factory::resolve` 返回不可变 `Bundle`。输入证券事实按 Instrument 和交易日唯一解析，Reference 区间左闭右开，拒绝重叠、
未知状态和来源。`2025.1` 政策适用于 `[2025-01-01, 2026-07-06)`；`2026.07` 自 `2026-07-06` 生效。
编译器冻结 Session、价格带、Tick、数量、停牌、零股清仓限制、NETTING/禁卖空和 T+1 六轴政策。
这些编译数据供市场规则消费，不是替代 Market Decision、Risk 或 Settlement Authority 的第二入口。

`CompiledPolicy::settlement_schedule` 只消费调用方明确提供的真实不可变 Calendar，不制造节假日数据。
价格带用 Domain Decimal 精确运算及 HALF_UP 对齐 Tick；无法证明中间除法精确时拒绝，禁止近似值进入价格带。

`FeePack::compose` 必须接收显式 Broker 合约、来源及 schedules，不假定零佣金。生产市场费包固定为
`CN_A_SHARE_PRODUCTION_MARKET_FEES@2025.06.30`，完整覆盖始于 `2025-06-30`。买卖侧、择期、公式与舍入
由真实 `onlyalpha_fee::Catalog` 处理。市场来源位于 `src/fee_sources.json`，是原已登记来源记录的静态迁移；
这不构成对所有当前市场政策的新认证。

本地库功能门禁：`cargo test -p onlyalpha-market-cn-ashare`。Rust Bundle 明确绑定实际实现，原历史 Python 工件与摘要不转换。
未覆盖新股特殊阶段、退市整理、北交所、ETF、B 股、可转债、融资融券、集合竞价撮合或动态价格笼子。
