# Virtual Broker 模拟场所

Virtual Broker 的发行单元是 `plugin-onlyalpha-broker-virtual`，Cargo 包名为 `onlyalpha-broker-virtual`，Provider ID 为 `virtual`。原生库在一个 BACKTEST 或 SIM Scope 中持有模拟场所的订单、成交和查询投影。正式资金、策略、风控、费用和结算继续由各自的 Runtime 模块负责。创建、驱动和查询接口见[插件 README](../plugs/onlyalpha-broker-virtual/README.md)及 [Rust 入口](../plugs/onlyalpha-broker-virtual/src/lib.rs)。

## 端口与实际装配

一个场所实例接收作用域、原生工件摘要、初始资金和显式配置。宿主通过 Broker 的 RuntimeReader 和 Journal 提交原命令；确定性驱动使用已闭合 Bar 和显式纳秒时钟。发布端通过 Broker 持久化规范化观察。只有拥有方 Runtime 的应用回执能证明观察已被本地应用。

产品现行回测由 [PreparedNextOpen](../packages/backend/src/workers/backtest.rs) 装配已绑定的 SpotSimulationPolicy 和 [NextOpenPolicy](../crates/backtest/src/next_open.rs)，其固定全量、开盘成交和费用依据保持原绑定。该产品路径尚未安装 Virtual Broker；库的可构造性也不代表 SIM 产品或 LIVE 已经开放。

## 价格、数量与外部投影

市价单在参考行情到达后可被接受，下一合格 Bar 使用开盘价。限价先按买单 low、卖单 high 判断是否触价，再按委托价计算。固定滑点采用可带符号的偏移量，买加卖减，改善成交价时仍核对限价与最终价格。提交、接受、成交发布与撤单延迟由配置给出。

[ADR 0051](adr/0051-virtual-broker-partial-fill-plan-and-multi-fill-recovery.md) 定义了按单冻结的成交计划。WHOLE、MAX_PER_BAR 或 SCHEDULE 决定数量，ONE_PER_BAR 或 ALL_DUE 决定一次推进几步。比例前缀按数量精度向下截断，末步承担余量。部分成交后撤单仅释放剩余额度；已经发生但尚未发布的成交保留原始身份。

场所独立持有模拟现金、预留和 LONG/SHORT 头寸。加权均价沿用 [Domain 十进制运算](../crates/domain/src/numeric.rs)。有限商精确计算，非终止商按明确的 28 位有效数字除法政策计算，再按成交价精度作 HALF_EVEN 量化。多头权益按实际市值计入。空头开仓不收本金、平仓只结算价差，因此新 Rust 工件下按现金加未实现盈亏计算空头权益。旧 Python 查询曾将整个空头市值加到现金中，原有观察和已冻结历史按原始工件处理。此项修正仅作用于新原生场所投影。

## 恢复与历史绑定

原生检查点 schema 4 绑定发行身份、Scope、原 Rust 工件 SHA、原配置及初始资金，保留有序输入、计划、待决动作、事实和发布游标。宿主从原持久化引用读取独立摘要，并按原输入重建及核对状态。在向 Broker 发布前必须确保场所事实可恢复。队列满、发布失败或 Journal 写入结果未知时保留当前待发事实，重新投递沿用原身份。UNKNOWN 提交或撤单只按原命令查询与对账。已拒绝的原撤单仍可通过已存在的同一场所订单、完整事实和 Runtime 回执收敛。断连或恢复时重交同一原命令会读取已登记的结果。未就绪时首次命令也绑定原身份并明确拒绝，重新认证不改变该结果。

历史 Python entry point、wheel 及 schema 1–3 属原实现。读取历史事实须使用原身份与精确工件；缺失绑定时保持不可恢复。原生实现、同版本号和 Git 源码归档均不能代替旧 wheel。原始设计与交易状态约束见 [ADR 0015](adr/0015-account-broker-ports-and-virtual-broker.md) 与 [ADR 0066](adr/0066-durable-broker-driven-order-lifecycle.md)。

新 BACKTEST 配置 3 通过 BoundVirtualActor 持有对应原 Run 的 broker.sqlite3。一个来源步在真实场所状态上运行原输入，核对前驱、原命令或发布证据，在同一 SQLite 事务中逐行保存实际新增事实。只有提交可读时才推进公开游标。失败后按同一序号和摘要读回，旧实例须从原库重开。绑定检查点只保存原绑定与位置；重开按序重跑真实撮合并核对每一条输出。配置 1/2 和独立 Virtual checkpoint4 继续使用原 Reader。

显式绑定模拟场所使用 broker.sqlite3 v2。每次命令生效时原 DISPATCHED 必须仍是当前协议头，场所结果和本步出生事实一并提交。observe_command 保存当前协议前缀和场所前缀上的发现结果，包括尚未流发布的事实及空查询；重开在相同位置重放。正常流发布按实际 stream_at 推进，已由查询观察的事实复用原观察。规范 genesis、CLOCK/BAR/命令和出生事实正文按原始 UTF-8 字节读取。
