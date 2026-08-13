# ADR 0071 — Final-SHA Certification and Transactional Engine Start

## Context

The development quality workflow could accept a master push while branch coverage was skipped, and a repository report could not truthfully contain future CI results for its own commit without creating a self-referential commit cycle. Separately, `OnlyEngine.start()` could leave an earlier Runtime running when a later Runtime failed to start. Streaming processing results were retained in an unbounded diagnostic list.

## Decision

P6 certification is an external proof about an immutable `subject_sha`. The manually dispatched `P6 Final-SHA Certification` workflow checks out that exact SHA for every job and requires static analysis, all-package build, canonical test lanes, branch coverage, Semgrep, and CodeQL. Its verdict and gate results are emitted as a workflow artifact; they are not written back into the subject commit. Development quality remains optimized for branch feedback and is not itself P6 certification evidence.

`OnlyEngine.start()` is transactional at the Engine lifecycle boundary. If any Runtime start fails, Engine closes every initialized Runtime in reverse order, continues cleanup after individual failures, releases Engine infrastructure, preserves the original startup exception, attaches cleanup failures as notes, converges all Runtime/Cluster sessions and handles to `FAILED`, and ends in `FAILED`. Closing resources is compensating cleanup; it never rolls back committed economic facts.

Streaming processing results are diagnostic state. Runtime retains a total counter and a bounded recent window. Continuity, checkpoints, transactions, orders, positions, accounts, timers, and other authoritative state are not truncated.

## Alternatives

- Updating a report after each successful CI run was rejected because each update creates a new, uncertified commit.
- Treating skipped coverage as sufficient on master was rejected because final certification requires complete evidence.
- Deferring cleanup to a later `stop()` call was rejected because `start()` would return with a partially started world.
- Persisting all processing diagnostics was rejected because no product requirement justifies a new durable authority.

## Consequences

- A code change can be implemented and locally verified without being certified.
- `ACCEPTED` requires a successful certification artifact for the exact final commit SHA; absent remote evidence remains conditional.
- Runtime objects may be internally `CLOSED` after failed Engine start while their Engine-owned sessions and product handles remain terminal `FAILED` evidence.
- No persistence schema, checkpoint schema, participant identity, transaction identity, or recovery identity changes.

## Invariants Introduced

- Every mandatory certification gate runs against one immutable full commit SHA and cannot be skipped in an accepted verdict.
- Engine start produces either all Runtime sessions running or a fully cleaned, known failed product state.
- Cleanup failure never replaces the original startup failure and never prevents remaining cleanup attempts.
- Diagnostic retention is bounded without truncating authoritative recovery or trading state.
