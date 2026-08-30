# ADR 0105 — Repository Truth and Bounded Task Acceptance

- Status: Accepted
- Date: 2026-08-30
- Scope: repository engineering acceptance, quality authority and development progression

## Context

OnlyAlpha previously accumulated several overlapping engineering-state mechanisms: project progression fields, per-increment reports, Task/Phase status vocabulary, local verification manifests, Base-SHA change certification and multiple narrative quality documents.

Those mechanisms duplicated information that can only be trusted from the current repository and encouraged repeated closure/audit work after the actual implementation was already sufficient.

The engineering requirement is therefore to preserve strong correctness proof while removing parallel progress and quality-state authorities.

## Decision

### Current engineering truth

Current source code, current tests and current executable behavior are the only authority for what the repository actually implements.

ADR / Architecture / Contract remain the authority for frozen long-term design constraints. A conflict between current code and a frozen design is a defect or an explicit design-change task; code does not silently supersede architecture.

### Task acceptance authority

Root `AGENTS.md` is the single normative repository authority for how each task is accepted. It defines the ephemeral Task Contract, risk classification, Impact-Aware validation, bounded Independent Review and Stop Condition.

Task-specific contracts and current validation results remain in the active development context and are not committed as repository state.

### Machine policy

`quality-policy.toml` owns only the machine gate set for continuous CI and Major Milestone Phase Gate composition. It does not own task completion, progression or authorization.

`scripts/test_suite.py` defines canonical lane execution. `scripts/verify.py` is a stateless selector for the current working-tree impact; it is not a certification or progression system.

### Retired repository state

The repository no longer versions:

- project progression state;
- per-task verification/closure/audit reports;
- quality evidence manifests or historical PASS records;
- Exact-SHA / Final-SHA engineering certification as a current acceptance mechanism;
- persistent task lifecycle states or next-increment authorization;
- task-summary documents created only to record development activity.

Roadmaps may describe future construction order and dependencies, but never current completion/progress state.

### Acceptance shape

Normal tasks use targeted tests, affected static/type checks and the nearest affected canonical lanes. Validation expands only according to real Impact Scope.

High-risk work additionally uses the specialist proof required by the affected authority and a bounded Independent Review. Critical/High findings in scope block; Medium/Low do not block unless they directly violate the frozen Task Contract or an explicit architecture invariant.

CI pending is not a default task blocker. A CI result blocks only when it proves a current-change regression or supplies irreplaceable evidence required by the current Task Contract.

Full repository Phase Gate execution belongs to a Major Milestone boundary rather than every increment.

### Determinism and evidence

Default task tests are deterministic, hermetic and offline-first. External systems are required only when the external environment itself is irreplaceable proof of Required Behavior.

Missing proof is not PASS. Conversely, unrelated pre-existing failures do not automatically expand the current task.

When the current Task Contract has sufficient proof and no in-scope Critical/High blocker remains, the task stops. Speculative optimization, unrelated debt and nonblocking findings do not extend the task.

## Consequences

- `project-state.toml` and its machinery are removed.
- quality/audit/closure reports under `docs/reports/` are removed.
- redundant narrative task-gate/quality-toolchain/current-state policies are removed.
- `AGENTS.md` becomes smaller and normative rather than a progress ledger.
- `scripts/verify.py` operates on staged/unstaged/untracked current-worktree changes without a Task Base SHA and without persistent manifests.
- release versioning is independent from Pn.m planning identifiers.
- historical Git commits and old prompts remain historical context only and cannot authorize or block current engineering work.

## Supersession

This ADR supersedes the project-progression ownership and local evidence-retention portions of ADR 0104. ADR 0104's retirement of Final-SHA engineering certification remains in force.

It also supersedes any older repository-engineering rule that requires per-increment persisted completion state, quality reports, Base-SHA acceptance manifests or exact-SHA completion certification.

Domain-level concepts that use words such as evidence, conformance or certification are unaffected when they are actual product/domain contracts rather than repository development status.
