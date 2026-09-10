# FP-STORAGE-001 — Trading projection exists without complete durable causal history

## Failure family

A runtime can reconstruct or display current account/portfolio state but does not durably preserve enough order, trade, position and portfolio history to explain how that state was reached.

## External / internal evidence

- RQAlpha issue #479: simulation persistence did not preserve trade and portfolio history needed to display historical trading/equity changes.
  - https://github.com/ricequant/rqalpha/issues/479
- Evidence status: observed upstream persistence limitation/defect relevant to stateful trading auditability.

## Observed symptom

After restart or later analysis, the system may know a current balance/position but cannot reconstruct the complete order/fill/portfolio evolution or produce the same historical projection.

## Generalized root cause

Mutable/current projection state was persisted while the causal facts needed for recovery, traceability and historical reconstruction were omitted or treated as optional presentation data.

## Risk to OnlyAlpha

Recoverability and Traceability can be violated even when the latest state appears correct. A projection may become an unexplained truth with no authoritative event/fact chain behind it.

## OnlyAlpha invariant

Critical trading state must be recoverable and explainable from durable authoritative facts plus explicit reconciliation. Current projections are derived state; they cannot replace the causal order/fill/account/runtime evidence needed to reproduce state transitions.

## Required protection

- persist authoritative intent/order/fill/reconciliation/runtime facts according to their contracts;
- treat Portfolio/Position/UI history as reproducible projections over durable facts where possible;
- explicitly version/checkpoint state that cannot be cheaply reconstructed;
- never claim recovery/audit completeness from current-state snapshots alone;
- retain external venue identity/evidence required to reconcile missing local facts.

## Required tests

- crash/restart after order acknowledgement, partial fill and full fill → reconstructed projection equals uninterrupted execution;
- rebuild Portfolio/Position history from durable facts → same ordered transitions and final state;
- remove/corrupt one required durable fact → verification fails closed rather than silently accepting the current projection;
- UI/report/query projections can be rebuilt without becoming an independent trading Authority.

## Non-solutions / rejected shortcuts

Persisting only the latest Portfolio object, writing extra mutable CSV history, or relying on logs does not establish authoritative recovery or causal traceability.

## Scope notes

Applies to Trading Runtime persistence, Order/Fill ledgers, Portfolio/Position projections, reconciliation and operational audit. It does not require every UI/read-model cache to be durable.