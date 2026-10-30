# ADR 0147: Time-series association and dependent uncertainty

- Status: Accepted
- Decision: owner requires dependence-corrected uncertainty in the first single-instrument Research
  and approves paired stationary bootstrap as the sole first-release uncertainty method.
- Constitution Impact: NO
- Related: ADRs 0082, 0119, 0143, 0145, 0146.
- Owning contract: [Research time-series statistics](../research-time-series-statistics.md).

## Decision

Introduce a distinct versioned time-series Pearson/Spearman statistic. Existing cross-sectional
IC/RankIC semantics and identities are unchanged. Rust backend Research Statistics owns calculation;
Agent and Web consume exact evidence only. Pair closed-bar Feature values with declared future
returns, purging labels crossing sample boundaries and retaining explicit missing/degenerate states.

Require paired stationary-bootstrap percentile intervals in the first usable single-instrument
Research. Freeze expected block length, replicates, confidence, seed, comparison family and numeric
policy before one-run Human authorization. Bonferroni adjusts only the registered comparison family;
unknown/adaptive historical selection remains explicitly uncorrected. No p-value, scientific PASS
or profitability is inferred. Exact decimal/integer math and explicit deterministic random streams
make results replayable; a seed alone does not imply scientific validity.

The owning contract's technical rules are implementation decisions for this method, rather than
claims that the owner selected every numeric default. Changes to those rules require a new semantic
method version; no mutable configuration may silently reinterpret retained evidence.

## Alternatives and limits

IID uncertainty ignores serial/overlapping-return dependence. HAC/Newey–West is useful for its
proper regression/influence-function estimand, but is not a drop-in correction of both correlations.
One paired bootstrap implementation directly reevaluates both statistics, avoiding a second inference
path in this slice. Weak-dependence/stationarity assumptions and finite-sample limitations remain
visible. Short/gapped/degenerate inputs yield unavailable uncertainty without IID fallback.

This adds no second Research authority, Statistics crate, orchestrator, automatic search or LIVE
permission. It refines ADR 0145/0146 first-release requirements: uncertainty cannot be deferred.
Pure statistical execution is a prerequisite, not completion of the Research/Product vertical slice.
