# Linux Rust Kernel development

The library in `crates/onlyalpha-kernel/` implements the six stateless Boolean/terminal primitives defined by
[Predicate semantics](predicate-semantics.md). It owns no Runtime selection, official state, persistence, Broker access or effects.
Python remains the admitted implementation; building this library grants no execution or LIVE permission. Managed comparison and
historical artifact retention remain governed by ADR 0139 and ADR 0117. No FFI, transport, workers or async runtime are introduced.

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
inhabit the typed API. No numerical/time parser, Decimal arithmetic, persistent identity hashing, transaction or recovery protocol
is present, so this subset provides no evidence about their overflow/rounding/replay behavior. Future modules must add their own
Contracts/vectors; do not infer full Kernel equivalence from these Boolean tests.

Both implementations use the same recorded 30-row corpus. The existing independent truth-table byte guard runs before Rust checks;
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

References are engineering evidence subordinate to OnlyAlpha Contracts. No floating stable channel, third-party compatibility
wrapper, hand-built cryptography, Rust Hash-based persistent identity or per-node RPC is adopted.
