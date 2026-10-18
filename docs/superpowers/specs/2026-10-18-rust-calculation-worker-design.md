# Rust Calculation / Python worker boundary

## Purpose and ownership

Implement a non-publishing Linux comparison lane from Rust Calculation through a managed private Python process to the existing registered SMA plugin. Rust owns exact execution binding and ordered batch commits; Python owns algorithm, warmup and readiness. Infrastructure owns transport, deadlines, process lifecycle and artifact verification. No official Runtime activation, admission bypass, historical translation, data migration, Web behavior or Release change is included. Constitution impact: NO.

The `calculation` library stays free of transport, Domain and concrete plugins. `packages/onlyalpha-calculation-worker/` contains the deployable worker and Rust process adapter. The existing Gateway package owns the Protobuf projection; canonical sources remain in `contracts/gateway/v1/`. One process may serve multiple instances only within one explicitly supplied exact generation. This component consumes that binding; it does not mint or persist official Runtime Generations.

## Contract

Protocol 1 uses an inherited Unix socket pair, a four-byte unsigned network-order frame length, and generated Protobuf messages. Maximum frame 1 MiB, batch 256 closed Bars, 16 instances per process, parameter period 1..4096. No TCP listener, generic Python object invocation, pickle, dynamic plugin path or runtime dependency resolution. Requests carry exact generation, sequence and typed operation. Responses echo generation/sequence and carry the independently computed loaded-artifact fingerprint. Operations are handshake, resolve, create, update, reset, checkpoint, restore and close. Bounded JSON byte fields carry explicitly versioned owning records, not executable objects. Decimal is a finite string; event nanoseconds are signed decimal strings, never float or machine-sized timestamps.

Resolve calls the actual registered `onlyalpha.indicator.sma` TRADING backend version 1. A component Definition3 is constructed from live semantic fields with tagged scalars, separately retaining the native Definition2 fingerprint and implementation fingerprint. No persisted Definition2 record is converted, loaded as Definition3 or treated as equal identity. Creation repeats exact resolution and rejects mismatched Definition/native/implementation bindings. Rust validates Definition3 and native binding. Invocation explicitly fixes Decimal precision 28, HALF_EVEN, the existing canonical exponent/trap policy and quantum 1e-12; this invocation policy is part of worker artifact identity. It does not assert equivalence to uncontrolled ambient Decimal execution.

Each instance binds exact generation, artifact, Definition3, native definition/implementation, runtime/cluster/local instance scope and input context. Input context includes canonical BarType and the caller's exact source fingerprint. Batches have ordered timestamps, an immutable content digest and expected revision. Rust validates order before submission and commits its cursor only after a complete matching result. Python prevalidates the entire batch and applies it to a fresh candidate, then atomically replaces the instance. Duplicate/late timestamps are errors, correcting the native plugin's silent duplicate behavior at this boundary. Partial mutation is never exposed as a successful update. Readiness is a producer fact, not inferred from catalog registration.

Checkpoint envelopes bind the same execution context, revision, sample count, last event and plugin state. Restore requires a fresh instance and caller-provided exact checkpoint digest; the envelope cannot authorize itself. Validate the entire payload, restore into a new candidate and compare re-capture before replacing. A new process may restore under the same exact generation/artifact binding. This proves process restart, not real service upgrade or durable store activation. Checkpoint storage remains the caller's responsibility.

## Lifecycle and failure

One synchronous exchange per owned connection provides bounded backpressure; no unbounded queue. Deadline covers the whole exchange, including partial reads/writes. Cancellation shuts down the owned socket and kills/reaps the exact child. Transport loss, deadline, cancellation, malformed/stale response or worker death after submission leaves execution UNKNOWN and poisons the process; no automatic retry, recreation or fallback. Explicit recovery uses a fresh exact process and an admitted checkpoint. Pre-submission validation errors do not mutate the owner. Valid structured request rejection preserves worker state. Child stderr is inherited for diagnostics; stdout/stdin are private protocol FDs, never logs.

Artifacts are hashed once at startup, covering the worker, used Python Core, plugin and generated Gateway source plus Decimal/runtime policy. The parent must supply the expected artifact fingerprint from exact materialization; handshake computes and compares independently. A diagnostic descriptor command may inspect an isolated frozen test materialization, but cannot confer formal Runtime admission or substitute latest code for historical work.

## Dependencies

Reuse admitted serde_json/sha2 and Rust std. Protobuf requires exact `prost`, `prost-types`, `prost-build` 0.14.4; the latter two are code-generation-only optional dependencies. Apache-2.0 Tokio project, maintenance/security focused, explicitly not Rust std or an official Rust-maintained guarantee. See [upstream](https://github.com/tokio-rs/prost/tree/v0.14.4), [security](https://github.com/tokio-rs/prost/security), and [historical recursion advisory](https://rustsec.org/advisories/RUSTSEC-2020-0002). Keep default recursion protection, bound frames and test malformed input. Do not use Timestamp/Duration convenience conversions, native C++ runtime, network framework or async runtime. Codegen only consumes the trusted canonical descriptor; no build-time downloads. Pin and review the resolved transitive lock graph before admission. Generated Rust/Python bytes must match canonical sources.

## Acceptance

Independent SMA vectors include partial warmup, zero and exact Decimal outputs. Verify single/batched equivalence, separate scopes, reset/close, fresh-process checkpoint continuation, duplicate/late/invalid later input atomicity, wrong generation/artifact/binding, corrupt checkpoints, bounded malformed frames, crash, deadline and cancellation using barriers rather than sleeps. Compile/test the pure Calculation and Infrastructure dependency closures independently in debug/release, verify protocol generation/compatible additive wire change, affected Python/static/package/tool checks and bounded independent review. Report startup, roundtrip and compute timing separately, comparing per-bar and batched calls; do not claim this solves Shipping UI/network acquisition latency.

The locked registry graph adds 33 packages. Runtime additions are `prost`/`bytes` and the derive macro closure
(`prost-derive`, `anyhow`, `itertools`, `either` plus the existing proc-macro toolchain). Optional code generation adds
`prost-build`/`prost-types`, descriptor graph/map collections, regex parsing, pretty-printing and temporary-file support.
`rustix`/platform bindings are codegen dependencies, not an async or networking runtime. No new native C/C++ build or vendored
cryptography is introduced. Keep generator dependencies feature-gated, source/checksum locked and offline in normal validation;
replacement requires only re-projecting the canonical descriptor and retaining the same bounded wire Contract.

Python Gateway `check`/`write` retain their Python-only tooling requirement. Linux Rust projection `check-rust`/`write-rust`
use the same canonical descriptor and pinned optional generator. The canonical Rust lane requires `check-rust`; the existing
Python Gateway CI lane does not acquire a host Rust dependency. This separation preserves existing platform/tooling boundaries
without making generated Rust verification optional.

State admissibility is identical before create/update/reset commit and during restore. Native SMA retains period+1 values;
therefore a maximum period4096 state permits exactly4097 window entries, within the same frame bound. Worker state Decimal
strings are finite, at most4096 characters, with adjusted exponent magnitude at most4096. A valid Domain Bar whose retained
plugin fields exceed this bounded worker envelope is rejected atomically before committing; it is not silently accepted into
an unrecoverable state. This invocation resource bound does not redefine the broader canonical Domain value space.
