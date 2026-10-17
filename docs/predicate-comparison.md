# Stateless Predicate comparison diagnostic

This Infrastructure diagnostic compares only the six stateless Boolean/terminal types in
[Predicate semantics](predicate-semantics.md), semantic version `1`. It is a bounded first consumer of the
[Rust implementation](rust-kernel-development.md), governed by ADR 0117 and ADR 0139. It does not select a Runtime
implementation or provide a human/Agent control API. Python remains the admitted official implementation.

## Inputs, identity and ownership

`OnlyPredicateComparisonService` in the Runtime Generation Manager accepts an existing complete immutable work-binding
Evidence, the canonical Calculation Definition, an ordered tuple of nullable Boolean operand tuples, and one exact retained
native Distribution Artifact manifest. It neither creates nor changes those authorities. Each observation binds the complete
Definition and fingerprint, all ordered inputs, fresh stateless initial state, nested work ownership, exact Python Generation,
Python implementation fingerprint, native manifest/byte identity, request digest and available native response digest.

The manager rematerializes the full Definition through a fresh registry containing only the admitted built-in Predicate types.
It requires exact Definition equality and STATELESS capability. While holding the existing work-binding read guard, it verifies
the expected binding, physical hosted Generation seal and exact implementation membership. New-work activation does not rebind
an existing comparison; released work, changed ownership, missing/corrupt proof or unavailable artifacts fail without fallback.
The guard must finish successfully before the observation can remain MATCH or MISMATCH.

The native manifest must satisfy the existing SUPPORT-only artifact Contract. Fetch checks the exact manifest, bytes, size,
SHA-256 and ELF header envelope before execution. Native artifacts stay outside Python Generation wheel closure. The diagnostic
requires the exact declared GNU Linux host target; it never substitutes a different build or latest artifact.

## Private local frame

The `predicate-diagnostic` executable uses bounded ASCII stdin/stdout, not files or a network listener. Version 1 is:

```text
ONLYALPHA_PREDICATE_DIAGNOSTIC_V1<TAB><64 lowercase hex context fingerprint><LF>
<ordinal><TAB><type_id><TAB><semantic_version><TAB><operand>[<TAB><operand>]<LF>
```

The context fingerprint binds all inputs above, including Generation and work ownership. Ordinals are contiguous canonical
decimal integers starting at zero. Operands are exactly `true`, `false`, `null`. A response echoes the header and every ordered
request row, appending `<TAB>OK<TAB><scalar>` or `<TAB>ERROR<TAB><code>`. Error codes are `UnknownType`, `UnknownVersion`,
`InvalidArity`; rejection is never a nullable scalar. The executable can report zero-operand InvalidArity; the service admits
only correctly typed and sized rows. Type IDs use lowercase ASCII letters, digits, dot and underscore, length 1–192; semantic
versions use ASCII letters, digits, dot, underscore, plus and minus, length 1–32. CR is forbidden and final LF mandatory.
The executable validates the complete frame before emitting output; malformed input exits nonzero without partial success.

The service admits 1–128 rows, at most two operands per row, 64 KiB request and response, and a 64 MiB executable.
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

The canonical Rust lane tests both profiles against the independently guarded 30-row corpus. It passes the exact Cargo-selected
binary to a hermetic Python integration helper that builds real wheels and a physically sealed Python Generation, binds isolated
test work through the existing registry, and runs the installed Python backend against that actual native executable. Controlled
fixture provenance and test namespaces are explicit; this is technical integration evidence, not a deployed upgrade or business UI
acceptance. Deterministic injected native timeout proves child cleanup without waiting for real time advancement.

Contract tests mutate identity, ordering, terminal value, rejection and context; test ownership/Generation/proof failures,
activation with retained work binding, released work, restart binding, malformed frames and separation from certified equivalence
Evidence. This scalar slice contains no Decimal, timestamp, rounding, Order, execution, recovery or UNKNOWN-submit semantics.
Those modules require their own vectors and comparison integration before broader R3 coverage or Kernel equivalence can be claimed.
The Gateway protobuf remains the sole cross-node/plugin protocol; this local diagnostic frame does not implement R4.
