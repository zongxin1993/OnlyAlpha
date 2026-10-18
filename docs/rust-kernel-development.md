# Linux Rust Kernel development

The library in `crates/onlyalpha-kernel/core/` implements the six stateless Boolean/terminal primitives in
[Predicate semantics](predicate-semantics.md), the six reference plus six fixed-literal [integer comparisons](integer-predicate-semantics.md), eight [Boolean/string equality types](scalar-equality-semantics.md), and six reference plus six fixed-literal [finite Decimal comparisons](decimal-predicate-semantics.md). It owns no Runtime selection, official state, persistence, Broker access or effects.
Python remains the admitted implementation; building this library grants no execution or LIVE permission. Managed comparison and
historical artifact retention remain governed by ADR 0139 and ADR 0117. The private local diagnostic process frame is defined in [Predicate comparison](predicate-comparison.md). No FFI, cross-node transport, plugin worker or async runtime is introduced.

## Predicate responsibility map

ADR 0139 section 1.1 aligns modules by responsibility, not by matching Python and Rust file trees. Paths below are relative to the
repository root. They identify source owners and consumers, not a second semantic specification or migration/admission status.

| Responsibility | Python location | Rust location / boundary |
| --- | --- | --- |
| Backend-neutral type definitions, parameters and semantic references | `src/onlyalpha/calculation/predicate.py` | Exact type/version resolution in `crates/onlyalpha-kernel/core/src/{predicate,integer_predicate,boolean_equality,string_equality}.rs`; these typed subsets do not replace the full Python registry/resolver |
| Scalar TRADING evaluation | `src/onlyalpha/runtime/trading/predicate.py` | The same four Rust modules implement the selected typed scalar semantics; they do not provide Python backend registration or Runtime composition |
| Exact finite Decimal reference/literal comparison | `src/onlyalpha/calculation/value_semantics.py` via the registered Predicate backends | `crates/onlyalpha-kernel/core/src/decimal_predicate.rs` implements the twelve typed comparisons, with immutable literal/position configuration; no arithmetic or diagnostic transport |
| Batch RESEARCH evaluation | `src/onlyalpha/research/calculation/predicate.py` | Python/Arrow backend retains its responsibility; scalar Rust modules are not a batch backend or Research execution path |
| Isolated exact-artifact comparison orchestration | `packages/onlyalpha-runtime-generation-manager/src/onlyalpha_runtime_generation_manager/predicate_comparison.py` (`OnlyPredicateComparisonService`) | `crates/onlyalpha-kernel/core/src/bin/predicate-diagnostic.rs` is the private diagnostic entry, outside the library's canonical semantics; its allowlist remains bounded by the comparison Contract |
| Independent shared expected values | `test-data/predicate/`, regenerated and byte-guarded by the owning scripts/tests | Both languages consume the same corpora; neither implementation generates the other's expected results |
| Language-specific verification | `tests/calculation/test_{predicate,integer_predicate,scalar_equality}_vectors.py` | `crates/onlyalpha-kernel/core/tests/` contains the corresponding Rust corpus, literal and diagnostic tests |

The owning Contracts are [Boolean/terminal semantics](predicate-semantics.md), [integer reference/literal semantics](integer-predicate-semantics.md),
[Boolean/string equality semantics](scalar-equality-semantics.md) and [isolated comparison](predicate-comparison.md). A matching
module name does not extend any Contract's supported types, numerical envelope, batch shape or diagnostic admission.
The separate `src/onlyalpha/application/calculation_equivalence.py` owns formal Calculation equivalence certification; the native
diagnostic service neither replaces that authority nor publishes its admission-grade Evidence.

The Decimal library additionally consumes independent 264-row reference and 504-row literal corpora; those twelve types are outside the V4 diagnostic allowlist.

The current separation already distinguishes definitions, scalar evaluation, batch evaluation and diagnostic orchestration.
Retain those paths while extending the selected semantic slices; no mirrored `research`, `application` or `runtime` shell is
needed inside the Rust library. Create a nested Rust module only when actual responsibilities/dependencies warrant it, and migrate
its real consumers atomically without old-path compatibility re-exports. New work binds the resulting exact implementation;
existing work keeps its retained artifact. Source movement alone does not redefine semantic type/version identity.

## Time responsibility map

Migration aligns semantic responsibilities, not Python package paths. Existing Python paths remain in place until their
implementation is retired; moving correct Python code solely to mirror Rust is not a prerequisite. Semantic defects still
require an explicit Contract decision and the correctness fixes needed by affected consumers. Comparison targets the owning
Contract and independent expected results, not unconditional equivalence to every legacy behavior.

| Responsibility | Python implementation | Rust implementation |
|---|---|---|
| UTC normalization and absolute instant values | `domain.time`, `core.time` | `domain/src/time.rs` |
| Exact nanoseconds to microsecond datetime | `core.time.only_unix_ns_to_datetime_utc` (default) | `OnlyTimestamp::to_datetime_exact` |
| Explicit lossy datetime projection | `domain.time.OnlyTimestamp.to_datetime`, `core.time` with `allow_truncation=True` | `OnlyTimestamp::to_datetime` |
| Immutable UTC half-open interval and interval algebra | `core.ranges` | `domain/src/ranges.rs` |
| Mutable clock, advancement, Timer scheduling and lifecycle | `core.clock` | `clock/`: independent scheduler, virtual driver and native boundary |

Strict projection rejects any sub-microsecond remainder. Explicit lossy projection floors signed nanoseconds to microseconds,
including before the epoch. Neither silently changes the authoritative nanosecond value. Datetime results cover years 1..9999;
unrepresentable inputs fail. Pure conversion never reads a clock. The shared `instant-conversion-v1.tsv` corpus exercises both
Python conversion policies and Rust against independent boundary expectations. Rust's canonical UTC text parser remains strict;
normalizing external aware datetime input is distinct from accepting noncanonical record text.

Time ranges use UTC microsecond datetime endpoints and require `start < end`. Membership is `[start, end)`, touching ranges do
not overlap, intersection can be empty, and subtraction returns ordered nonempty fragments. Merge sorts input and coalesces
overlapping or touching ranges, including duplicates. Missing ranges subtract merged coverage from the requested interval;
out-of-request coverage cannot extend the result. Operations are immutable and need no market, clock, Runtime, persistence or
provider. `time-ranges-v1.jsonl` uses explicit integer microsecond offsets from the epoch for test transport only; it introduces
no persistent record/schema or serialization compatibility promise. No new official writer or Runtime selection follows.

The broad architectural term Core, Python's `onlyalpha.core` package, and the existing Rust `core` crate are not identical
migration units. The Rust crate currently contains Predicate responsibilities. Do not place pure intervals there or merge
Clock/thread/system-time behavior into Domain merely to make directory names correspond.

The owner-approved [Rust Clock design](clock-rust-design.md) and [implementation plan](superpowers/plans/rust-clock.md)
apply the owning [Clock Contract](clock.md). Building the library does not claim parity or Runtime admission.

## Toolchain and build boundary

`rust-toolchain.toml` pins the official stable Rust 1.99.1 toolchain with rustfmt and Clippy. `deploy/Dockerfile.dev` obtains it from
the official `rust:1.99.1-slim-bookworm` image with its committed manifest-list digest, adding those components during image preparation.
Only the existing test/browser-test stages receive the compiler and GNU native linker. The existing validation service mounts
the exact compiler/proxy directories from that image read-only, with exact source image and subpath checks. The production runtime stage is unchanged.
The native GNU Linux targets are `aarch64-unknown-linux-gnu` and `x86_64-unknown-linux-gnu`; the check refuses other hosts and binds
its compiler host explicitly. Evidence is target-specific; a successful ARM64 run does not certify x86-64 or macOS/Windows.

Use the single dev project and source-mounted verification entry, never a parallel Compose deployment:

```sh
python scripts/dev_verification.py --rebuild prepare
python scripts/dev_verification.py run -- python scripts/test_suite.py rust-kernel
```

Rebuild only for changed toolchain/dependency/environment inputs. Rust source edits reuse the image. The formal entry freezes source
and serializes shared dev verification. Build output is under ignored `test-results/rust-kernel/target`, never inside frozen source;
no host Cargo directory or Rust installation is used. The canonical `rust-kernel` check is also a required Linux CI job.

The checker requires locked/offline Cargo, one build job and one test thread, and runs formatting and Clippy, then tests and builds in
both debug and release. It refuses unexpected lockfile packages pending dependency review. Ambient Cargo/Rust profile flags and
wrappers are removed. Missing toolchains/components fail rather than installing during tests. Compiler/Cargo identity, target,
source/lock/vector digests and the distinct debug/release artifact digests are retained in ignored test output only. These are
technical build observations, not formal Calculation equivalence Evidence, Runtime Generations or a certification registry.

Root `pyproject.toml` remains the sole release-number Authority. `scripts/version_sync.py` synchronizes `[workspace.package].version`
and the workspace package in `Cargo.lock` with the existing Python/Web graph. Cargo package version is implementation/distribution
identity, not the Predicate semantic version. `publish = false` prevents accidental registry publication; no external crates,
build scripts or native extensions are admitted. Standard library/compiler code is provided by the pinned official toolchain.

## Semantic and failure boundaries

Rust accepts typed nullable Boolean operands and exact type/version resolution. Wrong identity/version or operand arity is an
explicit error; errors are not false or missing. Unary versus binary arity is checked before indexing. Numeric operands cannot
inhabit the typed API. The integer module parses exact canonical decimal integer spellings without fixed-width conversion or arithmetic. Decimal reference comparison is exact and stateless; its fixed-point parser is not arithmetic or a diagnostic encoding. No timestamp parser, Decimal arithmetic, persistent identity hashing, transaction or recovery protocol is present, so this subset provides no evidence about their rounding/replay behavior. Future modules must add their own
Contracts/vectors; do not infer full Kernel equivalence from these Boolean tests.

The Boolean implementations use the same recorded 30-row corpus. Integer reference comparisons use their independent 216-row corpus; literal comparisons use a separate 408-row corpus, with required literal and position configuration. Both are checked by Python registered backends and the Rust library. The sealed-generation local diagnostic process compares these subsets plus the 250-row Boolean/string equality corpus under [its bounded V4/schema-4 private Contract](predicate-comparison.md), covering 904 independent cases across 26 exact types. Both registered Python backends and Rust retain the shared equality corpus checks; diagnostic integration does not grant formal Calculation certification or Runtime admission. Independent corpus byte guards run before Rust checks;
Rust tests preserve ordered rows, repeated evaluation, reversed order and distinct terminal identities. Errors remain different
from a nullable scalar. Builds use checked overflow and unwind in both profiles; this does not substitute for future checked
arithmetic tests. A fresh stateless library evaluation is not deployment upgrade/recovery evidence.

## Engineering references and derived protections

- [Official Rust 1.99.1 release](https://blog.rust-lang.org/2026/10/15/Rust-1.99.1/): upstream fixes include an x86-64 FFI Boolean
  return miscompilation and a target linker-symbol regression. Pin the patch release and test both profiles on each certified
  target. Reject assuming native scalar tests certify a future FFI/ABI; none is exposed here.
- [Cargo profiles](https://doc.rust-lang.org/cargo/reference/profiles.html): release defaults differ for overflow checking.
  Keep overflow checking and panic strategy explicit; run the same exact vectors in both profiles, not release-only smoke.
- [Generation contamination](engineering/failure_patterns/FP-RUNTIME-001-generation-contamination-and-fallback.md): record exact
  compiler/source/lock/artifact identity, refuse ambient wrappers and toolchain fallback. Build records never confer Runtime admission.

- [System V ELF header specification](https://gabi.xinuos.com/elf/02-eheader.html): validate the declared ELF64 header envelope
  with standard-library byte/struct operations; do not infer loadability, GNU ABI or compiler provenance from a header.

References are engineering evidence subordinate to OnlyAlpha Contracts. No floating stable channel, third-party compatibility
wrapper, hand-built cryptography, Rust Hash-based persistent identity or per-node RPC is adopted.

## Retained native diagnostic artifacts

The existing immutable Distribution Artifact manifest and Artifact Store also retain a narrowly bounded Linux diagnostic artifact.
Its role must be SUPPORT, distribution name `onlyalpha-kernel`, provenance authority ONLYALPHA_GIT with an exact source revision,
and logical name `onlyalpha_kernel-<normalized-version>-<target>.elf`. Targets are exactly `aarch64-unknown-linux-gnu` and
`x86_64-unknown-linux-gnu`. The logical target is identity metadata; it is not inferred from the current host or substituted.
A native diagnostic cannot declare a tested Core execution fingerprint, Provider, asset or Calculation admission binding.

The existing manifest schema/byte digest remain the identity authorities. `native_target` is derived from the logical name and is
not a second serialized field. Existing wheel manifests, fingerprints and `artifact.whl` store locations are unchanged. Native
bytes use `artifact.elf` in the same content-addressed store; new files are created with non-executable permissions. Put/fetch verify exact
size and SHA-256, then the ELF64 little-endian header envelope: version 1, executable/shared-object type, target machine and
64-byte header. This is format/declared-architecture validation, not an ELF loader, GNU ABI/dependency proof, signature,
trust decision, executable behavior verification or Rust compiler provenance certification. Malformed bytes fail even when their
declared digest matches. Missing/corrupt exact artifacts fail without a locator/latest/old-format fallback.

Both new and historical Python Generation construction reject a native diagnostic before venv/pip/process execution. Historical
preflight failure preserves a pre-existing environment; cleanup applies only after the current invocation atomically creates
its own environment directory. A competing directory creation fails without deleting the other invocation's files. Retention does not admit a native Kernel, activate a Generation, bind work, publish equivalence Evidence or
create a second official writer. Existing generation/work-binding authorities remain unchanged. The isolated [comparison consumer](predicate-comparison.md) verifies exact retained bytes, inputs, generation/work ownership and failure outcomes. File retention alone is not Python/Rust equivalence, compiler provenance or performance evidence.

This is an additive development-period manifest domain extension. Older readers refuse the new native logical name; no historical
wheel is rewritten, no schema fallback is added, and no deployment of mixed readers is certified by these storage tests.

## Kernel source organization

`crates/onlyalpha-kernel/` is the organizational umbrella for the Trading Kernel's Rust libraries, not another Cargo package.
The root Cargo workspace selects independent members inside it:

```text
crates/onlyalpha-kernel/
├── domain/  # package onlyalpha-domain: canonical Domain types and pure operations
├── core/    # package onlyalpha-kernel: the existing Predicate semantic library
├── clock/   # package onlyalpha-clock: mutable Clock/Timer mechanics
└── event/   # package onlyalpha-event: immutable envelopes and serial observation
```

Each member owns its `Cargo.toml`, `src/lib.rs` and tests. Thus `src/onlyalpha/domain/identifiers.py` corresponds to
`crates/onlyalpha-kernel/domain/src/identifiers.rs`. The directory expresses the Kernel/Domain containment relationship;
the crate boundary retains independent builds and dependency enforcement. Public package/import names are unchanged.
The allowed dependency direction is Core → Domain, never Domain → Core, Runtime, Application or concrete plugins.

Place further Domain responsibilities inside `domain/`. Use subdirectories when a responsibility actually needs multiple source
files, rather than adding an empty mirror tree or a crate per file. Package-selected and isolated-closure checks in
`scripts/rust_kernel_check.py` enforce the independent module boundary; this navigation description does not certify parity.

Rust Instrument uses composition: `OnlyInstrumentSpecification` holds common immutable fields, while
`OnlyInstrumentKind` retains each built-in subtype and its exact derivative terms. The enclosing `OnlyInstrument` validates
both together and keeps Python's flat, schema-versioned `model_type` record. This does not require reproducing Python
inheritance. `OnlyInstrumentCatalog<I>` admits an explicit concrete extension reader through `OnlyInstrumentModel`; unknown
tags fail closed and cannot be dynamically guessed or replaced by base fields. These types remain pure definitions and
queries, not Runtime activation or a second source of instrument authority.

## Domain numerical and record dependencies

The Domain library uses the following pinned community-maintained dependencies for its financial-value, record and time readers:

- `bigdecimal = 0.4.11` (Andrew Kubera, MIT/Apache-2.0): arbitrary integral magnitude and exact finite operations. Its ordinary
  division, default Context and Display are not the OnlyAlpha numerical or wire Contract. Domain preserves signed zero/scale and
  applies ADR 0140 precision and rounding explicitly. The unconditional `libm` dependency remains even without calling math APIs.
- `num-integer = 0.1.46` (rust-num, MIT/Apache-2.0): directly used gcd and div/rem for reduced rational division. Terminating ratios
  become exact decimals; non-terminating ratios round the integer quotient once to 28 digits/HALF_EVEN, without a rounded inverse.
- `serde_json = 1.0.154` (serde-rs, MIT/Apache-2.0): only `std` and `arbitrary_precision`. Financial fields remain strings;
  machine-width integer probes and floating-point conversion are not validators for arbitrary integer facts. Map keys use the
  default sorted representation. `preserve_order`, `unbounded_depth` and derive features are not admitted.

- `jiff = 0.2.38` (Andrew Gallant, MIT/Unlicense): only `std`; civil Gregorian dates, wall times and checked date arithmetic.
  Its `Timestamp` range excludes part of Python's final supported UTC day, so it does not own absolute time or timezone conversion.
- `tz-rs = 0.7.3` (x-hgg-x, MIT/Apache-2.0): only `alloc`; UTC instants and explicit TZif bytes from the same tzdata 2026.3 /
  IANA 2026c dataset as Python. Zero transitive dependencies, no build script or native code, MSRV 1.85, and `forbid(unsafe_code)`.
  Its exact archive SHA-256 is `4fc6c929ffa10fb34f4a3c7e9a73620a83ef2e85e47f9ec3381b8289e6762f42`.
  `std` remains disabled, excluding system-zone discovery and clock APIs. Gap `Skipped` results are rejected; normal fold
  candidates require explicit disambiguation. The library permits year zero and leap seconds, which Domain rejects.
  TZif v4 is unsupported; a future dataset containing it must fail admission rather than be rewritten or downgraded.
  This community project's maintenance breadth is smaller than Jiff's; its upstream history, exact source, license and RustSec
  entries require renewed review on upgrade. [Upstream](https://github.com/x-hgg-x/tz-rs),
  [explicit TZif API](https://docs.rs/tz-rs/0.7.3/tz/struct.TimeZone.html#method.from_tz_data).
- `sha2 = 0.11.1` (RustCrypto, MIT/Apache-2.0): no default features; standard SHA-256 for existing canonical fingerprints.
  The historical sha2 0.9.7 AVX2 issue (RUSTSEC-2021-0100) is outside this version's affected range; known-answer tests still apply.

These are not Rust-project-official libraries. The 40 published nodes in the committed lockfile have been checked against their
exact upstream archive checksums and manifests; the owning Rust gate binds that reviewed registry subgraph independently of local
release versions. Changes to versions, sources, checksums, graph or admitted direct features require renewed review. Locked
`serde`/`serde_derive`/proc-macro nodes through `cfg(any())` are distinct from the actually compiled target closure.
`bigdecimal`, `num-traits`, `libm`, `serde_core`, `serde_json` and `zmij` have configuration/probe/generated-Rust build scripts.
The inspected packages contain no C/C++ source or precompiled native libraries; this is not a claim that all transitive code is
unsafe-free. MIT is an available license choice for the active closure; locked `unicode-ident` additionally requires Unicode-3.0
notices, which must be retained on distribution. Consult each exact crate's included license files when packaging.

The public RustSec advisory database query found the historical sha2 advisory above, outside the selected version range,
and no matching entries for the other locked package names. This is not an
absence-of-vulnerabilities guarantee; future changes need a fresh query and exact manifest/source review. Upstream references:
[BigDecimal](https://github.com/akubera/bigdecimal-rs), [rust-num](https://github.com/rust-num/num-integer),
[Serde JSON](https://github.com/serde-rs/json), [RustSec](https://github.com/rustsec/advisory-db).

Dependency resolution/export uses `cargo update --workspace` to retain existing registry nodes and is an explicit `rust-lockfile` target in the existing dev Dockerfile, not a test or new deployment.
The fixed dev image fetches the committed lockfile's public dependencies during preparation. Formal builds remain frozen/offline
and seed their writable Cargo home from that admitted immutable image, clearing prior source replacements and cached mutations.
The Unicode 15.0.0 lexical data keeps the pinned Python runtime's identifier/currency/Decimal input domain; its generator is
`scripts/domain_unicode_tables.py --check`. This data does not implement decimal arithmetic or timezone rules.

The 22 additional exact archives for time and digest support were checked against the lockfile. New active dependencies include
Jiff's `jiff-core` and RustCrypto's digest/block-buffer/crypto-common/hybrid-array/typenum chain; Linux ARM additionally uses
`libc` through cpufeatures. libc's build script probes rustc/platform configuration. Inactive defmt, portable-atomic and thiserror
nodes also contain build scripts; locked presence does not imply execution. Optional log/defmt, non-pointer-atomic target helpers
and jiff-static/proc-macro dependencies remain part of Cargo's legitimate complete lock graph. Keep all applicable license notices.
Rust keeps upstream timezone resources separate from `src/` under
`crates/onlyalpha-kernel/domain/resources/tzdata/2026.3/`, including their licenses and `dataset.json` checksums.
The resources remain inside the Domain crate so its isolated build includes the complete input closure.
`scripts/domain_timezone_data.py --check` compares every byte and the Rust lookup index with the pinned Python package.
These copies contain the same upstream rules, not independent timezone authorities.

A timezone resource version is immutable. An upgrade explicitly updates the pinned Python package/lock, Rust resources,
dataset manifest, lookup index and dataset identity together; review upstream changes, preserve licenses, and run the
timezone/calendar cross-language tests and isolated Domain build. Do not modify individual zone bytes or use automatic
system/upstream updates. Historical artifact identity and upgrade requirements continue to follow ADR 0140.

## Clock build and dependency boundary

`crates/onlyalpha-kernel/clock/` owns package `onlyalpha-clock`. Its local dependency is Domain. Its only direct registry dependency
is `num-bigint = 0.4.8` (`default-features = false`, `std`), already present in the reviewed Domain registry closure. This direct
edge introduces no new registry package/checksum, scheduler library or async runtime. Native synchronization/time/thread facilities
use Rust std; the fixed toolchain and existing registry-closure digest remain authoritative build inputs.

`rust_kernel_check.py` validates exact edges/features, the complete local release graph and native-effect/source include boundaries.
It builds Domain with Clock absent, and Clock with only Domain plus declared registry dependencies; the Predicate library,
Runtime, application and Python production source are absent from those isolated source closures. Both isolated modules run
under debug/release. Independent Clock fixtures live in `test-data/clock/`; Python common-reference tests remain under `tests/clock/`.


## Event responsibility and isolation map

`event/model.py` and its record conversion correspond to Rust Event `model.rs` / `record.rs`; Python `bus.py` corresponds to
Rust `bus.rs`, with capability and bounded-diagnostic responsibilities separated into `capabilities.rs` / `diagnostics.rs`.
Python marker subclasses add no independent semantics; Rust retains their stable event-type values without duplicating empty
classes. `event/ports.py` corresponds to interface-only `ports.rs`; actual Runtime Router/Gate/Outbox owners are unchanged.

Event -> Domain is the only local dependency. Exact direct `num-bigint` and `serde_json` versions/features reuse the existing
reviewed 40-node registry closure. The owner is intentionally non-Send; immutable Event values can traverse owning ingress
boundaries. There is no event worker, hidden time/random input, Clock/Predicate edge or new deployment boundary.
The canonical Rust gate checks Event-specific source/dependency rules and builds/tests Event+Domain with other modules and
application source absent, in debug/release. It continues to verify independent Domain and Clock closures. Shared expectations
live under `test-data/event/`; their Python consumer exercises the actual current implementation only for correct common cases.
See the [owning Event Contract](event.md) and [selected design](superpowers/specs/2026-10-18-rust-event-design.md).


## Market Data State responsibility map

The Kernel umbrella's `market_data/state/` is package `onlyalpha-market-data-state`. Python `market_data/cache.py` corresponds
to `state.rs`; immutable snapshot queries and restriction correspond to `snapshot.rs`; strict current records correspond to
`record.rs`. This is a responsibility map, not a one-file/class translation: Pipeline/Construction/Dispatcher orchestration,
Indicator/Factor state and durable market history retain their owning boundaries. `model.rs` defines only scope/config/errors.

The only local edge is State -> Domain. The library reuses admitted exact num-bigint/serde_json features and adds no registry
nodes. `rust-kernel` validates its pure source/dependency boundary and extracts Domain+State without Core/Clock/Event or
Python/application/plugins. Both build profiles run the isolated closure. Independent common and schema-2 vectors live under
`test-data/market-data-state/`; the Python consumer exercises only real common semantics. The owning
[MarketData Contract](market_data_pipeline.md#rust-state-library-boundary) distinguishes component records from historical
Source/Construction/Generation proof and official Python Runtime registration. No admission or full module/wire parity follows
from a library build.

## Market Data Construction responsibility map

`market_data/construction/` (`onlyalpha-market-data-construction`) separates model/record, resolution, compiler, executor,
TIME_BAR and manager responsibilities. Python reference locations are `market_data/resolution.py` and
`market_data/aggregation/{compiler,base,time_bar,manager}.py`; this is a responsibility map, not a file/class translation.
Subscriptions' delivery/primary selection, completed-boundary product queries, Pipeline/State/calculation/Runtime integration
remain separate. Rust audits and corrects boundary/identity/recovery defects rather than preserving Python accidents.

Construction -> Domain is the sole local edge. Exact admitted num-bigint/serde_json/sha2 features add no registry nodes.
`rust-kernel` checks the seven-package graph and pure-source boundary, then extracts Domain+Construction independently and tests
both debug/release without Core/Clock/Event/State or application sources. The fixed Linux dev image supplies the offline
reviewed registry; ordinary source changes use frozen mounts. Shared independent inputs live in
`test-data/market-data-construction/`; Python consumes only the common valid API behavior. Component checkpoint schema4
and TIME_BAR schema1 do not activate the library in the official Python Runtime. The
[owning Contract](market_data_pipeline.md#rust-construction-library-boundary) defines ownership and failure semantics.

## MarketData business organization and delivery

`crates/onlyalpha-kernel/market_data/` groups State, Construction and Delivery under one business boundary. Subcrates exist
for actual independent build/dependency isolation, not one crate per class. State/Construction retain package names/current
records and depend only on Domain; Delivery depends only on these libraries and Domain. No facade, nested workspace, empty
Pipeline placeholder or new deployment is needed. The dev environment fingerprints Cargo manifests recursively so deeper
module dependencies cannot bypass rebuild admission.

Python `market_data/subscriptions.py` and the planning part of `dispatcher.py` correspond to `market_data/delivery/`.
Subscription/model and non-Clone owner/record concerns stay internal to one Delivery crate; callback execution, calculation
barriers and Pipeline coordination remain separate. Explicit IDs, pure scoped plans, bounded active cursors and atomic
configuration-bound recovery replace implicit UUID generation, unbounded handled-slice history and permissive readers.
Shared common routing vectors use real Python Pipeline/Dispatcher behavior and Rust State/Delivery APIs; they do not certify
whole-module parity, readiness or official Runtime admission. See the [owning Contract](market_data_pipeline.md#rust-delivery-planning-boundary).


## Calculation responsibility map

Python `calculation/{definition,graph,compatibility,registry}.py` is the semantic reference for the independently buildable
`crates/onlyalpha-kernel/calculation/` library. Record/parameter/definition/graph/registry concerns are private files within one
crate; provider-specific calculations remain plugins. Existing Core Predicate implementations remain in Core, with no duplicated
arithmetic or transport here. Calculation has no local dependency edge and cannot access Runtime, MarketData, Cluster or plugins.

Rust Definition component schema3 explicitly corrects untagged Decimal/string fingerprint collisions and scale-sensitive Decimal
identity. Tagged normalized sorted-key records are both persistence and hash input; Graph schema1 uses these exact Definition3
identities. Python Definition2 and its official consumers are untouched reference behavior. Rust3 is not an admitted replacement
writer/reader, a history migration, a Runtime Generation or an execution/readiness capability. Do not infer schema2 hash parity,
full Python-module equivalence, product activation or scientific Evidence from these common semantic vectors. Actual promotion
requires the existing exact consumer/history and Runtime admission gates. See the [design](superpowers/specs/2026-10-18-rust-calculation-foundation-design.md).

### Scoped Calculation execution and managed Python worker

`calculation/src/execution.rs` owns exact execution bindings, ordered prepared batches and a cursor committed only by complete
matching receipts. It has no Domain, process, plugin or transport dependency and never infers algorithm readiness. Six exact
fingerprints bind generation, worker artifact, component Definition3, native Definition2, native implementation and input context;
instance scope is explicit. These identity domains remain distinct.

`packages/onlyalpha-calculation-worker/` owns the Python process and Rust client/transport. It invokes the existing registered
SMA plugin, preserves native implementation identity, applies an explicit canonical Decimal context, and validates candidate
updates/restores before replacing state. Canonical Protobuf authoring/projections remain under the existing Gateway ownership.
The inherited same-host channel has no public listener; timeout/cancel/crash poisons its owner as UNKNOWN, with no retry/fallback.
Exact generation admission, checkpoint persistence, historical materialization and official Runtime integration remain their
existing owners' responsibilities. Process isolation is not authorization or a security sandbox.

See the [execution design](superpowers/specs/2026-10-18-rust-calculation-worker-design.md). `scripts/calculation_worker_check.py`
compares actual Rust/Python processes, independently expected SMA results and fresh-process continuation in both profiles; it
reports startup, backend and whole-client batch timing separately. This technical command is not a human business entry point,
Shipping Web UI acceptance, durable service upgrade proof, product-latency claim or Runtime activation.

Generate Python projections with `scripts/gateway_protocol.py write`; generate Rust projections in the admitted Linux tool
environment with `scripts/gateway_protocol.py write-rust`. The Rust canonical lane checks the Rust projection; the existing
Gateway lane checks Python bytes and additive wire compatibility.
