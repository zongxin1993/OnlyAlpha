# ADR 0073: Research Calculation Backend and Deterministic Execution

Status: Accepted

Date: 2026-08-13

## Context

ADR 0069/0070 established backend-neutral Calculation semantics and exact Registry resolution. ADR 0072 established immutable,
provider-independent Historical Bar Dataset Snapshots. Research still lacked an execution boundary that could consume those facts
without constructing Trading Runtime authorities. The official ATR `@1` contract also declared one value input while its Trading
implementation consumed high, low and previous close.

## Decision

Research and Trading backends share one `OnlyCalculationTypeDefinition` and semantic version. Implementations may differ, but the
observable output contract may not. Research providers implement a narrow finite columnar `execute(definition, inputs)` SPI and are
resolved through the existing Registry with exact `kind + type_id + semantic_version + RESEARCH`; no version or TRADING fallback
exists. Concrete algorithms remain in the official Indicator plugin. Calculation Core remains Arrow-, Dataset- and
Research-independent.

Research execution admits data only through `load_verified_table`. The store verifies the exact manifest, Definition and Dataset
Schema fingerprints, snapshot identity, every partition byte/semantic hash and row count, global content hash/count and exact Arrow
schema before returning the Snapshot and Arrow Table. Corruption fails closed; execution never rebuilds, repairs or falls back to
Historical Cache.

Dataset source binding is explicit and fail closed. Supported Historical Bar v1 sources map exact bar columns. Type, nullability,
TIME dimension, semantic role and unit contracts are checked without coercion, filling or dropping values. A backend receives only
the inputs declared by its Definition.

The executor processes instruments in stable identity order, rows in canonical event-time order, and nodes through the Graph's
existing `ordered_nodes` authority. Each instrument owns an isolated finite series. Node outputs are validated for exact names,
types, row counts and nullability before they can feed dependent nodes. Any admission, resolution, backend or validation failure
fails the whole ephemeral execution; no partial success object is returned.

Official RESEARCH backends use Arrow column input plus deterministic O(n) Python Decimal kernels. They preserve warmup, missing
value, EVENT_TIME, output quantum/rounding and multi-output semantics characterized against independent incremental Trading
backends. `atr@1` remains unchanged for backward compatibility and has no RESEARCH registration. `atr@2` declares high, low and
close explicitly and is supported by both Trading and Research backends.

Research Calculation identity is canonical SHA-256 over schema version, Dataset Snapshot fingerprint, Calculation Graph
fingerprint and `RESEARCH` backend kind. Runtime, Engine, Cluster, Job, process, path, time, worker and plugin implementation metadata
are excluded. Behavior changes require a Calculation semantic-version change.

P7.2 produces an immutable in-memory execution object tied to node fingerprint, instrument and event timestamp. It does not create
a Calculation Store, Result Store, Artifact, Job, scheduler or product Runtime. The Research Runtime factory remains unsupported.
The empty official Factor provider remains valid; no cross-sectional framework is invented without a concrete Factor.

## Consequences

The same verified Snapshot and canonical Graph now produce the same Research identity and exact canonical outputs across processes
and input ordering. Research does not depend on Engine, Runtime, Cluster, Strategy, Broker, Account or Trading state authorities.
Future parallel execution may use instrument partitions only if it preserves these exact semantics.

## Rejected Alternatives

Rejected alternatives include replaying bars through Trading Runtime or `update_bar`, falling back to TRADING providers, Pandas or
float64 as numeric authority, implicit Dataset coercion/repair, global rolling across instruments, mutating `atr@1`, placing concrete
algorithms in Core, and introducing a durable result/cache or premature Research Runtime.
