# ADR 0113: Common Calculation Algebra Semantic Policy

- Status: Accepted
- Date: 2026-09-03
- Related: ADR 0069, 0070, 0076, 0110, 0112

## Context

ADR 0110 classifies public mathematical Operators and financial Indicators while retaining Calculation and its Graph as the only
execution and DAG authorities. The initial Operator library did not yet define one common numeric, window, missing-value, invalid-domain,
statistical or ranking policy broad enough for reusable algebra. Leaving those choices to individual backends would make semantic identity
depend on pandas, NumPy, binary floating point or streaming implementation defaults.

## Decision

New common-algebra Operators use Decimal precision 28, `ROUND_HALF_EVEN`, and output quantum `0.000000000001`. Every result-affecting
operation executes inside that explicit Decimal context and quantizes its public output. Non-finite inputs are rejected.

A period-N time-series window at observation t is the inclusive interval `[t-N+1, t]`. Complete-window operations return null until N
observations exist and return their first value at observation N. Missing inputs propagate: a pointwise result is null when a required
input is null, and a rolling result is null when any value in its exact active window is null. Cross-section missing values remain null for
their own instrument and do not invalidate the remaining event-time plane.

Invalid result domains are deterministic null outcomes: division by zero and logarithm of a non-positive value return null. Correlation
returns null when either population variance is zero. Variance and covariance divide by N (`ddof=0`). No epsilon substitution is allowed.

Ranks use average ties. Time-series rank ranks the current observation within its exact active window. Cross-section rank constructs each
plane in canonical instrument order as required by ADR 0076. A non-null singleton ranks to `0.5`; otherwise average zero-based rank is
divided by `N-1`, producing `[0, 1]`. Cross-section z-score and demean exclude null instruments from the eligible population, preserve null
positions, and return null for z-score when eligible population variance is zero.

`scale@1` is an explicit pointwise Decimal multiplier with parameter `factor`; it does not infer a population or window. `decay_linear@1`
uses the complete inclusive period window with oldest-to-newest weights `1..N`, normalized by `N(N+1)/2`.

L1 keeps explicit `onlyalpha.operator.*` type IDs under non-FACTOR Calculation kind. Time-series Operators have exact RESEARCH and TRADING
backends. Cross-section Operators are RESEARCH-only in this decision. Stateful TRADING registrations are checkpointable with ordered,
schema-versioned Decimal state; pointwise registrations are explicitly stateless. For identical ordered inputs, RESEARCH batch, TRADING
streaming, and checkpoint/restore continuation must have identical null positions and quantized Decimal outputs.

The new L2 identities use these exact financial semantics: WMA applies oldest-to-newest weights `1..N` over a complete price window; ROC is
`price[t] / price[t-N] - 1`; windowed VWAP consumes an explicit price and volume and returns null for zero aggregate volume; OBV starts at
zero and then adds, subtracts, or ignores volume according to the exact close comparison; Stochastic uses a complete high/low/close window,
returns null for a zero high-low range, defines `%K = (close-low)/(high-low)*100`, and defines `%D` as the complete-window arithmetic mean
of the most recent `d_period` non-null `%K` observations. Their public inputs make price choice explicit rather than selecting close or
typical price inside the implementation.

## Consequences

Common formulas can compose stable public Calculation identities without a second algebra runtime or backend-defined defaults. Existing
Indicator semantic versions remain unchanged. Any alternative partial-window, skip-null, sample-statistic, epsilon, rank, VWAP price, or
Stochastic smoothing policy requires a new explicit semantic identity/version.

## Rejected Alternatives

- pandas/NumPy/TA-Lib defaults as semantic authority.
- Hidden `min_periods=1`, skip-null, sample-statistic, epsilon, or float behavior.
- A new Operator kind, graph, runtime, Feature Store, or Cross-Section TRADING backend.
- Reinterpreting an existing L2 semantic version to conform to the new L1 policy.
