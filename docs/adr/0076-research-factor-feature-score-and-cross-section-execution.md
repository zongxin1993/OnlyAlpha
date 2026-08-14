# ADR 0076: Research Factor / Feature / Score Semantics and Deterministic Cross-Section Execution

Status: Accepted

Date: 2026-08-14

## Context

ADRs 0069/0070 made Calculation Definition and Graph the canonical calculation semantic authority. ADR 0073 added exact
RESEARCH backend resolution and deterministic finite-series execution, but the executor was instrument-first and therefore
implicitly required every node to be instrument-isolated. The official Factor plugin had no concrete algorithm. Factor research
could neither distinguish a raw research value from a normalized comparison score nor execute a true cross section without
inventing hidden dependencies or a second authority.

## Decision

Calculation remains the only engineering abstraction and `OnlyCalculationGraphDefinition` remains the only DAG authority.
Indicator is a deterministic named transformation. Feature is an existing Calculation output port identified by node fingerprint
and output name; it gets no store, job, graph or fingerprint. A Factor is a Calculation carrying a research hypothesis. Its primary
output is a raw `FACTOR_VALUE`. A normalized `FACTOR_SCORE` is a different machine-readable port semantic and is constrained to the
closed Decimal interval `[0, 1]`.

Scoring is represented as a `FACTOR` Calculation with `factor_kind=CROSS_SECTION`, not a new `SCORER` kind. The existing Factor
kind already expresses research semantics, while the exact input/output semantic types distinguish scoring from raw Factor
calculation. Adding a kind would expand every Registry and persisted enum reader without adding execution information. Direction
and average-tie method are exact scorer parameters and therefore enter the node identity.

The official Factor plugin owns two RESEARCH-only algorithms at semantic version `1`:

- `onlyalpha.factor.momentum` is a TIME_SERIES Factor. Its two explicit graph inputs consume existing Rolling Return outputs and
  its Decimal formula is `short_weight * return_short + long_weight * return_long`. It propagates upstream nulls and never computes
  an Indicator internally.
- `onlyalpha.factor.cross_section_percentile` is a CROSS_SECTION Factor. It consumes `FACTOR_VALUE` and produces
  `FACTOR_SCORE`. It uses stable instrument identity order, exact event-time cross sections, Decimal average rank, an explicit
  direction, and Definition-owned precision, quantum and rounding.

Research execution is semantic-node-first. Graph topological order selects each node. Indicators and TIME_SERIES Factors execute
independently in stable instrument order and canonical event-time order. CROSS_SECTION Factors execute one exact timestamp plane
at a time over the Dataset's sorted instrument axis. The executor, not the backend, owns instrument/timestamp alignment. Duplicate,
noncanonical or missing exact `(instrument_id, ts_event_ns)` keys fail closed. Backend inputs remain narrow named Arrow arrays.
After execution, outputs are materialized back into the existing `(node_fingerprint, instrument_id)` partition shape and legacy
instrument-then-node observable ordering.

Percentile v1 includes non-null eligible values only. Null inputs remain null at the same instrument/timestamp and are never
filled or dropped. With no eligible values all outputs are null; a singleton receives `0.5`; otherwise ascending average zero-based
rank is divided by `N - 1`. `HIGHER_IS_BETTER` returns that base score and `LOWER_IS_BETTER` returns its Decimal complement.
Every non-null output is quantized and checked in `[0, 1]`.

Type introspection is serialized directly from the canonical `OnlyCalculationTypeDefinition`; Registry enumeration is read-only,
deduplicated across backends and stably sorted. Provider class, path and backend object identity are excluded. These descriptor
APIs do not participate in Calculation fingerprints.

P7.2 Calculation identity, P7.3 Result content/result identities and `(node_fingerprint, instrument_id)` partitions are unchanged.
P7.3 remains the only durable Factor Value and Factor Score authority. P7.4 remains the only Job orchestration authority and keeps
its `load_verified -> RESULT_NOT_FOUND-only execute -> immutable commit` behavior. Existing Definition schema version, Graph schema
version, Dataset identity and official Indicator semantic versions are unchanged, so Indicator-only graph and result identities
remain unchanged.

## Failure Semantics

Invalid semantic definitions and incompatible ports fail during Definition/Graph construction. Dataset corruption fails during
verified admission. Unknown backend/version and invalid providers fail exact resolution. Noncanonical rows, incomplete cross-section
keys or timestamp mismatch fail as Research input incompatibility. Backend exceptions, invalid output names/types/nullability,
and out-of-range scores fail the whole ephemeral execution. No partial result is returned and no durable authority is repaired,
overwritten or recomputed after verified-result corruption.

## Consequences

One verified Dataset and one canonical Graph now express and execute the full
Indicator -> Feature -> Factor Value -> Factor Score slice across processes and physical input layouts. Future composite Factors,
statistics and ML consumers can discover exact ports from the same schema without a Feature Store. Research Runtime remains
unsupported and no Trading Factor lifecycle is imported or instantiated.

## Rejected Alternatives

Rejected alternatives include hiding Indicators inside a Factor; treating every Factor as a `[0, 1]` score; introducing Feature,
Factor or Score stores/jobs/identities; reusing mutable Trading Factor context/lifecycle; using Pandas rank defaults or float64 as
numeric authority; adding a scorer-specific Result Store; ranking in provider/Parquet/dict order; implicit `dropna`, fill,
intersection or timestamp coercion; activating Research Runtime; and implementing Parameter Sweep before closing single-graph
semantics.

## Non-goals

Parameter Sweep, optimization, forward returns, IC/Rank IC and other statistics, Research Result/Artifact, Feature Store,
scheduler/worker/job database, distributed execution, Query/API/Web and Research Runtime activation remain outside this decision.
