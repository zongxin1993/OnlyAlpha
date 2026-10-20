# Rust Runtime Ledger Reconciliation

## Ownership and public boundary

Runtime Ledger Reconciliation is a read-only logical module in `crates/onlyalpha-kernel/execution/src/reconciliation.rs`. It checks the existing single Account against every configured Fixed Capital Cluster Ledger. Account remains the consolidated cash/equity owner, Position owns cost and Allocation, each Ledger owns Cluster attribution, Fee owns application economics, and Store/Ready owns committed visibility. No new crate, durable writer, accounting correction, provider policy or automatic balancing is introduced.

`Components::reconcile<S: Store>(&self, store: &S) -> Result<LedgerReconciliation, Error>` is the public owning query. The caller cannot submit raw snapshots, a hand-selected subset of Clusters or authored derived results. `LedgerReconciliation` has private fields and only detached `record()` and canonical `encode()` reads; no public derived-result constructor/decoder/writer exists. Its semantic identity is `RUNTIME_LEDGER_RECONCILIATION@1`. A changed reconciliation meaning requires an explicit semantic change; release numbers do not substitute for Kernel artifact identity.

## Complete source predicate

The query requires no pending projection prefix, exact current Store head, and a complete contiguous Ready lineage from configured genesis through the applied head. It reuses the existing owning Ready guard and scans the captured records one at a time, checking every predecessor/result hash against the current full owner checkpoint hashes. The complete Execution transaction index must bind each input-derived transaction identity to that occurrence: rehashing a changed input while retaining identical projections does not establish the same cause.

Engine, Runtime, Account, Gateway, Generation, Runtime kind, currency, configuration and configured Cluster universe retain exact identity. Owner configurations and Account snapshot scope must match, capital configuration must agree, and every configured Cluster (including zero capital and no Trades) must be present exactly once. Genesis is a complete initial owner with one or more configured Ledgers, not evidence-free absence. Missing fields, invalid scope, unavailable Store, stale owner, missing history, unready tail and partially installed projection are errors; none can become a zero amount, an omitted Cluster or MATCHED.

Hashes establish integrity and exact membership in this owning composition, not external producer authentication. Store drivers retain their existing exact immutable-record contract. This component does not establish formal Runtime artifact admission or authenticate an arbitrary external Store.

## Economic and relationship checks

Seven exact comparisons are required: initial equity, ledger cash, position market value, realized PnL, unrealized PnL, fees and equity. Decimal strings retain exact analytical residuals; no float, tolerance, currency conversion or re-rounding is introduced. Aggregate differences carry field, Account value, summed Ledger value, signed Account-minus-Ledger difference and all participating Cluster IDs.

Complete Ready Fill inputs are replayed through the existing canonical Fee producer. Cumulative Order targets are never mistaken for per-Trade fee deltas. The resulting Fee checkpoint must equal the current owning Fee checkpoint exactly; unsupported/omitted Fee history is unavailable rather than a successful comparison. Committed charges minus rebates must independently equal Account fees and Ledger aggregate fees: two accounting projections jointly omitting an amount cannot certify each other.

The full union of committed Trade applications, Account Trade journal entries and applied-Trade index, Ledger Trade ownership and every Ledger fee entry is checked. Per-Trade Cluster, Order, fee instruction, charges and rebates must agree. Missing, extra, orphan, duplicated and cross-Cluster entries are differences even when net totals match. Separate charges/rebates cannot be offset to hide a different application. A zero-fee Trade still requires Account and Ledger Trade ownership; the current Ledger producer emits no fee entry when both components are zero. Explicit positive charges with equal rebates still require their real application entry.

The current Execution contract admits Fill Fee applications, not a separate Fee Adjustment transaction. Such unsupported Account Fee history or a different Fee producer history cannot be silently excluded. Future adjustment transaction admission must extend its owning Execution contract and this complete relation together. External Broker reconciliation and Fee policy/evidence reconciliation remain their existing distinct responsibilities.

## Outcomes and immutable diagnostics

A complete matching source returns `MATCHED`. A complete source with economic or attribution differences returns `MISMATCHED`; it never mutates Account, Ledger, Position, Fee, Margin, holds, cash/fee entries, Store, Ready or Events. Evidence that cannot support a conclusion returns an explicit error. MATCHED is an accounting diagnostic, not execution permission, external Broker equality, owner lifecycle ACTIVE, Backtest success or Runtime READY authorization. UNKNOWN orders can retain holds while complete internal ledgers match.

Schema1 output binds scope, sorted Cluster IDs, exact configuration hash, current sequence, explicit last committed input time, head transaction/payload hash, and all six full owner checkpoint hashes. Genesis time/head are null; there is no wall-clock read or implicit latest source. `totals` exposes all seven comparisons. Ordered differences use AGGREGATE, COMMITTED_FEES or TRADE_FEE rows with the relevant values and identities. The content-derived RLR identity binds the entire record before its id field. Queries over the same exact source, including new-process replay, return the same canonical bytes. A returned JSON copy cannot mutate the result or any owner.

Account marks consolidated quantity once per Instrument, while Clusters mark their own Allocation quantities. A real per-owner HALF_EVEN difference remains MISMATCHED. For example, two Cluster market values of 9.98 total 19.96 while consolidated market value is 19.97; no cent is silently allocated, ignored or moved into a balancing account. ADR0034's final Backtest mismatch behavior remains unchanged. This task does not introduce an intermediate valuation-barrier trading gate.

## Reference and admission boundary

Python `src/onlyalpha/runtime/reconciliation.py` is the audited economic comparison reference. Its Backtest final seal and post-recovery validation are existing consumers, not Rust activation targets. It validates Runtime/Account/currency and seven aggregate fields plus expected Trade net-fee attribution, but has no independently configured full Cluster universe, explicit duplicate-Ledger proof or complete unexpected-entry/charges/rebates relation check. These are classified reference limitations, not expected native behavior. The recovery caller's initial-equity fallback is not a native input rule.

Shared independent vectors are at `test-data/execution/reconciliation-v1.jsonl`. The real native owning query is compared in Debug and Release against the literals; the actual Python service consumes controlled frozen public snapshots on its common subset. Native exact fractional residuals and stronger source/relationship guards are independently tested and are not falsely claimed as Python parity. Direct fixture comparison is technical evidence, not Shipping Web acceptance or a real account/deployment certificate.

This isolated diagnostic does not activate the official Rust Runtime, seal a formal Rust Backtest, retire Python, translate official history, certify service upgrade/restart, add FX/funding/liquidation or authorize LIVE. Future Backtest final seal/recovery admission must consume the exact source-bound result through its formal owning Runtime boundary; a matching local report alone cannot waive R3–R8.

Engineering evidence is advisory. [Nautilus #5000](https://github.com/nautechsystems/nautilus_trader/issues/5000) motivates complete-input and omitted-fact tests. [Nautilus #3622](https://github.com/nautechsystems/nautilus_trader/issues/3622) motivates explicit unresolved-difference diagnostics rather than retry/repair masquerading as convergence. Neither venue-state reset, inferred fills, retry policy nor upstream tolerance is adopted.
