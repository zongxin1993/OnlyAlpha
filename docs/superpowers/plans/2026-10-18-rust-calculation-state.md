# Rust Calculation State Implementation Plan

> Use superpowers:executing-plans inline; one fresh bounded independent review before publication. Owner authorized implementation and remote master without further questions.

**Goal:** exact scoped result state and readiness, consumed by the real Python worker client.
**Architecture:** existing pure Calculation crate owns cursor/state and pure readiness; existing worker Infrastructure owns transport and checkpoint pairing.
**Tech Stack:** admitted Rust std, serde_json, bigdecimal and sha2; existing Python SMA.
**Spec:** `docs/superpowers/specs/2026-10-18-rust-calculation-state-design.md`.

## Global constraints

No dependencies, official Runtime admission, historical migration, Web behavior or Release changes. Exact binding/input position and fail-closed uncertainty. Maximum 256 plan nodes and 64 result outputs/quality flags. Use sole dev frozen verification and preserve evidence separately from design.

## Review focus

Stale-but-ready outputs; optional ancestor of required node; partial response/worker death after commit; mutated nested checkpoint binding/position/status; mixed timeframe expectations and process-wide uncertainty.

## 1. Pure state and readiness

Create `calculation/src/state.rs`, `readiness.rs` and `tests/state.rs`; export from lib.rs. Reuse ExecutionCursor and tagged scalar validation. Add independent common reference vectors and their Python checker. Test missing APIs RED, then implement atomic receipts, immutable snapshots, strict records, explicit failure/reset/fresh restore and dependency barrier. Test each review-focus state including rejected restore preserving receiver.

Interfaces: CalculationState owns cursor; snapshot returns CalculationSnapshot; prepare/commit consume existing PreparedBatch and exact receipt record; InputPosition binds revision/samples/time/digest. ReadinessPlan consumes exact bindings/dependencies and evaluates snapshots against exact expected positions.

## 2. Real worker consumer and recovery

Update `crates/onlyalpha-calculation-bridge/rust/client.rs` to own CalculationState, expose snapshots and cancellation, pair state/worker checkpoint in schema2 bundle; retain native wire checkpoint. Extend bridge_check.rs for actual warming/ready/degraded/stale, process-wide UNKNOWN, nested bundle rejection and restart continuation. Watch the old checkpoint/snapshot behavior fail before implementation, then run targeted Rust/process bridge checks.

## 3. Canonical integration and publication

Update owning source navigation/contract and impacted source-vector guards only. Diagnose the existing provider golden discrepancy without changing identity/history or weakening tests. Run affected Python/tool checks, canonical Calculation and Rust lanes; retain any proven unrelated baseline failure distinctly. Complete bounded simplicity review and independent review with independent state-space reconstruction; resolve High/Critical with regression proof. Bind final receipt to current source, commit, fetch, ff-only master, push, fetch and verify exact remote alignment. No version bump.
