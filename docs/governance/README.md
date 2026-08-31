# OnlyAlpha Governance

This directory defines how long-term product intent is protected from implementation drift.

## Authority order

```text
L0  PROJECT_CONSTITUTION.md
    immutable product identity, boundaries and fundamental invariants

L1  Architecture / public Contracts
    target technical structure derived from L0

L2  Accepted ADRs
    local design decisions; MUST remain subordinate to L0/L1

L3  Roadmap / Work Program
    sequencing and decomposition; cannot redefine product scope

L4  Task Contract / Codex Prompt
    current authorized implementation scope only

L5  Source / Tests
    authoritative evidence of what is implemented now
```

Normative target truth and observational implementation truth are intentionally separate.

Source and tests can prove that a capability is not implemented. They cannot prove that the capability is no longer a goal.

## Mandatory agent behavior

Before architecture analysis, planning, implementation, refactoring or audit, Codex/Agents MUST read `PROJECT_CONSTITUTION.md` and the root `AGENTS.md` before relying on ADRs, roadmaps, prompts or current implementation.

If a task conflicts with the Constitution, the correct result is:

```text
PLAN_CONFLICT
```

The Agent must explain the conflict and stop implementation. It must not modify the Constitution, narrow the goal, or create an ADR that supersedes it.

## Constitution immutability

`PROJECT_CONSTITUTION.md` and its pinned SHA-256 fingerprint are protected governance artifacts.

Normal engineering tasks MUST NOT modify either file. The repository governance workflow verifies both the fingerprint and ordinary-PR immutability.

Repository administrators always retain physical Git authority. That administrative ability is not engineering authority: any founding-level constitutional change must be an explicit owner governance action outside ordinary implementation work.

## ADR rule

Codex may draft a proposed ADR when needed, but an ADR cannot override the Constitution. A local design decision that conflicts with the Constitution is invalid regardless of ADR status.

Sequencing changes are not product-goal changes. Implementation difficulty is not evidence for reducing the target architecture.

## Prompt rule

Historical prompts are implementation artifacts, not product authority. A prompt may narrow a task's local modification scope, but it may not narrow the long-term product goal or reinterpret an invariant.
