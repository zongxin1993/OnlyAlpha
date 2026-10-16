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
