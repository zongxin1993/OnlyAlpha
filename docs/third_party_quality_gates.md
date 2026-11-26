# Third-Party Quality Gates

This document defines the bounded role of third-party review and test tooling in OnlyAlpha.

The third-party CI workflow contains static review and security checks only. Its tools supplement repository-native checks, CodeQL and OSV; they do not define product behavior.

The only maintained third-party quality workflow is `.github/workflows/third-party-quality.yml`. No second third-party
workflow is a maintained quality interpretation or fallback entry point.

## Tool roles

| Tool | Version | OnlyAlpha role | Blocking behavior |
| --- | --- | --- | --- |
| reviewdog | 0.21.0 via action-setup 1.5.0 | Present Ruff findings as PR check annotations on changed lines | PR job follows Ruff exit status |
| Semgrep | 1.176.0 | Enforce small, repository-owned semantic security rules | Blocks on matching ERROR rules |
| Dependency Review Action | 5.0.0 | Review dependency changes introduced by a PR when GitHub Dependency Graph is available | Becomes blocking for moderate-or-higher newly introduced vulnerabilities once Dependency Graph is enabled; bootstrap detection is non-blocking while that repository capability is unavailable |
| pip-audit | 2.10.1 | Independently audit the resolved Python environment | Blocks known vulnerable installed Python dependencies |
| zizmor | 1.29.0 via zizmor-action 0.6.2 | Audit GitHub Actions definitions and publish code-scanning findings | Reporting-first; findings are triaged through code scanning while action execution failures block |

## Authority boundaries

1. Repository-native tests and contracts remain the source of truth for product behavior and architecture.
2. Third-party tools may detect evidence; they do not define product semantics.
3. A third-party rule must have a narrow documented purpose. Rules must not duplicate an existing gate solely to increase tool count.
4. Tool versions are pinned. GitHub Actions introduced by this workflow are pinned to immutable commit SHAs.
5. New findings are fixed at their owning boundary. Do not grow allowlists or suppressions merely to make CI green.

## Agent-side simplicity review

Ponytail is an Agent-side simplicity discipline, not a repository quality Authority and not a CI product. Its normative use is defined only by root `AGENTS.md` as part of the existing Task Acceptance flow.

- Ponytail is not added to `quality-policy.toml` and does not create another maintained GitHub Actions workflow.
- When the Codex Ponytail skill is available, `@ponytail` may supply the implementation-time simplicity discipline and `@ponytail-review` may perform the bounded diff review required by `AGENTS.md`.
- When that skill is unavailable, the same review must be performed directly from the repository rule; tool availability never changes Required Behavior or the Stop Condition.
- A Ponytail finding is a review candidate, not independent correctness evidence. Constitution, Architecture / Contracts / Accepted ADRs, frozen Required Behavior, correctness, security, reproducibility, data integrity, recovery and required tests take precedence over a request to make code shorter.
- The review stays inside the current Modification Scope and real Impact Scope. `@ponytail-audit` must not be used to turn an ordinary task into a repository-wide cleanup.
- Ponytail output remains in the active task context. Do not commit generated audit, debt, completion or PASS reports as repository state.

The purpose is to remove accidental complexity such as speculative abstractions, unnecessary dependencies and duplicated platform/stdlib behavior without deleting essential complexity required by OnlyAlpha semantics.

## Current rollout

The canonical third-party workflow runs independently from `Layered Quality` so failures can be evaluated without weakening existing gates. Its aggregate `third-party-quality-gate` requires every applicable blocking job to succeed.

`zizmor` is intentionally reporting-first because the repository predates this audit and existing workflow findings require bounded baseline triage before they can safely become a hard merge gate.

diff-cover, Schemathesis and Testcontainers are not run by CI. Existing coverage, contract fuzzing and container smoke tooling remains available for explicitly selected local verification.

`Dependency Review Action` depends on GitHub Dependency Graph. The workflow explicitly detects that repository capability before invoking the action and records the result as `AVAILABLE` or `UNAVAILABLE`. Until Dependency Graph is enabled, the workflow emits a warning and summary entry, does not claim a Dependency Review PASS, and does not block the third-party chain; the existing OSV dependency audit and `pip-audit` remain active blocking dependency-security evidence. Once Dependency Graph is enabled, the same workflow invokes Dependency Review normally and its configured vulnerability result is blocking. Ambiguous capability detection fails closed.

## Stop rule

Do not add another review/test product simply because it overlaps one of these categories. A new tool requires evidence of a quality gap that is not already covered by repository-native gates or by this third-party layer.
