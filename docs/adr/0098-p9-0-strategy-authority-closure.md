# ADR 0098: P9.0 Strategy Authority Closure

- Status: Accepted
- Date: 2026-08-24
- Related: ADR 0070, 0093, 0095, 0096, 0097

## Context

ADR 0097 introduced immutable Strategy Revision identity, Candidate Freeze, Revision-backed execution and append-only Promotion evidence.
The first implementation nevertheless retained callback-authored `OnlyStrategy` execution, hid `StrategyDecision` behind adapter state,
trusted caller-registered equivalence hashes, inferred Calculation checkpoint behavior from method presence, coupled Trading resolution to
RESEARCH backend availability, admitted adjustment semantics that Runtime BAR could not prove, and used audit timestamps to assist
Promotion ordering. Those surfaces preserve more than one interpretation of Strategy authority and must close before P9.1.

## Decision

`strategy_fingerprint` is the only Strategy identity. The only production creation path is verified Research Candidate Freeze into an
immutable `OnlyStrategyRevision`; production callers cannot author Revision semantic JSON directly. The only executable semantic form is:

```text
strategy_fingerprint
→ load_verified StrategyRevision
→ StrategyExecutionResolver
→ exact TRADING Calculation graph
→ StrategyDecision
```

Arbitrary Python `OnlyStrategy` subclass authoring and injection is unsupported and removed as a Strategy authority. The Trading Kernel
may retain exactly one internal Revision lifecycle adapter, but that adapter contains no authored trading rule. `StrategyDecision` is
propagated explicitly at the Cluster pipeline boundary and contains only `ELIGIBILITY`, `ENTRY`, and `EXIT`; it is not an Order Intent,
position-sizing, capital-allocation, Risk, Broker, or Execution command.

Calculation semantic identity remains owned by Definition and implementation identity remains owned by a closed Implementation Manifest.
Each TRADING registration used by Strategy explicitly declares `STATELESS` or `CHECKPOINTABLE`; checkpointable implementations bind a
schema version and must provide deterministic capture and restore. Unknown or inconsistent capability fails closed. Trading resolution
verifies only the exact TRADING implementation bound by the Revision and neither imports nor requires a RESEARCH runtime backend.

Cross-backend equivalence is an immutable, content-addressed, verified authority. An equivalence verifier runs both exact implementations
against one canonical deterministic corpus, compares aligned instrument/timestamp axes, missing values, numeric representation and exact
outputs, and is the only creation boundary for `OnlyCalculationEquivalenceEvidence`. Trading Admission verified-loads evidence for the exact
Calculation semantic reference plus Research/TRADING implementation fingerprints. Evidence-run identity stays outside Strategy identity;
Freeze provenance records the exact evidence fingerprints used.

P9.0 Trading BAR input is `FINAL_ONLY + RAW_ONLY`. Freeze and Trading Admission accept only `adjustment_type = RAW` and
`adjustment_reference = None`. Adjustment fields remain in the semantic model for a future Market Data provenance contract, but adjusted
input cannot execute in P9.0.

Promotion order is derived solely from the verified `previous_record_fingerprint` chain. There must be one head, one unbranched acyclic
path, no orphan, and every stored row must be consumed exactly once. `recorded_at` remains audit/display evidence and never participates in
semantic ordering or tail selection.

Official application composition owns Freeze and Promotion operator wiring under the existing P8 semantic namespace. PostgreSQL remains
catalog/provenance/ledger authority and never stores Strategy semantic truth.

## Consequences

Legacy callback Strategy examples and tests must migrate to Revision/Calculation fixtures or explicit non-Strategy scenario workloads.
Backtest and SIM continue to share one Cluster Factory and one Revision resolver. Missing implementation closure, capability, verified
equivalence evidence, RAW provenance, namespace coherence, checkpoint compatibility, or Promotion chain integrity fails closed with a
stable domain error.

P9.0 remains **Closure in progress** until all focused, architecture, equivalence, checkpoint, store, PostgreSQL, Backtest/SIM, full
quality and exact-final-SHA certification gates pass. Only an immutable exact SHA with an accepted certification artifact may be called
`DONE / CERTIFIED`.

## Rejected alternatives

- Retaining `OnlyStrategy` callbacks as a compatibility or testing execution path.
- Treating a caller-provided SHA or in-memory registration as equivalence evidence.
- Making a Trading Runtime load or instantiate RESEARCH implementations.
- Inferring state/checkpoint semantics from `update`, `capture_checkpoint`, or `restore_checkpoint` method presence.
- Admitting adjusted BAR semantics without exact observation provenance.
- Sorting Promotion records by audit timestamp or fingerprint as semantic append order.
- Adding downstream portfolio, risk, order, broker, LIVE, or automatic-promotion behavior to P9.0 Closure.
