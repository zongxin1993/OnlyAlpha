# 插件能力、接口与历史边界

本清单描述 `plugs/` 的职责和能力边界，配合[仓库架构](repository-product-architecture.md)、[ADR 0149](adr/0149-flat-rust-library-layout.md)和 [ADR 0150](adr/0150-product-layout-and-programmable-quant-assets.md) 使用。具体输入、输出和错误以对应 Rust 公开接口及正式契约为准。目录、语言、配置声明和能力标签都不能单独证明插件已经接入正式运行流程。

## 组件与能力

| 工程 | 类别 | 负责的能力 | 不负责的范围 |
|---|---|---|---|
| `onlyalpha-market-cn-ashare` | 市场制度 | 冻结证券 Reference、按交易日解析规则、普通人民币 A 股交易时段/价格/数量/结算约束、市场费包 | 行情采集、撮合、券商协议、资金仓位写入；不凭库存在声明完整 A 股或 LIVE 支持 |
| `onlyalpha-market-crypto` | 市场制度 | Spot/衍生品各自的标的解释、不可变规则输入、明确版本的费用与账户模式政策 | 外部数据连接、订单发送、模拟撮合、风控准入；Spot 模型不自动证明 USD-M 能力 |
| `onlyalpha-data-source-binance` | 数据源 | Binance 公开行情协议、标的和日历、历史/实时行情、源序列与重连连续性；Spot 与 USD-M 分别声明能力 | 交易鉴权、私有订单/成交流、市场规则执行、产品存储和正式发布 |
| `onlyalpha-data-source-tushare` | 数据源 | Tushare 日线、证券及交易日数据采集、单位和时间转换、明确基准的复权 | Broker、实时撮合、交易状态；不得把 SDK 综合接口误认为同名 HTTP 端点 |
| `onlyalpha-broker-virtual` | 模拟券商 | 模拟场所的订单/成交观察、撮合/滑点/延迟政策、成交排程、部分成交/取消与恢复 | Runtime 会计真相、市场交易制度、风险许可或第二套回测执行器 |
| `onlyalpha-broker-binance` | 真实券商协议 | Binance 已明确支持产品的签名请求、订单/成交/账户查询、用户流、原操作对账及协议恢复 | 行情数据源、市场制度、实盘启用、资金仓位权威；Spot 实现不自动覆盖期货或保证金交易 |

表中的职责不是对所有产品、端点、账户类型或运行模式的支持承诺。每个插件必须在 README 中列出实际已实现接口与限制；正式装配只安装真实实现，不能用 authoring 配置目录、未接入描述符或空适配器冒充运行能力。

## 接口和实际装配

数据源复用 `onlyalpha-integration-contract::source` 的 `Factory`、`Resource`、`Stream` 等接口。配置、真实安装、凭据、Source grant、不可变采集输入及产品发布分别由所属边界处理。公开行情和私有交易不得共用未经区分的身份或权限。历史、临时行情和实时流各自遵守正式语义，临时输入不能当作已闭合行情。

券商复用 `onlyalpha-broker` 的交易、查询、观察和日志端口。插件产生规范化场所观察，Runtime 通过自己的端口确认应用；发送成功或收到 ACK 不等于已成交。未知结果保留原 command/order/client identity，继续查询和对账，不生成第二个操作盲目重试。

市场插件输出显式输入确定的规则和经济约束。通用订单、费用应用、结算状态、资金、持仓和风险由对应 Rust 库拥有；模拟撮合由 Virtual Broker / Backtest 的所属机制处理。新的市场差异不得以具体市场分支进入 Kernel。

默认沿用 Cargo 库与后端显式安装，不以本轮语言迁移引入动态库热加载、独立插件进程或 Python 转发层。Python 因子与策略编写环境继续属于后端算法边界。

## 已存在的受限实现

这些限制必须通过实际能力闭合后才可以删除：

- Crypto 的原生 Reference 和 MarketBinding 库支持确切资源/内容指纹、精确 as-of、Spot 与线性合约规则、账户模式及分段保证金政策；新费用包依据真实 MAKER/TAKER 角色选择费用，并要求调用方提供显式账户 Broker Fee Contract。当前产品的 `SpotSimulationPolicy` 仍是 BTCUSDT/USDT 实验性现金回测模型。规则编译能力不等于对应成交经济、撮合、SIM 服务或 LIVE 已装配。
- Binance 提供原生 Spot 公开行情、Reference 原始响应捕获与不可变目录存储，以及 USD-M 历史 K 线、Mark/Index/Funding 和公开/账户 Reference 的独立归一化。账户与杠杆响应由调用方明确提供；没有因此增加期货私有账户客户端。Spot 双请求 Reference 捕获支持 GLOBAL 的已准入端点和 Spot Testnet，PUBLIC_MARKET_DATA、US 在发请求前拒绝。USD-M 非 Bar 事实的库级能力不等于正式产品已安装相应采集或交易流程。
- Tushare 已有原生日线数据源和正式历史 DAY 链路，绑定加密 Secret Slot、复权基准、原始输入及封存数据身份。Chart 的“1日”仅支持历史查询；分钟行情沿用原流程，DAY 尚不能保存为固定时长的 Workspace、Study 或回测输入。正式范围为沪深股票 2025 年起的封存日线；不据此声称 ETF、北交所或实时支持。
- Virtual Broker 提供原生 Rust 场所库，通过 Broker 的交易、查询、观察和 Journal 端口组合使用。产品现行回测继续使用已绑定的 NextOpenPolicy/SpotSimulationPolicy，SIM 服务另需显式安装。这些边界和原工件恢复条件见 [Virtual Broker](virtual_broker.md)。
- Binance Broker 提供面向现行 Rust Broker 端口的 Spot 协议库，覆盖签名 REST、用户流、原操作对账和检查点恢复。ReadOnly 与 Trading 分开授权，账户余额查询不提供伪造的统一权益快照。当前后端尚未安装私有 Binance Broker 宿主；该库不证明 SIM/LIVE 产品启用或期货交易支持。旧 Python 消费者及有效断言迁完后再清理，不作为生产回退。

Tushare 的 `pro_bar` 在 SDK 中组合基础数据及复权逻辑。纯 Rust 实现应记录原始行情、复权因子和基准范围，验证 `none/qfq/hfq`、单位及 `end_date` 语义；不能悄悄改用另一个静态复权产品。参考 [HTTP API](https://tushare.pro/document/1?doc_id=130)、[通用行情](https://tushare.pro/document/1?doc_id=109)和[复权说明](https://tushare.pro/document/2?doc_id=146)。

## 发行单元与历史身份

现有包名到发行单元 ID 的映射由 `scripts/release_metadata.py` 统一推导。发行单元与源码目录通过真实 workspace 成员及其包声明关联，不能靠去掉一个字符串前缀猜测路径。版本仍从所属 Cargo/package manifest 读取，不另存一份版本号。

| 工程包名 | 已登记发行单元 ID |
|---|---|
| `onlyalpha-market-cn-ashare` | `plugin-onlyalpha-market-cn-ashare` |
| `onlyalpha-market-crypto` | `plugin-onlyalpha-market-crypto` |
| `onlyalpha-data-source-binance` | `plugin-onlyalpha-data-source-binance` |
| `onlyalpha-data-source-tushare` | `plugin-onlyalpha-data-source-tushare` |
| `onlyalpha-broker-virtual` | `plugin-onlyalpha-broker-virtual` |
| `onlyalpha-broker-binance` | `plugin-onlyalpha-broker-binance` |

这些已经登记的 ID 不因本次命名对齐而重写。发行 ID、包名、Provider/Product identity、接口版本与实现指纹分别管理；例如 A 股历史 Provider `onlyalpha-plugin-cn-ashare` 不等于当前工程路径。旧事实、标签和归档使用原身份。

删除 Python 实现前，必须迁移实际调用方和有效断言，并保留原工件及读取能力。新 Rust ELF、当前插件或当前规则不能冒充旧 wheel、旧规则快照或旧 Generation。历史读取继续校验原 manifest、SHA、工作身份和关联；缺失或不匹配时明确拒绝，不重建、猜测或降级为成功。

## 验证边界

每项能力应覆盖正常值、错误身份与关联、缺失、篡改、取消及适用的未知结果。数据源核对行情边界、单位、序列/去重/断线恢复；模拟券商核对事件顺序、检查点与恢复后结果；真实券商核对签名、预算、未知发送与对账。旧测试中的独立期望值和事故断言必须保留其有效含义，不能以新实现输出生成期望值。

Rust 库按功能验证；公开 API 和用户步骤变化分别使用后端整体 API 测试和前端 Web 测试，统一走隔离的 `onlyalpha-dev`。外部服务或 Testnet 专项记录单独证据，不能替代正式权限检查或授予 LIVE 权限。
