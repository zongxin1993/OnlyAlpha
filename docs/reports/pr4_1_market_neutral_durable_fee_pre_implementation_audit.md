# PR4.1 Market-Neutral Durable Fee Authority: Pre-Implementation Audit

- Audit date: 2026-08-05
- Branch: `master`
- Baseline commit: `6758eafcfc06286f88facd34315ba02bf413d849`
- Worktree before implementation: only the user-provided untracked task Prompt
- Environment: Windows, Python 3.12, `uv`

## Baseline evidence

| Command | Result |
|---|---|
| `uv sync --frozen --all-packages --all-groups` | PASS; 71 packages audited |
| `uv run python scripts/test_suite.py full` | PASS; Core 1354 passed / 2 skipped, plugin suites 34 + 18 + 31 passed |
| `uv run python scripts/test_suite.py recovery` | PASS; 229 passed |
| `uv run python scripts/test_suite.py ashare` | PASS; 22 passed |
| `uv build --all-packages` | PASS; Core and all three plugin sdists/wheels built |

The two skips reported by the pre-existing Full lane were not added or changed by PR4.1. Performance warnings are
non-failing baseline diagnostics.

## Required current-state answers

1. **Single fee calculation entry.** `OnlyFeeResolver` is the Runtime composition entry and delegates both estimates and
   fills to `OnlyFeeEngine`. The engine combines local schedules and broker-reported values into `OnlyFeeBreakdown` and
   creates `OnlyFeeInstruction`.
2. **Order estimate construction.** Both the Account cash-reservation adapter and Strategy Ledger cash-reservation adapter
   independently call `OnlyFeeResolver.estimate_order()`. The resolver derives notional from price, quantity and contract
   multiplier, resolves schedules for the current trading day, and returns one estimate whose expected and maximum values
   are identical.
3. **Synthetic Trade identity.** Yes. `estimate_order()` constructs `trade_id=f"estimate:{order.order_id}"` even though no
   Trade exists.
4. **Market/Broker resolution.** Market `DEFAULT` reads the compiled Market Profile schedule ID and resolves it by trading
   day; `MODEL` resolves an explicit registry ID. Broker `MODEL` resolves an explicit registry ID; `REPORTED` consumes a
   broker value inside the same local calculation request. Runtime configuration still installs Core built-in registries.
5. **Version freeze.** There is no Order Fee Policy Binding. All schedules are resolved again for each estimate/Fill trading
   day, so an order-fixed version is not frozen at acceptance or persisted in the Order Snapshot.
6. **Minimum scope.** Rules explicitly support `FILL` and `ORDER_CUMULATIVE`. The accrual reducer correctly applies the
   cumulative target minus charged-before for the latter, but the model lacks an order-fixed policy fingerprint.
7. **Accrual identity.** The current key is fee type, authority, source ID, schedule ID, schedule version and calculation
   scope. It omits rule ID/fingerprint, schedule fingerprint, resolution policy and economic direction.
8. **Raw amount.** Yes. Schedule calculation stores raw amount in the free-form component `metadata` mapping, and the
   accrual reducer parses it with a fallback to target amount.
9. **Downstream consumption.** The accrual reducer rewrites a target `OnlyFeeInstruction` into an incremental breakdown.
   Fee Manager, Account reducer, Strategy Ledger reducer, Settlement reducer and committed fact then consume that rewritten
   legacy instruction/total. They do not consume an explicit Fee Application contract and cannot represent rebates.
10. **External broker fee ingress.** `OnlyOrderFill.reported_fee` and `fee_reporting_mode` pass directly from Broker Update
    into `OnlyFeeResolver.resolve_trade()` and then into `OnlyFeeEngine`.
11. **Durable reconciliation.** No. `OnlyFeeReconciliationService` owns an in-memory reference set and returns a result and
    adjustment instruction. It does not prepare/commit/project a Runtime transaction.
12. **Can external data alter local results?** Yes. `ALL_IN`, `DETAILED` and `COMMISSION_ONLY` paths replace or combine local
    calculated components inside `OnlyFeeEngine` before the TRADE_FILL transaction is prepared.
13. **Checkpoint coverage.** The Runtime checkpoint includes Order fee accrual and Fee Manager authorities, but their schema
    preserves the legacy instruction, metadata raw amount and incomplete component identity. External evidence,
    reconciliation, adjustment and trading-block authorities do not exist.
14. **Artifact explainability.** No. Existing fee rows expose charged/accrued amount and schedule ID/version, but not formula,
    basis, rule fingerprint, rounding/pipeline, cumulative target, prior applied amount or current increment. Raw amount is
    not a first-class durable field.
15. **Interfaces that must be removed.** `OnlyFeeRateRule`, `OnlyFeeCalculationRequest`, `OnlyFeeInstruction`, legacy
    `OnlyFeeComponent`/`OnlyFeeBreakdown` application semantics, `OnlyFeeStatus.ADJUSTED/REVERSED`, fee configuration
    `DEFAULT/REPORTED`, `OnlyFeeAdjustmentInstruction`, `OnlyFeeReconciliationService/Result`,
    `OnlyOrderFeeAccrualExecutionState`, `OnlyOrderFeeAccrualExecutionProjection`, `OnlyFeeExecutionProjection`, built-in
    registry installers and schedule resolver aliases.
16. **Out of PR4.1 scope.** Formal CN A-share rates/product opening; real broker network/statement adapters; formal futures
    and crypto packs; margin/borrow/funding/periodic account fees; FX conversion; tax reporting; unrelated matching,
    MarketData, Event Gate and broker-account synchronization work.

## Authority and failure-boundary decision

- Runtime remains the sole mutable-state owner.
- Versioned Policy Packs and Order Bindings freeze local fee policy; Fee Engine is a pure target calculator.
- Order Fee Accrual is the only target-to-increment authority.
- Fee Application is the only TRADE_FILL fee command consumed by ledger/account/strategy/settlement/fact projections.
- Runtime Transaction Store is the durable authority for both TRADE_FILL and FEE_RECONCILIATION.
- External Fee Evidence is immutable input. It never edits a prior local Application.
- Reconciliation computes against local applications plus prior adjustments and creates a durable decision with an optional
  adjustment or risk gate transition.
- Any identity, currency, schema, precondition, policy-fingerprint or projection-state conflict fails closed before opening
  or before a new transaction is committed.
