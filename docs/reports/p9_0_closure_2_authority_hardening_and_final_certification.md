# P9.0 Closure-2 Authority Hardening and Final Certification

Date: 2026-08-24

## A. Baseline

- Starting master SHA: `cf41a4f3a093d5ea157491f5a2b1e65ac43fdf87`.
- Certified final implementation SHA: `ab07a7c828bd23b7b1d10b95023413a7d83bad8e`.
- Branch: `master`; the user-owned Closure-2 Prompt remained untracked and was not committed.

## B. Previously Identified Blockers

All three blockers are **resolved**:

- Research implementation provenance: exact execution plans and immutable Execution Evidence are implemented in
  `research/calculation/execution.py` and `execution_evidence.py`, propagated through Job/Sweep/Runtime/Worker/Run, and covered by
  Research Calculation, Run, Execution and PostgreSQL tests.
- Equivalence actual-backend authority: V2 evidence in `calculation/equivalence.py` and
  `application/calculation_equivalence.py` binds the exact node and R/T implementations, uses system-owned profiles/corpora, and runs
  the registered backends. Caller runners, outputs, profiles and corpora are not accepted.
- Freeze-only Strategy publication: `strategy/freeze.py`, `strategy/store.py`, `strategy/admission.py` and PostgreSQL Strategy authority
  expose a Freeze-only publisher and reader-only Runtime capability. Raw and legacy namespaces are non-executable.

## C. Research Execution Evidence

`OnlyResearchCalculationExecutionPlan` resolves every canonical graph node before execution. Immutable Evidence records Dataset,
Calculation, Graph, Result and exact sorted node-to-RESEARCH-implementation bindings. Its fingerprint is content-addressed and remains
separate from Calculation Result identity, so equal semantic output from different implementations keeps one Result identity but creates
different Evidence identity. The staged store verifies linkage and immutable content on commit/load.

Job, Sweep, Research Runtime and Worker preserve all Evidence references. PostgreSQL completed Run rows store the canonical unique
Evidence fingerprint set. Normal completion rejects empty provenance. Cancellation recovery re-resolves the exact workload and
verified-loads every Result and unique Evidence before projecting COMPLETED. Legacy completed rows remain readable but cannot Freeze.

## D. Equivalence Certification V2

V2 binds exact Calculation node fingerprint, exact RESEARCH implementation fingerprint from historical Execution Evidence, and exact
currently resolved TRADING implementation fingerprint. Certification selects only system-owned profile and corpus definitions, executes
both registered backends, compares canonical observation/output contracts, and commits immutable Evidence. Production callers cannot
inject a runner, corpus, profile or expected output, so arbitrary runners or weak corpora cannot mint production evidence.

Admission lookup requires exact V2 evidence for every node/implementation pair. Legacy V1 remains readable only as historical data and
cannot satisfy admission.

## E. Admission / Freeze

The only path is:

```text
Completed Run
→ exact immutable Execution Evidence R*
→ exact Candidate
→ Equivalence V2(R*, T*)
→ immutable StrategyRevision
→ Freeze-authorized publication
```

Historical RESEARCH identity is read only from Run-linked Execution Evidence. The current RESEARCH Registry is not used to reinterpret
historical provenance; only the current exact TRADING implementation is resolved for admission.

## F. Strategy Publication

The executable namespace is `frozen-revisions`. Runtime/Cluster/Backtest/SIM receive only a reader capability. Freeze alone owns the
publisher and publication seal/token, and atomically publishes an admitted Revision plus Freeze Record. The raw Strategy namespace and
legacy store cannot be loaded by the Runtime reader. A raw `OnlyStrategyRevision` cannot become executable without Freeze, and Runtime
has no Strategy writer capability.

## G. Persistence

- Migration: `0010_p9_0_closure_2_authority_hardening.sql`.
- Research Run adds canonical Calculation Execution Evidence fingerprint references.
- Freeze Record V3 stores exact Run, Candidate, Execution Evidence and Equivalence V2 provenance.
- Frozen Strategy publication uses the Freeze-only namespace; legacy raw/V1 records are non-admission and non-runtime.
- Legacy completed Runs without provenance remain readable but Freeze-ineligible.
- Concurrent claim contention on `research_run_attempt_one_active` now rolls back and retries selection; unrelated PostgreSQL errors
  remain fail-closed as Store unavailability. The real four-worker claim scenario passed 20 consecutive stress runs.

## H. Test Results

Focused coverage gates:

- `uv run python scripts/test_suite.py research-factor --coverage`: 73 passed, 100% lines/branches.
- `uv run python scripts/test_suite.py research-run --coverage`: 47 passed, 100% lines/branches.
- `uv run python scripts/test_suite.py research-postgres --coverage`: 89 passed; repository baseline passed.
- Research Execution 49, Job 30, Sweep 28 and Dataset 37 coverage lanes passed their formal baselines.

Full local quality command:

```bash
PATH='/opt/homebrew/opt/postgresql@16/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin' \
ONLYALPHA_TEST_POSTGRES_DSN='postgresql://onlyalpha:onlyalpha_test@127.0.0.1:5432/onlyalpha_test' \
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache \
uv run python scripts/test_suite.py release
```

It passed Ruff/format, all mypy surfaces, version sync, Web static/unit/build/E2E, architecture/import boundaries, all canonical Research
lanes, PostgreSQL, Strategy, integrated Research→Evidence→V2→Freeze→Backtest/SIM E2E, `core-full` (2356 passed, 1 skipped), recovery
(330 passed), SIM recovery (38 passed), A-share (24 passed), MiniQMT contract (34 passed), and all-package build.

Final-SHA Certification:

- Workflow run: `32728974966`.
- Subject: `ab07a7c828bd23b7b1d10b95023413a7d83bad8e`.
- Artifact: `certification-ab07a7c828bd23b7b1d10b95023413a7d83bad8e`.
- Mandatory gates: subject, static, build, Web, lanes, research-postgres, coverage, Semgrep, dependency audit and CodeQL all `success`.
- Verdict: `ACCEPTED`.

Earlier rejected runs correctly exposed and did not conceal missing Factor/Run coverage and a PostgreSQL claim race. Those defects were
closed before the accepted immutable subject was created.

## I. Remaining Work

Only genuine P9.1+ work remains: re-audit then define the next production vertical increment. P9.0 does not implement Portfolio/Execution
Profiles, LIVE factory/workflow, Real Broker submission/synchronization/reconciliation, deployment permission, automatic promotion, or
the complete P9 milestone.

## J. Final Gate

- Historical Result reinterpretable by current Registry: **No**.
- Every Freeze-eligible Run has exact implementation provenance: **Yes**.
- Arbitrary runners can mint production Equivalence Evidence: **No**.
- Arbitrary corpora can certify production equivalence: **No**.
- Evidence V2 binds exact Calculation node: **Yes**.
- Admission consumes historical RESEARCH implementation from Evidence only: **Yes**.
- Raw StrategyRevision executable publication: **No**.
- Runtime Strategy writer capability: **No**.
- Candidate → Strategy publication authority: **Exactly one, Freeze**.
- Uniqueness and determinism fully closed for P9.0 scope: **Yes**.
- P9.0 DONE / CERTIFIED: **Yes**.
- P9.1 can safely begin after a fresh repository-truth audit: **Yes**.

This report and the README/Roadmap projection are post-certification documentation changes. They do not alter or replace the immutable
certified implementation SHA.
