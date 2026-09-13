# Third-Party Quality Gates

This document defines the bounded role of third-party review and test tooling in OnlyAlpha.

The tools in this layer supplement existing repository-native authorities. They do not replace the existing Layered Quality workflow, architecture tests, CodeQL, OSV dependency audit, pytest lanes, Hypothesis, CrossHair, or mutmut.

## Tool roles

| Tool | Version | OnlyAlpha role | Blocking behavior |
| --- | --- | --- | --- |
| reviewdog | 0.21.0 via action-setup 1.5.0 | Present Ruff findings as PR check annotations on changed lines | PR job follows Ruff exit status |
| Semgrep | 1.176.0 | Enforce small, repository-owned semantic security rules | Blocks on matching ERROR rules |
| diff-cover | 10.4.1 | Require coverage on changed core lines instead of relying only on global coverage | PR core diff coverage must be at least 90% |
| Schemathesis | 4.26.1 | Fuzz the deterministic Research HTTP/OpenAPI test surface for server-error behavior | Blocks on generated requests that cause server errors |
| Testcontainers Python | 4.15.0 | Certify disposable Docker-backed integration-test infrastructure | Blocks when a disposable container cannot be started/executed/cleaned up |
| Dependency Review Action | 5.0.0 | Review dependency changes introduced by a PR when GitHub Dependency Graph is available | Becomes blocking for moderate-or-higher newly introduced vulnerabilities once Dependency Graph is enabled; bootstrap detection is non-blocking while that repository capability is unavailable |
| pip-audit | 2.10.1 | Independently audit the resolved Python environment | Blocks known vulnerable installed Python dependencies |
| zizmor | 1.29.0 via zizmor-action 0.6.2 | Audit GitHub Actions definitions and publish code-scanning findings | Reporting-first; findings are triaged through code scanning while action execution failures block |

## Authority boundaries

1. Repository-native tests and contracts remain the source of truth for product behavior and architecture.
2. Third-party tools may detect evidence; they do not define product semantics.
3. A third-party rule must have a narrow documented purpose. Rules must not duplicate an existing gate solely to increase tool count.
4. Tool versions are pinned. GitHub Actions introduced by this workflow are pinned to immutable commit SHAs.
5. New findings are fixed at their owning boundary. Do not grow allowlists or suppressions merely to make CI green.

## Current rollout

The third-party workflow runs independently from `Layered Quality` so failures can be evaluated without weakening existing gates. Its aggregate `third-party-quality-gate` requires every applicable blocking job to succeed.

`zizmor` is intentionally reporting-first because the repository predates this audit and existing workflow findings require bounded baseline triage before they can safely become a hard merge gate.

`diff-cover` currently consumes the repository's `core-full --coverage` evidence and therefore establishes a changed-line gate for the `src/onlyalpha` core. Package-specific coverage remains owned by the existing lane model until package coverage reports are explicitly unified.

`Schemathesis` initially targets the deterministic Research HTTP test surface already used by Web E2E. The first invariant is narrow and high-signal: generated requests must not produce server errors. Broader response/status conformance can be promoted after existing API error semantics have been characterized. The initial integration exposed a Schemathesis 4.24.3 canonical-schema fuzzing crash after 301 generated requests had passed; the workflow therefore uses 4.26.1 rather than weakening or disabling the fuzzing phase.

`Testcontainers` initially certifies that GitHub-hosted runners can create, execute in, and clean up disposable Docker containers. Existing pinned PostgreSQL acceptance remains authoritative for database product behavior; future integration tests may migrate selected fixture orchestration to Testcontainers only where it reduces duplicated service setup.

`Dependency Review Action` depends on GitHub Dependency Graph. The workflow explicitly detects that repository capability before invoking the action. Until Dependency Graph is enabled, the job emits a warning and remains non-blocking; the existing OSV dependency audit and `pip-audit` remain active blocking dependency-security evidence. Once Dependency Graph is enabled, the same workflow invokes Dependency Review normally and its vulnerability result is blocking.

## Stop rule

Do not add another review/test product simply because it overlaps one of these categories. A new tool requires evidence of a quality gap that is not already covered by repository-native gates or by this third-party layer.
