# Open-Source Engineering Evidence Doctrine

## Status and authority

This document defines a long-lived engineering method for using mature open-source projects as external engineering evidence during OnlyAlpha design, planning, review and test design.

Its normative authority is subordinate to:

```text
PROJECT_CONSTITUTION.md
        ↓
Architecture / public Contracts
        ↓
Accepted ADRs
        ↓
Current Task Contract
```

Current source, tests and executable behavior remain **observational implementation truth** for what the repository actually implements now; this document cannot reinterpret that truth or use external precedent to override it.

Open-source projects, upstream documentation, issues, pull requests and bug reports are **advisory engineering evidence only**. They never become OnlyAlpha product, semantic, research, execution, persistence, promotion or quality Authority.

## 1. Permanent principles

### OA-REF-1 — External projects are evidence, never Authority

A mature project may demonstrate a useful architecture, failure mode or test strategy. OnlyAlpha must still decide from first principles whether the same problem exists under its own Constitution, Authority model and contracts.

The fact that NautilusTrader, Qlib, AlphaGen, RD-Agent, LEAN, vectorbt, Vibe-Trading or another project implements something in a particular way is not by itself a reason for OnlyAlpha to copy that implementation.

### OA-REF-2 — Design from first principles before adopting precedent

For a new capability or material architecture change:

```text
OnlyAlpha problem
→ current Authority / contract / implementation facts
→ first-principles design
→ relevant external comparison
→ challenge / refine the design
→ OnlyAlpha-specific decision
```

External precedent is used to improve reasoning, not replace it.

### OA-REF-3 — High-risk work must consult relevant failure history

For work whose failure could affect money safety, execution correctness, persistent truth, recovery, determinism, identity, public compatibility, security boundaries, Research validity or governance, planning must inspect relevant external failure evidence when mature references exist.

Useful evidence includes:

- open issues with demonstrated correctness impact;
- closed issues containing root-cause and regression discussion;
- incident reports / postmortems;
- bug-fix pull requests;
- breaking-change notes caused by correctness defects;
- provider / venue documentation describing ambiguous or unsafe failure semantics.

The review must remain bounded to the current domain and Impact Scope. It is not an excuse for an open-ended ecosystem audit.

### OA-REF-4 — Borrow failure modes and invariants, not patches

The primary output of external bug research is not a copied patch. It is:

```text
Observed external failure
        ↓
Generalized failure pattern
        ↓
OnlyAlpha invariant / failure semantic
        ↓
Regression or fault-injection test
        ↓
Certification evidence where applicable
```

If an upstream project fixed a race with a retry, timeout or sleep, OnlyAlpha must still determine whether its own deterministic state model requires a different solution.

### OA-REF-5 — Curated knowledge first; live upstream research when justified

Routine planning should first consult the repository's curated engineering reference notes and failure-pattern library.

Live upstream issue research is required when one or more of these are true:

- the task is high risk;
- the domain is new to OnlyAlpha;
- the design depends on provider / venue behavior that can change;
- an unresolved correctness defect resembles a known industry problem;
- curated evidence is stale, incomplete or contradictory;
- the task freezes a new architecture boundary or certification contract.

This keeps the method useful without turning every small change into a broad web-research task.

## 2. Planning workflow

For architecture analysis and repository-aware planning, use this sequence when external evidence is applicable:

```text
1. Read PROJECT_CONSTITUTION.md.
2. Read relevant Architecture / public Contracts / Accepted ADRs.
3. Inspect current source, tests and executable behavior.
4. Establish the real OnlyAlpha problem and Impact Scope.
5. Identify the relevant reference domain(s).
6. Read curated reference notes and known failure patterns.
7. For high-risk/new/unresolved areas, inspect relevant upstream docs/issues/PRs.
8. Extract only applicable design lessons and failure modes.
9. State which external approaches are intentionally rejected and why.
10. Convert applicable failure modes into OnlyAlpha invariants/tests.
11. Produce the minimum implementation plan.
```

The task remains governed by OnlyAlpha's own Task Contract and Authority hierarchy.

## 3. Required planning output for high-risk design

When external evidence materially affects a high-risk plan, the plan should include a bounded section with this shape:

```markdown
## External Engineering Evidence

Relevant references:
- ...

Applicable design lessons:
- ...

Applicable historical failure patterns:
- ...

Rejected reference approaches:
- ...

OnlyAlpha invariants / tests derived from the evidence:
- ...
```

This section is evidence for the plan, not a new acceptance or architecture Authority.

## 4. Reference selection

References should be selected by domain rather than popularity.

Examples of current reference domains include:

| Domain | Useful reference families |
|---|---|
| Trading Kernel / event-driven runtime | NautilusTrader, LEAN |
| Factor / Calculation expression systems | Qlib, AlphaGen |
| Agent research loops | RD-Agent, Vibe-Trading |
| Factor analysis / Research evidence | Alphalens-family tools, factor quality-control projects |
| Large candidate evaluation | vectorbt-style vectorized execution |
| Portfolio / risk research | skfolio, Riskfolio-Lib |
| Market-data replay / Tick protocols | Tardis and venue-native specifications |
| Calendars / sessions | exchange_calendars and market-specific reference data |
| Research integrity | PIT / look-ahead / null-control / multiple-testing projects |

This list is intentionally non-authoritative and may evolve. A reference is useful because of a specific demonstrated capability or failure history, not because its name appears in this document.

## 5. Issue and bug research discipline

When searching upstream issue history, prefer problem-oriented terms such as:

```text
race
reconnect
timeout
duplicate
idempotency
partial fill
out of order
sequence gap
snapshot delta
checkpoint
resume
recovery
corruption
precision
timezone
DST
lookahead
future leak
PIT
NaN
warmup
overflow
memory leak
schema drift
retry
```

Closed issues can be especially valuable because they often contain the complete chain:

```text
symptom
→ root cause
→ fix
→ regression test
```

Do not promote community preference, style debate or performance fashion into an OnlyAlpha rule unless it reveals a concrete problem relevant to the current task.

## 6. Converting external failures into OnlyAlpha tests

External evidence is most valuable when it becomes executable protection.

Examples:

```text
Upstream symptom:
stream reconnect duplicates the final trade

OnlyAlpha invariant:
a duplicate provider event cannot create a second canonical fact

Test:
reconnect + duplicate event → exactly one effective canonical observation
```

```text
Upstream symptom:
order submit times out after the venue accepted it

OnlyAlpha invariant:
unknown execution outcome must reconcile before any resubmit

Test:
venue accepts + response lost + restart → exactly one venue order and converged local state
```

```text
Upstream symptom:
streaming indicator checkpoint recovery diverges from uninterrupted execution

OnlyAlpha invariant:
continuous execution and checkpoint/restart execution must converge for identical ordered facts

Test:
continuous(events) == checkpoint_restart(events)
```

A document note such as "be careful with reconnect" is not a substitute for a regression test when the failure is reproducible and relevant.

## 7. Failure-pattern traceability

Long-lived failure knowledge should use this conceptual chain:

```text
External issue / incident / specification
        ↓
Failure Pattern
        ↓
OnlyAlpha invariant
        ↓
Test / fault case
        ↓
Certification evidence (when applicable)
```

Failure-pattern records must not copy third-party issue text wholesale. Record the generalized technical lesson, source references and the OnlyAlpha-specific protection.

## 8. What must not be copied into OnlyAlpha

Do not mechanically copy:

- another project's component graph;
- provider-specific DTOs into Core;
- another project's mutable status model as a new Authority;
- a third-party evaluator as OnlyAlpha Research truth;
- arbitrary retry / sleep / timeout behavior;
- a language/runtime choice merely because a reference project uses it;
- RL, multi-agent or microservice architecture merely because a research project demonstrates it;
- issue-specific patches that do not follow OnlyAlpha determinism, identity and recovery rules.

The governing question is always:

> What invariant was the external project trying to protect, and what is the correct OnlyAlpha-native way to protect it?

## 9. Repository organization

Curated material belongs under:

```text
docs/engineering/
├── open_source_engineering_evidence.md
├── reference_registry.md
└── failure_patterns/
    └── README.md
```

These documents are engineering knowledge and planning input. They must not contain task completion status, CI snapshots or claims that an external project is an OnlyAlpha Authority.

## 10. Review rule

During bounded Independent Review of a high-risk change, reviewers should check whether the task ignored a directly relevant known failure pattern already recorded in the repository.

The reviewer must not expand the review into unrelated external research after the current Impact Scope is adequately covered.
