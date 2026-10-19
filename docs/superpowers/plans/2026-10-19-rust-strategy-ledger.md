# Rust Strategy Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Isolated deterministic Cluster financial attribution and recovery.
**Architecture:** One Runtime Manager owns explicitly configured Ledgers; normalized Position/Order/Fee inputs retain their Authority.
**Tech Stack:** Existing pinned Domain/BigDecimal/BigInt/serde_json/sha2; Linux single dev Compose.
**Spec:** `docs/superpowers/specs/2026-10-19-rust-strategy-ledger-design.md`.

## Global Constraints

Constitution unchanged; version0.10.10; no new registry dependencies or Runtime activation/history migration. Fixed onlyalpha-dev entry. Owner authorized current-session execution and master publication without more prompts. No committed progress/quality ledger.

## Review Focus

Cross-Cluster identity reuse; gross hold versus rebates; altered causal checkpoint relations; incomplete/stale valuation; same-time global ordering and calendar/external-flow effects. Pin each with an adversarial test.

### Task 1: Atomic financial lifecycle and recovery

Files: crate `src/{lib,model,manager,accounting,valuation,recovery}.rs`, `tests/lifecycle.rs`; Cargo member/lock.
Interfaces: `Manager::new(Value)`, `apply(&Value)->Result<Outcome,Error>`, `snapshot(cluster)`, `state()`, `checkpoint()`, `restore(bytes,digest)`.
- [ ] Write capital/scope/Cluster/reservation/UNKNOWN/partial/terminal/conflict tests; run formal RED (missing API).
- [ ] Implement closed schema, bounded decimal, candidate state, immutable entries and exact Allocation chaining.
- [ ] Write and run RED for valuation/returns/calendar/global equity and adversarial recovery; implement and run debug/release GREEN.

### Task 2: Reference and canonical gates

Files: `test-data/strategy-ledger/valuation-v1.jsonl`, `scripts/strategy_ledger_reference_check.py`, crate `tests/reference.rs`, `tests/tools/test_rust_strategy_ledger_boundary.py`; canonical Rust/version/impact inventories.
Consumes Task1 API; produces permanent actual-Python/literal/Rust comparison and isolated Domain+Ledger closure.
- [ ] Write literal vectors and reference/boundary tests; run RED, then integrate real Python valuation/ledger and native reference check.
- [ ] Enforce exact dependency closure and source isolation; update fixture inventories atomically.
- [ ] Update owning Contract/development/roadmap source navigation; no status ledgers.
- [ ] Run targeted Python/Ruff/format/mypy and complete Rust canonical lane through formal dev entry.

### Task 3: Review and publish

Consumes preceding interfaces/evidence; produces reviewed master commit without Release.
- [ ] Bounded Ponytail diff review, apply warranted simplifications and rerun affected checks.
- [ ] One independent authority review: state-space, relation closure, negative invariants, structural mutations; High/Critical fixes RED→GREEN.
- [ ] Verify Constitution/frozen source; commit, fetch, ff-only master, push and fetch alignment without force.
