# P9.K.4 Closure — Current-v2 Schema Compatibility Completeness

- Date: 2026-08-26
- Environment: macOS arm64, Python 3.12, Node 24
- `AUDIT_BASE_SHA`: `2dcb3997027e6c10c688c0cae2fc184375ff31c1`
- `AUDIT_HEAD_SHA`: `47e12df6bb7119396bb3dcda4b3e4c8483efa066`
- `K4_INITIAL_IMPLEMENTATION_SHA`: `2dcb3997027e6c10c688c0cae2fc184375ff31c1`
- `K4_CLOSURE_TASK_BASE_SHA`: `2dcb3997027e6c10c688c0cae2fc184375ff31c1`
- `K4_CLOSURE_IMPLEMENTATION_SHA`: `47e12df6bb7119396bb3dcda4b3e4c8483efa066`
- `PUBLIC_API_COMPATIBILITY_BASE_SHA`: `d9713159eeb2e3dcc294d1dbd456e7332ef2cbac`
- Gate: impact-aware Task Gate; no Final-SHA Certification requested or run
- Scope: `scripts/openapi_contract.py`, contract characterization, and K4 status/evidence metadata

## Executive summary

The Closure repairs the existing compatibility authority without changing the K4 architecture or the public contract. Request and
response compatibility remain directional old-client→new-server set relationships. The comparator now governs current-v2 `const`,
`additionalProperties`, referenced composition semantics, recursive graphs, discriminators, constraints and the explicit schema
vocabulary. Unknown schema semantics fail closed.

Local Task Gate evidence is complete and both protected artifacts are byte-identical to the pre-fix baseline. Direct remote gates for the
exact immutable implementation SHA passed in Layered Quality run `32963766868`, so the Closure converges to GO.

```text
BLOCKER: 0
MAJOR: 0
MINOR: 0
SUGGESTION: 0
```

## Previous findings status

### F-K4-001 — Compatibility engine incompleteness

- Severity: MAJOR
- Status: RESOLVED
- Evidence: the pre-fix characterization run produced 15 failures, including silent `const`, `additionalProperties`, referenced component
  and discriminator compatibility misses, missing vocabulary governance, and `RecursionError` on a self-reference. The repaired suite is
  `40 passed`; the required local Task Gate is green.
- Violated rule: ADR 0103 requires v2 breaking changes to receive a deterministic mechanical fail-closed verdict.
- Actual behavior before fix: current-v2 breaking schema changes could return `COMPATIBLE`, and a recursive graph could fail to terminate.
- Expected behavior: directional compatibility is complete for the current-v2 schema vocabulary, recursive traversal terminates, and
  unknown semantics fail closed.
- Impact: an incompatible v2 server could pass the public contract gate or make its verdict unavailable through unbounded recursion.
- Minimum required fix: strengthen only the existing comparator and prove it with characterization and exact-SHA gate evidence.
- Blocking: NO

### F-K4-002 — K4 evidence metadata drift

- Severity: MINOR
- Status: RESOLVED
- Evidence: this report now distinguishes initial implementation SHA, Closure task base and historical public API compatibility base; it
  no longer describes the committed initial implementation as an uncommitted worktree.
- Blocking: NO

## Invariant matrix

| Invariant | Status | Evidence |
|---|---|---|
| INV-K4-C01 directional request compatibility | PASS | old accepted request set remains a subset of new; const/enum/AP/constraint tests |
| INV-K4-C02 directional response compatibility | PASS | new produced response set remains a subset of old consumable set; characterization tests |
| INV-K4-C03 referenced semantics | PASS | unchanged `oneOf` reference spelling with incompatible component semantics is BREAKING |
| INV-K4-C04 recursive termination | PASS | stable `(old identity, new identity, direction)` comparison-pair guard; recursive test terminates |
| INV-K4-C05 deterministic verdict/evidence | PASS | repeated recursive comparison returns identical ordered `CompatibilityResult` |
| INV-K4-C06 discriminator fail closed | PASS | changed discriminator object is BREAKING |
| INV-K4-C07 vocabulary completeness | PASS | real schema-root traversal inventories the exact current-v2 vocabulary |
| INV-K4-C08 unknown semantics fail closed | PASS | synthetic `contentEncoding` causes governance failure |
| INV-K4-C09 one compatibility authority | PASS | only `scripts/openapi_contract.py` changed in production; no second framework/baseline/waiver |
| INV-K4-C10 canonical identity immutability | PASS | OpenAPI SHA256 unchanged at `c72395…f8b0e` |
| INV-K4-C11 generated consumer immutability | PASS | generated.ts SHA256 unchanged at `7f9be5…13fd` |
| INV-K4-C12 Research/Trading/Runtime boundary | PASS | no semantic source change; architecture/research-command/research-query pass |
| INV-K4-C13 persistence/recovery boundary | PASS | no database schema, migration, state, retry or recovery change |
| Identity uniqueness | PASS | one canonical contract and one SHA256 identity remain authoritative |
| Determinism | PASS | canonical bytes, pair identity, sorted traversal and final issue ordering are stable |
| Single authority / state ownership | PASS | FastAPI/DTO authoring, canonical projection and immutable Git baseline roles are unchanged |
| Public contract / schema | PASS | canonical OpenAPI and generated TypeScript bytes are unchanged |
| Fail-closed semantics | PASS | unsupported vocabulary, external refs, stale projection/client and breaking changes fail |
| Result / artifact provenance | PASS | Result, Artifact and semantic fingerprints are outside the change set |

## New findings

None. No new BLOCKER or MAJOR was introduced by the fix.

## Compatibility characterization

```text
request const A → A / unconstrained           PASS
request unconstrained → const A / A → B       BREAKING
response const A → A / unconstrained → A      PASS
response const A → unconstrained / A → B      BREAKING
const ↔ enum singleton-set direction           PASS
missing additionalProperties                   ALLOW_ANY
request AP narrowing / response AP broadening  BREAKING
AP child schema directional recursion          PASS
same composition refs, changed component       BREAKING
recursive self-reference                       TERMINATES / DETERMINISTIC
changed discriminator                          BREAKING
unknown schema keyword                         FAIL CLOSED
existing K4 compatibility fixtures             PASS
```

## Verification evidence

```text
openapi verify --base d9713159...: PASS — UNCHANGED; 0 breaking changes
contract tests:                    PASS — 40 tests
architecture:                      PASS — 465 tests
research-command:                  PASS — 47 tests
research-query:                    PASS — 110 tests
web-static:                        PASS
web-unit:                          PASS — 17 files / 85 tests
web-build:                         PASS
ruff:                              PASS — repository scope
format:                            PASS — 1460 files
Core mypy:                         PASS — 617 source files
API mypy:                          PASS — 17 source files
governance mypy:                   PASS
import-linter:                     PASS — 3 kept / 0 broken
version sync:                      PASS — 0.9.0
git diff --check:                  PASS
remote exact-SHA openapi-contract: PASS — Layered Quality run 32963766868
remote exact-SHA architecture:     PASS — Layered Quality run 32963766868
remote exact-SHA static:           PASS — Layered Quality run 32963766868
remote exact-SHA web:              PASS — Layered Quality run 32963766868
remote exact-SHA research-command: PASS — Layered Quality run 32963766868
remote exact-SHA research-query:   PASS — Layered Quality run 32963766868
```

Byte identity evidence:

```text
Pre-fix OpenAPI SHA256:      c72395d6b9ba921c7e286f45e9b41ba0dbce7de3008fbdd76519d66d768f8b0e
Post-fix OpenAPI SHA256:     c72395d6b9ba921c7e286f45e9b41ba0dbce7de3008fbdd76519d66d768f8b0e
Pre-fix generated.ts SHA256: 7f9be5af016ae6685a03818056027a1dee88a1ab37334f4f9d5530e3e16b13fd
Post-fix generated.ts SHA256: 7f9be5af016ae6685a03818056027a1dee88a1ab37334f4f9d5530e3e16b13fd
```

## Focused reverse audit

1. Current-v2 response/request const incompatibilities can pass: **NO**.
2. An incompatible dict value schema can escape under `additionalProperties`: **NO**.
3. Same composition reference spelling can hide changed component semantics: **NO**.
4. Recursive traversal can loop forever: **NO**.
5. Traversal order can alter verdict/evidence ordering: **NO**.
6. Discriminator changes can pass silently: **NO**.
7. A new compatibility-sensitive schema keyword can be ignored: **NO**.
8. Canonical OpenAPI or generated.ts changed: **NO**.
9. HTTP, Research/P9.0 or database semantics changed: **NO**.
10. A second authority, mutable baseline or breaking waiver was added: **NO**.
11. K5, K6 or K7 was started: **NO**.

## Non-blocking technical debt / suggestions

None recorded for this Closure. The comparator intentionally remains a conservative current-v2 mechanism, not a general JSON Schema
theorem prover.

## Audit verdict

```text
Verdict: GO — P9.K.4 DONE / VERIFIED
P9.K.5: IMPLEMENTATION READY
```

This is a Task Gate review verdict, not a fourth Gate and not Final-SHA Certification.

```text
设计是否被正确实现？ YES
是否违反唯一性？     NO
是否违反确定性？     NO
是否违反 ADR/架构？  NO
是否可进入下一阶段？ GO
```
