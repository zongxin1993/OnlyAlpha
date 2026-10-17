# Boolean and UTF-8 string Predicate equality

This Contract describes the existing semantic-version `1` types
`onlyalpha.predicate.internal.compare.<op>.<family>.<layout>`, where `op` is exactly `eq` or `ne`, `family` is exactly `boolean`
or `string`, and `layout` is exactly `refs` or `literal`. These eight registered types are separate from the Boolean logical/terminal
subset and integer/Decimal comparisons. Python Definitions and implementation identity are unchanged by this Rust library slice.

## Scalars, configuration and missing values

The reference layout has nullable typed `left` and `right` inputs and no parameters. The literal layout has nullable typed `left`,
a required non-missing normalized scalar parameter `literal` of the same family, and BOOLEAN `literal_left` defaulting to false.
Owning Python parameter-schema normalization remains authoritative; the Rust typed constructors consume already normalized values,
not arbitrary raw Python parameter objects. True position compares literal to input, false compares input to literal. Although eq/ne
are symmetric, configuration remains explicit and is not erased or merged because outputs happen to be equal.

Definitions retain PREDICATE_OPERAND inputs, nullable BOOLEAN PREDICATE_VALUE output, PROPAGATE missing policy, EVENT_TIME and upstream
warmup. Any missing operand produces missing, including two missing reference operands. Complete `false` is distinct from missing.
In particular Boolean equality does not use AND/OR's dominance rules: `false == missing` and `false != missing` both yield missing.
These are calculation scalar results, not proof of Authority match/non-match, certified absence, terminal permission or LIVE authorization.

For complete Boolean operands, eq is true only for true/true or false/false; ne is the inverse. Numeric zero/one are outside the typed
Boolean slice. For complete strings in the common valid-UTF-8 envelope, eq compares the exact Unicode scalar sequence, equivalently
its unique UTF-8 bytes; ne is its inverse. No case folding, locale collation, trimming, NFC/NFKC normalization, NUL termination or
replacement-character decoding occurs. Empty string and text `null` are ordinary values, distinct from missing. Embedded NUL,
controls, non-BMP characters, combining marks and variation selectors are retained. Equal prefixes never imply equal full strings.

The existing Python str domain can contain unpaired surrogates; those are outside Rust str and this common-envelope proof. This
slice does not change Python admission, replace/drop those values, claim arbitrary byte comparison or introduce their transport.
A later transport must reject values it cannot represent explicitly; this corpus is not permission for lossy conversion.

## Rust API and scope

`boolean_equality` exposes `BooleanEqualityPredicate` and `BooleanLiteralEqualityPredicate`; `string_equality` exposes their
String counterparts. Exact refs/literal family IDs and version 1 resolve separately. Unknown family, layout, operator or version
is an explicit UnknownType/UnknownVersion error, without fallback. Ref evaluation checks exactly two inputs and literal evaluation
exactly one before missing propagation; wrong arity is InvalidArity. Required Boolean literals use bool and string literals borrow
str, so missing/wrong-family literals cannot inhabit these constructors. Literal fields are private immutable configuration.

The implementation uses std equality and typed nullable values only. String storage is borrowed, not normalized, cloned or parsed;
length is bounded by the caller's available memory, without a new transport cap. There is no clock, mutable execution state,
checkpoint, persistence, digest, Broker or effect. Repeated/reordered rows and fresh instances preserve corresponding outputs.
Wrong scalar families are rejected by the Rust type system, with compile-fail examples. No generic evaluator/worker framework,
crate, runtime selector or canonical identity format is added.

The [sealed-generation diagnostic](predicate-comparison.md) admits these eight types through its V4/schema-4 bounded private frame.
It retains exact family/literal/position identity and uses strict lowercase UTF-8 hex for string transport, with an independent
4096-UTF-8-byte per-value diagnostic budget and the existing frame budget. These caps do not narrow the Core borrowed-str API.
The equality types remain separate from the Boolean logical/terminal resolver. Neither library nor diagnostic correctness proves
whole-Kernel equivalence, formal Calculation certification, deployment recovery or latency.

## Independent vectors and failure guards

`test-data/predicate/scalar-equality-v1.tsv` records 250 cases: 42 Boolean and 208 string, across all eight exact types. Expectations
come from explicitly declared EQ/NE/NULL relations and truth tables, never backend output. For each valid required-literal case,
each non-missing reference side becomes the fixed literal in turn; missing literal parameters are not generated. String unequal
pairs also appear reversed. Test-only string tokens are `utf8:` plus lowercase UTF-8 hex; missing is the distinct word `null`.
Hex keeps NUL/tab/newline test values lossless in ASCII TSV; it is shared test encoding, also reused by the bounded diagnostic without becoming a Gateway or persistent format.

The independent byte guard rejects output, owner, input, literal, direction, Unicode spelling, duplicate and truncation mutations.
Registered Python TRADING and RESEARCH consume all cases, with strict Boolean/null results, repetition, reversed order and fresh
instances; omitted false position matches explicit false. Rust consumes the same corpus in Linux debug and release. Additional
Rust tests reject wrong family/layout/operator/version and validate arity before missing for every type. Corpus digest is recorded
separately by the existing frozen-source Rust checker. These are technical test/build observations, not formal equivalence Evidence.

## Engineering evidence

- [Rust str invariant](https://doc.rust-lang.org/std/primitive.str.html#invariant) requires valid UTF-8. Use borrowed typed str and
  explicit common-envelope tests; do not use unsafe construction or claim arbitrary Python strings fit this API.
- [Arrow equal](https://arrow.apache.org/docs/python/generated/pyarrow.compute.equal.html) is the existing Research kernel; retain
  exact nullable results against independent facts rather than treating its output as the oracle.
- [Arrow issue 51225](https://github.com/apache/arrow/issues/51225) records historical normalization-form behavior and is closed.
  It motivates composed/decomposed and compatibility-spelling regressions, not a claim of a current equal-kernel defect. Implicit
  normalization is rejected because it changes this owning Contract, regardless of a library normalizer's version or behavior.

Constitution and ADR 0139 remain authoritative; upstream behavior is engineering evidence only.
