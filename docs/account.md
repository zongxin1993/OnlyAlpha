# Account 组件

`OnlyAccountManager` 是每个 Trading Runtime 的本地账户单写入者，第一版支持 CNY 现金账户、Long-only 股票/ETF、现金、冻结、
待结算现金、费用、账户级盈亏、持仓市值、权益和 Reservation。内部状态受控可变，所有 Query、Context、Risk 和 Report
边界只读取 frozen `OnlyAccountSnapshot`。

Account 与 Strategy Ledger 是两本独立账：Account 表示 Trading Runtime 账户合并真值；每个 Strategy Ledger 只表示一个 Cluster
的虚拟资金与归因。Account 也不引用 Broker Store；Broker Snapshot 只能经 Runtime inbound queue 到达字段级 reconciliation，
冲突不能静默覆盖本地历史。

Research Runtime 不拥有 formal trading Account 或 Strategy Ledger；研究资金曲线只能是 Research Result，不得冒充交易账务真值。

现金账户不变量为：

```text
cash_balance >= 0
frozen_cash >= 0
unsettled_cash >= 0
trade_available_cash = cash_balance - frozen_cash
withdrawable_cash = trade_available_cash - unsettled_cash
equity = cash_balance + position_market_value
```

Order 创建后，Trading Runtime 同时协调 Risk Reservation、Account Cash Reservation 与 Strategy Cash Reservation。它们各有独立
状态和生命周期，不共享内部对象。成交后 Account 从标准化 Trade Cash Flow 更新，估值使用账户 Position 与已关闭行情。
Trade Cash Flow 的 fee 必须来自 Runtime 订单累计权威生成的 `OnlyFeeApplicationInstruction`；AccountManager 不读取
Market Profile、Broker Schedule 或外部费用证据，也不计算佣金。Strategy Ledger 与 Fee Application Ledger 应用同一指令投影。

受支持的 multi-fill Long Close 每笔使用 `gross_cash_inflow = sale notional`、`net_cash_inflow = sale notional -
incremental authoritative fee`。Account 不建立或消费现金 Reservation，frozen cash 保持不变；它只消费 Position 给出的
realized-PnL delta，并与 Strategy Ledger 的 cash、fee、realized PnL 和 valuation authority 在 Prepared Transaction 不变量中
交叉校验。Terminal Cancel/Reject/Expire 不产生现金流、Fee、realized PnL 或 Account Projection。

第一版不支持多币种换汇、保证金、融资融券、负债、期货/期权账户和 corporate action 现金流。

所有 Broker Account Update 由 ExecutionProcessor 分派到 `OnlyAccountReconciliationService`；Trade cash flow 位于 Ledger 后、
Reservation 前。Account Manager 事实经 Processor 缓冲，不会在后续 Reservation/Risk/Invariant 失败时形成完整成功事件。
# Close PnL 输入

Account 不计算平仓 PnL。它只消费 Planner 已由 Cluster Allocation 成本归因得到的 `realized_pnl_delta`；Runtime 对账比较 Account 与所有 Strategy Ledger 的聚合值。

## Rust component ownership and recovery boundary

`crates/account/` is an isolated CASH account component depending on Domain, canonical Margin Effects and source-derived Position Valuation Effects. It consumes normalized fee instruction totals and Position-attributed PnL; it never recomputes fee schedules, position costs or realized PnL. Account, Strategy Ledger and external Broker facts keep distinct Authorities. Cash-backed BUY consumes gross notional plus charges from its exact Reservation; rebates credit cash separately. SELL never consumes a buy Reservation. An explicit Order terminal_fill controls release of excess authority. Uncertain submit/cancel preserves holds, and reconciliation blocks new reserves/withdrawals while valid fills and observations continue.

The actual cash identities are `trade_available = ledger_cash - order_reserved_cash`, `withdrawable = trade_available - unsettled_receivable_cash`, `equity = ledger_cash + position_market_value`. This distinguishes the two availability views rather than using ambiguous available_cash shorthand. This component conservatively reserves and withdraws against withdrawable cash; market-specific settlement reuse is not inferred. Explicit source-bound settlement instructions consume recorded receivables. No hardcoded currency, venue, trading day or settlement date occurs.

Config schema2, commands schema1 and checkpoint schema4 are closed records. Exact scope, currency precision, full-payload receipt conflicts, signed times, ordered trade/Broker sequences, valuation economic basis and bounded resources are checked before candidate commit. Broker snapshots only compare; unverified or stale proof cannot overwrite economics or clear stale-trade blocks. Canonical checkpoints bind the complete journal/state and replay into a fresh owner before atomic replacement. See the [component design](superpowers/specs/2026-10-19-rust-account-design.md) for input limits and errors.

Python direct Manager and the formal Execution reducer are separate reference paths. Direct Manager's ID-only dedup, incomplete receipt restoration and mutation-before-validation are audited deviations, not expected Rust behavior. The complete literal cash corpus is asserted directly by native Rust and its independent output checker; neither invokes those old Python paths. Signed-fee cases, reservation effects and fresh owner restoration remain required. Rust does not introduce a second official writer, Runtime admission, durable cross-authority transaction, business history migration, Shipping UI acceptance or deployment certification. Margin/futures/FX/fee accrual/funding-policy derivation and reporting orchestration retain their owning boundaries and future admission tests.

Signed net Trade effects are accepted when the final cash invariants hold: charge/rebate components remain nonnegative, but fees can exceed sale proceeds and rebates can exceed purchase cost. A nonpositive sale net creates no positive unsettled receivable. A Fill proves submission even without an earlier send callback and can never permit NOT_SENT release of remaining authority. The input coefficient bound applies after canonical currency-precision padding, so every admitted config is readable by its checkpoint reader.

Reference distinction: the Python formal reducer adds a signed cash delta to unsettled receivables when a SELL is not withdrawable; a net-negative sale would violate its nonnegative receivable model. Rust instead records the real signed cash outflow without fabricating a negative settlement claim. This case has an independent Rust invariant test; it is not claimed as Python parity.

The Rust Execution composition evolves this isolated component's checkpoint body to schema2; it does not activate a writer or change official Python Runtime persistence. New semantic fields are mandatory and schema1 has no implicit fallback. New-risk admission budgets are distinct from complete safety history; existing observations/fills/releases and proved reduction retain complete replayable history beyond admission ceilings. See the [Execution boundary](execution.md#rust-component-execution-boundary) for cumulative Position PnL, explicit rounding residuals and exact Allocation cycle/identity inputs.

Rust pending withdrawal claims follow the actual positive Trade cash flow for both SELL and BUY (including a rebate exceeding purchase cost). Release consumes that exact Trade's receivable through an immutable settlement instruction; trading-available cash is not confused with withdrawable cash.


Native Account checkpoint schema4 adds exact before/version/owner-bound Margin projections. Margin collateral reduces trade/withdrawal availability and remains separate from cash/equity; snapshots expose reserved/occupied/released/maintenance totals. Margin Authority retains reservation truth. See [Margin](margin_model.md#rust-margin-responsibility-and-consumer-boundary).

Account 的 Margin writer 仅接受 `onlyalpha_margin::Effect`，不接受可写 derived before/after。必要依赖为 Account → Margin → Domain；Margin 仍只依赖 Domain。Account journal 保存 producer config/capacity、完整 producer checkpoint before/after digest 和 canonical input，每次消费及 fresh recovery 都由 Margin 重推导并校验完整历史连续性。

Account 的估值 writer 仅接受 Position owner 生成的 `ValuationEffect`。Raw 派生 market value / PnL 不是 authoring API；schema4 journal 保存完整 source checkpoint 与 mark intent，恢复时重新执行 canonical producer。Account → Position → Domain 是该实际消费者所需的单向依赖；完整原子 barrier 与精度语义见 [Valuation](valuation.md)。

原生 Account config schema2 必须显式绑定 `position_configuration` 指纹；applied Trade index 与 Position producer 重新执行的完整成交关系一致后才可估值。同 Scope、同最终 Snapshot 均不能替代完整 cause/configuration/Trade lineage。


The Rust `account` Manager implements `Clone` only as an independent in-memory data copy. It retains the exact configuration, complete canonical journal, state, receipts and indexes; later mutation of either copy does not mutate the other. Cloning performs no I/O, recovery, reconciliation or dispatch and grants no Runtime admission, source freshness or durable write authority. The owning Execution composition must prove its actual source independently; persisted bytes still require the existing complete checkpoint restore reader. Clone does not authenticate caller data or replace crash/restart recovery.


### Explicit native checkpoint5 source dictionary

`Manager::new` retains exact checkpoint4 capture and restore, including its existing safety-history behavior beyond admission limits. `Manager::new_checkpoint5` explicitly selects checkpoint5; each reader accepts only its selected version. Checkpoint5 is the exact closed object `{schema_version, config, journal, positions, state}`. Only serialized VALUATION payloads replace their full `position` with `position_ref`; their complete `intent` is unchanged. The self-contained `positions` map holds each complete original Position checkpoint once under its existing canonical `position_evidence` digest. Every reference must resolve to that exact digest, every dictionary entry must be used, and inline/reference mixtures or unknown fields fail closed. No file lookup, mutable source query or alternate producer is introduced.

The in-memory journal, canonical commands, complete receipts, state, number of valuations and economics are unchanged. Restore bounds the exact weighted checkpoint4-equivalent expansion to the existing 16 MiB before hydration, then restores one complete original command at a time through the original reducers and Position source reader. It never retains another fully expanded journal. Checkpoint5 capture and candidate acceptance enforce the same expansion bound before commit. The exact byte count includes UTF-8, JSON escapes, delimiters, configuration and state; a private rebuildable journal-byte count reuses the original normalized command encoding, is updated only on an actual append and is neither persisted nor source authority. Dictionary decoding independently recomputes every original source digest and expansion size. Clone, candidate transitions, performance replay and restore retain their selected format. Existing checkpoint4 bytes/hashes and historical artifacts are not translated.

Execution configuration1 remains bound to checkpoint4. The explicit BACKTEST configuration2 binds `account_checkpoint_version: 5`; its genesis and every Account projection must use checkpoint5. The new encoded checkpoints change their own fingerprints and dependent Prepared/genesis/Trace identities under that explicit configuration and artifact. Original Command/Trade identities, immutable Strategy semantics and economic calculations are not redefined. Runtime frame and Evidence budgets remain unchanged.

### Exact forward Account checkpoint extension

`Manager::restore` retains arbitrary cold recovery from a fresh canonical owner and replays the complete original journal. The explicit `restore_exact_extension` instead accepts only a strictly longer journal with the same selected format and exact configuration, whose complete original commands have the current canonical owner's journal as an exact prefix. It verifies the incoming full digest, canonical bytes, closed fields and, for checkpoint5, every dictionary digest/reference, full use and the unchanged weighted 16 MiB expansion bound before processing commands. Prefix comparison includes the full original Position source bodies without hydrating another copy per repeated reference. Only the newly retained commands are replayed through the original Account reducers and producer readers on an independent candidate; new command IDs recording a semantic duplicate still require their original new receipt. A prefix change, truncation, absent extension, failed replay or any final full checkpoint byte/hash mismatch refuses atomically, without cold-restore fallback. Existing checkpoint4 safety-history limits are unchanged.

Execution selects this API only for an Account projection whose actual committed Prepared, configuration, sequence, installation order and exact current before-hash have already been proved. Arbitrary `Components::restore` continues to use ordinary cold Account recovery. Runtime checkpoint verification still independently starts at genesis and advances through the actual complete ordered source on each call; this API avoids re-executing commands already reconstructed earlier in that forward pass. It neither retains a cross-call source proof nor introduces another history, checkpoint format, producer, admission or authority.

`Manager::valuation_intents` borrows the original accepted valuation intents in full journal order. Both checkpoint formats retain the same complete canonical in-memory commands; this current read neither expands a dictionary nor encodes a checkpoint, copies a Position source, caches a proof or changes checkpoint bytes. Mutation and arbitrary recovery remain with the original owning APIs.

The private checkpoint codec memo reuses one successful canonical encoding of an unchanged Manager. Clones share immutable accepted journal commands and encoding bytes; their journal vectors and mutable state remain independent. Each accepted candidate starts a fresh encoding, including a newly retained semantic-duplicate receipt. Failure leaves the original owner and its bytes unchanged. Both original checkpoint formats, size checks and complete cold/extension readers remain authoritative; neither shared data nor an encoding supplies a Store/source/Ready proof.
