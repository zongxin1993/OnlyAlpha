# OnlyAlpha L1 Operators

This public L1 library exposes exact Calculation registrations through `onlyalpha.calculations` and a versioned management provider through
`onlyalpha.quant_assets`. Install it from a checkout with `uv add --editable /path/to/operators` or
`python -m pip install -e /path/to/operators`; released environments may use a wheel or package index.

The management provider ID is `onlyalpha.operator.library`. Any implementation content change requires a new provider version; any semantic
change also requires a new Operator semantic version. Hot-plug refresh affects new catalog snapshots only.

## Common algebra inventory

The public semantic policy is frozen by ADR 0113. This inventory is a development-facing Alpha101-style vocabulary coverage aid, not a
Factor catalog or product authority.

| Primitive family | Status | B1 support / reason |
|---|---|---|
| add, subtract, multiply, divide | Supported | Exact pointwise Decimal; divide-by-zero is null |
| abs, sign, log | Supported | Exact unary Decimal; invalid log domain is null |
| delay, delta | Supported | Inclusive ordered history and checkpoint recovery |
| rolling sum/mean/min/max/std/var | Supported | Complete window, null propagation, population statistics |
| rolling correlation/covariance | Supported | Complete paired window, population statistics |
| time-series rank | Supported | Average ties, normalized `[0, 1]` |
| scale, decay linear | Supported | Explicit scale factor and oldest-to-newest linear weights |
| cross-section percentile/rank/z-score/demean | Supported (Research) | Stable plane order; per-instrument null propagation |
| group/industry rank, demean, z-score | Deferred | Requires versioned classification membership authority |
| winsorize and generic normalize | Deferred | P2/P1; no B1 composition need proves another semantic identity |

Every supported time-series primitive has RESEARCH and TRADING implementations. Cross-section primitives intentionally have no B1
TRADING backend.
