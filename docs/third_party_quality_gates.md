# Third-Party Quality Gates

This document defines the bounded role of third-party review and test tooling in OnlyAlpha.

第三方静态审查、安全扫描和测试工具不再由 GitHub Actions 执行。持续 CI 只跑 Rust 库单测和必需的 OpenAPI、Gateway 契约门禁；宪法检查独立运行。
根据 [工程指南](../AGENTS.md) 和任务影响选择本地专项验证。CI 未运行某项检查，不代表该检查已通过或相应要求已取消。

## Authority boundaries

1. Repository-native tests and contracts remain the source of truth for product behavior and architecture.
2. Third-party tools may detect evidence; they do not define product semantics.
3. A third-party rule must have a narrow documented purpose. Rules must not duplicate an existing gate solely to increase tool count.
4. Record the tool version for repeatable specialist verification.
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

## Stop rule

Do not add another review/test product simply because it overlaps one of these categories. A new tool requires evidence of a quality gap that is not already covered by existing repository-native checks or other available tools.
