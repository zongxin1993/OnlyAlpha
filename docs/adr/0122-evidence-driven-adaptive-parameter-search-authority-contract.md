# ADR 0122: Evidence-Driven Adaptive Parameter Search Authority Contract

- Status: Accepted
- Date: 2026-09-07
- Decision maker: repository owner through the B3.3 TASK B implementation authorization
- Related: ADR 0095, 0110, 0112, 0118, 0119, 0120, 0121

## Context

ADR 0120 owns Search Experiment and Iteration occurrence provenance, and ADR 0121 supplies a deterministic non-adaptive symbolic
Proposal stream. Neither owns an Evidence-to-next-Proposal policy, an adaptive decision occurrence, or recovery of an Iteration Plan
whose normal Research Run has progressed but whose terminal Iteration Result was not yet committed.

B3.3 requires a bounded adaptive parameter trajectory without creating a second Calculation Graph, Candidate, Research Result,
scientific metric, Qualification outcome, or mutable optimizer database. Completion order, process memory, filesystem order and current
algorithm code cannot become hidden decision inputs.

## Decision

### Authority chain

The sole formal chain is:

```text
Search Experiment V3
→ finite Parameter Search Space
→ immutable Search Policy
→ exact Algorithm Implementation Manifest
→ immutable Feedback Decision batch
→ ADR 0120 Iteration Plans
→ idempotent Product Command / Research Run
→ terminal Iteration Results
→ typed Research Summary Statistics Evidence
→ next Feedback Decision or durable STOP
```

Search proposes; normal Research proves; Qualification decides PASS/FAIL; Admission and Promotion retain their existing authorities;
human authority remains mandatory for LIVE. A search recommendation only identifies the selected Iteration Result under the exact
Experiment and Search Policy.

### Experiment V3 and immutable inputs

`OnlySearchExperimentManifestV3` is forward-only and adds one exact `OnlySearchPolicyReferenceV1` to V2. V1 and V2 bytes, readers and
identities are unchanged. V3 binds the Search Space, Evaluation Contract, Search Policy, algorithm ID/semantic version/implementation,
Dataset Snapshot, Catalog Generation, budgets, randomness and workflow. Any semantic change to those inputs creates a new Experiment.

The policy must be committed before the Experiment can pass contextual verification or consume Evidence. V1 policy freezes one primary
metric and direction, required constraints, ordered tie breakers, minimum improvement, consecutive no-improvement convergence,
coarse stride, batch size, missing-Evidence fail-closed behavior and Research-failure exclusion behavior. Qualification PASS/FAIL is not
a ranking input.

### Finite Search Space and Proposal identity

`OnlyParameterFactorSearchSpaceV1` reuses the existing Research Graph Template, Sweep Parameter Target and finite explicit candidate
dimensions. Values are normalized only through Calculation parameter schemas. Equivalent normalized values collapse; duplicate
semantic assignments fail closed. Arbitrary continuous generators and a new parameter DSL are forbidden.

The existing Sweep planner and Graph Template materializer produce canonical Calculation Graphs. A
`OnlyParameterGraphProposalV1` binds one normalized assignment, its canonical Graph, exact candidate node/output and deterministic grid
ordinal. These identities remain distinct:

```text
Search Space != Proposal != Calculation Graph != Research Candidate
```

Only the normal Research Specification Resolver constructs Candidate identity. Graph-to-Research materialization is shared with the
symbolic method so there is one Research semantic path.

### Deterministic coarse-to-fine V1

The only V1 algorithm is:

```text
algorithm_id = DETERMINISTIC_COARSE_TO_FINE
algorithm_semantic_version = 1
randomness_mode = NONE
seed = null
```

The initial batch is the canonical grid prefix selected by the frozen coarse stride, including the final grid point, then bounded by
batch and durable proposal/research budgets. Later decisions rank valid Evidence by required constraints, the primary objective,
ordered tie breakers and Proposal fingerprint. Refinement proposes untested adjacent normalized grid assignments in canonical Proposal
order. Exact tested assignments never repeat.

All terminal Evidence is canonicalized by Proposal ordinal and fingerprint. Research completion time and input load order are ignored.
The next decision is forbidden until every Plan in the prior frozen batch has a terminal or authoritatively reconciled terminal Result.

### Feedback Decision and STOP

`OnlyParameterSearchFeedbackDecisionV1` is the durable occurrence truth. It binds the Experiment, ordered terminal Iteration Result
prefix, selected anchor Result, exact ordered next Proposal batch and starting ordinal, Search Policy and algorithm implementation.
It structurally contains no Research numeric value and no Qualification outcome.

STOP is a stored Feedback Decision with one stable reason: search-space exhaustion, proposal-budget exhaustion, research-budget
exhaustion, no eligible Evidence, convergence without minimum improvement, or exhausted neighborhood. Missing/corrupt/mismatched
Evidence and ambiguous attempt state are errors, never substitute scores or normal STOPs.

The parameter Search Store uses canonical JSON, content-addressed put-once objects and one lock-protected, conflict-checked Experiment
feedback frontier. Locking is implementation coordination only; identity, put-once publication, exact batch occurrence checks and
ordinal/frontier conflict detection provide correctness. Historical decisions exact-load independently of current code. Reproduction
requires the matching historical manifest; changed code may report an explicit mismatch but cannot invalidate history.

### Recovery and budgets

Every Feedback Decision is committed before any Plan in its batch. Recovery recreates zero, partial or complete Plan batches from that
exact Decision. Each Plan shares the Decision fingerprint and proves its Proposal membership and ordinal.

The Research Product Command ID is a stable UUID4 derived from the immutable Iteration Plan fingerprint. Existing Product Command
Receipt and Research Run facts are reconciled; missing receipt permits the existing atomic idempotent submission path. QUEUED/RUNNING
remain behind the barrier. COMPLETED creates the exact Research Result reference; FAILED/CANCELLED creates a failed terminal Iteration
Result and consumes the authoritative attempt. Conflicting receipt/run identity or any ambiguous state fails closed and is never blindly
resubmitted.

Proposal, Research and Qualification consumption is always derived from durable Plan/Result/Run occurrences. Process-local counters are
not authority, so crash/restart cannot return or duplicate budget.

### Statistical boundary

Search reads metrics only through a typed reader that traverses exact Iteration Result → Research Result → referenced Summary Statistics
and selects registered scalar metric IDs. It does not read raw Parquet or recompute a metric. Search persists the complete proposal,
Candidate, attempt, budget, algorithm, space and Experiment lineage needed by later multiple-testing governance, but implements no DSR,
PBO, FDR, Bonferroni or sealed-holdout policy.

## Consequences

- Adaptive histories are deterministic, bounded, replayable and recoverable without mutable optimizer state.
- Parallel Research execution is allowed, while batch completion order has no semantic effect.
- Algorithm changes require new implementation identity and semantic changes require a new semantic version and Experiment.
- Future Bayesian, evolutionary, RL, LLM or multiple-testing methods require separate method/policy contracts and cannot reinterpret V1
  history.

### Authority and recovery closure amendment

The formal adaptive Controller accepts only a verified Parameter Search Context. It derives the complete terminal Result prefix from
Search Provenance and obtains every scientific scalar by exact traversal through the existing Research Result and Research Statistics
authorities. The metric-bearing typed Evidence value remains an ephemeral input to the pure deterministic algorithm; it is not accepted
from a caller by the formal durable workflow and is not a new scientific authority.

Historical Algorithm Manifest verification and current-runtime execution admission are separate. Exact historical Experiment, Manifest,
Feedback Decision, Plan and Result reads never compare historical bytes with current source. Before any new Feedback Decision is produced,
the current runtime resource-closure Manifest must exactly equal both the Experiment binding and its exact persisted historical Manifest
for algorithm ID, semantic version, implementation fingerprint and source revision. A mismatch fails closed as
`PARAMETER_ALGORITHM_RUNTIME_MISMATCH` without invalidating history.

A Feedback Decision becomes publishable only after contextual and occurrence verification recomputes the pure deterministic function from
the exact verified Context, complete canonical terminal Result/Evidence prefix, admitted current Algorithm implementation, durable budget
and exact prior Decision history, then proves full object equality. The Parameter Search Store accepts only that ephemeral verified
capability. Content addressing, locking and frontier CAS remain storage/coordination mechanisms and cannot authorize a structurally valid
but semantically fabricated Decision.

Fresh-process recovery continues exclusively from existing durable Search Provenance, Parameter Search, Product Command Receipt,
Research Run, Research Result and Statistics facts. A committed Decision precedes its Plan batch; missing Plans are recreated exactly,
stable Plan-derived Product Command identity reuses an existing receipt/run, and completed Research is projected into the missing terminal
Iteration Result without re-execution. Missing receipt is the only state that permits the existing atomic idempotent submission path;
conflicting or ambiguous receipt/run identity fails closed and never causes blind retry or mutable optimizer-memory repair.

### Final historical-execution closure amendment

Historical readability is distinct from current execution eligibility. Exact historical Experiment, Feedback Decision, Plan and Result
loads remain independent of the currently installed implementation and never rewrite historical bytes. Before a persisted Feedback
Decision may authorize Plan recovery, Research submission or another adaptive transition, the Controller must first admit the current
runtime, reproduce the relevant Decision chain from the exact durable Result/Evidence prefix, and prove that already committed Plans are
exactly a canonical prefix of each frozen Decision batch.

The loss of the ephemeral verified-commit capability at a process boundary does not create a persisted verification flag, migration
record or second authority. Execution eligibility is reconstructed from the existing durable authorities on every read-to-act path. A
runtime implementation mismatch therefore leaves history readable but fails closed before any new Plan, receipt, Run or budget
consumption.

For V1 successful Research, the completed Run's immutable Research Result remains the exact execution output and is never rewritten.
The parameter Evidence finalizer resolves the Policy's registered Effect Summary metric descriptors, requires one unambiguous matching
base Statistics source in that Result, invokes the existing Research Summary Statistics Authority, and uses the existing Research Result
Assembler to publish a separate immutable Evidence-composition Result containing both the source and derived Summary references. The
Iteration Result references this composition Result. Its Summary Plan binds the exact source Statistics logical and result identities,
while the Plan-derived Product Command identity retains the causal link to the completed Run. Re-entry is content-addressed and
idempotent. Unsupported, mixed, non-Effect or ambiguous metric/source contracts fail closed; supporting another Summary family requires
an explicit versioned extension and cannot reinterpret V1.

Fresh-process adaptive recovery is complete only after terminal Iteration Results traverse the authoritative Evidence reader and produce
the same next Feedback Decision or durable STOP as uninterrupted execution. Equality covers the ordered Decision/Plan/Proposal/Candidate/
Research/Statistics identities and payloads, frontier, final STOP semantics, all durable budget consumption, Product Command receipts,
Research Runs and execution attempts; recovery may introduce no duplicate occurrence or attempt.
