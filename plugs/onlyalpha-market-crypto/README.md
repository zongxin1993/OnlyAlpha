# Crypto 市场规则

## 目的与职责

本库将有来源和有效范围的 Spot、线性永续市场参考资源编译为可验证的市场规则。支持按标的和准确时刻解析的价格、数量、名义金额和费用政策，衍生品还需绑定账户模式、资金费率周期及分段保证金。已有 BTCUSDT/USDT 实验回测模型使用独立的版本化规则快照。

## 边界与依赖

Domain 提供时间、标的、数值、订单与货币语义，Fee 拥有费用估计和应用。bigdecimal 支持精确金额运算，serde_json、metadata-json、sha2 实现受控 JSON 读取与兼容身份计算。交易所响应由数据源捕获和归一化。账户、保证金、订单、成交及持久交易状态属于各自内核所有者。费用规则须与调用方显式选择的 Broker Contract 一起使用。

## 公开接口

USD-M 的实际编译生产者在完整原正文中明确产品身份及 LINEAR 合约类型，与原资源的账户模式、结算币、乘数、保证金曲线和 Funding schedule 共同参与原策略指纹。通用消费者比较这份真实投影，不允许用顶层 NETTING/CROSS 重标 HEDGING/ISOLATED，也不能保留原正文却替换较低保证金曲线。

CompiledPolicy::compiled_policy_json 返回实际 compile 计算原策略指纹的确切正文，static_limit_rules 经同一通用生产过程推导限价规则。原策略指针与整份规则 content_fingerprint 分开绑定；修改 tick、最小名义、binding 或有效期必须产生新策略身份。Runtime 按该包逐请求核验。

- [reference](src/reference.rs) 的 Reference::document 校验资源文件的独立 SHA、资源 ID、provider 和完整旧格式内容，Reference::load 供已有可信上下文的语义记录重建使用。Reference::spot 和 Reference::usdm 对归一化输入构造身份。resolve 接收标的及 UTC 时刻，缺证、跨域或歧义返回错误。Spot 观测时刻独立于规则内容身份。
- [market_policy](src/market_policy.rs) 的 MarketBinding::resolve 根据 Product、配置及资源映射核对预期身份与实际账户模式。compile 返回只读 CompiledPolicy。validate_limit 检查静态价格、数量与名义金额，动态价格返回参考证据要求；margin_requirement 返回当前名义金额所在档位的初始、维持保证金额。fee_catalog 组合配置的 Maker/Taker 规则及调用方提供的券商费用契约，按实际角色选择单项费用并绑定原生版本。
- [spot](src/spot.rs) 的 SpotRuleSnapshot 保存一次原始观察。SpotSimulationPolicy 为既有实验性现货回测生成入场估算、委托、成交和费用所需的模型输入；continuous_calendar 提供该模型的连续交易日历。

## 状态与生命周期

Reference、MarketBinding、CompiledPolicy 各自持有不可变的输入。公开与账户衍生资源分别保留内容和覆盖区间、采集证据的 Authority 身份。恢复已有运行时由实际工件和冻结资源选择 Reader；缺少原始引用、账户、覆盖或保证金域须拒绝。纯库不建立连接或写文件，也不安装产品运行路径。

## 使用与验证

运行 `cargo test -p onlyalpha-market-crypto`。原资源文件、观测边界、费率角色、保证金分段和身份负例见 [market_resources.rs](tests/market_resources.rs)，既有模型回归见 [spot_simulation.rs](tests/spot_simulation.rs)。资金事实及账户经济变化由真实 Execution/Runtime 验证。
