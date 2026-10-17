# Portable Predicate vectors

`boolean-v1.tsv` is the recorded exhaustive input/output table for the six stateless Boolean/terminal primitives in
[the Predicate semantic contract](../../docs/predicate-semantics.md). Python tests consume it through the existing registered
TRADING and RESEARCH backends; another implementation must consume the same recorded rows without deriving expectations from Python.
It is test data, not equivalence Evidence, an implementation identity, a Runtime binding or product certification.

The UTF-8 file has LF endings, a header and six tab-separated fields: `case_id`, exact `type_id`, exact `semantic_version`,
`left`, `right`, `expected`. Scalars are the case-sensitive tokens `true`, `false`, `null`. For unary operations `left` supplies
`value`; `right` is the fixed unused token `null`. The table order is explicit and stable. No time, floating point or locale is used.

Regenerate with `python scripts/predicate_vectors.py`; verify exact bytes with `python scripts/predicate_vectors.py --check`.
The generator contains explicit truth tables independently of backend implementations. Changes require contract review and atomic
updates of these tests/data; do not regenerate to accept a mismatching implementation.

`integer-refs-v1.tsv` records 216 cases for the six double-reference integer comparisons in
[the integer Contract](../../docs/integer-predicate-semantics.md). It uses the same six-column layout; operands are canonical signed
ASCII decimal integers or `null`, outputs are `true`/`false`/`null`. Case identities use mathematical boundary names.
Regenerate/check with `python scripts/integer_predicate_vectors.py [--check]`. The generator declares each pair's mathematical
relation and an explicit operator truth table independently of Python/Rust backend results. Both directions of unequal examples,
large equal values and all missing positions are retained. It does not change the Boolean corpus or certify a worker protocol.

`decimal-refs-v1.tsv` records 264 independent finite Decimal comparisons under
[the Decimal Contract](../../docs/decimal-predicate-semantics.md), in the same six-column layout. Operands use signed fixed-point
ASCII or `null`; equal numeric values may have different scales or zero signs. Regenerate/check with
`python scripts/decimal_predicate_vectors.py [--check]`. Explicit mathematical relations produce expectations without executing
a backend. The corpus is shared by registered Python backends and the Rust library; it does not extend the diagnostic protocol.
