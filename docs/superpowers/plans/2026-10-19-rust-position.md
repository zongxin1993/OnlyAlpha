# Rust Position implementation plan

> Execution: superpowers:executing-plans inline; one bounded independent review at the end. Owner authorizes autonomous execution and final master push.

**Goal:** implement the non-activated Position component in one isolated crate.
**Spec:** ../specs/2026-10-19-rust-position-design.md
**Global constraints:** Constitution immutable; one dev Compose; Domain-only local dependency; no new registry package; no Python production changes, activation, data migration or Release.

## Task 1 — Atomic economic state

Create position/src/{lib,model,manager}.rs and tests/lifecycle.rs. Consumes Domain values and strict component commands. Produces Manager::new(config), apply(command), account(instrument), cluster(cluster,instrument), unallocated(instrument), state(), checkpoint(), restore(bytes,digest). Write lifecycle, attributed costs, ownership, unsupported-input and receipt tests first; observe missing API failure in canonical dev. Implement deterministic cycles, exact accumulated costs, single-candidate Position/Allocation updates and explicit outcomes; pass tests.

## Task 2 — Holds, reconciliation and recovery

Add position/src/{reservation,reconciliation,recovery}.rs. Consume the same candidate state. Produce explicit reservation/broker/settlement/restriction commands and fresh atomic recovery. Write partial fills, acknowledged freezes, cancellation uncertainty, stale observation, interval, cross-owner and tamper/continuation tests; observe failures; implement then pass. Shared interfaces: all commands use one candidate state and journal; recovery must replay every Applied/Observed outcome and compare the full state, not snapshots alone.

## Task 3 — Actual comparison and engineering boundary

Create position corpus and scripts/position_reference_check.py, boundary/reference tests. Extend existing rust_kernel_check, version_sync, verify and their inventory fixtures atomically. Prove actual Python common Opens and canonical Close reducer vs independent literal expectations and real Rust debug/release output. Prove isolated Domain+Position compilation and reject effects/reverse edges. Formal scoped tests, Ruff/format/mypy, Clippy, debug/release and affected canonical lane through scripts/dev_verification.py.

## Review focus

Exact command/external identity aliases; mixed-cluster close cost/remainder; other-order holds and broker freeze double deductions; stale/UNKNOWN/missing Broker proof clearing restrictions; coherent checkpoint state/receipt/cycle/owner mutation and atomic failure. Cover each with tests. One fresh bounded independent review derives Authority state space, ownership relations and negative invariants; fix High/Critical with red-green regressions. Finish when required behavior and scope checks pass, then audited ff-only master push and fetch alignment proof; keep 0.10.10.
