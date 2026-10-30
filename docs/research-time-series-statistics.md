# Research time-series association and uncertainty

Authority: derived from the Constitution, ADRs 0082, 0119, 0145–0147. Backend Research Statistics owns
these calculations; Agent, chart, Query and Web only consume their evidence. This contract introduces
`ONLYALPHA_TIME_SERIES_ASSOCIATION_V1`; it does not reinterpret cross-sectional IC/RankIC V1.

## Inputs, applicability and identity

The first method evaluates one instrument's closed, equally spaced bars within an explicit half-open
UTC nanosecond interval. A Feature and a forward-return Target are paired at observation time.
The horizon is a positive integer number of bars. A label whose exit time reaches or exceeds the
interval end is excluded, including at development/out-of-sample/protected-holdout boundaries.
Feature warmup may consume earlier approved inputs; Target never becomes a Feature input.

Every plan binds exact Dataset, Feature Result, Target Result, Factor Revision and approved study
fingerprints. These are references, not certificates: the owning Research admission/executor must
verify the complete immutable upstream artifacts, graph/horizon/source relations, permissions,
approved proposal and generation before calling the pure executor. Arbitrary caller-supplied hashes
cannot authorize execution or publication. The pure executor neither issues nor persists Evidence.

The plan also binds interval, bar spacing, horizon, expected block length, replicate count,
family confidence, an explicit 32-byte seed and the complete declared comparison family.
Each family member names interval, horizon and metric (Pearson or Spearman). Both current metrics
must belong to that family; duplicates and invalid scopes are rejected. Canonical family order is
interval start/end, horizon, then metric name. Family size is derived, never a caller-supplied count.
Research owns proving that the registered family contains every promised comparison, including
other intervals/horizons. An altered seed, method, boundary, family or configuration is a new plan.

Input observations are strictly ordered and unique, inside the interval and aligned to its bar grid.
Absent timestamps remain gaps. Feature/Target values are nullable finite base-ten decimal strings:
optional minus, integer digits and optional fraction; no exponent/plus/whitespace, at most 38 digits,
at most 18 fraction digits and 20 integer digits. Numerically equal encodings normalize to the same
value; zero has no sign. The result binds the complete normalized input digest as well as the plan
digest. It cannot be reused for another series simply because declared references match.

## Point estimates and diagnostics

Pearson uses exact integer moments `C=n*sum(x*y)-sum(x)*sum(y)`,
`A=n*sum(x*x)-sum(x)^2`, `B=n*sum(y*y)-sum(y)^2`, and `C/sqrt(A*B)`.
Spearman assigns exact average ranks to ties in each complete paired sample, then uses Pearson.
Final correlations are rounded once to quantum `1e-12`, ties to even, by integer-square comparisons;
no binary floating-point approximation or environment Decimal context enters identity.

Diagnostics retain expected/observed grid rows, boundary exclusions, complete pairs, missing Feature,
missing Target and remaining axis gaps. Complete-pair count is not an independent effective sample
size. At least two pairs are needed for a point estimate. Zero Feature/Target variance produces a
typed absent number, never zero, NaN, infinity or an inferred lack of predictive effect.

## Sole first-release uncertainty method

Use **paired stationary bootstrap, percentile intervals** (Politis–Romano). Resample the observed
Feature/Target pair together, retaining their within-pair relation. For each replicate, choose a
uniform initial index; thereafter start a new uniform index with probability `1/L`, otherwise move
to the next index modulo sample length. `L` is the plan's expected block length, not a fixed block
size. Recompute Spearman ranks within every resample. Do not separately resample the two columns,
shuffle individual rows, reuse original ranks or use a naive IID standard error.

Inference requires one contiguous complete-pair window after excluding cross-boundary labels and
trimming incomplete edges. Interior missing pairs or absent bars inside that window yield unavailable inference;
they are not compressed into a fictitious equally spaced sequence. Full-interval gap counts remain
visible even when missing excluded-tail/edge rows do not affect that retained window. Point estimates may still be
reported with their diagnostics. Require `L >= max(2, horizon+1)`, at least 40 complete pairs and
at least `10*L` pairs. These are explicit operational sufficiency floors, not proofs of stationarity,
independence, an optimal block length or adequate power. Longer-memory dependence can exceed `L`.

Family-wise nominal coverage uses Bonferroni: for family confidence `c` in basis points and `m`
registered comparisons, each tail probability is `p=(10000-c)/(20000*m)`. Sort the `R` quantized
replicate estimates. Lower index is `max(1,floor((R+1)*p))`, upper index
`min(R,ceil((R+1)*(1-p)))`, with one-based indices. Require `R*p >= 20`; insufficient Monte Carlo
tail resolution yields unavailable inference. Coverage 8000–9900 bps and 400–8192 replicates are
supported; the proposed product default is 9500 bps, 4096 replicates, subject to the full family's
tail-resolution requirement. No adaptive increase/retry follows inspection of results.

All planned replicates are attempted exactly once. Any undefined replicate (zero variance) makes
that metric's interval unavailable, with a count; it is not dropped/replaced. A constant replicate
distribution is also unavailable, not a zero-width claim of certainty. Point-estimate degeneracy,
insufficient pairs/blocks, missing grid/pairs, tail resolution, replicate degeneracy and degenerate
distribution are distinct statuses. Each metric's status is independent of the other.

The reproducible random stream is `SHA256_COUNTER_UNIFORM_V1`: for replicate index starting at zero,
hash ASCII `ONLYALPHA_STATIONARY_BOOTSTRAP_V1`, the 32 seed bytes, the replicate index as big-endian
u64 and the draw counter (zero-based, big-endian u64). The first 8 digest bytes are a big-endian u64.
Uniform `[0,b)` rejects values below `2^64 mod b` before applying modulo. Each rejection consumes
one draw; exhaustion of 64 draws for one selection is an error, never a fallback. The initial
selection consumes one uniform draw. Each subsequent row consumes a uniform `[0,L)` draw and,
only when zero, a uniform `[0,n)` draw. A fresh stream is used per replicate; both metrics share
the exact same paired resample. Every bound and counter is independent of wall time/OS entropy.

Hard resource limits are 4096 observations, 32 declared comparisons and 8,388,608 observation ×
replicate operations per evaluation. Invalid/malformed plans or numbers fail before computation;
these bounds do not authorize source/date changes or silent truncation. Resource estimates and
the frozen plan are presented before the second Human confirmation in the later Product slice.

## Interpretation, repeated research and protected samples

Intervals are approximate under weak-dependence/stationarity/regularity assumptions, not guaranteed
finite-sample coverage or a stationarity certification. The report states those assumptions and
the chosen block length, horizon, family, nominal confidence, resamples, seed and missingness.
An interval excluding zero is conditional evidence, not scientific Qualification, profitability or
permission for Backtest/SIM/LIVE. V1 does not manufacture a p-value from bootstrap signs, turn a
bootstrap confidence level into a posterior probability, or declare a universal factor PASS.

The Bonferroni scope is **only the preregistered comparison family**. It does not correct an unknown
number of historical/adaptive trials. The owning study/Research records attempted proposals,
negative results and sample access. Changes after seeing results are exploratory new studies;
repeatedly viewed samples cannot be relabelled independent holdout. Absent complete trial/access
facts, evidence must state that across-study selection is uncorrected and cannot claim confirmatory
significance. Protected holdout release/access requires its owning durable policy before the UI
can present a confirmatory evaluation. This pure module grants no holdout access.

## Integration and acceptance

The backend internal implementation consumes exact supplied series and returns deterministic
point/interval results and digests. No new crate/service, API, mutable metric store, Python numeric
fallback, Generation activation or automatic research loop is introduced by this foundation.
Later Research integration must bind its output through the existing immutable Result/Artifact
authority with a new explicitly supported schema; V1 cross-sectional identities stay unchanged.

Acceptance covers hand-derived Pearson/tied-rank vectors, scale/sign invariance, quantization,
independent seeded bootstrap vectors, paired circular blocks and reranking, deterministic replay,
source/plan mutation, chronological boundary exclusion, missing axes/pairs, short/constant samples,
degenerate resamples, family correction, bounded work and corrupt payload denial. It does not claim
nominal empirical coverage from a few simulations or substitute unit tests for the real Research UI.

References are advisory mathematical evidence: [Politis–Romano (1994)](https://doi.org/10.1080/01621459.1994.10476870),
[arch confidence intervals](https://bashtage.github.io/arch/bootstrap/confidence-intervals.html),
[arch issue 800: p-values are a separate inference problem](https://github.com/bashtage/arch/issues/800).
