# ADR 0101 — Verification Authority Convergence

- Status: Superseded for Final-SHA authority by ADR 0104; remaining quality-policy decisions stay Accepted
- Date: 2026-08-29
- Scope: engineering verification control plane

## Context

Mandatory gate membership had drifted among GitHub workflows, `scripts/certification.py`, architecture tests and narrative documentation.
Commented workflow coverage configuration could satisfy raw-text assertions, historical K7 evidence could be collected by shallow generic
lanes, and broad pytest/mypy surfaces were copied into multiple command lists.

ADR 0071 established immutable exact-SHA certification and, at that time, made branch coverage mandatory. ADR 0078 preserved that
then-current matrix while separating local verification from certification. The current decision changes only coverage membership and
verification ownership; it does not weaken exact-SHA identity, fail-closed verdicts, coverage thresholds or local coverage capability.

## Decision

`quality-policy.toml` is the single machine-readable authority for mandatory quality and certification gate membership, coverage mode and
historical evidence ownership. Workflows and architecture tests are projections of that authority; `scripts/certification.py` reads it when
constructing evidence.

Coverage mode is `manual`. Coverage commands, thresholds, pytest-cov and evidence outputs remain supported, and an invoked coverage run
below threshold fails. Coverage is not mandatory in regular GitHub CI or Final-SHA Certification.

The `gateway-protocol` gate exclusively owns immutable Git-history evidence, runs with full history and is mandatory in both quality and
Final-SHA verdicts. Generic current-tree lanes exclude `historical_git` tests.

Root pytest `testpaths` and root mypy `files` are the canonical broad discovery surfaces. `scripts/test_suite.py` derives workspace test paths
from root configuration and owns the reusable static command sequence. Package-local mypy remains only for packages with distinct configs.

Certification evidence schema version 2 records the quality policy schema version so the changed required-gate identity cannot silently
reinterpret schema version 1 artifacts.

## Supersession

This ADR supersedes only the statements in ADR 0071 and ADR 0078 that branch coverage is mandatory in regular or Final-SHA certification.
Their exact immutable SHA, complete mandatory-gate, local-budget and fail-closed invariants remain active.

## Invariants

- One machine policy owns mandatory gate identity.
- Commented YAML is never active verification configuration.
- Same immutable SHA, policy and required evidence produce the same verdict.
- Missing, unexpected, duplicate, skipped, cancelled or failed mandatory certification evidence rejects the verdict.
- Historical evidence is executed only by its declared full-history owner.
- Coverage thresholds remain unchanged and enforce whenever coverage is invoked.
