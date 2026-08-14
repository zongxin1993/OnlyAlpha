# P7.5.2 Agent Verification Efficiency & Impact-Aware Quality Gate

- Date: 2026-08-14
- Starting SHA: `687a4135ae979cadb9db42c2d0f445400301cfda`
- Final SHA: pending immutable commit; this report cannot certify its own future SHA
- Product/version impact: none; version remains `0.4.4`
- P7.5.1 upstream certification: remote Final-SHA NOT EXECUTED, not `ACCEPTED`

## Problem Revalidated

The canonical `release` command correctly performs the complete static sequence, ten mandatory local lanes, and all-package build.
Using that boundary after every small Agent edit repeats unrelated heavy lanes and exposes full successful pytest output before the same repository-wide
proof is performed again for an immutable Final SHA. The problem is proof placement, not excessive correctness requirements.

## Current Truth

`scripts/test_suite.py` owns canonical lane paths, markers, workers, coverage behavior and release order. Layered Quality is development CI.
Final-SHA Certification independently checks an exact 40-character SHA and mandates static, build, ten lanes, six coverage gates, Semgrep and CodeQL;
missing, skipped, cancelled or failed gates produce `REJECTED`. Neither workflow was changed by P7.5.2.

## Design

- Change Set: explicit base plus committed delta, staged, unstaged, untracked, rename and delete; stable normalized order and visible dirty flag.
- Impact Rules: immutable explicit path rules with lane/check identities and rationale.
- Escalation: small monotonic levels; unknown paths select full local gates and infrastructure self-change selects the widest strategy.
- Planner: deterministic union in canonical release order; it imports lane/check identities from `test_suite.py`.
- Runner: sequential subprocesses preserving exact command and exit code; no coverage by default.
- Logs: compact console summaries with complete raw logs under `test-results/verification/`.
- Manifest: local-only JSON evidence containing revisions, change set, reasons, selected gates, commands, outcomes and durations.

## Safety Proof

Unknown impact cannot select an empty plan because every unmatched path receives `unknown-impact-fallback`, which selects all release lanes, static and
build. Verification tooling cannot self-downgrade because its paths match a higher escalation with the same complete local set. Rule union only adds
gates, uses canonical ordering and takes the maximum escalation. Final-SHA cannot be weakened because the impact tool is not referenced by the
certification workflow and `scripts/certification.py` retains its complete mandatory gate identity.

## Efficiency Evidence

Representative deterministic plans demonstrate avoided unrelated work without invented percentage claims:

| Change | Local development selection | Unrelated lanes omitted |
|---|---|---|
| Research Job implementation/test | release static + `research-job` | trading recovery, markets, providers and upstream calculation lanes |
| Streaming Runtime | release static + `core-full/recovery/sim-recovery` | research, A-share and MiniQMT lanes |
| Docs/prompts only | no Runtime lane | all executable lanes, with explicit docs-only rationale |
| Unknown/new production subsystem | full local release set | none; safety fallback |
| Verification infrastructure | full local release set | none; self-change firewall |

Successful subprocess stdout is retained outside Agent context. Remote certification polling behavior is documentation-only: an in-progress workflow
remains `REMOTE CERTIFICATION PENDING` until new evidence exists.

## Verification Evidence

Commands actually executed against the final implementation content:

- targeted Ruff check/format: PASS;
- `mypy scripts/verify.py scripts/test_suite.py`: PASS;
- targeted tooling/layering/certification tests: PASS, 30 tests;
- `scripts/verify.py plan --base HEAD`: PASS; `VERIFICATION_INFRASTRUCTURE`, complete local release set;
- impact runner static commands: PASS, 9/9;
- canonical lanes: PASS — research-factor 51, research-job 30, research-calculation 123, calculation 54,
  research-dataset 36, core-full 1552, recovery 330, sim-recovery 38, ashare 24, miniqmt-contract 34 collected;
- `uv build --all-packages`: PASS, 8 package sdists and wheels;
- `git diff --check`: PASS.

The ordered impact run retained full evidence under
`test-results/verification/20260814T074006Z-687a4135ae97-18364/`. Its static and all ten lanes passed, then sandboxed build isolation
failed to fetch `hatchling` because network access was prohibited. The exact build command was rerun with approved dependency access and passed.
Therefore all required local gates have real evidence, while that single manifest truthfully remains `VERIFICATION_FAILED`; it is not rewritten or
misrepresented as a one-run pass.

## Certification

State: `IMPLEMENTED / LOCAL VERIFIED`. Remote exact-SHA certification has not executed. No `CERTIFIED`, `ACCEPTED`, or `DONE` claim is made.

## Remaining Risks

- Explicit impact rules require maintenance as new repository subsystems appear; unknown fallback preserves safety at the cost of extra local work.
- v1 runs gates sequentially and has no remote cache or dynamic CI selection by design.
- Docs-only has no dedicated lint/link gate because the repository currently defines none.
