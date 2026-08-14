# P7.5 Research Factor / Feature / Score Semantic Closure

Date: 2026-08-14

## State

- Initial SHA: `b33e5ab8eee7949270aae45ab30ac2781db0b525`
- Final SHA: pending; this report is part of the current uncommitted working tree
- Branch: `master`
- Implementation: IMPLEMENTED
- Local verification: VERIFIED for the canonical local matrix below
- Remote exact-SHA certification: NOT EXECUTED for this working tree

The prompt records that the initial SHA had a successful remote Final-SHA Certification after its creation baseline. This local
environment has no authenticated GitHub CLI session and contains no downloaded certification artifact, so that historical remote
claim could not be independently revalidated here. It is not inherited by P7.5.

## Current Truth and Authorities

The implementation re-read current Calculation Core, official Indicator/Factor plugins, Research Dataset/Calculation/Result/Job,
their public exports, P7 ADRs, tests, quality lanes and certification workflow. The authority chain remains:

```text
verified Dataset Snapshot
-> canonical Calculation Definition / Graph
-> exact RESEARCH backend execution
-> immutable Calculation Result keyed by calculation_fingerprint
-> Research Job verified reuse or deterministic execute/commit
```

Dataset Store owns admitted facts. Graph owns dependencies and topology. Definition owns port/numeric/missing/timestamp/execution
semantics. Executor owns canonical axis alignment only. Result Store is the sole durable Factor Value/Score authority. Job owns no
second state and re-enters through `load_verified()`.

## Implemented

- ADR 0076 freezes Indicator, Feature, Raw Factor Value, Factor Score and cross-section semantics.
- Feature remains a `(node_fingerprint, output_name)` port and has no new identity/store/job.
- `FACTOR_VALUE` and bounded Decimal `FACTOR_SCORE [0,1]` are machine-readable port semantics.
- Deterministic read-only type descriptors and stably sorted Registry introspection come from canonical TypeDefinition only.
- Official `onlyalpha.factor.momentum@1` consumes two explicit Rolling Return nodes and emits a raw Factor Value.
- Official `onlyalpha.factor.cross_section_percentile@1` applies Decimal average rank with exact direction, null and singleton rules.
- Research execution is semantic-node-first: TIME_SERIES per stable instrument, CROSS_SECTION per exact timestamp and sorted
  instrument axis; outputs return to existing `(node_fingerprint, instrument_id)` partitions.
- Existing Calculation, Dataset, Result and Job identities/schemas remain unchanged. Research Runtime remains unsupported.
- A dedicated `research-factor` lane and 100% line/branch gate cover P7.5 execution/plugin logic and architecture boundaries.

## Identity Regression Evidence

The unmodified initial SHA was exported from Git and executed from an isolated `/tmp` tree. Its Indicator-only reference identities
were then compared with the P7.5 working tree and frozen by regression test:

| Authority | Initial SHA and P7.5 working tree |
|---|---|
| Graph | `7f631b1ec661ccacd14774cbe5c7cfd59cbef848642c72b5e0581ac0c1b6626f` |
| Calculation | `f337e136ee125a4080752407c39df42cd691bd70b0992ea99f79523e97e758a6` |
| Result Content | `6caf8ea98bfa08bd68a4047eab165dfac11e3b63b2dccbcfe43add850afd8ba0` |
| Calculation Result | `7177fa2d1ba38f891a5a9884a264f06357c1e277ddeff9e23d4a3517bc81b8fb` |

## Local Verification Evidence

Completed:

- pre-change `research-calculation`: 123 passed;
- pre-change `research-job`: 30 passed;
- pre-change `calculation`: 54 passed;
- P7.5 `research-factor --coverage`: 51 passed; 100.00% lines and 100.00% branches;
- `research-calculation`: 123 passed; coverage total 87.49%;
- `research-job`: 30 passed; coverage total 100.00%;
- `calculation`: 54 passed; coverage total 88.15%;
- `research-dataset`: 36 passed; coverage total 89.30%;
- `core-full`: 1535 passed, 1 skipped; coverage run 1535 passed, 1 skipped, 486 deselected; total 83.66%;
- `recovery`: 328 passed;
- `sim-recovery`: 37 passed;
- `ashare`: 24 passed;
- `miniqmt-contract`: 34 passed;
- full Ruff and format check: PASS across `src tests examples packages scripts`;
- Core mypy: PASS, 492 source files;
- official Indicator + Factor plugin mypy: PASS, 9 source files;
- Generic/CN A-share market and Tushare/MiniQMT provider mypy: PASS, 6/7/15/36 source files;
- import-linter: 3 contracts kept, 0 broken;
- version sync: PASS at `0.4.4`;
- `uv sync --frozen --all-packages --all-groups`: PASS;
- `uv build --all-packages`: PASS for all eight workspace distributions;
- `git diff --check`: PASS after the final report update;
- baseline archive versus working-tree identity comparison: exact match for all four authorities above.

Local Semgrep was attempted twice, including metrics/version-check disabled, but failed before scanning because the installed
binary could not create an X509 authenticator from the host's empty CA trust store. It is `NOT EXECUTED / ENVIRONMENT FAILURE`, not
PASS. A local CodeQL CLI is unavailable. Both remain mandatory in remote exact-SHA certification.

## Non-goals and Remaining Product Boundary

P7.5 does not implement Parameter Sweep, optimization, forward return, IC/Rank IC or other statistics, Research Result/Artifact,
Feature Store, scheduler/worker/job database, distributed Research, Query/API/Web, portfolio/order generation, or Research Runtime
activation. No TRADING backend was invented for the new Factors.

## Final State

`LOCALLY IMPLEMENTED / VERIFIED`. It cannot become `CERTIFIED` without one
immutable final commit and a successful remote Final-SHA Certification artifact for that exact SHA.
