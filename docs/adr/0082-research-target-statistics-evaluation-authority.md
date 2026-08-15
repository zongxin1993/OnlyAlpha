# ADR 0082: Research Target, Statistics, and Evaluation Authority

Status: Accepted

Date: 2026-08-15

## Context

ADR 0076 established runtime-neutral Factor semantics and ADR 0079 established Sweep as deterministic multi-Job composition.
Research could produce verified Factor Value/Score series, but it had no explicit future-outcome semantic, no architecture-level
look-ahead boundary, and no durable authority for cross-sectional IC or Rank IC. Treating Forward Return as a Factor would permit
future information to enter Feature graphs. Treating timestamp-level statistics as Calculation output would incorrectly duplicate
one cross-sectional fact into every instrument partition.

## Decision

Calculation kind adds `TARGET` without changing Definition schema v2, Graph schema v1, or the semantic payload of existing
Indicator/Factor nodes. Existing Indicator, Factor and Graph fingerprints remain unchanged. Execution shape remains orthogonal:
Indicator and Target are TIME_SERIES-shaped, while Factor continues to declare `TIME_SERIES/CROSS_SECTION`; backend remains
`RESEARCH/TRADING`, and Runtime remains a separate lifecycle concept.

Target belongs to a Research-only Evaluation Plane and never masquerades as Factor. P7.7 provides one official exact semantic type,
`onlyalpha.target.forward_return@1`, with RESEARCH backend only. It binds `entry_price` and `exit_price` through the existing Dataset
source-binding authority, accepts exact non-negative `entry_offset` and strictly greater `exit_offset`, computes SIMPLE RETURN on each
instrument's canonical closed-bar axis, attributes the result to observation time, and writes insufficient future tail as NULL.
Dataset adjustment semantics are not duplicated.

Feature and Target use independent Calculation Graphs and Calculation identities. Graph validation rejects mixed Feature/Target
graphs, any Indicator or Factor input from Target, and any Target V1 dependency on a Calculation node. Target V1 may consume only
external Dataset sources. Target execution and persistence reuse the existing Research Calculation Executor, immutable Calculation
Result Store, and Job `load_verified -> RESULT_NOT_FOUND-only execute -> commit` authority.

Statistics stops reusing Calculation where the natural result shape changes. An exact Feature Series Reference and Target Series
Reference identify `calculation_fingerprint + node_fingerprint + output_name`; mutable alias is excluded. Verified upstream Results
must reference the same Dataset Snapshot. Alignment uses exact `(instrument_id, ts_event_ns)` intersection and pairwise complete
non-null values; it never fills, truncates, nearest-joins, or infers timestamps.

Statistics Definition v1 supports `IC` and `RANK_IC`, minimum observations, `PAIRWISE_COMPLETE`, `OBSERVED_PAIRWISE`, AVERAGE rank
ties, EQUAL weighting, and Decimal(38) / 1e-12 / ROUND_HALF_EVEN numeric semantics. IC is timestamp-level Pearson correlation across
eligible instruments. Rank IC applies exact Decimal average ranks independently and then Pearson. Valid statistical degeneracy is a
durable NULL fact with explicit `INSUFFICIENT_OBSERVATIONS`, `ZERO_VARIANCE_FEATURE`, or `ZERO_VARIANCE_TARGET` status; invalid
identity, linkage, semantic port, axis, manifest, or upstream authority fails closed.

Statistics identity, Result Content identity, and Statistics Result identity are separate canonical authorities. The Statistics
Result Store is keyed by `statistics_fingerprint`, persists one timestamp-level Parquet table, verifies exact upstream Calculation
Result fingerprints and Dataset linkage, stages and reads back before atomic publication, and performs verified load. Equal content
recommit is idempotent; different content for one identity is `DETERMINISTIC_RESULT_CONFLICT`; corrupt authority is never treated as
missing, repaired, deleted, or overwritten.

## Consequences

- Changing Target horizon changes Target Calculation and Statistics identity, never Feature Calculation identity.
- One durable Target Result can be reused across Sweep cells and multiple Statistics plans.
- TIME_SERIES Factor output can be evaluated cross-sectionally; Factor kind does not select Statistics method.
- Feature → Evaluation is allowed; Evaluation → Feature is structurally forbidden.
- Research and Live Runtime factories remain unsupported.
- P7.7 adds no Optimizer, Research Result/Artifact, cross-Dataset evaluation, calendar horizon, scheduler, experiment database,
  Query/API/Web, or Trading Target backend.

## Rejected Alternatives

Rejected alternatives include Forward Return registered as Factor, a combined Feature/Target Graph, Runtime-specific Factor kinds,
BACKTEST/SIM/LIVE backend enum values, Target/Label Store duplication, pandas/scipy default correlation or ranking, binary-float
durable statistics, per-instrument IC duplication, mutable Statistics overwrite, cross-Dataset timestamp coincidence, implicit
missing-value fill, and Research Runtime activation.
