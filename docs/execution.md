# Execution Authority

The durable Trade chain is `Broker Update → immutable Prepared Transaction → Runtime Persistence Store → ordered Projection →
Projection Ready → durable Outbox`. Each Fill is an independent transaction; the Order is the cumulative authority.

PR4.3.2 opens Generic T0 Cash LIMIT BUY OPEN partial-fill accounting. Order alone determines terminal Fill; Position/Allocation
retain exact cumulative cost; independent Order Fee Accrual converts cumulative fee targets into Fill deltas; cash and Risk
reservations consume incrementally; Account, Strategy Ledger and Risk receive explicit deltas. Each Fill remains one immutable,
Projection Ready transaction with a contiguous per-Order Fill index. Duplicate Fill identity is idempotent and conflicting payload
fails before authority mutation. See ADR 0049, ADR 0050 and `execution_trade_planning.md`.

PR4.3.3 adds the plugin-owned deterministic Virtual Broker Fill Plan and complete Generic T0 Cash LIMIT BUY OPEN Multi-Fill
Recovery. WHOLE, legacy MAX_PER_BAR and explicit SCHEDULE share one execution chain; ONE_PER_BAR and ALL_DUE produce one
independent immutable Runtime transaction per Step. Broker execute-before-publish, Commit, Projection, Outbox and partial-plan
checkpoint boundaries recover through the existing phases. The same Fill Plan is now also proven for Long Close.

PR4.4.2 completes the deliberately narrow Close slice in that same chain: `GENERIC_T0_CASH + LIMIT + SELL + CLOSE + LONG +
NETTING`, cash account, one currency and Margin disabled. Every partial or final Fill is an independent transaction. The Planner captures existing Position, Allocation,
Position Reservation, Risk Reservation, Account, Strategy Ledger, fee, settlement and valuation authority before producing one
immutable transaction. Its projection order is Order, Position, Allocation, Settlement, Order Fee Accrual, Fee, Account,
Strategy Ledger, Position Reservation, Risk Reservation, Risk and Valuation. Removed non-durable execution source is absent;
unsupported shapes fail closed.

Position is the single realized-PnL authority: `(fill price × fill quantity - exact released cost) × multiplier`. Position and
Allocation use one cumulative-cost reducer; partial fills release `cumulative cost × fill quantity / quantity before`, while the
final Fill releases every remaining cost unit and sets cumulative cost exactly to zero. Allocation, Account, Strategy Ledger and
committed fact consume that exact delta. Gross cash inflow is sale notional,
net cash inflow is notional less the authoritative Fee instruction. Close carries no cash Reservation; its Position Reservation
is consumed inside the same ordered projection batch. Existing Fill identity/index, Coordinator, recovery phases, Event Gate and
at-least-once Outbox semantics are unchanged. Partial Fill Cancel/Reject/Expire uses an `ORDER_TERMINAL` transaction with stable
`ETERM-...` identity, no Trade ID and four ordered projections. Same identity/same payload is idempotent; a conflicting payload
fails closed. Terminal Facts are excluded from Trade Results. Short, Hedging, CloseToday/CloseYesterday, Futures/Margin and
SIM/Live products remain outside this implemented Backtest scope. SIM 的相同经济 shape 由共享 Trading Kernel 和独立 streaming
product tests 证明；Live 仍是未来目标。See ADR 0053 and ADR 0068.
# Attributed Close Cost

`OnlyTradeExecutionTransactionPlanner` 在 reducer 前创建 `OnlyAttributedCloseCostAuthority`。只有 builder 调用平均成本归约函数；Position 和 Allocation reducer 安装 Authority 给出的 after state，不再独立计算 released cost 或 PnL。缺失 Allocation、scope 冲突、数量不足或 Position 成本无法由 Allocation 聚合解释时，在 commit 前 fail closed。

## Rust component execution boundary

`crates/onlyalpha-kernel/execution/` composes the isolated Order, Position, Account, Strategy Ledger and Risk libraries through public immutable inputs and their canonical checkpoint/restore readers. Domain is the only additional local dependency. This library is not an activated Runtime participant, second production persistence store or LIVE permission.

The bounded shape is single-currency Generic T0 Cash LIMIT BUY OPEN / SELL CLOSE LONG NETTING, including admission, explicit submission outcome, external acceptance, pending cancellation, partial/full fills and terminal cancellation/rejection/expiry/failure. Explicit scoped plugin fee cumulative targets produce incremental cash charges/rebates; settlement requires a proved Generic T0 cash/settled-quantity instruction. No missing fee, market permission or settlement is interpreted as zero/available. Position remains the single attributed close-cost authority, including fractional proportional cost and the final all-remainder rule. Non-cash cost/PnL preserves exact admitted precision; currency settlement amounts retain their owning money precision.

Prepared payloads lock complete before/result component identities and exact immutable result checkpoints, including receipts/indexes. An opaque planner-produced value is required for a new commit. Decoded transport values can only recover an already committed exact Store record; a digest is integrity proof, not producer authentication. Source admission/authentication remains the future official Runtime adapter's responsibility. Replayed frozen component commands validate component state without rerunning Execution Planner, fee schedules, market rules or mutable queries.

The Store port is the sole durable execution authority: atomically commit Prepared + pending Events, verify the immediate predecessor Ready, install ordered component results, durably mark Ready, then expose business/outbox results. Public technical projection installation requires the exact owning Store record; completion requires its observed Ready state. Events have stable identity and at-least-once delivery. Applied progress is a rebuildable index. Failure retains the installed prefix, blocks new plans and proceeds by forward recovery; no cross-component rollback, blind UNKNOWN retry or alternate order identity is introduced.

New-risk history budgets cannot block accepted observations, fills, cancellations, releases or proved close. Extended safety history remains complete and fresh-reader recoverable. These admission ceilings are not physical storage quotas; the official durable owner still needs storage pressure handling. Actual-file test adapter reopen evidence is technical library evidence, not official Runtime startup, Shipping UI or deployment-upgrade certification. See the [design](superpowers/specs/2026-10-19-rust-execution-design.md) and existing migration gates.

Rust Prepared schema1 is an isolated comparison representation with ordered atomic component groups: Order, Position+Allocation+sell hold, Account+cash holds, Strategy Ledger+cash holds, Risk, then Execution fee/settlement/identity metadata. The full committed payload binds every result before installation; all prefixes remain non-business-visible. It is not Python Prepared schema4, does not decode that wire format, and does not change the existing formal Runtime projection order. Official admission must resolve the owning integration/public-contract and history gates atomically; this library introduces no adapter or compatibility fallback.

Position alone maintains exact cumulative realized PnL per Allocation cycle and emits the difference between successive half-even currency targets. Consumers retain an explicit residual from exact cost, authoritative settlement and Money realized deltas; Ledger PnL equity includes that independently accumulated residual. This preserves each final currency remainder without recalculating Position cost in Account/Ledger. Allocation inputs carry exact identity, cycle, result version and exact/Money realized state; a new cycle cannot erase lifetime ledger PnL or reuse an old identity. The Python per-Fill rounding path is a classified reference deviation on fractional residual cases; correct common integral vectors remain comparable.

Position, Account and Strategy Ledger isolated checkpoint bodies use schema2 for these new mandatory semantic fields. Schema1 is explicitly rejected, with no automatic reinterpretation. These components have no admitted official Rust Runtime writer or production history migration in this task; the existing Python Runtime persistence format/readers are untouched, and the previous exact implementation remains in Git/artifact provenance. This is not an existing-history upgrade certification.

Generic T0 monetary inputs explicitly bind currency, resolved notional and HALF_EVEN settlement rounding. Position retains raw price-times-quantity cost. Ledger accumulates settlement-versus-cost/realized rounding residual from validated trade deltas; Account consumes the sum of those owning residuals. The residual is not inferred from the equity equation. Full Ready-prefix causal hashes must connect genesis to the current projection before query, admission or completed recovery.

Market and valuation source references identify immutable evidence occurrences within their respective family. Reuse for a new request, watermark or payload is rejected. Positive quantity/exact gross can resolve to zero currency settlement; this does not make the Fill absent or waive price/quantity/settlement proof.

Rust cash Settlement now consumes explicit Calendar/policy input and owns registration plus `SETTLEMENT_MATURITY` through the existing coordinator; metadata schema5 replaces the former settlement alias-only map. See [Settlement](settlement_model.md#rust-settlement-responsibility-and-admission-boundary) for supported economic shapes, preserved resource bounds and deferred activation/history gates.


Native metadata schema5 includes the Margin owner. Explicit collateral declarations join ADMIT/FILL/TERMINAL atomically; UNKNOWN/cancel request do not release, actual closing Trade relations determine lifecycle-bound release. The existing six projection groups and Store authority remain. See [Margin](margin_model.md#rust-margin-responsibility-and-consumer-boundary) for capability and source-admission boundaries.

`VALUATION` freezes a complete current Position source and explicit mark facts in one no-Fill transaction, updates Account via opaque source-derived effects, and revalues all Cluster Ledgers against their own complete Allocation relation. Account checkpoint schema4 and Execution metadata schema5 reject raw/old shapes without fallback. See [Valuation](valuation.md). No Runtime activation or business-history migration is implied.

## Rust Runtime Ledger Reconciliation

The source-bound read-only query `Components::reconcile` consumes the exact current complete Ready prefix and all configured Account/Cluster owners. It replays the canonical Fee producer from committed Fill inputs, checks aggregate economics plus complete Trade attribution, and returns immutable diagnostics without writing any owner. See [the owning Contract](runtime_ledger_reconciliation.md). A matching diagnostic does not grant Runtime/LIVE admission or silently absorb per-owner rounding differences.

Account-authoritative [Runtime Portfolio Performance](runtime_portfolio_performance.md) uses the same complete Ready source guard and reconstructs its immutable timeline through the Account owner, without a new writer or Runtime/Backtest activation.
