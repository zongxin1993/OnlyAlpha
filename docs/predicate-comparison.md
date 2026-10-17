# Stateless Predicate comparison diagnostic

This Infrastructure diagnostic compares the six stateless Boolean/terminal types in
[Predicate semantics](predicate-semantics.md) and six reference plus six fixed-literal [integer comparisons](integer-predicate-semantics.md), semantic version `1`. It is a bounded first consumer of the
[Rust implementation](rust-kernel-development.md), governed by ADR 0117 and ADR 0139. It does not select a Runtime
implementation or provide a human/Agent control API. Python remains the admitted official implementation.

## Inputs, identity and ownership

`OnlyPredicateComparisonService` in the Runtime Generation Manager accepts an existing complete immutable work-binding
Evidence, the canonical Calculation Definition, an ordered tuple of nullable Boolean or integer operand tuples matching the exact Definition, and one exact retained
native Distribution Artifact manifest. It neither creates nor changes those authorities. Each observation binds the complete
Definition and fingerprint, all ordered inputs, fresh stateless initial state, nested work ownership, exact Python Generation,
Python implementation fingerprint, native manifest/byte identity, request digest and available native response digest. Diagnostic context schema 3 records `input_encoding`: `NULLABLE_BOOLEAN` keeps JSON Boolean/null, while `INTEGER_DECIMAL_TEXT` records canonical decimal strings/null. Integer inputs and the explicit `literal_configuration.literal` use decimal text; the full Definition and its existing canonical fingerprint remain unchanged. Its bounded integer parameter is captured exactly by Python canonical serialization, never converted through a float. This diagnostic schema is distinct from Calculation semantic version 1 and the unchanged work/Generation identities.

The manager rematerializes the full Definition through a fresh registry containing only the admitted built-in Predicate types.
It requires exact Definition equality and STATELESS capability. Literal admission requires exactly the canonical `literal` and `literal_left` parameters: a non-missing, non-Boolean plain integer within the transport digit budget, and a plain Boolean position. These checks precede Definition fingerprint/context serialization and physical proof. Invalid or oversized literal configuration returns UNAVAILABLE with null Definition/fingerprint, never a truncated configuration; only an admitted complete Definition can produce MATCH/MISMATCH. While holding the existing work-binding read guard, it verifies
the expected binding, physical hosted Generation seal and exact implementation membership. New-work activation does not rebind
an existing comparison; released work, changed ownership, missing/corrupt proof or unavailable artifacts fail without fallback.
The guard must finish successfully before the observation can remain MATCH or MISMATCH.

The native manifest must satisfy the existing SUPPORT-only artifact Contract. Fetch checks the exact manifest, bytes, size,
SHA-256 and ELF header envelope before execution. Native artifacts stay outside Python Generation wheel closure. The diagnostic
requires the exact declared GNU Linux host target; it never substitutes a different build or latest artifact.

## Private local frame

The `predicate-diagnostic` executable uses bounded ASCII stdin/stdout, not files or a network listener. The current private frame is version 3:

```text
ONLYALPHA_PREDICATE_DIAGNOSTIC_V3<TAB><64 lowercase hex context fingerprint><LF>
# Boolean/reference row:
<ordinal><TAB><type_id><TAB><semantic_version><TAB><operand>[<TAB><operand>]<LF>
# Integer literal row:
<ordinal><TAB><type_id><TAB><semantic_version><TAB><literal><TAB><literal_left>[<TAB><operand>]<LF>
```

The context fingerprint binds all inputs above, including Generation and work ownership. Ordinals are contiguous canonical
decimal integers starting at zero. Boolean-family operands are exactly `true`, `false`, `null`. Integer refs operands are `null` or canonical decimal integer text (`0` or `-?[1-9][0-9]*`), selected by the declared type family. Literal rows carry one required non-missing canonical integer followed by exactly `true` or `false` for position, then their one nullable input. The complete echoed row binds both parameters even where different parameters happen to produce equal outputs. Missing/invalid literal or position is a malformed frame, never a nullable scalar. The executable also permits zero/two inputs to report InvalidArity; the service admits exactly one. Boolean values are never integers, and float/string Python inputs are rejected rather than coerced. Integer parsing reuses the Rust library; invalid syntax is a malformed frame, never a missing value or false output. A response echoes the header and every ordered
request row, appending `<TAB>OK<TAB><scalar>` or `<TAB>ERROR<TAB><code>`. Error codes are `UnknownType`, `UnknownVersion`,
`InvalidArity`; rejection is never a nullable scalar. The executable can report zero-operand InvalidArity; the service admits
only correctly typed and sized rows. Type IDs use lowercase ASCII letters, digits, dot and underscore, length 1–192; semantic
versions use ASCII letters, digits, dot, underscore, plus and minus, length 1–32. CR is forbidden and final LF mandatory.
The executable validates the complete frame before emitting output; malformed input exits nonzero without partial success.

The service admits 1–128 rows, at most two operands per row, 64 KiB request and response, and a 64 MiB executable. Each integer operand and required literal has at most 256 decimal digits excluding its sign, solely as a diagnostic transport budget; the Core integer comparison API retains arbitrary digit length. An 851-bit precheck bounds conversion before decimal serialization, so even huge caller integers produce UNAVAILABLE without changing Python's global conversion limit. The entire repeated literal/position configuration counts toward the frame budget. Admission reserves nine output bytes per row before physical proof/execution; a request whose worst-case reply exceeds 64 KiB is UNAVAILABLE without native execution. Both native and Python readers enforce the same scalar grammar and budget. The reply lexer admits canonical Boolean/integer echo tokens; byte-exact comparison detects a well-formed changed identity, operand, order, result or rejection.
One comparison slot per Python process is acquired without waiting; busy returns UNAVAILABLE, with no queue or retry.
Native pipe IO and process completion share a three-second deadline. This is a native-process budget, not a promised latency
for physical Generation proof verification. Bounded nonblocking reads/writes prevent pipe deadlock and unbounded output capture.
A crash, nonzero exit, timeout or oversized output terminates/reaps the direct child and closes its pipes.

## Isolation and outcome

Verified native bytes are copied to a Linux memfd sealed against write, resize and seal changes before execution through the
same descriptor, avoiding mutable-path replacement. The child receives only that descriptor and stdin/stdout, an empty temporary
working directory, a minimal language environment and no inherited unrelated descriptors. Stderr is discarded. The executable
is trusted, approved deployment input: this process arrangement is **not an untrusted-code sandbox**, and a matching digest/header
does not certify compiler provenance, admit code or grant authority. The selected binary has no Broker, network or storage API.

An immutable canonical JSON observation has exactly one status:

- MATCH: both executions succeeded with byte-exact echoed context, ordered identities and nullable outputs.
- MISMATCH: a well-formed response differs in context, identity, order, value or rejection.
- UNAVAILABLE: admission/proof cannot complete, input/frame is invalid, capacity is busy, or execution fails.

An exception when the work-binding guard finishes retracts an otherwise matching result to UNAVAILABLE. Missing proof never
becomes equality. Observations are returned to the technical caller; they are not stored as official Research Evidence,
`OnlyCalculationEquivalenceEvidenceV2`, lifecycle facts, Runtime admission or trading output. No comparison result triggers a
Broker submit, formal publication, activation, fallback or retry. The existing generation ledger remains unchanged.

## Validation boundary

The canonical Rust lane tests both profiles against the independently guarded 30-row Boolean, 216-row integer-reference and 408-row integer-literal corpora (654 cases, 18 exact types). The helper groups literal cases only by exact type plus literal value and position; no different configuration shares a Definition. It passes the exact Cargo-selected
binary to a hermetic Python integration helper that builds real wheels and a physically sealed Python Generation, binds isolated
test work through the existing registry, and runs the installed Python backend against that actual native executable. Controlled
fixture provenance and test namespaces are explicit; this is technical integration evidence, not a deployed upgrade or business UI
acceptance. Deterministic injected native timeout proves child cleanup without waiting for real time advancement.

Contract tests mutate identity, ordering, terminal value, rejection and context; test literal-value/position echo mutations (including unchanged outputs), oversized configuration before serialization/proof, total repeated-configuration budgets, ownership/Generation/proof failures,
activation with retained work binding, released work, restart binding, malformed frames and separation from certified equivalence
Evidence. This scalar slice contains no Decimal, timestamp, rounding, Order, execution, recovery or UNKNOWN-submit semantics.
Those modules require their own vectors and comparison integration before broader R3 coverage or Kernel equivalence can be claimed.
This is a development-period breaking evolution of the private frame and diagnostic context, not a public Gateway/API change.
All current producer/consumer/tests migrate atomically to V3/schema 3. V1/V2 are refused; no legacy loader or compatibility shim is
added. Exact old native artifacts and all historical work/Generation facts remain retained and unchanged. Selecting an old V1/V2
binary with the current V3 service yields UNAVAILABLE, without substitution or rebinding. Diagnostic observations are not persisted
as formal facts, so no stored-history transformation is introduced.

The Gateway protobuf remains the sole cross-node/plugin protocol; this local diagnostic frame does not implement R4.


[Python's integer conversion limit](https://docs.python.org/3.12/library/stdtypes.html#integer-string-conversion-length-limitation)
and [CPython issue 136250](https://github.com/python/cpython/issues/136250) motivate bounded admission independent of interpreter
settings. The local digit/bit checks run before context capture; regression inputs exceed 10,000 digits and exhaust the total frame
budget. No global limit relaxation, floating conversion or oversized-value omission may produce MATCH.
