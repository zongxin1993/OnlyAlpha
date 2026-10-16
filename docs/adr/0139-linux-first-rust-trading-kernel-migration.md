# ADR 0139: Linux-first Rust Trading Kernel migration

- Status: Accepted
- Date: 2026-10-16
- Decision maker: repository owner, through the explicit GrillMe decisions and instruction to persist and publish the resulting plan.
- Related: PROJECT_CONSTITUTION.md; ADR 0057, 0067, 0099, 0101, 0106, 0117, 0130, 0135.
- Implementation sequence: [Rust Kernel migration work program](../rust-kernel-migration-work-program.md).

## Context

The owner selects Rust as the long-term implementation of stable Trading Kernel semantics, after the corresponding Python modules
are stable. Python/Rust coexistence is a bounded migration technique, not a permanent promise to maintain two Kernels. Highly
variable indicators, factors and research authoring remain Python-oriented. Market rules, DataSources and Brokers remain plugins,
regardless of language; their SDK/platform constraints determine implementation language.

Slow new-instrument and missing-history journeys motivate a separate end-to-end performance workstream. They include session
initialization, external acquisition, durable publication, proof-backed reads, computation and browser rendering. Changing the
Trading Kernel language does not establish that Provider waiting or the entire journey is faster. This ADR records a target and
construction order; it neither claims Rust is implemented nor certifies Python stability, latency, recovery or platform support.

## Decision

### 1. One semantic Kernel, a bounded dual-implementation transition

The final maintained Kernel implementation is Rust. Module ownership continues to follow the Constitution's invariant/variable
boundary, not language or perceived change frequency. Backtest, SIM and LIVE share the same Runtime-neutral Kernel semantics.
Runtime drivers, HTTP/Web presentation, Infrastructure, provider protocols and research calculations do not become Kernel logic
merely because they are slow or comparatively stable.

During transition, each Runtime/work identity binds one exact execution implementation, artifact and immutable Runtime Generation.
Only that owner can advance official state, publish official facts or cause execution side effects. The comparison implementation
receives the same explicit inputs and isolated initial state; it cannot submit orders, duplicate Command effects, write official
stores or publish competing Evidence. Comparison results are diagnostic observations with exact provenance, not trading Authority.
No automatic fallback, mid-work rebinding, latest-version selection or second mutable authority is introduced.

Python is initially the official implementation. Rust modules enter comparison only after their Python Contract and relevant
correctness/recovery behavior are stable. Stability is established per module, not by waiting for the entire product to finish.
The first complete Rust-owned product slice is Backtest; SIM follows, then LIVE under its existing human authorization gates.
Deployment staging never creates Runtime-specific economic semantics. Running work retains its exact binding; new-work activation
and draining follow ADR 0117. A long-lived Runtime handover needs explicit validated checkpoint/reconciliation semantics before
activation; replacing a process or changing a version string is not a handover protocol.

### 2. Contract equivalence, not Python-as-oracle

The canonical Contract, immutable inputs and language-neutral deterministic vectors define correct behavior. Python is a reference
implementation, not an authority above the Contract. A discrepancy requires diagnosis; neither copying a Python bug nor weakening
an assertion is an acceptable migration method.

Canonical identifiers, bytes/digests, decimal monetary/quantity values, rounding, event ordering, state transitions, rejections,
UNKNOWN outcomes, evidence relations and restart/replay results require exact equivalence under the same declared semantic inputs.
Rust artifact identity remains distinct from Python artifact identity; never falsify executable provenance to make comparison pass.
Comparison normalizes only explicitly implementation-specific diagnostic fields; it does not discard causal or authority fields.
Numerical tolerance is allowed only where the existing owning calculation Contract explicitly defines it. No implicit f32/f64
conversion, lossy timestamp, platform-sized integer or unordered iteration may alter canonical results.

Tests must cover successful, denied, incomplete, unavailable, cancelled, failed and UNKNOWN outcomes, plus duplicate/late/ordered
facts, ownership mutations, crashes at durable boundaries, replay and reconciliation. Fault fixtures use deterministic barriers
and controlled inputs, not sleeps or live-account traffic. Existing formal API and Shipping Web UI remain the product entry.

### 3. Python workers at real plugin/calculation boundaries

Python factors and indicators run in managed worker processes by default, using bounded batches and explicit versioned Contracts.
Market plugins may use Python or Rust according to their SDK and operating-system constraints. This does not require one process
or microservice per indicator/plugin. Reuse a process only within its exact admitted generation and resource/failure boundary.
Kernel-internal risk/order/state transitions remain direct typed calls under ADR 0101; do not turn the trading graph into RPC per
node, per bar or per scalar value. Process isolation alone is not authorization or a sandbox.

Reuse the existing protocol ownership and generation/admission infrastructure. Current gateway test messages are not a production
calculation protocol. Extend the canonical protocol only for the first real consumer, defining decimal/time encodings, ordered
batch identity, exact input/output provenance, deadlines, cancellation, crash, bounded queues and backpressure. A timeout does not
prove that work never ran; UNKNOWN must not trigger a second order identity. In-process Python embedding requires measured evidence
that the process boundary is the bottleneck and a separate boundary/security/lifecycle decision.

### 4. Linux first, the existing single dev environment

The first Rust stage targets Linux only, developed, compiled and validated in the existing `onlyalpha-dev` project and
`deploy/docker-compose.dev.yml`. No host Rust installation or parallel Compose topology is required. Extend the fixed dev tool
image only when its toolchain/dependencies need change; use frozen source views, isolated test data and one worker by default.
Pin a stable official Rust toolchain and retain compiler, target, profile, source and dependency-lock provenance. The first toolchain
version and Linux target are selected and frozen in the toolchain implementation task, not guessed by this planning release.

Windows/macOS Rust delivery is deferred, not certified or permanently cancelled. Existing non-QMT Python platform checks remain.
No data-volume deletion, empty-store replacement or weakened authentication is authorized by migration or dev image changes.

### 5. Maintainable dependencies

Prefer Rust std and official Rust toolchain facilities, then an already admitted dependency, before introducing a new crate.
Publication on crates.io or ownership of a rust-prefixed organization is not proof of official maintenance. A necessary third-party
crate needs an explicit assessment of maintained releases, responsible maintainers, license, security history, transitive graph,
features/build scripts/native code, Contract fit and replacement cost. Record the rationale at the dependency declaration/design
that owns it; do not create a second approval/status registry. Minimize features and pin the committed lockfile/toolchain.

No crate or numerical/serialization default becomes OnlyAlpha semantics automatically. Upgrade verification includes debug/release
parity, overflow and panic behavior, canonical bytes and exact numeric vectors. Do not use std Hash/DefaultHasher as durable
canonical identity. Do not implement cryptography/TLS from scratch to avoid a maintained necessary dependency. Do not preselect
an async framework, decimal crate or serialization stack before the first consumer's requirements are established.

### 6. Retire the current MiniQMT adapter without deleting universal behavior

The owner withdraws the current unavailable QMT/MiniQMT implementation and its adapter-specific tests. The retirement task removes
its package, entry points, dependency/lock references, SDK tooling, dedicated CI/build/release checks and current support claims.
Shared SIM, execution, Authority and recovery assertions that currently borrow its fake feeds move to a neutral hermetic Source;
they are not deleted. Generic worker/lifecycle capabilities and the independent CN A-share market/reference plugin remain.

This narrows ADR 0067's requirement to keep active MiniQMT provider tests: adapter-only suites may retire. Preserve its frozen
offline historical golden payloads/manifests and provenance identifiers required to interpret existing facts; preserve independent
reference/product conformance assertions. A provenance value is not an installed SDK dependency. Historical Integrations,
revisions, grants, runtime bindings, sealed data, Evidence, keys and exact artifacts must not be erased or silently rebound.
A missing implementation remains explicitly unavailable/fail-closed through the owning reader/admission path.

This withdraws one current adapter; it does not redefine the market-agnostic product or cancel A-share, cross-market or future
suitable gateway capabilities. ADR 0099's future sequencing is not evidence that the current adapter is usable.

### 7. Separate latency acceptance from migration correctness

Measure the whole Shipping UI path for both warm history and cold/missing history. With existing verified bars, show only the
current exact context's proven history while gaps fill. For new instruments, a bounded recent batch may paint first, followed by
completion of the required window. Partial history has presentation-only identity; it cannot grant complete input readiness,
Research Evidence or realtime handoff. Indicators await their complete admitted inputs. Auth/proof/context failures withdraw
untrusted display; absence is never invented and acquisition is not a manual extra user step.

Report first verified paint, complete 2000-bar readiness and all required indicators separately. The previously agreed warm P95
budgets remain 1s/2s for one-page K-line/three-indicator display and 2s/4s per page for two simultaneous pages. Errors, busy and
unfinished attempts count; partial paint cannot satisfy complete-load budgets. Cold external acquisition/restart baselines and
monitoring overhead are separate; do not invent a guaranteed public-network budget. If the agreed goals prove difficult, return
the measured limiting phases and options to the owner instead of silently relaxing them. Rust correctness is not a latency PASS.

### 8. Python Kernel retirement

Remove the current maintained Python Kernel only after the replacement's affected semantic, Product, recovery, upgrade and
failure gates pass and the owner explicitly activates the corresponding release. Migration must prove existing history through
current owning readers and real stop/start/upgrade as applicable; fresh-process replay alone is not deployment-upgrade evidence.
Preserve language-neutral Contracts, vectors and replay fixtures as permanent tests. Historical exact artifacts needed by bound
work remain retrievable under ADR 0117; artifact retention is not a current Python compatibility shim or dual-maintenance promise.
Do not introduce a legacy loader, translate identities silently, discard old facts or fabricate a Rust identity for old work.

## Alternatives and consequences

Permanent dual Kernels were rejected because every semantic change would require two implementations and drift control forever.
A whole-backend rewrite before profiling was rejected because acquisition/network/storage work is not equivalent to Kernel CPU.
Rust-only plugins/research were rejected because variable authoring and vendor SDK constraints differ from stable trading semantics.
The chosen transition costs temporary comparison tooling and exact-generation storage, but ends with one maintained Kernel.
This design adds no exception to Constitution, Authority, deterministic execution, recoverability or LIVE authorization.

## Engineering references and derived protection

- [Rust std Hash portability](https://doc.rust-lang.org/std/hash/trait.Hash.html#portability): std hashing is not a persistent format;
  require Python/Rust canonical-byte and digest vectors, varied field ordering and repeated-process runs.
- [Cargo build profiles](https://doc.rust-lang.org/cargo/reference/profiles.html): build profiles can change overflow/panic behavior;
  test checked arithmetic and error semantics in both debug and release, including boundary values and worker termination.
- [rust-lang/rust issue 150323](https://github.com/rust-lang/rust/issues/150323): discussion of unspecified-precision floating-point
  operations is a reason to make numeric requirements explicit, not evidence that arbitrary tolerances or an entire crate are safe;
  test existing exact Decimal/rounding envelopes and reject unintended binary-float conversions.
- [FP-RUNTIME-001](../engineering/failure_patterns/FP-RUNTIME-001-generation-contamination-and-fallback.md): isolate exact worker
  generations; test missing/corrupt artifacts and simultaneous different generations without ambient/latest fallback.
- [FP-STORAGE-001](../engineering/failure_patterns/FP-STORAGE-001-trading-projection-without-durable-history.md): test crash/replay
  from durable causal facts; a matching final projection alone does not prove recoverability.

References are advisory evidence, not OnlyAlpha Authority or a crate adoption decision.
