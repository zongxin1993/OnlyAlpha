# P9.K.4 OpenAPI Contract Governance — Task Gate Report

- Date: 2026-08-26
- Environment: macOS arm64, Python 3.12, Node 24
- `TASK_BASE_SHA`: `d9713159eeb2e3dcc294d1dbd456e7332ef2cbac`
- Implementation subject: dirty worktree based on `TASK_BASE_SHA`; closure SHA pending commit
- Gate: impact-aware Task Gate; no Final-SHA Certification requested or run

## Scope and authority chain

```text
FastAPI Routes + API DTO
→ deterministic canonical OpenAPI v2
→ external canonical SHA256
→ immutable Git historical baseline
→ structural/policy lint + compatibility verdict
→ pinned generated TypeScript freshness
→ Task / dedicated CI gate
```

The authoring authority remains `create_research_app()` plus its FastAPI routes and Pydantic DTOs. The only committed v2 projection is
`contracts/research-api/v2/openapi.json`. No mutable baseline file exists. `scripts/openapi_contract.py` is the single governance
implementation; `scripts/export_research_openapi.py` delegates for backward command compatibility and owns no rendering logic.

Compatibility direction is old accepted v2 client to new v2 server. Same-major compatible additions pass; breaking v2 changes fail
closed. Exact contract revision is lowercase SHA256 of canonical bytes and is never self-embedded. The generated Web contract derives
only from canonical OpenAPI through locked `openapi-typescript` 7.13.0.

## Contract evidence

```text
API major:                    2
Canonical contract:          contracts/research-api/v2/openapi.json
Baseline source:              immutable Git TASK_BASE_SHA artifact
Base contract SHA256:         c72395d6b9ba921c7e286f45e9b41ba0dbce7de3008fbdd76519d66d768f8b0e
Head contract SHA256:         c72395d6b9ba921c7e286f45e9b41ba0dbce7de3008fbdd76519d66d768f8b0e
Contract change:              UNCHANGED
Breaking changes:             0
Structural lint:              PASS
OnlyAlpha policy lint:        PASS
Generated client freshness:   PASS
Generated TypeScript SHA256:  7f9be5af016ae6685a03818056027a1dee88a1ab37334f4f9d5530e3e16b13fd
Public HTTP semantic delta:    none
Database/schema delta:         none
P9.0 semantic delta:           none
K5/K6/K7 status:               not started
```

## Invariant matrix

| Invariant | Status | Evidence |
|---|---|---|
| INV-K4-01 one authoring authority | PASS | governance renders the canonical Product FastAPI app; architecture guard |
| INV-K4-02 one canonical projection | PASS | exactly one JSON artifact under `contracts/research-api`; no baseline file |
| INV-K4-03 deterministic generation | PASS | two renders and repeated canonicalization are byte-identical |
| INV-K4-04 canonical SHA256 revision | PASS | direct hash characterization and exact base/head evidence |
| INV-K4-05 fingerprint not self-embedded | PASS | canonical bytes unchanged; fingerprint exists only in CLI/report output |
| INV-K4-06 immutable Git baseline | PASS | exact full commit validation plus `git show <SHA>:<canonical-path>` |
| INV-K4-07 historical source not regenerated | PASS | baseline loader consumes historical committed bytes only |
| INV-K4-08 explicit compatibility direction | PASS | ADR 0103 and request/response directional comparison tests |
| INV-K4-09 v2 compatible-only | PASS | breaking characterization returns non-zero formal verdict |
| INV-K4-10 no waiver | PASS | command surface is only write/check/verify; architecture guard |
| INV-K4-11 canonical generated-client source | PASS | package command and one shared freshness helper |
| INV-K4-12 reproducible toolchain | PASS | no external diff/lint download; locked Python graph and exact openapi-typescript 7.13.0 |
| INV-K4-13 transport identity isolation | PASS | Core/semantic architecture import/token guard |
| INV-K4-14 semantic delta zero | PASS | base/head OpenAPI and generated.ts byte identities; affected Research/Web lanes |
| Identity uniqueness | PASS | one compatibility family artifact and one exact canonical SHA256 identity |
| Determinism | PASS | same render/canonical document/base-candidate pair produces identical bytes/hash/verdict |
| Single authority / ownership | PASS | FastAPI/DTO authoring, committed projection and Git baseline roles remain distinct |
| Immutability / durable authority | PASS | historical accepted baseline is immutable Git content; no mutable baseline store |
| Architecture dependency direction | PASS | architecture lane and import-linter pass; Core imports no API governance tooling |
| Research / Trading / Runtime boundary | PASS | no semantic package change; research-command/query and architecture pass |
| Persistence / recovery | PASS | not impacted; no schema, migration, state, retry or recovery mechanism changed |
| Public contract / fail closed | PASS | stale source/client, invalid/missing baseline and all frozen breaking cases fail |
| Result / artifact provenance | PASS | no Result/Artifact authority or fingerprint change |

## Compatibility characterization

```text
identical                          → UNCHANGED
add path                          → COMPATIBLE
add optional request field        → COMPATIBLE
remove path                       → BREAKING
add required request field        → BREAKING
request type change               → BREAKING
remove response field             → BREAKING
response type change              → BREAKING
operationId change                → BREAKING
response enum expansion           → BREAKING
```

Negative tests also prove invalid full SHA, missing historical artifact, stale FastAPI projection and stale generated TypeScript fail
closed. Repeating the same inputs produces the same verdict.

## Verification evidence

```text
openapi verify --base TASK_BASE: PASS — UNCHANGED; 0 breaking changes
contract tests:                   PASS — 16 tests
architecture:                     PASS — 465 tests
research-command:                 PASS — 47 tests
research-query:                   PASS — 110 tests
web-static:                       PASS
web-unit:                         PASS — 17 files / 85 tests
web-build:                        PASS
ruff:                             PASS
changed-file format:              PASS
Core mypy:                        PASS — 617 source files
API mypy:                         PASS — 17 source files
governance/wrapper mypy:          PASS — 3 source files
import-linter:                    PASS — 3 kept / 0 broken
version sync:                     PASS — 0.9.0
git diff --check:                 PASS
remote exact-SHA relevant gates:  NOT RUN
```

The first architecture execution exposed one expected K4 CI-freeze assertion requiring synchronization and one local ignored `env/`
directory being scanned as repository source. The final run passed after the CI assertion included the new mandatory job and the scanner
was narrowed to tracked plus non-ignored untracked repository manifests. The ignored environment was neither modified nor treated as
product evidence.

## Reverse audit

1. A developer can hand-edit a second OpenAPI authority: **NO**.
2. Candidate and accepted baseline can change together: **NO**.
3. A breaking change can be bypassed with a CLI flag: **NO**.
4. Accepted baseline is an immutable Git artifact: **YES**.
5. Generation depends on timestamp/machine/environment: **NO**.
6. Same contract always produces the same SHA256: **YES**.
7. Same base/candidate pair always produces the same verdict: **YES**.
8. v2 can accept a known breaking change: **NO**.
9. Response enum expansion can silently pass: **NO**.
10. `operationId` can change undetected: **NO**.
11. `generated.ts` can derive from another source: **NO**.
12. Contract metadata can enter semantic fingerprints: **NO**.
13. K4 modified HTTP behavior: **NO**.
14. K4 modified canonical OpenAPI bytes: **NO**.
15. K4 modified generated TypeScript bytes: **NO**.
16. K4 started v3: **NO**.
17. K4 started K5/K6/K7: **NO**.
18. K4 modified PostgreSQL schema/version migration: **NO**.

## Audit result

- Previous findings: none; this is the initial K4 implementation audit.
- BLOCKER: 0
- MAJOR: 0
- MINOR: 0
- SUGGESTION: 0
- Verdict: **GO — P9.K.4 DONE / VERIFIED (worktree)**
- Remote exact-SHA relevant gates: **NOT RUN**; this Task Gate does not claim Final-SHA Certification.
- Next: **P9.K.5 — Idempotency, Long-running Operations & Recovery Closure — IMPLEMENTATION READY**.

```text
设计是否被正确实现？ YES
是否违反唯一性？     NO
是否违反确定性？     NO
是否违反 ADR/架构？  NO
是否可进入下一阶段？ GO
```
