# Rust Margin Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline. Owner explicitly authorizes implementation, verification, independent review and mainline publication without further questions.

**Goal:** deterministic isolated Margin with real native consumer and strict recovery.
**Architecture:** Domain-only Margin; Execution consumes immutable results and freezes state with Account collateral in existing transaction groups.
**Tech Stack:** existing pinned Rust/Decimal/JSON/SHA and integer dependencies; single Linux dev environment.
**Spec:** ../specs/2026-10-20-rust-margin-design.md

## Global Constraints
No Constitution edits, official Runtime activation, LIVE, new Compose topology, hidden fallback, data reset or speculative dependency. Scope binds all owners and preserves immutable inputs. 512 history slots and 32 MiB checkpoint; source/record bounds are pre-admission obligations. Task/proof results remain ignored scratch.

## Review Focus
Whole-context and nested source substitutions must fail atomically; closing/cancel facts cannot borrow another reservation; split release retains final minor-unit remainder; resource admission must preserve existing safety progress; fresh-process recovery must prove all relations and immutable history.

### Task 1: Complete canonical Margin library
Files: crates/onlyalpha-kernel/margin/{src,tests,examples}, test-data/margin, scripts/margin_reference_check.py and direct Cargo/guard/version consumers.
Interfaces: Manager::new(config,capacity), apply(command)->Effect, snapshot(id), snapshots(), checkpoint(), restore(checkpoint,digest); Effect is opaque and detached.
- Write missing-module and behavioral assertions; run formal RED.
- Implement exact state machine and pre-reserved resource model; shared independent vectors and actual Python common cases.
- Run targeted native debug/release and Python reference; expected PASS with explicit classified deviations.

### Task 2: Real consumer and recovery
Files: Execution components/planning/tests, Account model/manager/tests and owning Contracts.
Interfaces: opaque effect -> exact per-reservation collateral projection; existing Store/Prepared/coordinator APIs retained.
- Add real consumer assertions and witness RED for missing operation.
- Implement Order/Trade preconditions, Account before/version/owner checks and atomic frozen Margin checkpoint.
- Prove partial Fill/cancel/close, duplicate/UNKNOWN/denied paths, all six projection cuts and true new-process recovery.

### Task 3: Integration, review and publication
Files: owning docs, dependency/source guards, version graph.
- Run affected baseline/static/types and canonical Rust lane in fixed dev, plus corresponding builds.
- Apply bounded Ponytail review and independent Authority re-derivation; fix High/Critical with witnessed regression.
- Verify one final source cut, release transition, Constitution fingerprint; commit, ff-only, push and fetch/tree proof while preserving unrelated local work.

## External evidence
NautilusTrader issue 4011 reports missing/margin accounts bypassing checks: derive mandatory funding/owner proofs and denied-atomicity tests, reject permissive fallback (https://github.com/nautechsystems/nautilus_trader/issues/4011). Curated FP-BROKER-002 requires fees remain part of affordability; FP-STORAGE-001 requires full causal history rather than snapshot-only recovery. No upstream code or retry behavior is imported.
