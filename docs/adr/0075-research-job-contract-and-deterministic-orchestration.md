# ADR 0075: Research Job Contract and Deterministic Orchestration

Status: Accepted

Date: 2026-08-14

## Context

ADR 0069/0070 established canonical Calculation Definitions and Graphs. ADR 0072 established the immutable verified Dataset
Snapshot authority. ADR 0073 established deterministic ephemeral RESEARCH Calculation execution, and ADR 0074 established the
immutable verified Calculation Result authority. Those primitives did not define one canonical application operation for an exact
Research request. Callers could otherwise duplicate reuse decisions, mistake physical existence for a verified Result, recompute
over corruption, or prematurely embed Research work in the trading-shaped Runtime hierarchy.

P7.4 needs one single-job boundary before Sweep, Statistics, Research Runtime, API, or Web layers can safely compose Research work.
The current `OnlyResearchRuntime` still inherits `OnlyRuntime`, and its Factory remains intentionally unsupported.

## Decision

`OnlyResearchJobPlan` is an immutable resolved contract containing exactly a schema version, an exact Dataset Snapshot fingerprint,
and the existing canonical `OnlyCalculationGraphDefinition`. It contains no alias resolution, provider, path, store root, process,
worker, clock, compression, or other operational property. Dataset fingerprint shape is checked with the existing strict Dataset
validator; Graph construction and identity remain owned by the Calculation layer.

The canonical operation is:

```text
Resolved Research Job Plan
→ derive existing Calculation identity
→ load_verified(Calculation identity)
    valid      → REUSED
    NOT_FOUND  → P7.2 execute → P7.3 immutable commit → EXECUTED
    other      → fail closed
→ immutable successful Job Outcome
```

`OnlyResearchJobExecutor` owns orchestration only. Dataset verification remains in the verified Dataset/Calculation/Result paths;
calculation algorithms remain in P7.2 backends; durable admission, atomic publication, idempotency, race resolution, and corruption
verification remain in the P7.3 Result Store.

Success returns `SUCCEEDED` with `EXECUTED` or `REUSED`, the Calculation fingerprint, and the Calculation Result fingerprint.
Failure raises `OnlyResearchJobError` with the exact Job phase and preserved stable underlying code. No failed Outcome is created.

## Identity Decision

P7.4 v1 adds no Research Job or Research Plan fingerprint. The exact Dataset Snapshot, canonical Calculation Graph, and fixed
RESEARCH backend semantics are already fully represented by the current Calculation fingerprint. Hashing that identity again would
create a duplicate authority for the same semantic fact. `EXECUTED`/`REUSED` and invocation provenance are operational facts and do
not alter Calculation or Calculation Result identity.

## Verified Reuse and Failure Semantics

Physical `exists()` is not an authority decision and is never used by Job orchestration. Only `load_verified()` may establish reuse.
`RESULT_NOT_FOUND` is the sole execution miss. `RESULT_CORRUPT`, `RESULT_INVALID`, path/linkage mismatch, deterministic conflict, and
all other Result failures are terminal for that invocation: they are not converted to misses, recomputation, repair, deletion, or
overwrite.

The stable phases are `PLAN_VALIDATION`, `DATASET_VERIFICATION`, `RESULT_REUSE`, `CALCULATION_EXECUTION`, and `RESULT_COMMIT`.
Underlying Dataset, Calculation, and Result codes remain observable through the Job error and exception chain.

## Recovery and Concurrency

P7.4 recovery is deterministic re-entry. A crash before Result commit leaves no authority, so the same exact Job executes again. A
crash after commit but before Outcome delivery is recovered by verified reuse. Corrupt durable state fails closed. No mutable Job
database, checkpoint, lease, retry daemon, or second recovery authority is introduced.

Concurrent identical Jobs may both calculate ephemerally. P7.3 remains the sole durable race authority: equal Results converge
idempotently to one Calculation Result; different Results fail with `DETERMINISTIC_RESULT_CONFLICT`. P7.4 adds no global Job lock.

## Research / Trading Boundary

The Job package depends only on canonical Calculation, Research Dataset validation, P7.2 execution contracts, and P7.3 Result
contracts. It does not import or own Runtime, Cluster, Strategy, Account, Broker, Order, Position, Allocation, Risk, Reservation,
Fee, Settlement, Trading Transaction, Projection, or Strategy Ledger authorities. It does not branch on Runtime mode.

The Research Runtime Factory remains unsupported. P7.4 is a clean Research-shaped application primitive, not product Runtime
activation and not an alternate product entry around `OnlyEngine`.

## Non-goals

P7.4 does not implement Parameter Sweep, optimization, Factor research product semantics, forward returns, IC/statistics, Research
Result, Research Artifact, scheduler, queue, worker pool, distributed execution, Notebook/REST/Web interfaces, Query service,
Research Runtime activation, Engine RESEARCH execution, or Trading Runtime refactoring. The official Factor provider remains empty.

## Consequences

Future Sweep, Research Runtime, or API layers can compose one canonical exact operation without reimplementing identity, verified
reuse, or durable conflict semantics. Verification may reread Dataset and Result authorities and may allow duplicate ephemeral work
during a race; this is intentional because integrity and one durable authority take priority over speculative locking or caching.
