# P7.7 Research Target & Statistics Semantic Closure

- Date: 2026-08-15
- Repository baseline SHA: `b3a4a0da76b35646a1da28a3f72861cb7a23178a`
- Implementation branch: `codex/p7-7-research-evaluation`
- Implementation commit SHA: `b04ed630462b41ac761077b35a8403815f30a383`
- Verification subject SHA: `ea0bcf8628435b12125c6e67f481ad2c1be575ac`
- Version: `0.7.7`
- P7 milestone: `IN_PROGRESS`
- Increment status: `VERIFIED`

## Current Truth Before Change

The baseline already implemented immutable Research Dataset, batch/vectorized Calculation, immutable Calculation Result, verified
Job orchestration, Factor/Feature/Score, and deterministic Sweep. Target, Forward Return, Statistics, IC, Rank IC and a Statistics
durable authority did not exist. Research and Live Runtime factories remained unsupported. Architecture documentation still
incorrectly described Job/vectorized execution as absent.

P7.6.2 remote evidence was also stale in documentation. Exact merged subject
`b3a4a0da76b35646a1da28a3f72861cb7a23178a` passed Layered Quality `31857857900`, CodeQL `31857857896`, Final-SHA Certification
`31859600423`, and Nightly Heavy Quality `31862902178`; exhaustive, formal, mutation and performance jobs all succeeded. P7.6.2 is
therefore recorded as `VERIFIED` without claiming that its later documentation commit inherited the certification subject.

## Calculation Semantic Change and Compatibility

`OnlyCalculationKind` adds `TARGET`; Definition schema remains v2 and Graph schema remains v1. Indicator/Factor semantic payloads are
unchanged. Frozen regression values remain:

- Indicator Definition: `49d97b301c4879ce787c87c1745a965fb8dc4ed1c037d4a9fd082e4bafb069c3`.
- Factor Definition: `148722d0c89cdcd47bf4cef94a0d4179abf579c3d01e49fd70f6ef55c435f02d`.
- Representative Factor Graph: `94220fca8f569c34bba94073dda8808d0060ddb9ce904100c7732cfbfd7f0cf3`.
- Existing Indicator Graph/Calculation/Result golden identities remain covered by the P7.5 regression test.

Target is TIME_SERIES-shaped without acquiring `OnlyFactorKind`. Existing Factor remains runtime-neutral and declares only
TIME_SERIES/CROSS_SECTION; backend remains RESEARCH/TRADING and Runtime remains RESEARCH/BACKTEST/SIM/LIVE.

## Target / Forward Return Contract

The new workspace distribution `onlyalpha-plugin-targets` registers only
`TARGET + onlyalpha.target.forward_return + semantic_version 1 + RESEARCH`. SIMPLE RETURN is computed as
`exit_price[t + exit_offset] / entry_price[t + entry_offset] - 1`, with `entry_offset >= 0` and
`exit_offset > entry_offset`. Price meaning comes solely from existing Calculation bindings. Horizon is canonical per-instrument bar
offset only. Output remains aligned to observation timestamp and insufficient future rows are NULL. Dataset adjustment authority is
not duplicated. Null, non-Decimal, non-finite or non-positive prices fail closed rather than producing NaN/Infinity.

Target execution reuses verified Dataset admission, exact RESEARCH backend resolution, Calculation fingerprint, Calculation Result
Store and Research Job. No Target/ForwardReturn/Label Store is introduced.

## Feature / Evaluation Isolation

Graph construction enforces:

- Feature and Target require separate Graphs.
- Indicator/Factor consuming Target is forbidden.
- Target consuming Indicator/Factor/Target is forbidden in V1.
- Target consuming external Dataset sources is allowed.

Changing Target horizon or source changes Target identity and downstream Statistics identity, not Feature Calculation identity.
Research Runtime remains unsupported and Target has no TRADING backend.

## Statistics Semantics

Statistics Plan references exact Feature and Target series by Calculation fingerprint, node fingerprint and output name. Both
Calculation Results are loaded through `load_verified()` and must reference the same Dataset Snapshot. Feature port must be a Factor
Value or Factor Score; Target port must be TARGET_VALUE. Alignment is exact `(instrument_id, ts_event_ns)` with pairwise complete
non-null selection and stable instrument/timestamp ordering.

Definition v1 supports IC and Rank IC, explicit minimum observations, PAIRWISE_COMPLETE, OBSERVED_PAIRWISE, AVERAGE tie ranking,
EQUAL weighting, and Decimal(38)/1e-12/ROUND_HALF_EVEN numeric semantics. TIME_SERIES Factor output is valid input for timestamp-level
cross-sectional IC. Result rows contain `ts_event_ns`, nullable `statistic_value`, `sample_count`, and explicit status: VALID,
INSUFFICIENT_OBSERVATIONS, ZERO_VARIANCE_FEATURE, or ZERO_VARIANCE_TARGET.

## Identity and Durable Result

Three semantic identities remain distinct:

```text
Feature Reference + Target Reference + Statistics Definition
→ statistics_fingerprint

canonical ordered timestamp rows
→ result_content_fingerprint

statistics_fingerprint + result_content_fingerprint
→ statistics_result_fingerprint
```

The Statistics Store uses a content-addressed path keyed by `statistics_fingerprint`, exact versioned manifest and one natural
timestamp-level Parquet table. It verifies upstream Calculation Result fingerprints, Dataset linkage, plan/statistics identity,
Arrow schema, byte SHA-256, canonical rows and both Result identities. Publication is staged, logically read back, fully verified and
atomically renamed. Equal recommit is idempotent, unequal content is deterministic conflict, and corrupt existing authority is never
treated as missing or overwritten.

## Sweep Composition

Integration verification executes multiple independent Feature calculations against one shared verified Target Result. The Target
Job returns REUSED across consumers. P7.7 introduces no optimizer, objective, best-trial selection, Sweep Store or experiment DB.

## Test and CI Changes

A single `research-evaluation` canonical lane owns evaluation tests, official Target plugin tests, look-ahead architecture tests and
frozen Calculation identity regression. It enforces line coverage >=95% and branch coverage >=90%, and is wired into Layered Quality
PR/master matrices, coverage, local release composition and Final-SHA Certification. `scripts/test_suite.py` remains the sole pytest
selection authority; existing Nightly architecture is reused.

Local evaluation evidence at report creation:

- research-evaluation: 96 tests PASS with the CI Hypothesis profile for coverage.
- line coverage: 95.90%.
- branch coverage: 94.17%.

Additional final-tree local evidence:

- `uv sync --frozen --all-packages --all-groups`: PASS.
- Ruff check / format check: PASS across src, tests, examples, packages and scripts.
- strict mypy: PASS across 522 Core/Indicator/Factor/Target source files.
- import-linter: PASS, all 3 contracts kept.
- version sync and lock checks: PASS at 0.7.7.
- research-calculation: 127 PASS.
- research-factor: 57 PASS; its existing 100% coverage gate is unchanged.
- research-job: 30 PASS.
- research-sweep: 27 PASS; its existing branch floor is unchanged.
- calculation: 58 PASS.
- core-full: 1697 PASS, 1 skipped on the final tree.
- `uv build --all-packages`: PASS; all 9 formal workspace distributions produced sdist and wheel, including Target plugin 0.7.7.
- `git diff --check`: PASS.

Remote verification for exact subject `ea0bcf8628435b12125c6e67f481ad2c1be575ac`:

- Layered Quality: `31865555598` — PASS. Static, dependency audit, Semgrep, build, all mandatory PR lanes, coverage, recovery and
  aggregate quality-gate completed successfully.
- CodeQL: `31865555591` — PASS. Independent Python analysis completed successfully. The Layered Quality workflow's embedded CodeQL
  compatibility job was skipped by design; it is not the independent CodeQL authority.

This later documentation update records evidence for the immutable verification subject above; it does not claim that the
documentation commit inherited that subject's exact-SHA evidence.

## Documentation and Version

README, roadmap and architecture now describe implemented Dataset/Calculation/Result/Job/Factor/Sweep/Target/Statistics boundaries,
P7.6.2 verified evidence, P7.7 current status, and remaining Research Result/Artifact/Runtime work. ADR 0082 freezes the evaluation
authority. `scripts/version_sync.py set 0.7.7` updated the root and all workspace distribution versions, exact internal pins, README
version row and `uv.lock`; the new Target plugin is a formal workspace member.

## Known Limitations and Deferred P7.8 Work

- Research Runtime and Live Runtime remain unsupported.
- Research Result, provenance composition, Research Artifact and finite product lifecycle remain P7.8+ work.
- No optimizer, calendar/session horizon, cross-Dataset evaluation, ICIR/decay/portfolio analytics, scheduler, distributed execution,
  Query/API/Web or Trading Target backend is implemented.

## Current Verdict

`P7.7 VERIFIED — local semantic, identity, corruption, property, coverage and integration closure passed; exact verification subject
ea0bcf8628435b12125c6e67f481ad2c1be575ac passed mandatory Layered Quality and independent CodeQL.`
