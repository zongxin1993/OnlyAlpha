# P8.5 Post-Closure — Composition Authority and Architecture Gate Closure

## Repository baseline

- Start SHA: `fadb3af2ffd87ab9df033b707c1b89ddd2a3f807`
- Branch: `master`
- Start worktree: only `prompts/P8.5Post-ClosureCompositionAuthority&ArchitectureGateClosure.md` was untracked.
- Baseline architecture suite: 335 passed, 3 failed.

## Problem A — dual Worker composition

The baseline Worker built a local Calculation registry for Specification re-resolution and then let each `OnlyEngine` build an independent default registry for actual Research Runtime execution. Correctness therefore depended on two plugin discoveries producing equivalent content.

The first-principles invariant is:

```text
One Worker process -> one startup composition C
Resolve(S, C) -> verify -> fresh Engine(services=C) -> Execute(S, C)
```

`worker_main` now creates one fail-fast `OnlyEngineServices` at process startup. The Specification resolver consumes `services.assembler.components.calculations`, and `OnlyEngineResearchRuntimeExecutor` receives the same services object. The executor creates a fresh `OnlyEngine` for every claim and injects those services, so mutable Engine and Runtime lifecycles remain attempt-local while process composition remains stable. Claim execution does not call default composition or plugin discovery.

No registry freeze, composition manager/store, database table, semantic identity, admission fingerprint, Run/Attempt state, scheduler, or recovery path was added or changed.

## Provider state audit

The official RESEARCH providers were inspected:

- Indicator backend state (`deque`, EMA/MACD accumulators, output lists) is local to each `execute()` call or its pure helper calls.
- Factor and Target backends use only local inputs and local result collections.
- Predicate backend is stateless and delegates to Arrow compute functions.
- Definition resolvers are frozen semantic objects.

Registry-owned provider instances therefore hold no per-execution mutable semantic state and can safely be reused through the process-lifetime services composition.

## Problem B — architecture firewall drift

The baseline failures were:

1. The Dataset firewall claimed to protect `research.dataset` but scanned all of `research/**`, with an exception for the execution directory.
2. Process signal ownership was centralized in the application stop controller, but the newer Research Worker composition root installed handlers directly.

The Dataset firewall now scans exactly `src/onlyalpha/research/dataset/**`; all original forbidden Trading authority imports remain forbidden. This narrows the gate to its named semantic owner rather than excluding production files.

The Worker now delegates signal installation/restoration to the existing `OnlyApplicationStopController`. `OnlyResearchWorkerService` accepts a read-only stop predicate and converts the application stop request into its existing draining path. The signal gate remains unchanged and fully enforced; no Worker path exception was added.

Research execution architecture gates now additionally prove that startup services feed both resolver and executor, startup composition precedes claim processing, and the executor cannot rediscover composition. Existing gates still prove that semantic execution enters only through `OnlyEngine` and that Scheduler/PostgreSQL boundaries remain semantics-blind.

## Problem C — milestone truth duplication

`docs/roadmap.md` remains the current-state authority. `README.md` projects the current milestone, state, increment, and next semantic direction. The certification architecture test now parses those Roadmap fields and proves that the README projection matches; it no longer hardcodes an obsolete third milestone value.

The frozen state is:

```text
P8.5 — IMPLEMENTED / VERIFIED / POST-CLOSURE PASS
P8 — IN_PROGRESS
Next: P8.6 — P8 Product Closure & Final Certification
```

## Authority review

- Worker process composition: startup-created existing `OnlyEngineServices` and its registries.
- Calculation semantic identity: existing Calculation domain and registry contracts.
- Run operational state: PostgreSQL Research Run authority.
- Attempt ownership and lease: PostgreSQL Research Run Attempt authority, fenced by exact Attempt and Worker identity.
- Research semantic execution: `OnlyResearchWorker -> OnlyEngineResearchRuntimeExecutor -> OnlyEngine -> OnlyResearchRuntime`.
- Dataset/Calculation/Statistics/Research Result/Artifact truth: existing immutable semantic stores.
- Composition refresh: only a fresh Worker process startup; never a claim path.

## Changed files

- `src/onlyalpha/research/worker_main.py`
- `src/onlyalpha/research/execution/worker.py`
- `tests/research/execution/test_worker.py`
- `tests/research/postgres/test_research_execution_authority.py`
- `tests/architecture/test_research_execution_boundaries.py`
- `tests/architecture/test_research_dataset_boundaries.py`
- `tests/architecture/test_certification_contract.py`
- `README.md`
- `docs/roadmap.md`
- `docs/operations/research-service.md`
- `docs/reports/p8_5_post_closure_architecture_gate.md`

## Verification

- Focused Worker and affected architecture tests: 42 passed.
- Full architecture baseline after closure: 340 passed, 0 failed.
- `research-execution`: 36 passed.
- `research-runtime`: 67 passed.
- `research-run`: 46 passed.
- `recovery`: 330 passed.
- `research-postgres` against PostgreSQL 16.15, UTF-8 database, UTC session: 72 passed.
- `mypy src/onlyalpha`: 594 source files, no issues.
- `ruff check src tests packages scripts`: passed.
- `ruff format --check src tests packages scripts`: 1,378 files formatted.
- `git diff --check`: passed.

## Remaining risks

Default Engine composition still discovers Trading plugin groups that a Research Worker does not execute. A failing Trading plugin can therefore fail Worker startup. This is an existing coupling, not a second composition authority; selective discovery/hot reload and heterogeneous Worker capability routing remain outside this closure.

## Verdict

`P8.5 POST-CLOSURE — PASS`

`P8.6 — READY TO START`
