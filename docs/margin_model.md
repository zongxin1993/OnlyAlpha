# Margin Model

`OnlyMarginModel` 以 `price × quantity × contract_multiplier` 计算 notional，再计算 initial 与 maintenance margin。
`OnlyMarginState` 独立表达 collateral、used、available、maintenance 和 ratio，保证金不会塞入 CashBalance。

A 股与 Generic T0/Crypto Spot 是 Cash。Generic Futures 使用 10% initial、8% maintenance，并验证资金不足拒绝。
平仓释放、逐日盯市和强平尚未接入生产 ExecutionProcessor；Cross/Isolated、Mark Price、Liquidation 与 Funding 仅是 Perpetual
后续扩展边界。

Order planning 的 margin reservation 接受当前 operation 已解析的 optional planning price，优先级为 Order price、explicit planning
price、legacy non-reference callback。它不读取 realtime market projection；因此 realtime-reference MARKET planning 与 Risk、fee 和
cash reservation 使用同一价格。Valuation 是独立 logical operation，仍使用既有 closed-Bar mark policy；本合同不引入 Trade-driven
valuation。


## Rust Margin responsibility and consumer boundary

`crates/margin/` owns immutable collateral reservations, exact RESERVE/OCCUPY/RELEASE_RESERVED/RELEASE_OCCUPIED, directional quantity conservation, initial/maintenance state and complete deterministic replay. It depends only on Domain and already-admitted numeric/serialization/digest crates. Market `OnlyMarginModel` rate compilation remains outside this library; Python `margin/{models,manager,order_port}.py` maps to native reservation/Manager and the Execution consumer, rather than a copied provider factory.

Scopes bind full Engine/Runtime/Account/Gateway/Generation/kind/Cluster/Revision/Instrument/Request and immutable mode/isolation/position side. A release names its opening reservation and actual closing Order/Trade; another order's unfilled reservation is never a close source. Partial release allocates integer minor units with HALF_EVEN and consumes the exact final remainder. Explicit zero occupancy increments may follow front-loaded compiled requirements; absent inputs never imply zero.

Before submission, reserve two future instruction slots per canonical quantity quantum plus reserve/terminal slots, with at most 512 total history slots. Valid positive fills and closes cannot increase this bound. Configuration/scope, commands, state and records have explicit structural/byte limits under a 32 MiB checkpoint. The immutable history, not snapshots alone, reconstructs a fresh receiver atomically; alternate contexts, incomplete histories, aliases and derived-state substitutions are rejected. These native component codecs/identities do not decode official Python history.

Execution metadata schema5 freezes Margin alongside existing Fee/Settlement state in the same six-group transaction. Required collateral NONE/MARGIN declarations make missing proof explicit. ADMIT reserves before dispatch; FILL occupies or releases from exact Order/Trade and Position/Allocation lifecycle relations; terminal remainder releases never follow UNKNOWN or cancellation request alone. Account checkpoint schema4 retains exact before/version-bound collateral projections, reducing availability without changing cash/equity. Account and Cluster fixed-capital admission both include held collateral; a joint check reads existing Ledger and Margin owners without creating a second balance authority.

The current native cash-security LONG/NETTING consumer requires one active mode/isolation pool per Position scope. Close input explicitly selects RESERVATION_ID_ASCENDING and exact mode/isolation/side; derived instructions avoid an unbounded external allocation frame. The isolated Margin library supports CROSS/ISOLATED and LONG/SHORT independently. Full futures economics, MTM, Funding, liquidation, production storage/Runtime/deployment upgrade, Python retirement, LIVE and Shipping UI product admission remain separate gates. Native monetary behavior is checked against independent expectations in all four mode/side cases, with exact intermediate-checkpoint recovery and final closure; the checker invokes no Python Margin Manager. Quantity allocation, strict recovery and corrected release ownership remain native requirements rather than whole Python parity. Source digests prove integrity, not external producer authority.

Account 的 Margin writer 仅接受 `onlyalpha_margin::Effect`，不接受可写 derived before/after。必要依赖为 Account → Margin → Domain；Margin 仍只依赖 Domain。Account journal 保存 producer config/capacity、完整 producer checkpoint before/after digest 和 canonical input，每次消费及 fresh recovery 都由 Margin 重推导并校验完整历史连续性。

## 线性永续的入场与标记价

BACKTEST 正向线性 LONG/NETTING/CROSS 在开仓前预留初始保证金。成交后 RESERVE 转 OCCUPY，以实际成交名义计算增量；由最终成交或可证的场所终态释放未用部分。入场占用按成交记录保持。Position 重新估值后，Margin 的 schema 2 MARK_MAINTENANCE 指令通过原 reservation、剩余开仓量、前版本和状态哈希更新维护要求。多笔开仓按 reservation ID 顺序分摊同一持仓总名义的分段维护额。Account 从实际 Margin 效果更新抵押视图，抵押权益为现金加未实现盈亏，可用抵押再减费用预留及预留/占用保证金。维护额除以正抵押权益形成 maintenance_to_equity，抵押权益非正时该比率为空。抵押不足阻止新风险，真实资金费仍入账。自动追加资金、强平及外部账户对账需要另行安装相关模型。

显式 BACKTEST 的新 Margin 配置包含 observation_capacity。检查点 schema 2 独立保留履约历史、最多该数量的维护额更新，以及缺证的开始和恢复来源。每条记录仍受总检查点 32 MiB 字节上界约束。RESERVE 不能占用已经用尽的观测额度，已准入订单仍能成交、释放及重建。额度耗尽并首次需要重新定价时，Margin 记录原 reservation、来源及版本，Account 将 maintenance_status 置为 UNAVAILABLE，当前维护额和比率为空，并保留上一次整笔事务已确认的维护额、时间和来源。此后完整 Mark 和资金费继续入账。历史现金配置仍读取原 schema 1。

若原冻结最后一档有上限，Margin 按已开仓数量乘以当前 Mark 的单位合约名义，与同一配置的 model_notional_limit 核对。超过该上限使用 MARK_OUTSIDE_MODEL，当前维护额为空。恢复需新标记事实落在模型定义域内、观测仍有余额，并由所有相关 reservation 重新计量。相邻缺证不重复占用历史；每次恢复至少消耗一次有限观测。新委托纳入原未终结的全部剩余限价名义、已成交总额和当前敞口。若不同成交顺序可能令原预留不足，准入拒绝新增风险。

配置 3 显式选择 `entry_profile=LINEAR_LONG_NETTING_CROSS_OPEN`，只用于本轮 BACKTEST 正向线性 LONG/NETTING/CROSS 开仓。入场累计基数来自 Position 精确 cost × multiplier，只有明确无仓位时为零，其他读取失败传播；不能累加已按货币精度舍入的 Settlement 名义。冻结曲线首档的精确 initial(0)、maintenance(0) 必须均为零。

货币投影分别 HALF_EVEN 后，合法曲线不保证每笔维护增量小于初始增量。新 profile 因而在保留原订单、数量、来源、版本、amount≤reserved、幂等及守恒约束后，以同一 CROSS 池累计入场维护额 ≤ 累计初始占用核对 OCCUPY。池包含完整 owner、cluster、revision、instrument、mode、isolation、position_side，排除 request/order；不能借用其他池占用。reservation schema2 的 entry_maintenance 仅由原 OCCUPY 历史重建，Mark 不覆盖它，也不接受调用方提供的汇总证明。当前 Mark 维护额可以高于入场占用，已准入成交仍须履约。新 profile 不支持平仓，release_quote 与 RELEASE_OCCUPIED 明确拒绝；未选该 profile 的 schema1/schema2 原编码、增量规则和关闭路径保持。
