# P2 Fee Reconciliation Semantic Closure — Implementation Report

Date: 2026-08-09

## Baseline

The Prompt baseline, local `master`, and implementation baseline are identical:
`3a53ebe464d40c2bf77b4f57bdbd4aefde858049`
(`Feat: Fee Authority Integrity Closure`). The pre-existing untracked Prompt was
read as the execution contract and was not modified.

## Before Architecture

Before P2, external fee evidence was compared as an aggregate against local fee
applications. Runtime callers supplied the materiality threshold and classified
the reason, statement scope was an untyped string with account-wide selection,
DETAILED evidence still collapsed to a total, and prior adjustments had no fee
component attribution. Evidence versions had duplicate/conflict checks but no
ordered lineage. Risk state stored one redundant boolean and one blocker, and any
later match could clear it. The fee gate itself interpreted SELL+CLOSE.

The existing generic durable transaction envelope, Transaction Store, projection
ledger, and ordered FEE_RECONCILIATION chain were already the correct authorities
and were retained.

## Root Problems

- Reconciliation governance was caller input rather than a versioned authority.
- Evidence could not prove a single legal trade, order, or statement scope.
- Equal aggregate totals could conceal different fee components.
- Statement local-fact selection lacked an economic time authority and bounded query.
- Aggregate prior adjustments could offset the wrong component.
- Revised reports could not prove predecessor or compute a forward correction.
- A single account blocker was neither attributable nor safely resolvable.
- Fee code duplicated order-direction semantics owned by Risk and Position.
- Broker/account/contract/currency validation and normalized broker ingress were incomplete.

## Deleted Interfaces

- Deleted `OnlyBacktestRuntime.reconcile_external_fee(evidence, reason,
  materiality_threshold)` and replaced it with evidence-only
  `submit_fee_evidence(evidence)`.
- Deleted nullable enum-plus-fields scope modeling and `statement_scope: str`.
- Deleted aggregate-only prior-adjustment and sum-only DETAILED semantics.
- Deleted single-blocker/clear-on-any-match state transitions.
- Deleted order-side/offset interpretation from the fee risk gate.
- Old evidence, decision, adjustment, fact, ledger, reconciliation-authority, and
  risk-gate schemas are rejected; no compatibility adapters or implicit migration
  were introduced.

## New Policy Authority

`OnlyFeeReconciliationPolicy` is an immutable, versioned governance authority
with policy identity, currency, materiality threshold, unknown-difference action,
incomplete-evidence action, component-mismatch action, and canonical fingerprint.
Its registry rejects unknown policies, duplicate versions, and fingerprint
conflicts. Account configuration must explicitly select a policy. Runtime
assembly resolves that selection; missing policy and currency mismatch fail closed.

## Typed Scope Model

External evidence contains exactly one tagged trade, order, or statement scope.
Illegal mixed or empty states cannot be constructed. Statement scope freezes
broker, account, currency, statement identity, fingerprint, and a UTC
`[period_start, period_end)` interval.

`OnlyFeeApplicationRecord` now freezes `effective_at`. The fee ledger maintains
deterministic trade, order, and account/currency/time indexes, and
`OnlyFeeReconciliationLocalFactQuery` is the sole scope-selection authority.
Statement selection therefore neither scans nor falls back to all account history.

## Component Reconciliation Model

Broker adapters provide normalized OnlyAlpha component identities; broker SDK
field names do not enter Core. DETAILED planning operates on the stable union of
local, external, and prior-adjustment component identities. Each row records local,
reported, prior-adjustment, effective-local, difference, status, and fingerprint.
Missing and zero remain distinct, and a supplied total inconsistent with detailed
components fails closed.

The aggregate decision freezes policy identity, exact scope, local-fact authority
fingerprint, prior-adjustment authority fingerprint, component rows, totals,
status, and its own deterministic identity. Equal totals with different components
cannot match.

## Revision / Supersede Model

Evidence family identity is derived from broker, account, external reference, and
scope. Revisions use an integer `revision_sequence` and an explicit predecessor;
no string ordering is used. The authority distinguishes duplicate, same-version
conflict, independent family, and valid revision. Evidence and adjustments remain
immutable.

A revision reconciles reported components against local components plus cumulative
component-aware prior adjustments. Corrections are new immutable facts, so a
previous `+5` followed by a corrected external result creates `-3`, never edits the
first adjustment.

## Blocker Model

The account gate now owns a deterministically sorted active blocker set; `blocked`
is derived. Each blocker freezes its evidence family, evidence, reconciliation,
scope, policy, reason, creation time, and fingerprint. Only a valid reconciliation
in the same evidence lineage may replace or resolve it. An unrelated match cannot
clear it, and resolving one blocker leaves other active blockers intact.

## Risk Change Boundary

Risk classifies an order as RISK_INCREASING, RISK_REDUCING, RISK_NEUTRAL, or
UNKNOWN using the order/position model. The fee gate consumes only that
classification and imports neither side nor offset. While blocked, only proven
RISK_REDUCING changes are allowed; increasing, neutral, and unknown changes are
denied.

## Broker Evidence Port and Runtime Ingress

`OnlyBrokerFeeEvidencePort` exposes normalized `OnlyExternalFeeEvidence`, not a
dict, SDK object, or broker DTO. Runtime ingress validates evidence account,
broker, bound broker fee contract, scope, and currency before resolving policy,
querying exact local facts, planning, and committing. P2 adds no MiniQMT network
or real statement integration.

## Schema Changes

- External evidence schema: v2.
- Fee application record schema: v2; ledger checkpoint schema: v4.
- Reconciliation decision/fact payloads: v2.
- Fee adjustment schema: v2.
- Reconciliation authority checkpoint: v2.
- Reconciliation risk-gate checkpoint: v2.
- Result and Parquet schemas include evidence lineage, scope/policy proofs,
  component reconciliation rows, adjustment attribution, and blocker changes.

The generic prepared/committed runtime transaction envelope did not change because
its contract remains valid.

## Recovery Semantics

The existing ordered projections remain:
EXTERNAL_FEE_EVIDENCE, FEE_RECONCILIATION, component adjustment ledger, ACCOUNT,
STRATEGY_LEDGER or UNALLOCATED_EXTERNAL_FEE, then one atomic risk-gate state.
Projection replay remains idempotent through the committed Transaction Store and
Applied Projection Ledger.

Recovery tests cover failures across the projection chain, revised evidence with
exactly one `+5` and one `-3` correction, blocker resolution, multi-blocker state,
and checkpoint round trips. Repeated forward recovery produces the same canonical
evidence, decisions, component adjustments, cash/ledger effects, and blockers as
an uninterrupted run.

## Test Matrix and Exact Gate Results

All required gates completed without adding skip/xfail behavior or weakening
assertions:

| Gate | Exact result |
|---|---|
| Dependency sync | audited 67 packages |
| Ruff | PASS |
| Ruff format check | PASS |
| Core mypy | 486 source files, no issues |
| Tushare provider mypy | 15 source files, no issues |
| MiniQMT provider mypy | 36 source files, no issues |
| fast | 962 passed, 1 skipped, 14.56 s |
| integration | 126 passed, 57.59 s |
| core-full | 1088 passed, 1 skipped, 71.84 s |
| recovery | 294 passed, 159.77 s |
| ashare | 5 passed, 2.25 s |
| miniqmt-contract | 31 passed, 3.59 s |
| exhaustive | 112 passed, 9.36 s |
| version sync | all packages synchronized at 0.3.4 |
| build | all 4 packages produced sdist and wheel successfully |

Per the task instruction, pre-commit was not run.

## Remaining Technical Debt — NOT IMPLEMENTED IN P2

P2 closes domain and durable reconciliation semantics only. It does not implement:

- Production CN A-share Market Fee Pack.
- Real Broker Commission Contract provisioning.
- Real MiniQMT fee/statement ingestion.
- Paper Streaming Recovery.
- Live Runtime.
- Durable Outbound Order Commands.
- Production Futures Execution.
- Production Crypto Execution.
- Multi-account Runtime.
- Multi-broker Runtime.
- Advanced fee allocation.
- FX reconciliation or conversion.
- Vectorized Backtest.

Cash-insufficient supplemental charges remain fail-closed; a durable pre-commit
evidence ingress journal or fee-debt facility is a P3+ design question. Real
broker-specific component normalization and personalized contract provisioning
also remain adapter/product work. These limitations do not alter the immutable
evidence, policy, scope, component, correction, or blocker roots established here.
