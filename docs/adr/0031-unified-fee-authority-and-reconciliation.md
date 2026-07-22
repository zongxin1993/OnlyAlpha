# ADR 0031: Unified fee authority and reconciliation

Status: Accepted

## Context

Market, venue, regulator and clearing rules describe economic sources of fees.
Broker contracts and reports describe separate sources. Neither source is an
accounting mutation authority. Previously, Market Rules, the Virtual Broker and
the execution collector each represented fees independently.

## Decision

Fee schedules are immutable, versioned Market or Broker schedules. `OnlyFeeEngine`
is the sole resolver that combines schedules and normalized broker reports into
an immutable `OnlyFeeBreakdown`; it emits `OnlyFeeInstruction`. Only the
ExecutionProcessor's controlled transaction may apply this instruction to the
account, strategy ledger and fee facts.

Backtest and paper runs treat the resolved model as confirmed. Live runs use a
local provisional model until a broker report or statement confirms it. A broker
report is explicitly classified as NONE, COMMISSION_ONLY, DETAILED, ALL_IN or
DEFERRED_STATEMENT. In particular, ALL_IN reports are never combined again with
market components.

Historical fee facts are immutable. A difference creates an
`OnlyFeeAdjustmentInstruction` whose amount is exactly reported minus prior
amount. The reconciliation service records matching, duplicate, incomplete,
explainable adjustment and blocking/unexplained outcomes. A material unknown
difference blocks new risk-increasing orders; it does not create an `OTHER`
fee to force balances to agree.

Every component records source and schedule identity/version/fingerprint; the
result/artifact projection must retain instructions, adjustments,
reconciliations and schedule timelines.

### Product assembly

The product path is explicit and contains no fee singleton or implicit broker default:

```text
OnlyClusterRunConfig.market.fees / brokers[].fees
→ OnlyBacktestRuntimeFactory
→ OnlyFeeResolverConfig + market/broker schedule registries
→ OnlyRuntimeAssemblyConfig
→ OnlyBacktestRuntime
→ one Runtime-owned OnlyFeeResolver
```

`market.fees.mode=DEFAULT` resolves the compiled Market Profile schedule for the instrument and trading day. `MODEL`
resolves the configured immutable schedule ID; `NONE` disables that authority. Broker fees must select `NONE`, `MODEL`,
or `REPORTED` explicitly: Core does not invent a default broker contract. Missing and overlapping schedule versions fail
during assembly, before Runtime execution.

## Consequences

* `NONE` is an intentional disabled source. It is distinct from a MODEL whose
  rate happens to be zero; absent configuration resolves explicitly to DEFAULT.
* Broker plugins provide normalized external evidence only and do not import or
  mutate Runtime account/ledger/collector state.
* Virtual Broker fills report `reported_fee=None` with reporting mode `NONE`; its account store is an external snapshot
  projection and intentionally does not include Runtime-resolved fees.
* Account reconciliation can explain an exact cash difference through an
  immutable fee adjustment, but cannot overwrite local account history.
* The old `fill.fee`/fixed-commission runtime truth path must be removed in the
  same release as the ExecutionProcessor migration; retaining it would preserve
  two accounting authorities.

## Rejected alternatives

* Treating a broker fill fee as the universal final fee: fails in backtest and
  loses source/reporting-mode semantics.
* Letting AccountManager or StrategyLedgerManager recalculate fees: violates
  single-writer ownership and makes replay non-deterministic.
* Overwriting a prior fee with a broker statement: destroys audit history.
* Folding all broker reports into market fees: double-counts ALL_IN reports.
