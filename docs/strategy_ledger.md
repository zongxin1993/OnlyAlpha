# Strategy Ledger：策略资金、收益与净值

## 1. 边界与所有权

每个 Trading Runtime 独占一个 `OnlyStrategyLedgerManager`，每个 Cluster 按
`RuntimeId / AccountId / ClusterId / BaseCurrency` 拥有独立 Ledger。券商账户是真实现金和合并持仓的外部事实；Strategy
Ledger 是策略虚拟账，不修改券商现金，也不把账户合并均价或账户总收益按比例分摊给策略。

Research Runtime 不拥有 Strategy Ledger；Research Job 的收益或资金曲线属于 immutable Research Result，不构成 Cluster
资本归因或正式交易账务。

第一版只实现 Fixed Capital、单 Account、单币种、Long-only 股票/ETF、Average Cost Allocation 和 Linear PnL。它不实现
Shared Pool、动态资本再分配、多币种换汇、融资、分红、System Ledger 或策略间资金转移。

## 2. Capital、Cash 与 Fee Ledger

资本属于 Cluster 配置。单 Cluster 可省略 capital 并严格取 Account initial cash；多 Cluster 必须分别显式声明
`FIXED_CAPITAL`，币种与 Account Base Currency 相同、金额非负且总和严格等于 Account initial cash。不存在 Runtime 默认
Strategy capital、自动平均、剩余资金回退或旧字段双读。初始资金、外部现金流和交易现金流分开保存。Cash Entry 覆盖初始分配、预占/释放、买卖结算、费用和人工调整；
Fee Entry 按稳定 ID、类型、Trade/Order 和 UTC 时间独立记录，费用不混入持仓均价。

买单在送往 Execution Port 前建立 Strategy Cash Reservation。`cash_available = cash_balance - active_reserved`，连续订单同步
看到最新预占；重复预占幂等，成交按实际成交额与费用消费，拒单、失败、过期或取消后释放。超出预占只在剩余可用现金足够时
允许，底层永远拒绝负现金。卖单不预占现金，仓位预占仍由 Position 组件负责。

## 3. Trade Accounting 与 Position Allocation

成交更新顺序是 Execution 标准化 Trade → Account Position → Cluster Position Allocation → Strategy Ledger。Ledger 输入必须
携带 Allocation before/after、已实现收益增量、成本增量、Fee Entries 和买单 Cash Reservation。Manager 从 Allocation
边界重新验证收益及成本增量，不能接收账户平均成本或自行维护另一套持仓成本。

买入 `cash -= notional + fee`；卖出 `cash += notional - fee`。Realized PnL 是 Allocation realized 的前后差；Unrealized
PnL 和 Position Market Value 由 `OnlyStrategyValuationService` 使用该 Cluster 的 Allocation、Mark Price 和 Multiplier
生成。无法归因的 Position 仍属于 Position `Unallocated`，不会进入普通策略 Ledger。

Generic T0 Cash multi-fill Long Close 的每个 Ledger Projection 与 Account Projection 位于同一 durable transaction。Ledger
追加一笔 SELL_SETTLEMENT cash entry 和一笔增量 FEE cash/fee entry，不创建现金 Reservation；其 realized-PnL delta 直接
使用 Position reducer 的唯一结果，并与 Allocation/Account/Committed Fact 保持相等。Terminal Cancel/Reject/Expire 不生成
Ledger Projection，已成交 Fill 的账务事实保持不变。

## 4. Equity、Return 与 Drawdown

```text
Cash View = cash_balance + position_market_value
PnL View  = initial_capital + external_cash_flow + realized_pnl + unrealized_pnl - fees
Cash View == PnL View
```

不一致时 Ledger 进入 `RECONCILING` 并携带 `EQUITY_VIEW_MISMATCH`，Risk 默认禁止新订单；恢复一致后才回到 ACTIVE。
`net_pnl = realized + unrealized - fees`。没有外部现金流且初始资金大于零时提供 Simple Return；发生外部现金流后第一版返回
None，避免伪装成 TWR/MWR。High Water Mark 单调不降，Drawdown 与 Maximum Drawdown 均使用非正 Rate。

Trading Day 由 Runtime Calendar 提供；切换时锁定 day-start equity，用于 Daily PnL/Return，绝不以 UTC 日期猜测交易日。

## 5. Snapshot、Context、Risk 与 Scope

所有 Query 返回 frozen Snapshot。`ctx.ledger` 绑定当前 Runtime/Account/Cluster，只提供 snapshot、cash、PnL、equity、
return 和 drawdown 属性，没有 reserve/apply/deposit/reset 等修改入口。Risk Context 接入 `OnlyStrategyLedgerRiskView`，可读
资金、净值、日收益、回撤和状态；非 ACTIVE 状态 Fail Closed。

所有生产调用方通过 `OnlyStrategyLedgerLocator` 使用完整的
`RuntimeId / AccountId / ClusterId / BaseCurrency` scope 定位。Manager 创建时维护唯一 scope index；仅凭 Cluster ID 的
`get_by_cluster` / `by_cluster` 接口已删除。每次保存 Ledger Snapshot 同时追加不可变 Equity Point，显式 sequence 使同时间戳
变化仍可审计，并为 Cluster Return、Drawdown 和 valuation count 提供唯一证据。

## 6. 幂等、事件、Repository 与 Replay

Trade 按 trade/execution/venue trade ID 去重，Fee、Cash Flow、Reservation 和 Valuation 各自按稳定 ID/version 去重。稳定顺序
为 external sequence → event time → trade ID；迟到 Trade 进入 RECONCILING，第一版不静默重算历史。

Manager 先完成状态修改和持久化，再发布事实 Event。内存 Repository 保存 Snapshot、Cash/Fee Entry、Reservation 和 Event，
不暴露实体。Replay Entry 保存连续序号、操作类型和无损 JSON command；Replay Service 从初始资金重新执行命令，不恢复可变
实体。Money/Decimal 不转换为 float。第一版并发约束为 Trading Runtime 单写入者；Gateway 线程和 Cluster 都不能直接修改 Ledger。

## 7. Demo 与限制

对应 tests 覆盖 Ledger 场景。当前胜负统计按 realized delta 更新，尚未建立 Closed Position Result，因此不把
每个 Fill 宣称为完整交易；Backtest Runtime 已通过 Runtime Transaction Store、ordered Projection 与 checkpoint/forward
recovery 完成标准化 Fill 到 Ledger 的 durable 纵切面。目标 Sim/Live 的 streaming recovery 与 Live 真实券商同步仍待后续阶段。

Processor 调用 Trade Accounting 时延后 Strategy Cash Reservation 消费：Ledger 先验证 Reservation 身份并完成 Allocation-
authoritative accounting，Account 更新后再由 Processor 按实际 notional+fee 统一消费。Ledger 独立调用仍保持原有默认原子语义。
## 与 Account 的边界

Strategy Ledger 继续按 Cluster 记录固定初始资金、Allocation 成本、费用和 PnL；AccountManager 记录同一 Runtime 账户的合并
现金与权益。多个 Ledger 可以共享一个 Account，但不能读取或复用 Account/Virtual Broker 内部对象。Runtime 对同一 Fill
分别投递强类型 accounting input，账户合并成本不得反向污染 Cluster 归因。

回测结束时 `OnlyRuntimeLedgerReconciliationService` 验证初始资本、现金、持仓市值、已实现/未实现 PnL、费用和权益的
Account 值等于所有 Cluster Ledger 加总，并用 Committed Execution 核对逐 Trade fee 的 Cluster 归属。差异形成结构化结果，
Backtest 标记失败，服务不会修改 Account 或任一 Ledger。当前只正式执行最终 barrier 对账；逐估值 barrier 对账尚未实现。
# Close PnL 与全局序列

Strategy Ledger 不重算 Close PnL，只消费 attributed delta。各 Ledger 的 equity timeline 使用 Runtime 全局 sequence；checkpoint 按该 sequence 排序并完整恢复，避免多 Cluster 分组序列化造成冲突。

## Rust component ownership and recovery boundary

`crates/onlyalpha-kernel/strategy_ledger/` is one independently buildable virtual-account library with Domain as its only local dependency. One Manager binds exact Engine/Runtime/Account/Generation/currency and explicitly configured Cluster capital whose sum equals Account initial cash. Config, commands and checkpoints are closed schema1 values. Runtime remains Python; this library does not activate another formal writer.

Rust validates normalized Allocation before/after, exact attributed cost and realized deltas, per-Cluster ownership and valuation completeness. It never reconstructs cost from average price or uses consolidated Account cost. Marks/multipliers and Runtime calendar day/ordinal are explicit inputs. Trade/fee/order/reservation aliases bind full normalized payloads and exact Cluster. Rejections/conflicts cannot mutate accepted state. A candidate updates economics, cash/fee entries, holds and global equity occurrence together.

Rust CASH BUY reservations consume gross notional plus charges; rebates credit cash separately. Its standalone boundary rejects consumption exceeding the exact hold, instead of the older direct Manager's free-cash overrun behavior. Partial fills retain positive remaining authority, terminality is supplied by Order, UNKNOWN retains holds, and a Fill proves sent. This conservative component restriction must be resolved with owning Execution admission before official activation; it is not a claim that all external fills can be discarded. Valid fills and safe releases continue under stale-observation blocks. No provider settlement/margin policy is inferred.

Cash/PnL equity views are compared exactly. Returns after external flows are absent rather than labeled TWR; drawdown ratios round HALF_EVEN at precision8. Global runtime sequence keeps distinct equal-time Cluster points. Calendar identity/ordinal cannot regress. Daily return remains absent for the entire day after any external-flow occurrence, even when flows offset; only an explicit new day resets that occurrence flag. Accepted stale Trade observations retain Order ownership across restore, while only economically applied Trades may authorize linked fee adjustments. Complete checkpoint replay verifies receipts, financial entries, Allocation lines, holds, flags, timeline and config before atomic replacement; hashes are integrity evidence, not producer authentication.

The Python direct Manager's ID-only dedup and reservation-before-validation paths are classified reference defects. The real valuation service uses exact cumulative Allocation cost, while some Trade reducer paths still use rounded average for unrealized. Independent literal vectors compare real Python Ledger/Allocation/Valuation with native Rust on the supported subset; adversarial Rust tests retain stricter identity/atomicity/UNKNOWN/fee-rebate requirements. No broad Python repair is implied. See [design](superpowers/specs/2026-10-19-rust-strategy-ledger-design.md).

Producer proof, Account/Position/Order/Fee/Ledger durable atomic composition, aggregate reconciliation, service restart/upgrade and business-history migration remain Execution/Infrastructure admission responsibilities. Component replay does not certify those gates, Shipping UI, SIM/LIVE or other platforms. Reports/closed-trade statistics and market-dependent rules remain outside this stable ledger owner.

The Rust Execution composition evolves this isolated component's checkpoint body to schema2; it does not activate a writer or change official Python Runtime persistence. New semantic fields are mandatory and schema1 has no implicit fallback. New-risk admission budgets are distinct from complete safety history; existing observations/fills/releases and proved reduction retain complete replayable history beyond admission ceilings. See the [Execution boundary](execution.md#rust-component-execution-boundary) for cumulative Position PnL, explicit rounding residuals and exact Allocation cycle/identity inputs.

Generic T0 monetary inputs explicitly bind currency, resolved notional and HALF_EVEN settlement rounding. Position retains raw price-times-quantity cost. Ledger accumulates settlement-versus-cost/realized rounding residual from validated trade deltas; Account consumes the sum of those owning residuals. The residual is not inferred from the equity equation. Full Ready-prefix causal hashes must connect genesis to the current projection before query, admission or completed recovery.

Rust `SETTLEMENT` consumes an exact owning Allocation before/after witness and unique maturity identity. Only a +1 version/evidence change with unchanged identity, cycle, quantity, cost and realized fields is accepted; cash, fees, PnL, economic and valuation versions remain unchanged. This preserves the next Trade's exact before-state guard after Settlement advances the Position allocation.

Native final-barrier reconciliation is the read-only [Runtime Ledger Reconciliation](runtime_ledger_reconciliation.md) responsibility in Execution. It checks the entire configured Cluster universe and committed Fee relation; missing evidence never proves zero, and exact per-owner rounding differences remain explicit mismatches. Formal Runtime activation and business acceptance remain separate gates.

Ledger return/drawdown quantization uses exact integer quotient/remainder and one precision8 HALF_EVEN boundary, including coefficients large enough to exceed a decimal library default division context. Result consumers reuse these owning values. Nonpositive return bases stay unavailable and the existing zero-high-water Ledger drawdown policy remains zero; this does not substitute that policy for Account performance. A historically incorrect derived rate does not become current proof merely by recomputing a checkpoint digest: restore still verifies exact owning replay. The rate correction changes affected derived bytes, not the checkpoint format, and does not certify old-artifact history migration or official Runtime admission.
