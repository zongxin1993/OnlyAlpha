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

`crates/onlyalpha-kernel/margin/` owns immutable collateral reservations, exact RESERVE/OCCUPY/RELEASE_RESERVED/RELEASE_OCCUPIED, directional quantity conservation, initial/maintenance state and complete deterministic replay. It depends only on Domain and already-admitted numeric/serialization/digest crates. Market `OnlyMarginModel` rate compilation remains outside this library; Python `margin/{models,manager,order_port}.py` maps to native reservation/Manager and the Execution consumer, rather than a copied provider factory.

Scopes bind full Engine/Runtime/Account/Gateway/Generation/kind/Cluster/Revision/Instrument/Request and immutable mode/isolation/position side. A release names its opening reservation and actual closing Order/Trade; another order's unfilled reservation is never a close source. Partial release allocates integer minor units with HALF_EVEN and consumes the exact final remainder. Explicit zero occupancy increments may follow front-loaded compiled requirements; absent inputs never imply zero.

Before submission, reserve two future instruction slots per canonical quantity quantum plus reserve/terminal slots, with at most 512 total history slots. Valid positive fills and closes cannot increase this bound. Configuration/scope, commands, state and records have explicit structural/byte limits under a 32 MiB checkpoint. The immutable history, not snapshots alone, reconstructs a fresh receiver atomically; alternate contexts, incomplete histories, aliases and derived-state substitutions are rejected. These native component codecs/identities do not decode official Python history.

Execution metadata schema5 freezes Margin alongside existing Fee/Settlement state in the same six-group transaction. Required collateral NONE/MARGIN declarations make missing proof explicit. ADMIT reserves before dispatch; FILL occupies or releases from exact Order/Trade and Position/Allocation lifecycle relations; terminal remainder releases never follow UNKNOWN or cancellation request alone. Account checkpoint schema4 retains exact before/version-bound collateral projections, reducing availability without changing cash/equity. Account and Cluster fixed-capital admission both include held collateral; a joint check reads existing Ledger and Margin owners without creating a second balance authority.

The current native cash-security LONG/NETTING consumer requires one active mode/isolation pool per Position scope. Close input explicitly selects RESERVATION_ID_ASCENDING and exact mode/isolation/side; derived instructions avoid an unbounded external allocation frame. The isolated Margin library supports CROSS/ISOLATED and LONG/SHORT independently. Full futures economics, MTM, Funding, liquidation, production storage/Runtime/deployment upgrade, Python retirement, LIVE and Shipping UI product admission remain separate gates. Python common money behavior is compared against independent expectations; quantity allocation, strict recovery and corrected release ownership are not represented as whole Python parity. Source digests prove integrity, not external producer authority.

Account 的 Margin writer 仅接受 `onlyalpha_margin::Effect`，不接受可写 derived before/after。必要依赖为 Account → Margin → Domain；Margin 仍只依赖 Domain。Account journal 保存 producer config/capacity、完整 producer checkpoint before/after digest 和 canonical input，每次消费及 fresh recovery 都由 Margin 重推导并校验完整历史连续性。
