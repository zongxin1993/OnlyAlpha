# OnlyAlpha 模拟券商

## 目的与职责

`onlyalpha-broker-virtual` 提供确定性的模拟场所订单、成交与查询投影，Provider ID 为 `virtual`。接收命令、接受订单、场所成交和向 Broker 发布观察分别发生。场所负责自己的虚拟外部事实，Runtime 负责风控、正式资金与仓位、费用和结算。发行单元为 `plugin-onlyalpha-broker-virtual`，版本取自 [Cargo manifest](Cargo.toml)。

## 边界与依赖

适用 BACKTEST 和 SIM 的 Rust 库装配。正式回测产品继续走原先绑定的 `NextOpenPolicy` 和 Spot 模型；本库没有新增 Web、API、SIM 服务或 LIVE 准入。输入采用 [Domain](../../crates/domain/src/lib.rs) 的不可变 Bar、初始 Money 和 [Broker](../../crates/broker/src/lib.rs) 的 Scope、命令和 Journal，金额按十进制定点精度运算，配置和检查点使用 serde_json。依赖 BigDecimal 做归一化、截断与舍入，不访问墙钟、随机数、网络或数据库。

## 公开接口

[`BoundVirtualActor`](src/source_host.rs) 为显式配置 3 的新 Run 创建或重开 broker.sqlite3，绑定 scope、代际、插件工件、初始场所现金和撮合配置。CLOCK、BAR、命令和发布先在私有场所候选执行，再以原头 CAS 将一步与每条新增事实原子提交。旧实例持有的前驱失效须重开。原 Virtual checkpoint4 仍由 `VirtualBroker::restore` 读取，绑定宿主的紧凑 checkpoint 指向原来源库的确定前缀。

新增 Discovery 的 economic_through_ns 仅声明 `now - 1ns` 的封闭前缀，使用实际有符号时钟 checked subtraction，最小值溢出时拒绝。Virtual 未来事实使用当时的 now，时钟不倒退，因此当前纳秒仍可继续出现成交，不能当作 inclusive 封口。该语义不修改旧 CLOCK、Bar 或 checkpoint 编码；真实 driver 应先消费边界成交，再将时钟推进越过边界并读取前缀。as_of 保持供应商序列，Runtime 另核对原成交 Ready 投影。

- [VirtualBroker](src/lib.rs) 的 `new` 接收完整 Scope、经装配方验证的原生工件 SHA-256、初始资金和模拟配置。先通过 `ConnectionPort` 建立连接并认证，再通过 `Broker::dispatch` 携带拥有方 RuntimeReader、Journal 和本库 TradingPort 下达已准入的命令。原操作结果跨断连和重启保持幂等。未就绪时首次提交会记录明确拒绝并绑定原命令，重连不会触发重发。变更内容或错误 Scope 会被拒绝。
- [配置](src/config.rs) 支持 `matching.type=NEXT_BAR`，`slippage.type=NONE/FIXED`，以及非负 `submit_ns/acceptance_ns/fill_ns/cancel_ns/query_ns`。同步查询与旧接口一致，`query_ns` 只参加配置绑定。按 1 开始的提交序号可指定 `REJECT_BEFORE_ACCEPTED` 或 `ACCEPT_THEN_EXPIRE`。理由保存在原订单检查点中；Broker 的 EXPIRED 端口只携带规范终态。
- [数量计划](src/plan.rs) 支持 WHOLE、MAX_PER_BAR、SCHEDULE，以及 ONE_PER_BAR、ALL_DUE。MAX_PER_BAR 固定每 Bar 一笔，单笔订单最多展开 65536 个等量分步。显式数量必须精确守恒；比例前缀向下量化，末步接收余量。配置中的分步数量、比例、上限与滑点可使用 JSON 数字或十进制字符串，两者按原始十进制文本归一化。原身份绑定账户、Gateway、订单、场所 ID、精度、规范化计划与模式。
- `advance(now_ns)` 推进模拟时钟。`on_bar(sequence, &OnlyBar)` 按全局连续序号消费闭合原始 Bar；同一 Bar 重复投递保持幂等。只有价格满足条件且到期的计划步才成交。市价按下一根合格 Bar 的开盘价，限价买单使用 low、卖单使用 high 判断触价。固定滑点可为正或负，买加卖减，负偏移可改善成交价。限价受委托价约束，滑点使最终价格非正时整次 Bar 推进失败。Market 订单接受时需要已有参考 Bar。
- `OrderQueryPort/TradeQueryPort/AccountPort/PositionPort` 返回对应 Scope 的模拟场所投影。接收中订单尚无可用的规范 OrderView，对账返回不确定。支持明确 LONG/SHORT 的净持仓开平、模拟现金或数量预留，允许同日卖出可用数量。普通限价/市价和 DAY/GTC 以外的指令不获准；DAY 没有隐式日历或市场收盘时钟。可选 FeeEvidencePort 对已知订单返回空列表。
- [对账](src/discovery.rs) 的 `reconcile/resolve` 使用同一个串行拥有的 Broker Journal 检查原命令与场所状态。只有已提交的对应 DISCOVERY 记录才能省略重复事实。原撤单被拒绝时，已存在的原订单仍按真实状态参与发现。Runtime 的逐条应用回执与最新订单视图参与收敛；缺失证据保持不确定，错误身份、篡改和不可读日志返回错误。

持仓加权均价使用 Domain 的 `domain-exact-28-half-even-v1` 数值政策。可表示为有限十进制的商保留精确结果；非终止除法依政策保留 28 位有效数字，再按成交价格精度执行 HALF_EVEN 量化。

原生场所的多头权益采用现金加持仓市值。模拟空头开仓不收本金，平仓时只结算开平价差，因此空头权益采用现金加未实现盈亏。旧 Python 在开仓和平仓也按价差处理，却将空头持仓市值全额加到权益中。本修正仅用于绑定新 Rust 工件的运行；历史观察按原身份精确读取。

## 状态与生命周期

`publish` 通过 `Broker::ingest` 按到期时间和相同到期时刻的生成顺序逐笔发布。外部成交先进入可查投影，队列溢出或 Journal 写入结果未知时保留当前待发布事实。恢复后重交相同事实，Broker 按语义身份和内容去重。撤单释放余量，已经发生的成交仍可查询和发布。若撤单先于已排程的接受到期，原订单进入 CANCELLED，恢复后后续接受动作不会重新开单。

宿主必须按运行的持久化协议保存原始输入和原检查点引用，先确保场所成交可恢复再对外发布。检查点保存原配置与工件绑定、事件输入、不可变计划与游标、待决命令和未发布事实。恢复必须由原拥有方提供正确 Scope、原工件与独立持久化的检查点摘要；重放后逐项比对状态。恢复实例需要重新连接才能发送新命令。历史 Python wheel 或旧检查点仅能交原绑定环境和原始归档处理，原生 schema 4 不接受历史 Python schema 1–3，同版本不能代替原工件。

## 使用与验证

从 [Rust 端口集成用例](tests/venue.rs) 查看提交、驱动 Bar、查询、发布、UNKNOWN 对账和从执行后发布前恢复的完整调用。仓库根目录运行 `cargo test --locked -p onlyalpha-broker-virtual`，或使用 `python3 scripts/dev_verification.py run -- cargo test --locked -p onlyalpha-broker-virtual` 在隔离环境验证。正常产品调用需由各自正式装配入口和权限检查接入。

绑定介质 v2 的 [BoundVirtualActor::observe_command](src/source_host.rs) 在原场所状态上执行查询，同时保存实际来源步、协议前驱、阶段、原命令、结果及有序事实引用，返回原 occurrence 索引。命令步保存收到或拒绝的实际结果，重开会按当时两个前缀重演每次查询。原 v1 绑定介质缺少这些原件，打开时拒绝接管。
