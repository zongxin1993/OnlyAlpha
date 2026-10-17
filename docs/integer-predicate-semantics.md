# Exact integer Predicate comparison semantics

This Contract describes the existing semantic-version `1` registered double-reference INTEGER Predicate subset. Exact type IDs
are `onlyalpha.predicate.internal.compare.<op>.integer.refs`, with `<op>` exactly `eq`, `ne`, `lt`, `le`, `gt`, `ge`.
Definitions have no parameters, nullable INTEGER `left`/`right`, nullable BOOLEAN `value` with PREDICATE_VALUE semantics,
PROPAGATE missing policy, EVENT_TIME and upstream warmup. Type/version, Definition, implementation fingerprint and Runtime
Generation remain separate existing identities. Boolean, Decimal, string and literal comparison families are not substitutions.

## Admitted values and result

For admitted integer operands, compare exact mathematical values: `eq` equality, `ne` inequality, `lt` less than, `le` less than
or equal, `gt` greater than, `ge` greater than or equal. Any missing operand yields a missing output, including both missing.
A complete false comparison is distinct from missing input. These are calculation scalars, not Authority proof predicates,
certified absence, order permission, LIVE activation or recovery outcomes. There is no mutable state, checkpoint, clock or effect.
Ordered rows, repeated rows and fresh instances preserve their corresponding outputs.

Python TRADING uses admitted non-Boolean Python integers and has no machine-integer-width bound. Existing RESEARCH Arrow integer
transport has its own width envelope: tests exercise int64 explicitly, without claiming arbitrary Python integers fit that array.
This slice does not change Python admission, Research transport, literal parameters or existing executable identity.

The Rust library accepts a private-field borrowed `IntegerOperand` constructed from canonical decimal ASCII text: `0`, or an
optional minus followed by a digit 1–9 and zero or more digits 0–9. Thus plus, leading zero, negative zero, decimal/exponent notation,
whitespace, Unicode digits and Boolean/null words are explicit InvalidInteger errors. Missing is passed as typed `None`, never
constructed by swallowing a parse error. This text is a Rust API/test representation, not a new persistent identity format. The separate [comparison diagnostic](predicate-comparison.md) adopts the same spelling within its explicit transport budget.
Arbitrary digit length is supported within the caller's available string memory; no i64/i128/usize numeric conversion, float,
truncation or rounding is used. Comparison examines sign, magnitude digit count, then equal-length ASCII digits, reversing magnitude
order for negatives. It allocates no big-integer arithmetic structure and requires no external crate.

Wrong type/version resolves to an explicit UnknownType/UnknownVersion error, with no fallback. Evaluation checks exactly two
operands before missing propagation; wrong arity is InvalidArity, never false or missing. PredicateError gains InvalidInteger for
the new parser; existing Boolean methods still return only their original applicable errors. This development-period
Rust API/error variants remain distinct from the separately versioned diagnostic process frame.

## Independent vectors and proof boundary

`test-data/predicate/integer-refs-v1.tsv` contains 216 independently declared cases across the six exact types, including sign,
digit-count order, same-width order, zero/equality, 2^53 adjacent values, signed/unsigned 64-bit and signed 128-bit boundaries,
100/101-digit values, reversed unequal pairs and every missing position. Expectations derive from explicit mathematical relation
labels and truth tables, never captured Python/Rust outputs. `scripts/integer_predicate_vectors.py --check` fails on byte drift;
mutation tests change expectations, precision, owner type, duplicate and truncated rows. Corpus identity is recorded separately
from the Boolean corpus by the existing Rust checker.

Registered Python TRADING and Rust consume every case; registered RESEARCH consumes the int64-representable subset. Tests preserve
replay/reversal and exact bool/null equality; Rust rejects noncanonical spelling, wrong family/version and wrong arity. Linux debug
and release use the same corpus and no profile-specific tolerance. The separate bounded [sealed-generation diagnostic](predicate-comparison.md) compares both scalar subsets. Library correctness and that diagnostic do not establish official Runtime admission, whole-Kernel equivalence,
Decimal arithmetic, persistent identity, recovery/UNKNOWN behavior or latency improvement.

## Engineering evidence and derived guards

- [Rust str ordering](https://doc.rust-lang.org/std/primitive.str.html#impl-Ord-for-str) compares bytes lexicographically. Numeric
  digit-count and sign handling must precede lexical comparison; vectors include 9/10 and negative reverse-order boundaries.
- [Arrow issue 34901](https://github.com/apache/arrow/issues/34901) records scalar/array integer-to-float conversion inconsistencies.
  It motivates exact 2^53-neighbor regressions and explicit int64 transport rather than floating conversion, not adoption of a cast
  or relaxation of current Arrow behavior. Historical upstream behavior is advisory, not OnlyAlpha semantics.

No crate defaults, string hashing, binary floats, worker protocol, runtime switch, compatibility fallback or second Authority is
introduced. Constitution, ADR 0139 and the owning Calculation Contracts remain authoritative.
