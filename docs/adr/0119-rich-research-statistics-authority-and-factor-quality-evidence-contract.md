# ADR 0119: Rich Research Statistics Authority and Factor-Quality Evidence Contract

- Status: PROPOSED
- Date: 2026-09-05
- Related: ADR 0082, 0083, 0084, 0085, 0092, 0095, 0097, 0114, 0115, 0116, 0117, 0118

## Context

OnlyAlpha currently has one deterministic Research Statistics authority for per-timestamp `IC` and `RANK_IC` facts. Statistics
Definition V1 freezes pairing, observed-universe, rank-tie, weighting, minimum-observation and Decimal semantics. Statistics Result
V1 stores canonical rows containing `ts_event_ns`, `statistic_value`, `sample_count` and an explicit status. It uses layered logical,
content and result fingerprints, immutable put-once storage, verified reuse and fail-closed corruption handling.

Research Result Scientific V2 is composition-only. Its Plan contains the complete canonical Statistics membership and an exact
`Candidate.statistics_fingerprints` subset for each Candidate. Strategy Freeze records the exact Candidate and Research Result in
`OnlyStrategyFreezeRelation`. Qualification presently follows that relation but exposes only manifest-owned count metrics. Artifact,
Query, HTTP and Web are read projections and do not own scientific calculation.

B3 factor mining needs deterministic, machine-readable factor-quality facts including effect summaries, coverage, explicit temporal
stability, factor-pair correlation and parameter-neighborhood robustness. Adding those calculations to Qualification, Query, Web or an
Agent would create a second numeric authority. Reusing the V1 timestamp row as an untyped universal metric record would erase the
different identities, shapes, statuses and dependency semantics of series and summary facts.

This decision freezes the authority and public semantic contract only. It does not authorize production implementation.

## Problem

OnlyAlpha needs one contract under which rich factor-quality metrics:

1. remain owned by Research Statistics;
2. bind exact immutable Dataset, Candidate, Calculation and upstream Statistics evidence;
3. have deterministic, versioned mathematics and typed invalidity rather than plausible default values;
4. compose through Research Result without turning it into a calculator;
5. resolve through the exact frozen Candidate during Qualification without first/latest/fuzzy selection;
6. remain portable through a future Artifact/Query/API projection without recomputation; and
7. preserve every existing Statistics V1, Research Result V1/V2 and Artifact V1/V2 identity and meaning.

## Decision

### Authority model

The permanent authority chain is:

```text
verified Calculation Results
        ↓
Research Statistics Authority
  ├── base series Statistics
  ├── derived/summary Statistics
  ├── metric vocabulary
  └── immutable Statistics Results
        ↓ exact membership only
Research Result V2 composition authority
        ↓ exact Candidate membership
FreezeRelation.candidate_fingerprint
        ↓ exact scalar resolution only
Qualification policy authority
        ↓
QualificationDecision
```

Ownership is fixed as follows:

| Fact | Sole authority |
|---|---|
| IC/RankIC timestamp values | Research Statistics |
| mean, sample standard deviation and non-annualized IR | Research Statistics |
| timestamp and observed-pair coverage | Research Statistics |
| explicit-slice stability | Research Statistics |
| Factor A versus Factor B correlation | Research Statistics |
| exact parameter-neighborhood summaries | Research Statistics |
| exact Statistics membership of a research product/Candidate | Research Result |
| whether exact evidence meets an exact policy | Qualification |
| Candidate-to-Strategy publication | Freeze |
| portable/readable projection | Artifact/Query/API/Web |

Research Result, Qualification, Artifact, Query, HTTP, Web and Agent calculate none of the numeric facts above. PostgreSQL may retain
operational/control records and exact evidence references, but is not a mutable factor-metric authority.

### Typed Statistics model

Research Statistics becomes a versioned discriminated family, not one universal row and not `dict[str, float]`:

```text
Research Statistics
├── Series Statistics
│   ├── Feature/Target Correlation Series V1 (existing, unchanged)
│   │   ├── IC
│   │   └── RANK_IC
│   └── Factor-Pair Correlation Series V1 (new schema/domain)
│       ├── FACTOR_CORRELATION
│       └── FACTOR_RANK_CORRELATION
└── Summary Statistics V1 (new schema/domain)
    ├── Effect Summary
    ├── Coverage Summary
    ├── Temporal Stability Summary
    ├── Factor-Pair Effect Summary
    └── Parameter-Neighborhood Summary
```

Each family has its own definition, plan, manifest/result schema and typed payload. Shared protocols may expose `statistics_fingerprint`,
`statistics_result_fingerprint`, `dataset_snapshot_fingerprint`, dependency references and `load_verified()`, but a shared protocol does
not erase the discriminant or permit arbitrary fields.

Existing `OnlyResearchStatisticsDefinition`, `OnlyResearchStatisticsPlan`, `OnlyResearchStatisticRow` and Statistics Result V1 retain
their current schemas and identities. Factor-pair rows may have the same physical columns, but belong to a new typed schema and use
pair-specific references and statuses. Summary results contain fixed typed scalar fields rather than synthetic timestamps.

Every summary scalar is represented by a typed value:

```text
metric_id
value_kind = INTEGER | DECIMAL
integer_value or decimal_value, exactly one when status = VALID
status
```

The concrete result payload uses named fields, not a free-form metric map. `metric_id` is derived from the result discriminant and named
field through the canonical metric registry; callers cannot attach an arbitrary metric name to a value. A non-`VALID` scalar has no
numeric value. Integer counts remain exact integers in Statistics; Qualification may project an exact integer to `Decimal` solely for
comparison without changing the owned fact.

### Definition and plan contracts

Definitions own versioned mathematical meaning. Plans bind that meaning to exact subjects and inputs.

New Definition V1 discriminants are:

```text
EFFECT_SUMMARY
COVERAGE_SUMMARY
TEMPORAL_STABILITY
FACTOR_PAIR_CORRELATION
FACTOR_PAIR_RANK_CORRELATION
FACTOR_PAIR_EFFECT_SUMMARY
PARAMETER_NEIGHBORHOOD_SUMMARY
```

Definitions include every applicable mathematical policy: source method, minimum observations, complete-pair alignment, observed-pair
universe, equal weighting, average rank ties, sample standard-deviation convention, non-annualized IR convention, Decimal precision,
output quantum, rounding and definition schema version. Unsupported values fail closed.

Plans additionally contain, as applicable:

- one exact Dataset Snapshot fingerprint;
- one exact subject Candidate fingerprint for candidate-owned summaries;
- exact Feature/Target or Factor A/Factor B series references;
- exact upstream pairs of Statistics logical fingerprint and Statistics Result fingerprint;
- exact ordered temporal intervals;
- an exact focal Candidate and exact ordered neighbor Candidate/assignment/source-result bindings; and
- plan/identity schema version.

Factor references contain `calculation_fingerprint + node_fingerprint + output_name`. Candidate references contain the exact Candidate
fingerprint and canonical parameter assignment. An assignment is a sorted, duplicate-free mapping using the existing canonical
Calculation scalar representation.

Derived plans may depend only on verified Statistics Results. Factor-pair series plans may directly depend on two verified Factor
Calculation Results. No plan may select an upstream input by latest, creation time, path, label, approximate semantic match or Store
scan.

The Statistics dependency graph is a finite DAG. A plan cannot reference itself, form a direct/transitive cycle or consume a result
family not admitted by its typed Definition. Family allowlists are part of the Definition schema; they are not inferred from matching
physical columns.

### Identity and fingerprint layering

Every new Statistics family uses three layers:

```text
Statistics logical fingerprint
    = canonical(new identity schema version,
                typed semantic definition,
                exact Dataset Snapshot,
                exact subject bindings,
                exact logical upstream references,
                explicit slices/neighborhood where applicable)

Statistics result-content fingerprint
    = canonical(new result schema version,
                exact upstream logical/result fingerprint pairs,
                fixed typed result payload)

Statistics Result fingerprint
    = canonical(new result schema version,
                Statistics logical fingerprint,
                result-content fingerprint)
```

The explicit Dataset fingerprint is required in every new plan even when it is derivable from an upstream result. Verified execution
must prove the explicit value equals every direct and transitive upstream Dataset binding. This closes accidental cross-Dataset
coincidence without changing Statistics V1.

Exact upstream Result fingerprints enter result content, not the reusable mathematical Definition. If authoritative content were ever
different under the same logical upstream fingerprint, put-once verification produces a deterministic conflict rather than silently
changing the derived result.

The following enter identity when applicable:

- Statistics family and schema version;
- complete semantic Definition and numeric contract;
- Dataset Snapshot fingerprint;
- subject/focal/pair/neighbor Candidate fingerprints and canonical assignments;
- exact Calculation/Graph series references for direct inputs;
- upstream Statistics logical fingerprints;
- explicit half-open temporal slices; and
- the exact ordered neighborhood membership.

The following never enter semantic identity:

```text
wall clock / created_at
filesystem or temporary path
host / PID / worker / process
execution disposition (EXECUTED or REUSED)
display label
HTTP request or Product command identity
Agent prompt, explanation or UI state
physical Parquet layout, compression or byte hash
```

Canonical serialization uses the repository canonical JSON rules: exact field sets, explicit schema versions, sorted duplicate-free
sets, role-preserving ordered arrays where order is semantic, integer nanoseconds, canonical Decimal strings and lower-case SHA-256.
Physical byte hashes protect materialization integrity but do not replace semantic content fingerprints.

Therefore:

```text
same semantic inputs -> same Statistics logical fingerprint
same logical Statistics + same deterministic content -> same Statistics Result fingerprint
semantic change -> a new Definition/schema and identity
```

### Result status semantics

Summary scalar status V1 is:

```text
VALID
NO_VALID_OBSERVATIONS
INSUFFICIENT_OBSERVATIONS
ZERO_VARIANCE
INSUFFICIENT_COVERAGE
NOT_APPLICABLE
```

The status belongs to each scalar because one result can validly contain a mean while its sample standard deviation and IR are not
computable. The containing Result remains verifiable even when some scalars are non-`VALID`.

- `NO_VALID_OBSERVATIONS`: the required source set is empty after applying only the frozen status/filter rule.
- `INSUFFICIENT_OBSERVATIONS`: some source observations exist, but fewer than the metric's explicit mathematical minimum.
- `ZERO_VARIANCE`: the exact denominator variance/standard deviation is zero.
- `INSUFFICIENT_COVERAGE`: an explicit versioned coverage precondition in a Definition is unmet. V1 metrics without such a precondition
  must not emit this status merely because coverage seems low.
- `NOT_APPLICABLE`: the typed schema requires a field but the selected method explicitly defines it as inapplicable. It must not hide an
  unsupported method or missing dependency.

`VALID` requires exactly one finite typed value. Every non-`VALID` status requires both numeric value slots to be absent. Numeric zero is
a valid fact only when the mathematics actually produces zero; it never represents missing, corrupt or non-computable evidence.

### Numeric determinism

All authoritative decimal outputs use:

```text
representation = DECIMAL
precision = 38
output_quantum = 0.000000000001
rounding = ROUND_HALF_EVEN
execution_context = onlyalpha.decimal.execution@1
```

The complete canonical Decimal execution context from ADR 0114 is constructed explicitly; ambient Python Decimal state and binary
floating point are forbidden. Inputs to each aggregation are the exact stored canonical Decimal values of its verified upstream Result.
Intermediate mean, sum-of-squares, square root and division are evaluated in the explicit precision-38 context and are quantized once at
the published scalar boundary. A higher-level summary consumes the published canonical values of its direct upstream summary/series,
not inaccessible extra precision.

A change to precision, quantum, rounding, annualization, degrees of freedom, sign rule, denominator, interval assignment or source-status
filter is a semantic change and creates a new version/identity.

## Mathematical semantics

### Effect Summary V1

An Effect Summary consumes one exact IC, RankIC, Factor Correlation or Factor Rank Correlation series Result. Only rows whose source
status is `VALID` participate in value aggregates. Non-`VALID` rows are never coerced to zero and remain represented by exact status
counts.

Let all source rows be `R`, valid values in timestamp order be `x_1 ... x_n`, and `N = |R|`.

Fixed fields are:

```text
total_count = N
valid_count = n
source-status count for every status legal in the source schema

mean = sum(x_i) / n                              requires n >= 1
sample_stddev = sqrt(sum((x_i - mean)^2)/(n-1)) requires n >= 2
information_ratio = mean / sample_stddev        requires n >= 2 and sample_stddev != 0

positive_count = count(x_i > 0)
negative_count = count(x_i < 0)
zero_count = count(x_i = 0)

positive_ratio = positive_count / n             requires n >= 1
negative_ratio = negative_count / n             requires n >= 1
zero_ratio = zero_count / n                     requires n >= 1
```

`total_count`, `valid_count`, source-status counts and sign counts are `VALID` exact integers, including zero. Mean and sign ratios are
`NO_VALID_OBSERVATIONS` when `n = 0`. Sample standard deviation and IR are `INSUFFICIENT_OBSERVATIONS` when `n < 2`. If `n >= 2` and the
exact sample variance is zero, sample standard deviation is valid zero and IR is null with `ZERO_VARIANCE`.

Information ratio is deliberately non-annualized. V1 never multiplies by `sqrt(252)`, `sqrt(240)`, periods-per-year or another inferred
calendar factor.

### Coverage Summary V1

Coverage consumes one exact series Result and reports only facts the existing observed-pair authority can prove:

```text
total_timestamp_count
valid_timestamp_count
valid_timestamp_ratio = valid_timestamp_count / total_timestamp_count
count for every non-VALID source status

pair_count_total = sum(row.sample_count for every source row)
pair_count_mean = pair_count_total / total_timestamp_count
pair_count_min = min(row.sample_count)
pair_count_max = max(row.sample_count)
```

Counts and `pair_count_total` are valid exact integers, including for an empty series. Ratios and pair-count mean/min/max are
`NO_VALID_OBSERVATIONS` when `total_timestamp_count = 0`; otherwise they are valid. Mean and ratio are quantized Decimals; min/max are
integers.

These are observed timestamp/pair facts. They must not be named or presented as eligible-Universe coverage, instrument coverage,
survivorship coverage or expected-pair coverage because no authoritative expected eligible universe is bound in V1.

### Temporal Stability V1

A Stability Plan binds one exact IC/RankIC series, its exact Result fingerprint and a non-empty ordered list of explicit intervals:

```text
[start_ts_event_ns, end_ts_event_ns)
```

Every endpoint is an integer nanosecond, `start < end`, and intervals are strictly ordered and non-overlapping. Adjacency is allowed.
Intervals need not cover the Dataset and rows outside all intervals are deliberately excluded. A row belongs to the single interval for
which `start <= ts_event_ns < end`. No timezone, calendar year, market regime, volatility regime or inferred label participates.

For every interval, the result contains the Effect Summary mean/sample-stddev/IR rules and Coverage Summary valid timestamp ratio over
that interval. Empty intervals and intervals with too few valid rows retain their typed statuses.

Across slices, let `m_1 ... m_k` be only per-slice means whose status is `VALID`:

```text
slice_count = number of explicit intervals
valid_slice_count = k
positive_mean_slice_count = count(m_j > 0)
negative_mean_slice_count = count(m_j < 0)
zero_mean_slice_count = count(m_j = 0)

positive_mean_slice_ratio = positive count / k   requires k >= 1
negative_mean_slice_ratio = negative count / k   requires k >= 1
zero_mean_slice_ratio = zero count / k           requires k >= 1
min_slice_mean = min(m_j)                         requires k >= 1
max_slice_mean = max(m_j)                         requires k >= 1
stddev_of_slice_means = sample stddev(m_j)        requires k >= 2
```

The cross-slice standard deviation uses the already published quantized slice means as its exact inputs. V1 defines no aggregate
`stability_score`, regime discovery or hidden slice generation.

### Factor-to-Factor Statistics V1

Factor pair evaluation is first-class and never models Factor B as a Target. A pair plan binds:

```text
exact Dataset Snapshot
exact Candidate A + Factor A series reference
exact Candidate B + Factor B series reference
method = FACTOR_CORRELATION | FACTOR_RANK_CORRELATION
minimum_observations >= 2
alignment = exact (instrument_id, ts_event_ns) intersection
pairing = PAIRWISE_COMPLETE
universe = OBSERVED_PAIRWISE
rank ties = AVERAGE (rank method only)
weighting = EQUAL
numeric contract
```

Both verified Calculation Results must bind the same exact Dataset. Both ports must be admitted Factor value/score semantic outputs.
Non-null pairs are intersected exactly; fill, truncation, nearest join and timestamp inference are forbidden.

Correlation is symmetric, so identity canonicalizes the two complete `(candidate_fingerprint, series_reference)` operands
lexicographically. The canonical first/second operands define the corresponding zero-variance status names. Swapping caller order
therefore produces the same logical identity, not a parallel fact.

Per timestamp, Pearson and average-rank Pearson mathematics are exactly the existing IC/RankIC V1 mathematics. Status is one of
`VALID`, `INSUFFICIENT_OBSERVATIONS`, `ZERO_VARIANCE_FIRST_FACTOR`, or `ZERO_VARIANCE_SECOND_FACTOR`. A Factor-Pair Effect Summary applies
the Effect Summary V1 rules to one exact verified pair-series Result.

### Parameter-Neighborhood Summary V1

Neighborhood Statistics measures an explicitly supplied neighborhood; it does not search or choose it. A plan binds:

```text
exact Dataset Snapshot
source metric ID
exact focal Candidate fingerprint + canonical assignment
exact focal Statistics logical/result fingerprint pair
ordered, duplicate-free neighbor entries:
    exact neighbor Candidate fingerprint
    canonical neighbor assignment
    exact neighbor Statistics logical/result fingerprint pair
```

The focal Candidate cannot appear as a neighbor. Neighbor Candidate fingerprints must be unique. V1 does not infer distance, adjacency,
parameter type, search region or the next assignment. Every source Result must expose exactly one scalar for the registered source metric,
must bind the declared Candidate and Dataset, and must verify through the Statistics authority.

V1 admits exactly `research.factor.ic.mean@1` or `research.factor.rank_ic.mean@1` as the neighborhood source metric. This makes the
`neighborhood.ic` and `neighborhood.rank_ic` output namespaces complete rather than context-dependent. Supporting IR or another focal
metric later requires an explicit new registered neighborhood metric family/version; it must not reuse these IDs.

Fixed outputs are:

```text
focal_metric_value
neighbor_count
valid_neighbor_count
invalid-neighbor status counts
neighbor_mean
neighbor_min
neighbor_max
neighbor_sample_stddev
local_range = neighbor_max - neighbor_min
focal_minus_neighbor_mean = focal_metric_value - neighbor_mean
```

Only neighbor source scalars with status `VALID` enter numeric neighbor aggregates; invalid neighbors remain counted and are not zero.
Mean/min/max/local range require at least one valid neighbor. Sample standard deviation requires at least two. The focal-minus-mean
requires a valid focal value and at least one valid neighbor. `neighbor_count` and status counts remain valid exact integers.

The evaluator produces no next-parameter recommendation, expansion decision, family rejection, score or Qualification outcome. Those
actions belong to later search/Agent work.

## Metric vocabulary ownership

Research Statistics owns an append-only, versioned metric registry. A canonical metric ID includes its semantic version as `@1`; an ID
is never rebound to different family, field, subject type, value kind, mathematics or status semantics. A semantic change adds a new ID.
Registry descriptors are immutable canonical values and map one ID to one typed result discriminant and named scalar field.

Initial IDs include the following families (the same fixed field suffixes are registered separately where shown):

```text
research.factor.ic.{total_count,valid_count,mean,stddev_sample,ir,
                    positive_count,negative_count,zero_count,
                    positive_ratio,negative_ratio,zero_ratio}@1
research.factor.rank_ic.{same effect fields}@1

research.factor.ic.coverage.{valid_timestamp_count,valid_timestamp_ratio,
                             total_timestamp_count,
                             insufficient_timestamp_count,
                             zero_variance_feature_count,zero_variance_target_count,
                             pair_count_total,pair_count_mean,pair_count_min,pair_count_max}@1
research.factor.rank_ic.coverage.{same coverage fields}@1

research.factor.ic.stability.{slice_count,valid_slice_count,
                              positive_mean_slice_count,negative_mean_slice_count,
                              positive_mean_slice_ratio,negative_mean_slice_ratio,
                              min_slice_mean,max_slice_mean,stddev_of_slice_means}@1
research.factor.rank_ic.stability.{same stability fields}@1

research.factor_pair.correlation.{mean,stddev_sample}@1
research.factor_pair.rank_correlation.{mean,stddev_sample}@1

research.factor.neighborhood.ic.{focal_value,neighbor_count,valid_neighbor_count,
                                 neighbor_mean,neighbor_min,neighbor_max,
                                 neighbor_stddev_sample,local_range,
                                 focal_minus_neighbor_mean}@1
research.factor.neighborhood.rank_ic.{same neighborhood fields}@1
```

The implementation registry must include the omitted fixed zero/source-status counts and zero-slice ratios described by the typed
results even when this abbreviated list uses `same` for readability. Metric IDs are constants/descriptors in the Research Statistics
public contract, not arbitrary strings whose meaning is invented by Qualification. Unsupported IDs fail closed. ADR 0118's existing
manifest-count metrics retain their historical meaning; they are not silently renamed into rich Statistics metrics.

## Candidate binding and Research Result compatibility

Research Result Scientific V2 is sufficient and no Research Result V3 is required.

V2 already expresses both necessary sets without interpreting the Statistics payload:

```text
ResearchResultPlan.statistics_fingerprints
    = complete base + derived Statistics membership

ResearchResultCandidatePlan.statistics_fingerprints
    = exact Statistics membership owned by that Candidate
```

Rich Statistics use the same existing logical/result reference pair in the Result manifest. Result content identity already hashes the
canonical reference set. The Result remains composition-only and need not know whether a reference addresses a series or summary.

For a V2 Plan containing any new rich Statistics schema, verification additionally requires dependency closure: every directly or
transitively referenced upstream Statistics logical fingerprint must also be in the global Statistics membership. Candidate-owned
Effect, Coverage, Stability and Neighborhood summaries must appear only in the exact subject/focal Candidate membership. Factor-pair
series/summary may appear in each exact operand Candidate membership, and its own typed plan proves both operands. These rules apply only
to the new Statistics discriminants; they do not add a new interpretation to historical V2 members.

For every new candidate-owned Statistics member, Result verification must also prove that the typed Statistics subject's Factor series
reference uses the exact `calculation_fingerprint` recorded by that Candidate Plan and that the referenced node/output exists in its exact
Graph. For Factor-pair members, this proof is performed independently for both operand Candidates. A caller-supplied Candidate fingerprint
beside an unrelated Factor series is therefore an identity/linkage error, not valid evidence.

Candidate membership is not inferred from Calculation ID, assignment similarity or ordering. A Statistics reference outside the exact
Candidate membership is ineligible for that Candidate even if its Definition looks equivalent.

Research Result V1 remains readable unchanged but has no Candidate binding and therefore cannot supply rich Candidate qualification.
Historical Scientific V2 Results remain readable with their existing fingerprints. No migration rewrites a V1/V2 Plan, Result or
fingerprint.

## Qualification metric-resolution contract

Research qualification retains the existing `RESEARCH_RESULT` evidence kind. No `FACTOR_EVIDENCE` or third evidence authority is added.

For each Research criterion, Qualification performs exactly this algorithm:

```text
1. load_verified(subject StrategyRevision)
2. load_exact(QualificationPolicyRevision)
3. load_verified(exact FreezeRelation named by the Evidence reference)
4. require relation.strategy_fingerprint == subject
5. require relation.research_result_fingerprint == evidence.evidence_fingerprint
6. load_verified(Result by its exact plan locator)
7. require Result fingerprint == evidence.evidence_fingerprint and schema == Scientific V2
8. select exactly one Candidate whose fingerprint == relation.candidate_fingerprint
9. consider only that Candidate's statistics_fingerprints
10. join each logical fingerprint to the Result's exact logical/result reference
11. load_verified each referenced typed Statistics Result and require both identities, Dataset,
    subject binding and dependency closure to match
12. resolve the criterion's registered metric ID to a typed named scalar
13. require exactly one matching scalar source and status == VALID
14. compare its exact integer/Decimal value with the exact policy threshold
15. seal the deterministic Criterion Result and QualificationDecision
```

Qualification does not scan Statistics rows, calculate mean/stddev/IR/correlation/coverage/stability/neighborhood facts, resolve an
upstream dependency itself, or choose among multiple sources. It may convert an exact integer scalar to an exact Decimal for the existing
comparison contract.

The following fail closed before policy comparison:

| Condition | Required classification |
|---|---|
| unregistered or unsupported metric ID | `QUALIFICATION_POLICY_UNSUPPORTED` |
| Result schema cannot carry Candidate membership | `QUALIFICATION_REQUIRED_EVIDENCE_MISSING` |
| exact Candidate absent | `QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH` |
| Candidate membership and typed Statistics subject disagree | `QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH` |
| no matching metric in exact Candidate membership | `QUALIFICATION_REQUIRED_EVIDENCE_MISSING` |
| more than one matching scalar source | `QUALIFICATION_EVIDENCE_AMBIGUOUS` |
| scalar status is not `VALID` or numeric value is absent | `QUALIFICATION_REQUIRED_EVIDENCE_INVALID` |
| Statistics missing | `QUALIFICATION_EVIDENCE_NOT_FOUND` |
| Statistics corrupt or identity/dependency/Dataset mismatch | `QUALIFICATION_EVIDENCE_CORRUPT` |
| Research Result/Freeze upstream identity mismatch | `QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH` |

There is no default zero, first match, latest result, nearest Candidate or semantic-near-match substitution. A rejected policy comparison
produces a normal rejected criterion/Decision; invalid or ambiguous evidence prevents a Decision from being fabricated.

Existing Qualification Policy/Decision V1 identity can continue to carry a versioned metric ID as its `metric` string and therefore does
not require a schema change for the initial registered scalar vocabulary. If a future reusable policy needs selectors beyond one
canonical metric ID, that is a forward-only Qualification schema decision; it must not overload the string or reinterpret V1.

## Storage and reuse semantics

New Statistics Results reuse the existing content-addressed philosophy:

- Store address is the exact Statistics logical fingerprint.
- Commit stages the complete typed manifest/data, verifies a round trip, and atomically publishes once.
- `load_verified()` validates exact files/schema, canonical content, logical/content/result fingerprints, direct upstream
  logical/result pairs, transitive Dataset equality and typed subject bindings.
- Equal deterministic recommit returns `REUSED`.
- Different content or dependencies under one logical identity raises `DETERMINISTIC_RESULT_CONFLICT`.
- Missing/corrupt/mismatched upstream evidence fails closed.
- Corrupt existing authority is never treated as absent, deleted, repaired, rebuilt over or silently replaced.

A common reader may dispatch by the manifest's exact schema/domain. It must reject unknown schemas. No mutable PostgreSQL metric rows,
materialized-view values, cache entries or Agent memory become Research truth.

## Artifact, Query, API and Web boundary

The projection chain remains:

```text
Statistics Result = numeric authority
Research Result = exact composition authority
Artifact = portable immutable projection
Query = ephemeral read projection
HTTP/OpenAPI = transport contract
Web = presentation
```

Scientific Artifact V2 is not sufficient for rich Statistics. Its fixed verified file set and `statistics.parquet` schema encode the
existing timestamp-row model. Adding arbitrary summary rows or synthetic timestamps would reinterpret Artifact V2.

A later authorized implementation must therefore introduce a forward-only Scientific Artifact V3 (or an equivalently explicit new
profile/schema) that preserves V1/V2 readers and fingerprints unchanged and carries typed series and typed summary sections with their
exact Statistics definitions, dependencies, statuses and identities. It must materialize only the exact Research Result membership and
must remain self-verifying without upstream Stores.

Query and Product API/OpenAPI must later gain versioned typed summary descriptors/read endpoints before Web or Agent can consume these
metrics. They may filter, select and project Artifact-owned typed values but may not load raw IC rows to derive a mean or IR. Browser
sorting, formatting and plotting remain disposable presentation operations; React never computes an official metric.

## Historical compatibility

This decision is forward-only:

- Statistics Definition/Plan/Result V1 and all existing fingerprints are unchanged.
- Research Result V1 and Scientific V2 schemas, serialization and fingerprints are unchanged.
- Artifact V1 and Scientific Artifact V2 schemas, exact file sets and fingerprints are unchanged.
- Existing Query/OpenAPI responses retain their meaning.
- Existing ADR 0118 manifest-count metric IDs and historical Qualification Decisions are unchanged.
- No migration rewrites or backfills historical semantic truth.

Old readers reject unknown new Statistics/Artifact schemas explicitly. New readers dispatch exact old schemas through their existing
verification paths. A semantic change always creates a new schema/version/metric ID rather than changing an old decoder.

## Failure semantics

The following are hard failures, never empty evidence or numeric zero:

- unknown Definition, Result, metric or Artifact schema;
- missing, corrupt or identity-mismatched Calculation/Statistics/Research Result;
- cross-Dataset direct or transitive dependency;
- invalid Factor/Target semantic port;
- non-canonical/overlapping slice interval;
- duplicate, missing or mismatched Candidate/neighborhood binding;
- missing dependency closure in a rich Research Result;
- multiple sources for one Candidate metric request;
- invalid scalar status required by Qualification;
- deterministic recommit conflict; and
- attempted latest/nearest/fuzzy resolution.

Execution failure must not partially publish a Result. Failure of a projection does not mutate or invalidate its upstream Statistics
authority. An unavailable projection is not permission for Query, Web, Qualification or Agent to recompute the fact.

## Consequences

- Factor-quality numbers have one typed immutable authority and a complete causal chain to Dataset/Calculation evidence.
- Existing Result V2 can compose new facts without becoming coupled to their payloads, avoiding unnecessary Result V3 identity churn.
- Candidate-specific qualification is exact even when one Research Result contains multiple Candidates.
- Per-metric status permits partial scientific validity without plausible defaults.
- Factor-pair and neighborhood evidence are reusable measurements while search decisions remain outside Statistics.
- Portable read support requires an explicit Artifact/API version increment, adding implementation work but protecting historical
  identity.
- Qualification must gain a bounded Statistics reader/resolver dependency, but remains a policy evaluator rather than a statistics
  engine.

## Rejected alternatives

- **Independent `FactorEvidenceStore`/`FactorMetricStore`:** duplicates Research numeric truth.
- **Qualification recomputing metrics:** merges evidence production with policy evaluation.
- **Query/API or Web recomputing metrics:** creates a second scientific analytics plane.
- **Agent-computed IC/IR/coverage as official truth:** grants an untrusted consumer evidence authority.
- **Factor B represented as Target:** destroys Factor/Target semantic and dependency boundaries.
- **One `dict[str, float]` metric bag:** loses vocabulary ownership, exact Decimal semantics and typed status.
- **One universal timestamp row for all summaries:** requires fake timestamps and erases result shape.
- **Mutable PostgreSQL factor-metric table:** creates overwriteable parallel Research truth.
- **Latest/nearest/fuzzy Statistics resolution:** violates exact identity and deterministic replay.
- **Silent reinterpretation of existing schemas:** changes historical meaning and fingerprints.
- **Default zero for invalid/missing values:** makes absence indistinguishable from a real zero.
- **A magic V1 stability score:** hides weighting and policy inside an opaque number.
- **A neighborhood evaluator that selects the next action:** makes Statistics a search optimizer.
- **Research Result V3 solely to label rich Statistics:** V2 already carries exact global and Candidate membership.
- **Stuffing summaries into Scientific Artifact V2:** violates its fixed schema/file-set identity.
- **A third Qualification evidence kind for factor metrics:** bypasses the exact Research Result and Freeze relation.

## Out of scope

This ADR does not implement or authorize:

```text
production code or tests for B3.0.1+
Artifact/Query/HTTP/OpenAPI/Web changes
Agent, LLM, RAG, model routing or Agent storage
Experiment/Search provenance
symbolic, parameter, Bayesian, evolutionary or learned search
factor-pool selection or incremental contribution
backtest PnL/Sharpe/drawdown metrics
SIM, LIVE, Broker, Market Data or Trading Kernel changes
regime discovery, Universe stability or a stability score
sealed-holdout/multiple-testing policy
```

## Implementation sequencing

After owner acceptance, the smallest dependency-complete B3.0.1 is:

1. add the new schema-discriminated public Statistics protocols, canonical metric registry, scalar status/value types and identity
   helpers without changing V1;
2. add exact derived-plan dependency references and a verified immutable store/reader dispatch path;
3. implement only Effect Summary V1 over existing verified IC/RankIC V1 Results using the frozen Decimal mathematics;
4. prove canonical serialization/fresh-process identity, deterministic math, invalid-status behavior, exact upstream/Dataset/Candidate
   binding, commit/reuse/conflict/corruption handling and unchanged V1 pinned identities; and
5. keep Research Result, Artifact, Qualification, Query/API, factor-pair, stability and neighborhood production changes out of that first
   slice unless their direct contract types are strictly required for compilation.

Subsequent B3.0 slices may add Coverage, Stability, Factor-Pair and Neighborhood executors, then Result composition/Artifact V3/read
projection and Qualification resolution. Each slice must preserve public-example/private-asset contract parity when it actually changes
an L3/L4 public authoring, Research, Evidence or Freeze contract. Compatibility with `OnlyAlpha-alpha` and `OnlyAlpha-strategies` may be
claimed only after executable certification against the exact Core revision.

## Architecture acceptance answers

1. Mean IC is owned by Research Statistics Effect Summary.
2. ICIR is owned by Research Statistics Effect Summary and is non-annualized mean/sample-standard-deviation.
3. Coverage is owned by Research Statistics Coverage Summary and only claims observed timestamp/pair facts in V1.
4. Stability is owned by Research Statistics Temporal Stability Summary over explicit half-open intervals.
5. Factor A/B correlation is owned by first-class Research Factor-Pair Statistics.
6. Parameter-neighborhood summaries are owned by Research Statistics and bind exact focal/neighbor evidence.
7. Research Result calculates none of them; it composes exact references.
8. Qualification calculates none of them; it resolves one exact valid scalar and compares policy.
9. Query calculates none of them; it projects a verified portable Artifact.
10. Each metric has an immutable versioned registry ID mapped to a typed result field.
11. Typed status plus absent numeric value distinguishes unavailable/invalid from real zero.
12. Candidate-scoped Result membership plus typed Statistics subject bindings prevent Candidate mixing.
13. FreezeRelation selects the sole exact Candidate fingerprint; no order or similarity is used.
14. Research Result Scientific V2 already expresses global and Candidate Statistics membership.
15. Research Result V3 is not required; Artifact V3 is required for portable typed rich Statistics.
16. V1/V2 readers, schemas, identities and fingerprints remain unchanged and are never rewritten.
17. Canonical Decimal execution, exact inputs and layered fingerprints reproduce the same Result.
18. Plans/results bind exact Dataset, Candidate, Calculation series and upstream Statistics logical/result fingerprints.
19. Unknown, missing, corrupt, mismatched, non-VALID or ambiguous evidence fails closed.
20. The smallest B3.0.1 adds typed foundations plus Effect Summary V1 only, with deterministic identity/store tests.

## Constitution consistency

Constitution Impact: **NO**.

The decision strengthens Uniqueness, Single Authority, Determinism, Reproducibility, Traceability, Fail-Closed behavior and Explicit
Boundaries. It keeps Research outside the Trading Kernel, keeps Core market-agnostic, gives Agent no authority and preserves the human
LIVE boundary. No change to `PROJECT_CONSTITUTION.md` is required or permitted.
