# Rust Strategy Execution Implementation Plan

> Implement inline with superpowers:executing-plans and TDD, followed by one fresh independent review. Owner authorized recommendations and main publication without further questions.

**Goal:** deterministic Rust-owned Strategy decisions using exact Python TRADING calculations and complete fresh recovery.
**Architecture:** one Strategy semantic crate; the existing worker Infrastructure implements its port and the actual MarketData coordinator.
**Tech Stack:** existing admitted Rust Domain/Calculation/serde_json/sha2 and Python Calculation SPI/Protobuf; no new registry packages.
**Spec:** `docs/superpowers/specs/2026-10-18-rust-strategy-execution-design.md`.

## Global constraints

Explicit non-admitted Revision2/Definition3 identity; official Revision1/Freeze/history unchanged. Sole Linux dev environment and frozen source; serial tests. No economic effects, formal activation, history conversion, Web or Release.

## Review focus

- Old calculation/decision states transplanted into newer observations or input cuts.
- A later-node failure after an earlier remote commit; no implicit retry or stale ready result.
- Native/component definition or implementation identity mismatch despite matching type names.
- Nullable Boolean decisions, warmup and exact scalar type boundaries.
- Candidate worker failure during restore, preserving receiver and killing candidates.

## Task 1: Current semantic records and pure executor

Create `strategy/src/{lib,model,execution,recovery}.rs` and owning tests/corpus. Consume Domain and Calculation public types. Produce strict
Revision2, Program, CalculationPort, Observation/Decision/Outcome and Executor APIs. Write boundary/identity/execution/restore regressions
first; observe failures, then implement exact graph bindings, ordering/input projection, receipts/readiness/fail-stop and fresh restore.
Python remains a classified reference. Record corrected semantics in owning Strategy Contract, not a quality/status ledger.

## Task 2: Actual registered node worker and MarketData coordinator

Extend canonical `calculation.proto` with a bounded closed node operation and regenerate exact projections. Add worker node backend/client
using real declared registry factories, explicit typed inputs/outputs/state capability and exact artifact/binding checks. Reuse existing
transport/deadline/cancellation lifecycle. Add a technical coordinator under worker Infrastructure, binding MarketData and Strategy recovery
at the same cut; do not put state into the pure preparation callback. First write Python/protocol/real bridge tests, then implement.
Prove SMA plus another indicator/operator/predicate, independent expected decisions, actual Python reference comparison and fresh-process
continuation/faults. Atomically update actual package/lock/artifact inputs.

## Task 3: Build, review and publish

Update actual Cargo/member/version/dependency/source guards, isolated closures, owning navigation and impact selection with regression
coverage. Verify RED/GREEN, affected static/protocol/package checks and canonical lanes serially. Keep diagnosed pre-existing failures
separate. Complete bounded simplicity review and a fresh whole-branch independent review; fix blockers with failing regressions.
Run final frozen-source Rust debug/release/isolated/real bridge lane. Commit exact verified content, fetch/check base, ff-only master,
push and fetch again. Preserve version0.10.10 and do not publish a Release.
