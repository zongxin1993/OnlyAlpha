# P6 Runtime Architecture Final Certification

## Final SHA

Pending: this report is part of the uncommitted P6.6 working tree. Same-SHA remote evidence is not yet available.

## Scope

P6.0–P6.6 runtime control/semantic separation, canonical SIM, continuity, durable recovery, taxonomy cutover, and legacy removal.

## Runtime Product Taxonomy

The active taxonomy is exactly `RESEARCH / BACKTEST / SIM / LIVE`. BACKTEST and SIM are implemented; RESEARCH and LIVE remain explicit future targets.

## Legacy Products Removed

The PAPER and standalone SHADOW enum values, packages, factories, registrations, public exports, configs, scripts, and product tests were removed. No alias or compatibility wrapper remains.

## Streaming Ownership

`runtime/streaming` owns product-neutral subscription, worker, phase, semantic lane, bootstrap/handoff, watermark, continuity, gap/reconnect, timer, checkpoint coordination, recovery, diagnostics, and processing admission. `runtime/sim` owns SIM composition, Virtual Broker wiring, persistence, and state lease.

## Backtest Certification

PASS locally. `core-full` (1303 passed, 1 skipped), `recovery` (328 passed), A-share conformance (24 passed), and workspace build completed without failure.

## SIM Normal-Path Certification

PASS locally. Existing public Engine integration proves Bar N Accepted, no same-bar fill, Bar N+1 Trade, durable transaction, and ordered projection; `integration` passed 129 tests.

## SIM Continuity Certification

PASS locally. Existing integration coverage includes unexpected gap, stale/disconnect recovery, buffered catch-up, and processing cutoff.

## SIM Durable Recovery Certification

PASS locally. `sim-recovery` passed 36 tests, including checkpoint verification, new instance/process restart, corruption fail-closed, state lease, repeated restart, and canonical-world comparison. An initial concurrent run had one unchanged three-second checkpoint wait expire while other heavy lanes ran; the complete lane passed unchanged when run in isolation.

## Existing SIM Durable Compatibility

No checkpoint or persistence schema, participant identity, transaction identity, or runtime identity derivation was changed by P6.6.

## Legacy PAPER Durable-State Policy

Intentionally unsupported. Legacy state is not converted or interpreted as canonical SIM state.

## Architecture Invariants

The Trading Kernel and Strategy Context remain Runtime-neutral. SIM uses simulated Broker capabilities and cannot submit through a Real Broker path.

## Config / Public API Migration

`PAPER` and `SHADOW` now fail closed during config parsing. Their Runtime classes and factories are no longer importable.

## Scenario / Product Certification

Finite Scenario execution remains BACKTEST-only. Streaming SIM certification uses the public Engine lifecycle and existing deterministic integration/recovery suites.

## Documentation Reconciliation

README, architecture, runtime, roadmap, quality-system, and ADR implementation history were reconciled with active source truth.

## Test Evidence

- targeted taxonomy/config/factory/application/scenario: 63 passed;
- SIM product plus architecture: 216 passed;
- fast: 1174 passed, 1 skipped;
- integration: 129 passed;
- core-full: 1303 passed, 1 skipped;
- recovery: 328 passed;
- sim-recovery: 36 passed;
- A-share conformance: 24 passed;
- MiniQMT contract: 33 passed;
- branch-coverage gate: 1303 passed, 1 skipped, 83.11% total coverage;
- ruff, format, Core/package mypy, import contracts, version sync, and all-package build: PASS.

Local Semgrep could not start because the installed binary found an empty system X509 trust store. This is recorded as unavailable, not passed; remote Semgrep/CodeQL evidence remains required.

## CI Evidence

Unavailable until a final commit SHA exists and remote checks run on that exact SHA.

## Explicit Non-Goals

Research Job implementation, production Live Runtime, Real Broker durability/reconciliation, and automatic PAPER-state conversion.

## Remaining Known Limitations

SIM certification does not cover Real Broker, long-running production operations, 24-hour soak, or a broad MiniQMT environment matrix.

## P7 Readiness

NO. Local functional/static/build gates passed, but no final commit SHA or same-SHA remote quality/security evidence exists yet.

## Final Decision

CONDITIONALLY_ACCEPTED pending complete local gates and same-SHA remote CI evidence.
