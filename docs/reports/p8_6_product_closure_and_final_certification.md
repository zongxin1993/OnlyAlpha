# P8.6 Product Closure & Final Certification

Date: 2026-08-22

## 1. Repository baseline

- Start SHA: `a98f0241ae73fb578254b3dfecb98d2ee33b1853`
- Branch: `master`
- Start worktree: no tracked modification; `prompts/P8.6P8ProductClosure&FinalCertification.md` was the only untracked file.
- Candidate Final SHA: not frozen. The mandatory browser/product and deployment-coherence conditions below are unresolved.

## 2. First-principles invariants

- One fact / one authority remains unchanged: PostgreSQL owns Run/Attempt/lease facts; immutable stores own Dataset, Calculation,
  Statistics, Research Result and Artifact facts.
- Product semantic execution remains `Run -> Worker -> OnlyEngineResearchRuntimeExecutor -> fresh OnlyEngine -> OnlyResearchRuntime`.
- Capability comparison projects exact semantic type definitions plus RESEARCH backend availability; provider class, module, wheel and
  entry-point ordering are excluded.
- Recovery remains forward-only through fenced operational facts and verified immutable reuse. No mutable semantic checkpoint was added.
- Missing/corrupt semantic authority and incoherent restore pairs fail closed in certification tests.

## 3. P8.6.0 Final Correctness Closure

Two reproducible defects were found and fixed inside existing owners.

1. `OnlyResearchWorkerService.stop()` called during housekeeping set the internal stop event, but the pre-claim barrier only re-read the
   external stop predicate. One new claim could therefore begin after internal stop was observed. The existing Worker Service now checks
   both its internal event and external predicate immediately before `claim_once()`. Deterministic tests cover external stop during
   reconciliation, direct idempotent service stop during reconciliation, and stop after claim begins.
2. Repository operational connection options bounded I/O but did not force the PostgreSQL session timezone. On a server whose default was
   `Asia/Shanghai`, API submission committed a UTC instant and then strict Run load rejected the returned `+08:00` value as non-UTC. The
   existing connection policy now sets `timezone=UTC`; no schema, timestamp identity or durable fact changed.

Verdict: `PASS` for the reproduced defects and focused closure.

## 4. P8.6.1 External Plugin Certification

`tests/fixtures/external_plugins/onlyalpha_test_plugin` now exposes a real `onlyalpha.calculations` entry point. Its deterministic,
stateless RESEARCH Indicator imports only the public `onlyalpha.calculation` contract. The product-closure test proves installed entry-point
discovery, Catalog visibility, Definition/Specification resolution, durable Run submission, fresh Worker composition, OnlyEngine /
OnlyResearchRuntime execution, immutable Result/Artifact, and HTTP Artifact Query without Core importing the fixture.

Verdict: `PASS` in the tested coherent deployment.

## 5. P8.6.2 Machine Authoring Certification

The no-React client in `test_external_plugin_product.py` uses only HTTP Catalog, Definition Resolution, Command and Artifact Query APIs. The
server remains the exact Specification authority. Replaying one idempotency key returns one Run. Existing Web transport tests prove the
structured Builder emits the same formal Definition contract; existing Definition semantic-closure tests prove presentation metadata and
input ordering do not alter resolved semantic identity.

Verdict: `PASS` for public machine authoring and contract neutrality. A real browser execution is separately mandatory and unresolved.

## 6. P8.6.3 Web Product E2E

The current `apps/onlyalpha-web/e2e/research.spec.ts` uses route-level mock responses and is not accepted as P8.6 product proof. A real local
PostgreSQL/API/Worker/Web environment was started, but the required browser-control surface reported no available browser instances. No
mock, source inspection, or alternate browser surface was substituted for the missing real browser run.

Verdict: `REJECTED / NOT CERTIFIED`.

## 7. P8.6.4 Fault / Recovery Matrix

| Fault | Durable facts / evidence | Recovery action | Final fact | Verdict |
|---|---|---|---|---|
| F1 Browser refresh | no real browser available | not executed | unproven | BLOCKING |
| F2 Browser close | no real browser available | not executed | unproven | BLOCKING |
| F3 API restart | PostgreSQL Run + portable Artifact | fresh API process | identical Run/Artifact DTO | PASS |
| F4 Worker starts with QUEUED Run | PostgreSQL QUEUED | fresh Worker startup composition | COMPLETED | PASS |
| F5 crash after claim | ACTIVE Attempt + server lease | expiry + fresh Attempt | stale Attempt fenced | PASS |
| F6 crash during semantic execution | Run/Attempt plus immutable commits | deterministic re-entry | covered at commit boundaries, not every calculation boundary | PARTIAL |
| F7 Calculation commit | immutable Calculation Result | verified reuse during result/artifact re-entry | same Result identity | PASS via aggregate re-entry tests |
| F8 Statistics commit | immutable Statistics Result | verified reuse during result/artifact re-entry | same Result identity | PASS via aggregate re-entry tests |
| F9 Research Result commit | immutable Research Result | fresh Engine re-entry | Result not rewritten | PASS |
| F10 Artifact commit before finalization | immutable Artifact, RUNNING Run | fresh Attempt + fenced complete | COMPLETED | PASS |
| F11 stale Worker return | expired old Attempt, new owner | exact fence rejection | new owner remains authoritative | PASS |
| F12 cancellation/completion race | semantic completion inspection | semantic-fact-first CAS | one terminal winner | PASS |
| F13 PostgreSQL outage | StoreUnavailable / ownership uncertainty | bounded retry/recovery | no unsafe finalization | PASS |
| F14 heartbeat uncertainty | timeout at heartbeat Store | ownership lost | no local finalization | PASS |
| F15 immutable corruption | corrupt Dataset/Artifact | structured verified-load rejection | FAILED / no repair | PASS |

Verdict: `REJECTED` because F1/F2 are unexecuted and F6 does not yet have a dedicated process-kill proof at every requested boundary.

## 8. P8.6.5 Backup / Restore

The product-closure lane performs a real PostgreSQL 16 custom-format backup at `Tdb`, then copies the immutable user-data tree at
`Tfs >= Tdb`, restores PostgreSQL into an isolated empty database, loads the exact completed Run, verified-loads the exact Research Result
and Artifact from the restored tree, and starts a fresh API against the restored pair. The restored API returns the same completed Run and
Artifact summary.

Negative cases remove Research Result, remove Artifact, corrupt the Artifact manifest, request a mismatched fingerprint, and pair the
restored completed database with an empty semantic root. Each fails through the existing strict readers; no regeneration, reference
rewrite, terminal reopen or startup repair is introduced.

Verdict: `PASS` for the automated local restore-pair scenario.

## 9. Authority Audit

| Fact | Single authority | Writer | Readers | Evidence |
|---|---|---|---|---|
| Run state/reference | PostgreSQL `research_run` | Command / fenced Execution Store | API, Worker, operations | real product and PostgreSQL lanes |
| Attempt/lease | PostgreSQL `research_run_attempt` + server clock | Execution Store | Scheduler/Worker/operations | lease/fencing tests |
| Process stop | application StopController + Worker Service event | signal/controller/service | Worker loop | deterministic stop tests |
| Calculation capability | Calculation Registry semantic contracts | startup plugin composition | API resolver, Worker services | canonical projection tests |
| Scientific semantics | immutable semantic stores | OnlyResearchRuntime chain | verified readers/Query | product/restore test |
| Browser state | disposable presentation only | browser | browser | architecture/unit tests; real E2E unresolved |

## 10. Determinism / Reproducibility Audit

- The external fixture uses fixed Dataset content and exact type/version/parameters.
- API and Worker projections compare equal in independent startup compositions; an empty/different projection raises a fail-closed mismatch.
- Submission retry preserves one Run identity.
- Fresh API and restored API return identical terminal Run and Artifact summary facts.
- Package/module provenance does not enter Calculation semantic identity.

## 11. Changed production files

- `src/onlyalpha/research/execution/worker.py`: closes internal stop-before-claim race in the existing owner.
- `src/onlyalpha/persistence/postgres/config.py`: forces operational PostgreSQL sessions to UTC.
- `src/onlyalpha/calculation/capability.py` and public export: pure canonical deployment-conformance projection; no registry/store/identity.

No migration, Manager, Service, Store, Runtime, Run/Attempt state, semantic fingerprint or alternate execution path was added.

## 12. Tests and Gates

Passed locally:

- `research-product-closure`: 3 passed.
- `research-execution`: 41 passed.
- `calculation`: 59 passed.
- real `research-postgres` on PostgreSQL 16: 76 passed.
- full architecture suite: 341 passed.
- focused closure/architecture/certification set: 48 passed.
- focused stop + UTC regression set: 17 passed.
- `mypy src/onlyalpha`: 595 source files, no issues.
- API mypy: 17 source files, no issues.
- Ruff and format check: passed over 1,384 files after formatting.
- version sync (`0.8.5` current unreleased graph) and `git diff --check`: passed.

The full release/coverage/security/build/Web matrix was not promoted to a Final-SHA Phase Gate because mandatory real-browser product proof
and the deployment-coherence blocker remain unresolved.

## 13. Remaining Risks

### Blocking design defect: operational DB / semantic root deployment coherence

A Worker connected to the same PostgreSQL authority but configured with a different `user_data_root` can legitimately claim a Run, commit
immutable evidence under its own root, and fenced-finalize `COMPLETED`. An API using another root then reads the terminal PostgreSQL
references but returns `RESEARCH_ARTIFACT_NOT_FOUND`. This was reproduced with two real Worker environments during the audit.

The current product requires API and every Worker sharing one operational database to share the same coherent immutable-store deployment,
but that compatibility is not fenced or admitted across processes. Fixing this may require a new deployment/admission fact and therefore
an ADR plus explicit schema/compatibility analysis; adding a convenient central registry or silently copying evidence is forbidden.

### Other blockers and exclusions

- No real Browser instance was available, so refresh/close/reopen and Scientific Viewer projection were not certified.
- Dedicated process-kill barriers for every F6-F8 intermediate semantic boundary are not all explicit; aggregate re-entry is proven.
- Remote exact-SHA CI, CodeQL, Semgrep and dependency-audit evidence was not run against a candidate SHA.
- Branch protection/release governance was not inspected as semantic proof.
- The user-provided P8.6 prompt remains an untracked implementation input and prevents a clean-worktree candidate capture unless repository
  governance explicitly decides whether to commit or exclude it.

## 14. Phase Gate

`NOT RUN AS FINAL PHASE GATE / BLOCKED BY MANDATORY PRODUCT CONDITIONS`.

## 15. Final SHA

No candidate Final SHA was created or claimed.

## 16. Final-SHA Certification

- Workflow/run identifier: none.
- Immutable certification artifact: none.
- Verdict: `REJECTED`.

## 17. Milestone Verdict

`P8 = IN_PROGRESS / REJECTED`

README and Roadmap must remain at P8 `IN_PROGRESS`; no `DONE / CERTIFIED` projection is permitted.
