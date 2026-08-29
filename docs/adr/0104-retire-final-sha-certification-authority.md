# ADR 0104 — Retire Final-SHA Certification Authority

- Status: Accepted
- Date: 2026-08-29
- Scope: repository engineering acceptance and project progression

## Context

OnlyAlpha previously defined Task Gate, Phase Gate and a manually dispatched exact-SHA Certification Gate. In practice, the additional
certification workflow duplicated already-required static, functional, persistence, build, Web and security proof after regular quality CI,
and project progression became dependent on a separate dispatch credential and artifact verdict.

The domain concepts named certification—such as Calculation Equivalence evidence or product conformance—are unrelated semantic contracts
and remain unchanged.

## Decision

Repository engineering acceptance has exactly two formal levels:

```text
Task Gate
Phase Gate
```

Task Gate proves an increment's impact scope. Phase Gate proves the composed milestone through the required canonical lanes, architecture,
recovery/persistence, static, build, Web and security evidence selected by the machine quality policy and current Phase Contract.

The standalone Final-SHA Certification workflow, evidence builder, verdict schema and mandatory gate set are removed. Project progression
does not consume a certification run, subject SHA or `ACCEPTED/REJECTED` verdict. `project-state.toml` owns only current development
progression.

Existing certification workflows, artifacts, reports and `DONE / CERTIFIED` labels remain immutable historical facts. They do not create a
current requirement and must not be used to block or authorize future increments.

Regular GitHub quality CI, CodeQL, dependency audit, Semgrep, build, Web and canonical functional lanes remain active evidence. This decision
removes a duplicate acceptance authority; it does not remove those proofs or lower their assertions.

## Supersession

This ADR supersedes the repository-engineering Final-SHA requirements in ADR 0071, ADR 0078, ADR 0098, ADR 0099 and ADR 0101. Their unrelated
Runtime, recovery, execution-evidence, publication and verification-budget decisions remain active.

## Invariants

- Current project progression depends only on Task Gate and Phase Gate evidence.
- No workflow, script, schema, policy table or project-state field authors a Final-SHA verdict.
- Historical certification evidence remains historical and cannot become current authority.
- Local budget may defer required proof to regular CI but cannot call deferred proof PASS.
- Removing Final-SHA Certification does not remove canonical quality, security, build, persistence or recovery evidence.
