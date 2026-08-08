# P0 Test Baseline & Feedback Loop Closure

Date: 2026-08-08

## Outcome

P0 closes the local and CI feedback loop without changing Runtime business semantics. Test layer and concern are now orthogonal, `full` is replaced by `core-full`, each lane uses one pytest session, failed sessions still write visible metrics, and CI gates run independently before a final quality gate.

The original MiniQMT snapshot failure was caused by the CLI test loading the example Windows `userdata_mini_path`. The test now serializes a parser-normalized temporary configuration and asserts that the lifecycle path is under `tmp_path`; MiniQMT path validation remains strict.

## Baseline after closure

Measured locally on the implementation worktree with the configured xdist workers:

| Lane | Collected | Passed | Skipped | Seconds |
|---|---:|---:|---:|---:|
| Fast | 1038 | 1037 | 1 | 18.06 |
| Integration | 120 | 120 | 0 | 60.63 |
| Core Full | 1054 | 1053 | 1 | 65.16 |
| Recovery | 289 | 289 | 0 | 169.11 |
| A-share | 5 | 5 | 0 | 2.11 |
| MiniQMT Contract | 31 | 31 | 0 | 3.96 |
| Exhaustive | 111 | 111 | 0 | 8.39 |

Metrics are written to `test-results/metrics/<lane>.json`. The final files confirm zero Recovery, Conformance, and Exhaustive overlap in Core Full; Recovery selects only Recovery concern; A-share selects only Conformance concern; Exhaustive selects only Exhaustive concern.

## Exhaustive migration

Every identified 100-run determinism check now has a 3-run ordinary correctness counterpart and a retained 100-run Exhaustive test. Complete real projection failure and conflict component matrices are also Exhaustive Recovery concerns. Representative commit, projection, checkpoint, outbox, A→B→C, multi-fill, and long-close recovery coverage remains in the ordinary Recovery lane.

## Verification

- Ruff check and format check: pass.
- Core mypy strict: 479 source files, pass.
- Tushare mypy: 15 source files, pass.
- MiniQMT mypy: 35 source files, pass.
- Version synchronization: pass at 0.3.4.
- All-package source and wheel build: pass.
- No pre-commit command was run, as requested.

Performance budgets remain observation warnings. No skip, xfail, assertion weakening, or Runtime transaction-path optimization was introduced.
