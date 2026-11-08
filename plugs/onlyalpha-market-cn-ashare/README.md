# OnlyAlpha 普通人民币 A 股市场规则库

## 目的与职责

同路径 Rust 库拥有冻结版本的普通人民币 A 股 Reference、政策编译和市场费包，消费公开 Domain、Fee、Settlement API。
不拥有可变交易状态、行情或 Broker 接口，不授予 A 股 Runtime、SIM 或 LIVE 运行许可。

## 边界与依赖

直接依赖 `onlyalpha-domain` 的日期、精确数值、证券身份及市场规则类型，`onlyalpha-fee` 的费用 Catalog 和摘要，
以及 `onlyalpha-settlement` 的结算日期解析；`bigdecimal` 用于输入十进制规范化，`serde_json` 用于冻结记录。
市场差异停留在本插件；Market Decision、Risk、Fee 和 Settlement 的正式通用语义仍归各自模块。

## 公开接口

公开类型由 [src/lib.rs](src/lib.rs) 导出，错误以 `Error` 返回，包含拒绝原因或底层边界错误。

`Factory::resolve` 返回不可变 `Bundle`。输入证券事实按 Instrument 和交易日唯一解析，Reference 区间左闭右开，拒绝重叠、
未知状态和来源。`2025.1` 政策适用于 `[2025-01-01, 2026-07-06)`；`2026.07` 自 `2026-07-06` 生效。
编译器冻结 Session、价格带、Tick、数量、停牌、零股清仓限制、NETTING/禁卖空和 T+1 六轴政策。
这些编译数据供市场规则消费，不是替代 Market Decision、Risk 或 Settlement Authority 的第二入口。

[Reference 与 ReferenceAuthority](src/reference.rs) 分别解析单条证券事实、排序并查询不可变事实集，拒绝缺证、
未知来源、区间重叠及摘要不匹配。[PolicyCompiler 与 CompiledPolicy](src/policy.rs) 接收该事实集、证券身份和交易日，
输出冻结政策及 Domain 的 Tick、Lot、价格带与 Session 类型；版本不生效或精确运算无法成立时拒绝。

`CompiledPolicy::settlement_schedule` 只消费调用方明确提供的真实不可变 Calendar，不制造节假日数据。
价格带用 Domain Decimal 精确运算及 HALF_UP 对齐 Tick；无法证明中间除法精确时拒绝，禁止近似值进入价格带。

`FeePack::compose` 必须接收显式 Broker 合约、来源及 schedules，不假定零佣金。生产市场费包固定为
`CN_A_SHARE_PRODUCTION_MARKET_FEES@2025.06.30`，完整覆盖始于 `2025-06-30`。买卖侧、择期、公式与舍入
由真实 `onlyalpha_fee::Catalog` 处理。市场来源位于 `src/fee_sources.json`，是原已登记来源记录的静态迁移；
这不构成对所有当前市场政策的新认证。

[FeePack 与 FeeComposition](src/fees.rs) 暴露冻结费包、显式 Broker 合约组合和按交易日绑定的接口。
`FeeComposition::catalog` 返回真实费用 Catalog；`compose` 拒绝缺少或归属不符的合约，`bind` 拒绝完整覆盖之前的交易日。

[PolicyCompiler::version_for](src/policy.rs) 返回指定交易日适用的政策版本。查询早于已冻结版本的日期会返回版本未生效错误。

## 状态与生命周期

本库仅持有不可变事实和编译记录，不启动进程、不读写数据库、不维护订单或仓位，也不拥有持久化恢复 Authority。
调用方保存其正式绑定及证据；记录读取返回副本，不能修改已解析 Bundle。
Rust Bundle 明确绑定实际实现，原历史 Python 工件、版本身份和摘要不转换，也不能以新 Rust 记录冒充。

## 使用与验证

本地库功能门禁：`cargo test -p onlyalpha-market-cn-ashare`。
公开接口功能测试见 [tests/product.rs](tests/product.rs)，覆盖冻结参考数据、政策边界和实际费用 Catalog 计算。
未覆盖新股特殊阶段、退市整理、北交所、ETF、B 股、可转债、融资融券、集合竞价撮合或动态价格笼子。
