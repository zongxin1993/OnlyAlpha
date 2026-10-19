# Rust Account implementation plan

> Execute inline with superpowers:executing-plans and TDD; one bounded independent review at the end. Owner authorizes autonomous implementation and final mainline push.

**Goal:** independent, non-activated Account cash semantics.
**Spec:** ../specs/2026-10-19-rust-account-design.md
**Global constraints:** immutable Constitution; Domain-only local edge; no new registry package; sole dev Compose verification; no Python production changes, activation, data migration or Release. Keep 0.10.10 per owner release cadence.

## Task 1 — Account cash and reservations

Create account/src/{lib,model,manager,reservation}.rs and tests/lifecycle.rs. Consumes Domain values and closed schema1 inputs. Produces Manager::new(config), apply(command), snapshot(), reservation(id), state(), checkpoint(), restore(bytes,digest), Status and Outcome. First observe missing API failure through dev verification, then implement atomic cash/trade/reservation transitions. Test actual money conservation, fee/rebate attribution, partial and terminal holds, uncertain cancellation, exact identities, cross-scope and numeric bounds.

## Task 2 — Observations and recovery

Create account/src/{reconciliation,recovery}.rs using the same candidate/journal. Add tests for stale/unverified Broker proof, valuation basis, settlement identity, duplicate acknowledgements, journal/full-state tampering and fresh deterministic continuation. Observe failures then implement. No lower-level state/receipt is duplicated in callers.

## Task 3 — Cross-language comparison and engineering integration

Add independent account cash corpus, scripts/account_reference_check.py and tests/tools/test_rust_account_boundary.py. Extend existing rust_kernel_check/version_sync/verify and exact inventory fixtures; no threshold or gate weakening. Prove real Python common economics and reducer results vs independent literals and native Rust debug/release. Run scoped Python/static checks, full affected Rust canonical lane and isolated Domain+Account builds. Perform bounded simplicity review and one independent Authority review; fix blocking findings with red-green regressions. Push only after passing scope checks and audited ff-only alignment.

## Review focus

Fee and trade alias reuse across different orders; terminal and unknown releases; excess fill consuming other holds; Broker comparison clearing stale/uncertain state; replay laundering duplicated receipts or omitted state. Retain tests for each. Later Account/Ledger/Risk/Execution integration owns durable cross-authority atomicity.
