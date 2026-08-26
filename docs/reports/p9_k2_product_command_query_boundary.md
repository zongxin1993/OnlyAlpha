# P9.K.2 Product Command / Query Boundary — Task Gate Evidence

- Date: 2026-08-26
- Task base SHA: `14a5726839f013e7567a1c19edfecfef3f749518`
- Implementation subject: current worktree; closure SHA pending commit
- Evidence status: `P9.K.2 DONE / VERIFIED (worktree)`
- Release mapping: K2 retains the current `0.9.0` P9 architecture line; no release bytes changed

## Scope and authority

K2 adds one small transport-neutral typed intent boundary. `onlyalpha.kernel.command` owns READY admission, immutable binding validation,
exact-type lookup and invocation. `onlyalpha.kernel.query` separately owns immutable read dispatch. Neither owns business truth,
persistence, idempotency, recovery, authorization, HTTP mapping or dynamic registration.

The only production binding topology is `onlyalpha.application.product_boundary`. It maps immutable Product intent to the existing
Research authorities:

```text
OnlyCreateResearchRun → OnlyResearchCommandService.submit_research_run
OnlyCancelResearchRun → OnlyResearchCommandService.request_research_run_cancellation
OnlyGetResearchRun    → OnlyResearchRunQueryService.get_run
OnlyListResearchRuns  → OnlyResearchRunQueryService.list_runs
```

No Strategy binding was needed for the canonical K2 proof. P9.0 Freeze/Promotion implementation and identity bytes were untouched.
`GetKernelStatus` was not added because the current Host has no narrow status-only Port; a Query handler must not capture the full
mutation-capable Host.

## Invariant matrix

| Invariant | Status | Evidence |
|---|---|---|
| INV-K2-01 one Command exact type → one handler | PASS | duplicate construction, permutation and exact lookup unit tests |
| INV-K2-02 unknown/subclass Command fails closed | PASS | no `isinstance`/MRO fallback; unit tests |
| INV-K2-03 every Command crosses READY first | PASS | CREATED/DRAINING/STOPPED/FAILED tests prove zero handler calls |
| INV-K2-04 immutable binding topology | PASS | tuple-only construction, mapping proxy, frozen binding, no registration API |
| INV-K2-05 one Query exact type → one handler | PASS | duplicate/unknown/subclass/permutation Query tests |
| INV-K2-06 Query is read-only | PASS | separate C19; Dispatcher holds only handlers; Research Query receives `OnlyResearchRunReader` |
| INV-K2-07 existing Research authority remains unique | PASS | product/direct create, cancel, get and list outcomes are equal |
| INV-K2-08 deterministic dispatch | PASS | exact type plus frozen topology; binding permutation does not change resolution |
| INV-K2-09 Kernel remains neutral | PASS | AST guards forbid transport, Research, Strategy, persistence, Engine and Runtime imports |
| INV-K2-10 C18/C19 ownership is exact | PASS | authority reachability and constructor-site guards; one Product composition path |
| INV-K2-11 public/persistence contract unchanged | PASS | OpenAPI freshness passed; no API or database schema/migration file changed |
| INV-K2-12 P9.0 semantics unchanged | PASS | no Strategy/Calculation identity or authority implementation changed |

## Verification evidence

```text
uv run python scripts/test_suite.py kernel
→ 41 passed

uv run python scripts/test_suite.py architecture
→ 452 passed

uv run python scripts/test_suite.py research-command
→ 45 passed

uv run python scripts/test_suite.py research-query
→ 108 passed

uv run python scripts/export_research_openapi.py check
→ PASS; canonical contract unchanged

targeted changed-source mypy
→ 5 source files; no issues

uv run ruff check .
→ PASS

uv run mypy src/onlyalpha
→ 617 source files; no issues

uv run lint-imports
→ 3 contracts kept; 0 broken

uv run python scripts/version_sync.py check
→ workspace release graph consistent at 0.9.0

git diff --check
→ PASS
```

The repository contains a pre-existing ignored `env/` build tree dated 2026-08-15. It was moved temporarily outside repository traversal
for the canonical Architecture Gate and restored unchanged immediately afterward; otherwise the pre-existing nested project copy is
misread as extra console entry points.

Because K2 extends `scripts/test_suite.py`, the conservative impact planner correctly expanded once to the complete local release set.
That expanded run passed 22 gates through release static, Web static/unit/build/E2E, Kernel, Strategy, Research
Definition/Specification/Run/Command/Execution, then stopped at `research-product-closure`: the local environment has no PostgreSQL on
port 5432 and does not define mandatory `ONLYALPHA_TEST_POSTGRES_DSN`. All 11 errors were the same fixture setup failure before test
execution. This environment-only expanded-gate limitation is not part of the Prompt's K2 Task Gate, does not contradict any passed K2
test, and matches the repository's documented local K0 limitation. No PostgreSQL/schema/store implementation changed.

## Reverse audit and scope exclusions

```text
Command bypass of READY:                 impossible through Dispatcher
multiple handler resolution:             impossible; duplicate exact type fails construction
base-class/subclass fallback:             absent
runtime topology mutation:               absent
Query mutation capability:               absent from Query Dispatcher/handler contract
Research semantic duplication:           none
Strategy semantic duplication/change:    none
Dispatcher persistence/business truth:   none
transport/concrete infrastructure import:none
second lifecycle/readiness authority:     none
HTTP/K3 implementation:                  NOT STARTED
generic idempotency/K5 implementation:   NOT STARTED
remote protocol/K7 implementation:       NOT STARTED
database schema/migrations:              UNCHANGED
canonical OpenAPI:                       UNCHANGED
```

## Audit verdict

```text
BLOCKER:   0
MAJOR:     0
MINOR:     0
SUGGESTION:0
GO
```

Design correctly implemented: YES. Uniqueness violation: NO. Determinism violation: NO. ADR/architecture violation: NO. The current
worktree may proceed to P9.K.3 after final K2 static gates pass. This Task Gate evidence is not Final-SHA Certification and does not claim
`CERTIFIED / ACCEPTED`.
