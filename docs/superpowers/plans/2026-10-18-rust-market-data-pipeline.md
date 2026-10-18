# Rust MarketData Pipeline Implementation Plan

> Use superpowers:executing-plans inline, then one fresh bounded independent review. Owner explicitly authorized implementation and master publication without more questions.

**Goal:** deterministic composed MarketData preparation and actual non-effectful handoff through real Python calculations.
**Architecture:** one Pipeline library under MarketData; existing worker Infrastructure implements calculation port. Existing authorities remain.
**Tech Stack:** admitted Rust std, serde_json/sha2 and existing Domain/MarketData/Calculation; no new registry packages.
**Spec:** `docs/superpowers/specs/2026-10-18-rust-market-data-pipeline-design.md`.

## Global constraints

No official Runtime activation, economic consumer effects, history migration, Web change or Release. Explicit Source/Generation identity, bounded inputs/checkpoints, deterministic order and UNKNOWN semantics. One sole dev frozen validation service, serial tests.

## Review focus

Ambiguous source/BarType ownership; stale-but-ready calculation results; native vs Trade root/no-output distinctions; partial remote execution before shared failure; mutated nested recovery relations and mismatched cursor sets.

## 1. Pure composition and records

Add Pipeline Cargo member/model/program/pipeline/recovery and tests, with existing semantic crates only. First write failing boundary/behavior tests. Add explicit unobserved expected position to Calculation and support all-optional declared plans; atomically update affected tests/contract. Implement exact program and order guards, staged construction/state, real calculation receipts, cluster-scoped barrier and actual pure consumer outcomes. Shared errors fail-stop; per-cluster consumer failures quarantine. Capture/restore binds all components, validates fresh candidates before replacement. Preserve source isolation and no Trade-to-strategy shortcut.

## 2. Real worker adapter

Add worker Infrastructure adapter implementing Pipeline calculation port with explicit interpreter/artifact/generation/parameters. Fresh restore must create candidate processes and restore exact bundles before installing. Add real technical probe for multicycle shared Source construction, SMA warmup/ready, actual consumer counts, known rejection/UNKNOWN and fresh restart continuation; keep observations distinct from official Runtime behavior.

## 3. Build/verification/publication

Atomically update Cargo locks, dev dependency seed inputs, version graph, impact selectors, strict source/dependency guards and isolated closures; do not weaken existing lower-layer reverse-edge guards. Update owning Contract/navigation. Run RED/GREEN, targeted unit/vector/fault tests, affected Ruff/format/mypy/tools/build checks, closest canonical lanes (Python serial) and complete Rust lane. Review bounded simplicity and independent state space/relations; fix blockers with regression proof. Commit verified content, fetch exact remote base, ff-only master, push, fetch and prove alignment. Preserve any diagnosed pre-existing lane failure distinctly.
