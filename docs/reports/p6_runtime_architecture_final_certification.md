# P6 Runtime Architecture Final Certification

## Certification Model

This repository report records scope and local evidence; it is not the certification authority for its own commit. The certification subject is an immutable 40-character `subject_sha`. The external `P6 Final-SHA Certification` workflow checks out that exact SHA in every job and emits `p6-certification-evidence.json` as a workflow artifact. The artifact is the final verdict authority, so no follow-up report commit is needed and no self-referential certification cycle exists.

`IMPLEMENTED` means the code is complete. `VERIFIED` means named gates have actual evidence. `CERTIFIED / ACCEPTED` requires the external artifact to report every mandatory gate successful for one exact subject SHA.

## Current Subject

Pending: this hardening report is part of the working tree based on initial HEAD `910bce3eb08cd9728a0226e6ee4dce4438de278f`. A final subject SHA and remote evidence do not exist until the changes are committed and the certification workflow completes.

## Implemented Scope

P6.0–P6.6 provide runtime control/semantic separation, canonical SIM, realtime Virtual Broker normal causality, continuity repair, durable checkpoint/new-process recovery, taxonomy cutover, and removal of active PAPER/SHADOW products. Active taxonomy is exactly `RESEARCH / BACKTEST / SIM / LIVE`; BACKTEST and SIM are implemented, while RESEARCH and LIVE remain unsupported future targets.

P6 Final Hardening adds:

- transactional `OnlyEngine.start()` convergence across multiple Runtime sessions;
- reverse compensating cleanup with original-failure preservation and cleanup-error notes;
- bounded Streaming processing diagnostics with an independent lifetime total counter;
- an immutable-subject certification workflow with mandatory branch coverage and security gates;
- an explicit historical-Prompt boundary.

No checkpoint/persistence schema, participant identity, transaction identity, runtime identity derivation, durable transaction semantics, or recovery canonical identity changed.

## Mandatory Certification Gates

The exact subject SHA must pass:

- ruff check and format check;
- Core and every workspace package mypy target;
- import contracts and version sync;
- all-package build;
- `core-full`, `recovery`, `sim-recovery`, `ashare`, and `miniqmt-contract`;
- branch coverage at the repository threshold;
- Semgrep;
- CodeQL.

Missing, skipped, cancelled, or failed mandatory gates cannot produce `ACCEPTED`.

## Local Verification Evidence

The hardening working tree passed:

- targeted lifecycle/diagnostics/certification tests: 28 passed;
- `fast`: 1184 passed, 1 skipped;
- `core-full`: 1313 passed, 1 skipped;
- `recovery`: 328 passed;
- `sim-recovery`: 37 passed;
- A-share conformance: 24 passed;
- MiniQMT contract: 33 passed;
- branch coverage: 1313 passed, 1 skipped, 83.11% combined coverage (87.81% lines, 61.11% branches);
- ruff check and format, Core and package mypy, import contracts, version sync, frozen workspace sync, workflow YAML parsing, and all-package build: PASS.

Local Semgrep remains unavailable because the installed binary fails before startup on an empty system X509 trust store. This is not recorded as a pass. CodeQL and the mandatory remote Semgrep job require the final committed subject SHA and GitHub-hosted workflow execution.

## Certified Boundary and Limitations

SIM remains Realtime MarketData + Live Clock + Virtual Broker + the shared Trading Kernel. It cannot compose a Real Broker. The scope does not include Research Job/Plan, production LIVE, durable outbound Real Broker commands, Broker synchronization/reconciliation, 24-hour production soak, long-running production operations, broad MiniQMT environment coverage, or automatic legacy PAPER-state conversion.

## Current Decision

`CONDITIONALLY_ACCEPTED`: mandatory local functional/static/build/coverage gates pass, but no final committed subject SHA or exact-SHA remote Semgrep/CodeQL/certification artifact exists. Until that external evidence succeeds, P7 Readiness is `NO` and no remote PASS is asserted.
