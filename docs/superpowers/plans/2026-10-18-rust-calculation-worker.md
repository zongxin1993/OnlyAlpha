# Rust Calculation worker implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline; one fresh bounded final reviewer.

**Goal:** Execute the actual registered Python SMA from Rust with explicit provenance, atomic batches and recoverable lifecycle.

**Architecture:** Pure Calculation cursor and binding; Infrastructure managed child; canonical Gateway Protobuf. Existing plugin remains the algorithm owner.

**Tech Stack:** Linux Rust std, pinned prost 0.14.4, existing Python Decimal/plugin and Gateway generators.

**Spec:** `docs/superpowers/specs/2026-10-18-rust-calculation-worker-design.md`.

## Global constraints

Protocol 1; frame 1 MiB; batch 256; instances 16; period 1..4096. No Runtime activation, historical migration, fallback or version bump. Unique dev validation only. Task evidence stays in ignored `test-results/`, not this plan.

## Review focus

- Valid first Bar followed by an invalid Bar must not commit any state.
- Same local instance in different scopes must not share state.
- Worker timeout/cancel after mutation must remain UNKNOWN, without hidden retry.
- Restoring corrupt or foreign checkpoint must leave a fresh instance unchanged.
- Artifact mismatch and stale response must fail before accepting results.

### Task 1: Contract and pure execution owner

Files: canonical `calculation.proto`, Gateway Rust projection/manifests, `calculation/src/execution.rs`, component tests, build/generation/impact tools.

Interfaces: immutable `ExecutionBinding`, `ExecutionCursor::prepare/commit/reset` and exact batch receipts; generated `CalculationRequest/Response`.

- [ ] Write failing strict binding, ordering, stale receipt and protocol projection tests; run RED.
- [ ] Implement minimal pure state and typed wire, optional deterministic codegen; update declared dependency/environment inputs and lock.
- [ ] Run targeted Rust tests, schema generation/compatibility and boundary/tool tests.

### Task 2: Python worker

Files: `packages/onlyalpha-calculation-worker/pyproject.toml`, Python `contracts.py`, `backend.py`, `worker.py`, local tests; workspace metadata/lock.

Interfaces: strict component codecs, native SMA backend operations, Protobuf socket serve/describe entry points.

- [ ] Write failing hand-calculated warmup, Decimal context, atomic invalid batch, scope, checkpoint/reset/close tests; run RED.
- [ ] Implement exact plugin selection and Definition3 projection, startup manifest, candidate mutation/restore and bounded frame parsing.
- [ ] Run targeted Python tests and affected Ruff/mypy/package checks in unique dev.

### Task 3: Rust managed process and real bridge

Files: component Cargo manifest, `rust/lib.rs`, integration diagnostic and tests; Rust source closure and package/version tools.

Interfaces: `Worker::spawn/exchange/cancel/close`, typed plugin lifecycle client, technical bridge executable.

- [ ] Write failing real SMA, restart, malformed peer, crash, total deadline and cancellation tests; run RED.
- [ ] Implement inherited Unix socketpair, exact handshake, remaining deadline, deterministic poison/kill/reap and lifecycle validation.
- [ ] Run real Rust→Python tests and per-bar versus batch benchmark; separate startup/IPC/compute evidence.

### Task 4: Review and publication

Files: owning development maps and direct affected documentation only.

- [ ] Run initial targeted/static gates; apply bounded Ponytail review without weakening semantics.
- [ ] Obtain one fresh independent review limited to diff/real impact; fix blocking findings with regression evidence.
- [ ] Freeze source and run affected canonical lanes, generation/build/compatibility and isolated closure checks.
- [ ] Commit, fetch and verify remote base, fast-forward local master, verify tree, push and fetch to prove alignment.
