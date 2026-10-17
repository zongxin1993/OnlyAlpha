# Internal Boolean Predicate semantics

This contract spells out the existing semantic-version `1` Boolean subset of `onlyalpha.calculation.predicate` and its registered
TRADING/RESEARCH implementations. It does not introduce a new semantic version or change Strategy admission. The owning type
reference is `(PREDICATE, onlyalpha.predicate.internal.<name>, "1")`; implementation manifests/fingerprints and Runtime Generation
remain separate identities under the existing Calculation and Runtime contracts. An unknown name/version fails exact registry
resolution; another registered type/version is never a fallback.

## Scope and input/output inventory

`boolean.and`, `boolean.or` accept nullable Boolean `left`/`right`. `boolean.not` and `terminal.eligibility`,
`terminal.entry_signal`, `terminal.exit_signal` accept nullable Boolean `value`. Each returns one nullable Boolean `value`.
There are no parameters. Existing definitions retain EVENT_TIME, PROPAGATE and upstream warmup metadata. Terminal outputs retain
their distinct ELIGIBILITY / ENTRY_SIGNAL / EXIT_SIGNAL semantic roles; they are not interchangeable graph owners.

The admitted scalar domain is exactly `true`, `false`, missing. Strings, numbers and malformed worker frames are outside this
scalar slice; these vectors do not certify their admission or any transport/parser. Missing is neither a trading decision nor
certified absence. The strong three-valued tables below are calculation logic, not the Authority proof predicate convention
where `False` requires complete non-match proof. An incomplete proof may not be silently converted to a complete scalar input.

| left | right | AND | OR |
|---|---|---|---|
| true | true | true | true |
| true | false | false | true |
| true | missing | missing | true |
| false | true | false | true |
| false | false | false | false |
| false | missing | false | missing |
| missing | true | missing | true |
| missing | false | false | missing |
| missing | missing | missing | missing |

NOT swaps true/false and preserves missing. Each terminal preserves its admitted scalar unchanged, including missing.
A missing terminal does not authorize an entry, an order, LIVE activation or a retry. Downstream Strategy/Runtime authorities
continue to decide admission/execution; evaluating these primitives publishes no official facts or external effects.

## State, ordering and error boundary

These six primitives are STATELESS and declare no checkpoint schema. Ordered input rows produce equally ordered output rows;
repeated rows are repeated calculations, not duplicate event admission. Prefixes, reversed row order and fresh instances cannot
alter the result of a given row. There is no random, wall-clock, market/provider or external-account input. Reconstructing a fresh
instance therefore suffices for this scalar slice; it is not proof of transaction crash/recovery or deployment upgrade.

Errors at exact type resolution remain explicit errors, never Boolean false. This subset has no monetary arithmetic, Decimal
rounding, finite integer width, timestamp conversion, canonical digest, Broker submit, cancellation or UNKNOWN-submit transition.
Those obligations must be specified/tested in their owning later slices; this table provides no evidence about them.

## Recorded vectors and verification

[test-data/predicate/boolean-v1.tsv](../test-data/predicate/boolean-v1.tsv) records all 30 admitted cases, including all nine pairs
for each binary operator and each of three values for every unary/terminal primitive. The independent explicit-table generator
and exact-byte guard prevent accidental fixture drift. Tests compare each registered backend against these expectations using
exact typed Boolean/null equality, repeated updates, reversed input order and fresh instances. They also reject wrong type/version
resolution. Source language, package version and executable artifact identity are not erased to obtain equality.

The corpus remains offline test input. It does not create formal Calculation equivalence Evidence or grant an implementation
admission/activation. Rust comparison integration and immutable executable provenance remain governed by ADR 0139 and ADR 0117.

The separate [Boolean/string equality Contract](scalar-equality-semantics.md) covers eq/ne reference and literal types. Their missing propagation differs from logical AND/OR dominance; the six logical/terminal identities above do not expand to those comparisons.
