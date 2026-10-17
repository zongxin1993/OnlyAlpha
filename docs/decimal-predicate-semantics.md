# Exact finite Decimal Predicate comparisons

This Contract describes the existing semantic-version `1` double-reference DECIMAL types
`onlyalpha.predicate.internal.compare.<op>.decimal.refs`, where `op` is exactly `eq`, `ne`, `lt`, `le`, `gt` or `ge`.
Definitions retain nullable DECIMAL `left`/`right`, nullable BOOLEAN PREDICATE_VALUE output, no parameters, PROPAGATE missing policy,
EVENT_TIME and upstream warmup. Python registered definitions, implementation manifests and semantic identity are unchanged.

## Values and results

The owning Python `onlyalpha.calculation.value_semantics.OnlyCanonicalValueSemanticsV1` compares finite Decimal values exactly.
Comparison does not quantize to `output_quantum`, round to numeric/context precision or convert through binary floating point.
Different scales with equal mathematical value compare equal: `1.0 == 1.000`; negative and positive zeros compare equal.
This is numerical comparison, not representation identity: trailing zeros, sign-of-zero provenance and canonical serialized bytes
are not rewritten by the comparison API. Any missing operand yields missing, including both missing; complete false remains distinct.
Non-finite and wrong-family complete operands are outside this admitted slice, never mapped to false or missing.

The Rust `decimal_predicate` module supplies private-field borrowed `DecimalOperand` and six `DecimalPredicate` variants. Its input
representation is ASCII fixed-point text: optional minus, then `0` or `[1-9][0-9]*`, optionally followed by a dot and one or more
ASCII fractional digits. Signed zero and trailing fractional zeros are accepted. Plus, leading integer zeros, bare decimal point,
exponent notation, whitespace, underscores, Unicode digits, Boolean/null words, NaN and Infinity fail as `InvalidDecimal`.
Missing is typed `None`; a failed parse never becomes missing. This is a Rust API/test representation, not a new canonical
serialization format, Python constructor grammar, persistent identifier or diagnostic transport. Finite exponent-spelled Python
values can be expressed as fixed point; this slice adds no converter or claim about bounded transport for very large exponents.

Parsing borrows integer/fraction slices, removing only insignificant zeros from its internal comparison view and treating every
zero as nonnegative. It preserves the caller's source string. Magnitudes compare significant integer digit counts, integer ASCII
ordering, then fractional ASCII ordering. Trailing fractional zero removal makes a proper prefix numerically smaller: any extra
suffix ends in a nonzero digit. Negative magnitudes reverse ordering. No arithmetic, allocation, fixed-width coefficient,
exponent expansion, locale, clock, unsafe code or third-party crate is involved. Length is bounded by caller-available string memory.

The reference resolver refuses wrong family, operator, literal layout or version; the literal constructor below resolves its own exact types.
Wrong arity is `InvalidArity`, checked before missing propagation. Adding `InvalidDecimal` to the development-period Rust error enum
requires consumers to account for that variant; it does not extend the V4 diagnostic's wire-error allowlist or change Python APIs.
Repeated evaluation, fresh instances and row reordering preserve corresponding results. These scalars do not prove ownership,
certified absence, formal Calculation equivalence, execution permission or LIVE authority.

## Required DECIMAL literal configuration

The six `onlyalpha.predicate.internal.compare.<op>.decimal.literal` types have one nullable DECIMAL input named `left`,
required finite DECIMAL parameter `literal` and BOOLEAN `literal_left` defaulting to false. Their output, missing, time and
warmup metadata match the reference types. Existing Python schema normalization remains authoritative and is unchanged; it rejects
missing/non-finite literals and non-Boolean positions. This Rust slice does not reimplement that schema or add raw parameter coercion.

`DecimalLiteralPredicate` consumes an already parsed `DecimalOperand` and explicit bool, retaining them as private immutable
configuration. With false position it compares input to literal; true compares literal to input. It checks exactly one input
before missing propagation and delegates to `DecimalPredicate`. A required literal cannot be missing or non-finite in the typed
constructor. No new parser, arithmetic, rounding, allocation, error variant, dependency or state is added. Direction and literal
value are retained even if missing inputs or symmetric equality happen to give the same outputs. This numeric view is not a
replacement for the complete Definition/parameter fingerprint; it grants no new semantic identity or execution permission.

`test-data/predicate/decimal-literal-v1.tsv` contains 504 cases derived from the reference corpus's independent mathematical
relations. Each non-missing side becomes the literal in turn; rows with a missing required literal are excluded, while nullable
inputs remain. `scripts/decimal_literal_vectors.py --check` guards exact bytes. Output, precision, owner, literal, direction,
duplicate and truncation mutations must fail. Python TRADING and Rust consume every row with repetition, reversal and fresh
instances. Python tests retain the normalized literal tuple and explicit position, check omitted position against false, vary
ambient precision and test the common Arrow decimal128(38,18) input/literal envelope with exact output cardinality. Rust rejects
wrong family/layout/operator/version and wrong arity before missing; compile-fail coverage prevents a missing required literal.

## Independent vectors and validation

`test-data/predicate/decimal-refs-v1.tsv` contains 264 independently declared cases across all six types. Expectations derive from
explicit EQ/LT/GT/NULL mathematical relations, not either backend. Cases include signed zero, unequal scales, sub-quantum differences,
2^53 neighbors, coefficients beyond default Decimal precision, very large integers and tiny/long fractions, reversed unequal pairs
and every missing position. `scripts/decimal_predicate_vectors.py --check` binds exact bytes; mutations of outputs, precision,
owner type, duplicate and truncation fail its guard. Rust validation runs the guard and retains the corpus digest separately.

Registered Python TRADING and Rust consume every vector with repeat/reversal/fresh-instance checks. Python tests vary ambient
Decimal precision between 2 and 50. RESEARCH uses only the explicit common Arrow decimal128(38,18) envelope, without rounding,
and checks output cardinality and exact Boolean/null values. This does not certify arbitrary Python Decimal values in Arrow.
Rust tests additionally reject malformed values, wrong identities/versions/arity and wrong scalar types, in Linux debug and release.

The existing V4 sealed-generation diagnostic remains limited to its 26 Boolean/integer/string types and 904 vectors. These six
reference types and six literal types below are library-only until a separate bounded transport/diagnostic consumer is implemented and verified. This slice
provides no Decimal arithmetic/rounding, Runtime activation, state/recovery, deployment-upgrade or latency proof.

## Engineering evidence and derived protection

- [Python Decimal documentation](https://docs.python.org/3.12/library/decimal.html): Decimal construction retains digits independently
  of arithmetic precision; numerical comparison must not become quantization or binary-float conversion. Tests preserve scale and
  beyond-context differences without copying external implementation code.
- [CPython issue 46271](https://github.com/python/cpython/issues/46271) records historical NaN comparison behavior. The existing
  OnlyAlpha finite-value boundary is retained: NaN/sNaN/Infinity are rejected explicitly rather than adopting a library's special
  comparison/trap default. This is failure-history guidance, not a claim of an unresolved Python bug.

Constitution, ADR 0139 and the owning Calculation Contracts remain authoritative. No external library default defines OnlyAlpha semantics.
