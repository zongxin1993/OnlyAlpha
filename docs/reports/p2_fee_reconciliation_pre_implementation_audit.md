# P2 Fee Reconciliation Semantic Closure — Pre-Implementation Audit

Date: 2026-08-09

## Baseline

Prompt baseline, local `master`, and development HEAD are identical:
`3a53ebe464d40c2bf77b4f57bdbd4aefde858049` (`Feat: Fee Authority Integrity Closure`).
The only pre-existing worktree item is the untracked task Prompt.

## Current authorities and ingress

Local immutable fee facts are `OnlyFeeApplicationRecord` rows owned by the
Runtime fee ledger. External facts are `OnlyExternalFeeEvidence`, but their scope
is represented by an enum plus three nullable fields and statement scope is an
untyped string. `OnlyBacktestRuntime.reconcile_external_fee()` accepts caller-owned
`reason` and `materiality_threshold`, scans all fee rows itself, and treats any
statement as account-wide.

The pure planner receives local component rows but reduces DETAILED evidence to
one total. Previous adjustments are one aggregate `OnlyMoney`; an adjustment has
no component identity. Evidence identity distinguishes duplicate and same-version
conflict but has no evidence-family identity, ordered revision, or predecessor.

## Decision, projection, and persistence

The existing durable operation and ordered chain are sound and remain the path to
reuse: EXTERNAL_FEE_EVIDENCE, FEE_RECONCILIATION, FEE_ADJUSTMENT_LEDGER, ACCOUNT,
STRATEGY_LEDGER or UNALLOCATED_EXTERNAL_FEE, then RECONCILIATION_RISK_GATE. The
Transaction Store is durable authority and projection ledgers provide idempotence.
The generic transaction envelope need not change; evidence, decision, adjustment,
fee-ledger and risk-gate payload schemas do.

`OnlyFeeReconciliationRiskGateState` persists a redundant boolean and one evidence
ID/reconciliation ID. Transaction planning clears that blocker after any MATCHED
or adjusted evidence, even when unrelated. The gate imports order side/offset and
hard-codes SELL+CLOSE as reducing risk.

## Current recovery semantics and tests

Fee reconciliation already has projection codec, checkpoint, real projection
target, and fail-after-each-projection tests. They cover one adjustment and one
blocker only. Missing cases are revision forward correction, component attribution,
multiple blockers, unrelated evidence, exact statement periods, and stable
component ordering.

## Interfaces and schemas to delete

- Caller-owned `reconcile_external_fee(reason, materiality_threshold)`.
- Enum plus nullable scope fields and `statement_scope: str`.
- Aggregate-only prior adjustment and DETAILED planning.
- Single blocker state and clear-on-any-match transition.
- Fee-gate BUY/SELL and offset interpretation.
- Evidence schema 1, decision/fact schema 1, adjustment schema 1, reconciliation
  authority checkpoint schema 1, risk-gate checkpoint schema 1, and fee-ledger
  checkpoint schema 3.

Old schemas will be rejected without an implicit migration.

## Authority answers

- Runtime owns every mutable ledger, policy selection, evidence authority, gate,
  account and strategy ledger.
- External callers may submit normalized evidence only.
- A typed local-fact query exclusively determines fee rows covered by a scope.
- A pure planner classifies component differences under a versioned policy.
- The transaction planner plans state transitions; projections install them.
- Broker adapters normalize provider fields and never mutate Runtime managers.
- Failure occurs at schema, account/broker/currency validation, exact local query,
  policy resolution, planning, durable commit, or ordered projection.
- Restart must equal uninterrupted execution in evidence lineage, component
  adjustments, account/strategy effects, unallocated facts, and active blockers.
