# Rust Calculation Foundation Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline; owner waived further questions. Tracking remains in ignored task context per AGENTS.

**Goal:** independently buildable Calculation contracts, normalization, DAG and registry.
**Architecture:** one pure library; immutable validated records; no algorithm or execution authority.
**Tech Stack:** existing pinned Rust, serde_json, bigdecimal, sha2; Linux onlyalpha-dev.
**Spec:** docs/superpowers/specs/2026-10-18-rust-calculation-foundation-design.md

## Global Constraints

Definition component schema3 is not admitted to Python Definition2 or official Runtime. No data changes, Python retirement, Release or version bump. Existing registry closure stays unchanged. No Runtime/algorithm/loading effects.

## Review Focus

- Tagged Decimal/string collision and numeric spelling equivalence.
- Malformed nested types, bounds/default/enum mismatches and resource limits.
- DAG ordering/compatibility, deep traversal and exact producer references.
- Cross-backend conflicts must leave registry unchanged.
- New dependency must enter every exact source/environment/version/build closure atomically.

### Task 1: semantic records and normalization

Files: calculation/src/{lib,record,definition,parameters}.rs, tests/contracts.rs; shared definitions-v1.jsonl and Python consumer.
Interfaces: Definition::from_record/to_record/fingerprint/execution_shape, TypeDefinition::from_record/resolve, normalized parameters.
Write tests for schema3/typed hash/equal decimals, nested invalid mutations and strict normalized parameters; run missing-API RED through dev runner. Implement bounded immutable records using existing dependencies. Run Rust targeted tests and Python projected common corpus. Expected green. Commit source/docs after affected checks.

### Task 2: DAG and registry

Files: calculation/src/{graph,registry}.rs, tests/graph_registry.rs.
Interfaces: Graph::from_record/new/to_record/fingerprint/ordered_nodes and Registry<P>::register/resolve/resolve_type/types/registrations.
Write tests first for graph identity/order/alias/compatibility, exact registration and atomic conflict. Verify RED, implement iterative traversal and typed exact keys; run package tests debug/release. No backend execution API.

### Task 3: admission and publication

Files: root Cargo manifests/lock, rust_kernel_check/version_sync and directly affected test fixtures, owning navigation docs.
Write failing boundary/isolated closure tests, verify RED, admit exact new package and source guard. Update all direct fixture manifests. Rebuild fixed dev image only once if final manifests change environment identity. Run affected Python/Ruff/mypy/version/Constitution and rust-kernel canonical lane; simplicity and one independent review. Fix blocking findings with regression. Commit, verify source/tree equality, ff master, push and fetch. Expected remote exact HEAD, clean worktree. No Release.
