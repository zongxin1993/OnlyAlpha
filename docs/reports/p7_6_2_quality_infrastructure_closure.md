# P7.6.2 Quality Infrastructure Closure

- Date: 2026-08-15
- Starting SHA: `05052448239f2aac178695362d67d6731a7d229c`
- Starting branch/default branch: `master`
- Final implementation SHA: PENDING IMMUTABLE COMMIT
- Version: `0.4.4` (unchanged)
- P7 status: `IN_PROGRESS`
- P7 Final Certification: `NOT COMPLETE`

## Scope and Non-Goals

This increment closes verification infrastructure integrity, performance verification integrity, dependency security visibility,
and current-status truthfulness. It does not implement Research Target, Forward Return, IC/Rank IC, Statistics, Research Result,
Research Artifact, Research Runtime, Live Runtime, Broker synchronization, or any Trading/Calculation semantic capability.

No file under `src/onlyalpha/` or `packages/**/src/` is changed. Public API, persistence/checkpoint/result schemas, Runtime semantics,
Calculation identity, coverage thresholds, and product capability remain unchanged.

## Current-Truth Audit

The audit fetched `origin/master`, confirmed local and remote HEAD at the starting SHA, read recent commits, current README,
roadmap, architecture documents, applicable ADRs/reports, every active quality/release workflow, canonical test/certification tools,
ASV configuration/benchmarks/performance tests, and the current Research implementation boundary.

Three gaps remained at the starting SHA:

1. Nightly used shallow checkout plus `asv run --quick HEAD^!`, had no fresh-runner machine bootstrap or suite validation, and uploaded
   paths without proving that useful comparison evidence existed.
2. The latest commit had deleted Dependabot and Dependency Review; `uv.lock` had no repository-controlled mandatory vulnerability
   audit in Layered Quality or Final-SHA Certification.
3. README identified P7 as `IN_PROGRESS`, while roadmap still titled P6 as the current phase and had no singular current milestone/
   increment authority block.

## Performance Closure Contract

- Performance jobs fetch full Git history.
- `asv check` distinguishes invalid benchmark definitions from execution/regression failure.
- `asv machine --yes` creates a run-local `github-actions-${GITHUB_RUN_ID}` identity on the ephemeral runner.
- `asv continuous --interleave-rounds HEAD^ HEAD` compares parent and candidate in the same job, runner, environment, and machine
  identity using ASV 0.6.6 statistical comparison semantics; no custom factor was invented.
- `--quick` is absent from formal evidence.
- pytest-benchmark writes explicit JSON; ASV writes saved result JSON and a captured comparison transcript.
- subject SHA, parent SHA, ASV version, machine identity, and workflow run are persisted; required evidence paths are validated before
  success and artifact upload rejects an empty path.

Starting-state `asv check` reproduced a real definition failure because `benchmarks/` lacked `__init__.py`. The minimal package marker
was added without adding, deleting, or changing a benchmark. The first immutable-candidate comparison then exposed a second real
monorepo defect: ASV's default uv build produced every workspace wheel and could not select the benchmarked distribution. The ASV
configuration now uses ASV's environment Python to build only the root project wheel with `pip wheel --no-deps` into the
commit-specific cache. Runtime dependencies remain installed by ASV's subsequent wheel install; the command does not change the
workspace release build or benchmark count.

## Dependency Security Contract

- Scanner: OSV-Scanner `2.5.0`, pinned in workflows to action commit
  `06b2ab4348248b456ee06c9e953637f55e03504f`.
- Audit authority: root `uv.lock` only; repository recursion and runner `pip freeze` are not used.
- Policy: known vulnerability or scanner infrastructure failure is not a pass. There is no `continue-on-error` and no soft-pass.
- Exceptions: `NONE`; no exception configuration was created.
- Evidence: exact subject SHA, `uv.lock` SHA-256, scanner/version, UTC scan time, raw-result digest, findings, approved exceptions,
  workflow run/URL, and explicit `PASSED / VULNERABILITY_FOUND / SCAN_INFRASTRUCTURE_FAILURE` status.
- Composition: dependency-audit is mandatory in both Layered Quality `quality-gate` and Final-SHA certification evidence/verdict.

The initial authoritative scan found `cryptography 49.0.0` affected by `PYSEC-2026-3552 / GHSA-g6cj-pr64-35w5`
(`CVE-2026-69247`, fixed in `50.0.0`). It was a development-only transitive dependency through
`twine -> keyring -> secretstorage`. No exception was accepted. A single-package lock update moved it to `50.0.0`; a second scan of
104 resolved packages returned zero findings.

## Changed Files

- `.github/workflows/quality.yml`: mandatory exact-lock dependency audit and aggregate dependency.
- `.github/workflows/certification.yml`: exact-subject dependency audit and certification evidence gate.
- `.github/workflows/nightly.yml`: fresh-runner, same-run performance comparison and durable evidence.
- `.github/workflows/release-quality.yml`: align active release performance verification with the same non-quick ASV contract.
- `asv.conf.json`: build exactly one root `onlyalpha` wheel for ASV commit installation.
- `benchmarks/__init__.py`: make the existing ASV suite valid.
- `scripts/dependency_audit.py`: fail-closed, time-scoped dependency evidence builder.
- `scripts/certification.py`: add `dependency-audit` to the exact mandatory gate identity.
- `tests/architecture/test_certification_contract.py`: freeze workflow/certification/performance composition.
- `tests/architecture/test_dependency_audit_contract.py`: freeze pass/finding/infrastructure-failure evidence semantics.
- `uv.lock`: only `cryptography 49.0.0 -> 50.0.0` to remediate the actual finding.
- `README.md`, `docs/roadmap.md`: establish one truthful current P7/P7.6.2 status and P7.7 as planned.
- this report: immutable implementation/evidence record.

## Local Verification

Actual results on Darwin 24.6.0 arm64, Python 3.12.12, uv 0.10.5:

- `uv sync --frozen --all-packages --all-groups`: PASS.
- OSV-Scanner 2.5.0 initial `uv.lock` scan: FAIL CLOSED, one affected package/group
  (`cryptography 49.0.0`, `PYSEC-2026-3552 / GHSA-g6cj-pr64-35w5`).
- OSV-Scanner 2.5.0 after the single-package lock update: PASS, 104 packages scanned, zero findings.
- Dependency evidence builder against the clean raw JSON: PASS, `status=PASSED`, exceptions empty.
- Starting-state `asv check`: FAIL as expected, missing `benchmarks/__init__.py`.
- Final-content `asv check`: PASS; ASV 0.6.6 created and checked the uv/Python 3.12 benchmark environment.
- pytest-benchmark health with explicit JSON output: PASS, 2 benchmarks.
- Targeted dependency/certification/verification/layering architecture tests: PASS, 41 tests.
- `uv lock --check`: PASS; `scripts/version_sync.py check`: PASS at 0.4.4.
- Impact-aware `VERIFICATION_INFRASTRUCTURE` run: all 9 static checks PASS and all 11 canonical lanes PASS:
  research-sweep 27, research-factor 57, research-job 30, research-calculation 127, calculation 58, research-dataset 36,
  core-full 1601, recovery 330, sim-recovery 38, A-share 24, MiniQMT contract 34 collected.
- Virtual Broker strict mypy: PASS, 15 files; import-linter: PASS, 3 contracts.
- The impact runner's build step alone failed because the sandbox prohibited build-isolation access to PyPI. The identical
  `uv build --all-packages` command was rerun once with approved dependency access and PASSed, producing all 8 workspace sdists and
  wheels. No already-passing test/static gate was rerun or reclassified.
- `git diff --check`: PASS.

The first immutable-candidate ASV comparison failed closed before measurement because the default monorepo build emitted multiple
wheels; the explicit root-distribution build contract was added in response. The final candidate comparison result remains to be
recorded after the amended candidate exists. The required fresh-runner comparison remains owned by the remote Nightly performance
gate and is never inferred from `asv check`.

## Remote Evidence

- Layered Quality: `NOT EXECUTED`
- CodeQL: `NOT EXECUTED`
- Nightly Heavy Quality: `NOT EXECUTED`
- Final-SHA Certification: `NOT EXECUTED`
- Certification artifact/run: `NONE`

No remote result is inferred from local evidence.

## Remaining Risks

- External advisory state is time-scoped; the same lock may receive new findings later, which is why every mandatory run rescans.
- GitHub-hosted runner performance remains noisy; same-run interleaving reduces order bias but does not create cross-run hardware
  comparability.
- Remote checkpoint evidence is still required before this increment can be marked `VERIFIED`.

## Current Verdict

`P7.6.2 NOT VERIFIED — mandatory remote aggregate gates and exact-SHA certification have not executed.`
