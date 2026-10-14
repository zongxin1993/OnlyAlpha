# Chart Study Transient Evaluation — Slice Dependencies and Acceptance Design

Status: **Construction map under Accepted ADR 0138.** This is a future construction map, not a progress/quality Authority.
It supports [ADR 0138](../adr/0138-chart-study-transient-evaluation-and-formal-research-separation.md) and its
[Product design](../superpowers/specs/2026-10-11-chart-study-transient-evaluation-design.md).
Scenario IDs organize this design; they are not proposed permanent test names or new CI gates.

## 1. Dependencies and scope

| Slice | Dependency / user goal | Minimal complete change | Explicit exclusions |
|---|---|---|---|
| W3-A0 | Need an owner-reviewed separation before production work | Proposed ADR, source/constraint analysis, API alternatives and test design; independent review | No Accepted edit or API/SQL/Worker implementation; stop for owner approval |
| W3-A1 | Explicit owner authorization for limited ADR/L1 adoption and an independent Draft PR; exact context/manifest, process composition, local caller/Source grants and resources must be proved before support | Real closed historical SMA@1 Query + OpenAPI/generated client + strict transient adapter + shipping Web + deterministic backend and Browser E2E; no support published before numeric/manifest prerequisites | No PR118 dependency, unclosed preview, private Factors, cache service, new database/topology or Research writes |
| W3-A2 | A1 real user path verified | Add EMA/RSI/MACD/ATR/Bollinger only per exact registration, init/readiness/output contract; multiple numeric members and typed nonnumeric exclusions | No support inferred from library name; no version upgrades/fabricated warmup |
| W3-A3 | Exact supported time-series Factor capability admitted | Single-instrument Factor projection with source/Revision/Provider/runtime proof; optional independently verified Research overlay | CROSS_SECTION rank/universe needs its own scope/time/data proof; statistics/IC/search remain W6; no direct private code invocation |
| W3-A4 | Closed batch semantics proved, separate preview approval | Closed realtime and explicit unclosed preview, longer history/init semantics, exact non-authoritative cache, bounded performance/error UX | No TTL freshness, stream-as-Seal, incremental promotion, new numeric Authority or speculative microservice |
| W6 formal Chart Research | Independently authorized continuation of formal Research foundations | Installed Host -> original Work/Attempt -> exact scientific publication -> terminal/expiry/recovery/unknown ACK -> Work release; formal browser submission | W3 success does not authorize Claim/merge/deployment; no implicit command per edit |

Existing main-chart acquisition/stream behavior remains unchanged. Study evaluation reads already stored data only; any required
source/acquisition action is separately explicit, never a hidden consequence of configuring SMA. Real stock data/session availability
must be checked, not promised by 24x7 sample fixtures. Parameter/source changes are user intent; style is only presentation.

PR118's default-closed 0050 foundation was merged before PR119; historical Draft/SHA comparisons in the design are not current
merge-status claims. Integration does not substitute for W6 lifecycle acceptance. A1 starts from a freshly read master and
does not call its Claim/Heartbeat/Work/publication entries.

Admission order is explicit numeric/actual manifest + retained Provider/Catalog composition, then concrete trusted caller and
Source entitlement/resource proofs, then Product API/generated client/production adapter/real Browser integration. A1 window
size is capped at the owning current `MAX_TARGET_BAR_COUNT=2000`; the earlier 10000 candidate is neither supported scope nor
an SLO. No assumed proxy, same-origin route or internal Agent token can supply the human Chart caller proof. Missing protection
evidence blocks enabling the surface; see the design's access-control responsibility and test ownership.

## 2. W3 source-level acceptance matrix for future implementation

All fixtures are deterministic/offline; decimals and timestamps asserted exactly before lossy renderer projection. Browser tests
use controlled request barriers, not sleeps or retry-until-green. “New” below means a **test to implement**, not an existing NodeID.

| ID / scenario | Source boundary and required assertion | Future evidence |
|---|---|---|
| W3-01 Open chart | Existing Market Data Query/ledger/stream path remains; real source/history/closed-vs-preview labels; no Study-triggered acquisition | Existing MarketDataChart and realtime unit tests + Compose main-chart compatibility E2E |
| W3-02 Add SMA20 | Application exact registry backend executes; actual shipping Workspace passes production transient values to PriceChart; exact outputs/time align | New Application/HTTP tests + real canonical Compose browser path, not intercepted value fixture |
| W3-03 SMA(1) | First point READY/NONE, exact value equals input under canonical quantum, zero accepted | Indicator plugin parity/readiness tests + new Query contract test |
| W3-04 SMA(20) | Backend partial-window numerics/readiness atomic, twentieth observation READY; explicit finite input origin | New Query/backend parity + exact DTO/admission test |
| W3-05 period > input length | Complete known finite window yields only genuine PARTIAL/WARMUP_INCOMPLETE, no fabricated historical-absence claim | New Query + browser PARTIAL labels |
| W3-06 warmup / zero / null / gap | Exact zero nonnull READY; nullable state/reason matrix preserved; SMA FAIL null input rejected; incomplete range has no backend call/series; no forward fill | New Application/HTTP mutations + projection/renderer gap tests |
| W3-07 Change period20->30 | Preserve StudyInstance, clear old values/config fence; new exact calculation, old delayed result rejected | New ChartStudies/client unit barriers + browser parameter flow |
| W3-08 Duplicate configuration | Two instances independent selection/color/pane/visibility; identical numeric computation may share immutable result, neither is Research identity | New instance/adapter tests + browser duplicate flow |
| W3-09 Hide/style/pane | No evaluation/Market Data Query/acquisition/stream restart, no scientific writes; current projection restored on show; stale binding never revived | Unit call counters + browser network assertions |
| W3-10 Wrong Source/version | Exact Integration Revision/Source/instrument/BarSemantic and registration/type/version/output mismatches reject; no latest/Trading fallback | New Query/HTTP strict contract and registry mutation tests |
| W3-11 Change context / A->B->A | Source, symbol, timeframe, incarnation and request generation discard late results even if original context key returns | Browser barrier injection + Workspace integration tests |
| W3-12 Data backfill/revision | Changed complete owning fingerprint marks stale; unavailable proof is not a match/non-match; old cache cannot show as current | New Market Data Query/adapter tests; real PG/CH when revision reader boundary touched |
| W3-13 Zero durable side effects | Before/after exact Research Command/Receipt/Operation/Preparation/Compilation/Run/Attempt/Result/Evidence/Artifact inventory + source-history frontier unchanged; no Runtime Work admission | Real isolated canonical PG + scientific-store inventory; read-only credentials and rejected writer calls, not only browser request count |
| W3-14 Explicit Create Research | Only source/window/parameters intent transfers; forged transient payload/hash cannot be Evidence or bypass freeze/Work; W3 creation itself sends no command | New transport negative and application consumer tests; independent W6 command E2E |
| W3-15 Immutable inputs/cache | Repeated read/evaluation, consumer order and future hit/miss produce same exact numerics; reload owning Source unchanged | Plugin/Query differential test; A4 cache fault tests |
| W3-16 Exact rendering | Valid canonical zero timestamp admitted/preserved; wrong family, duplicate owner/member/time, disorder (including zero-containing datasets), subsecond alias, Decimal overflow/underflow, whole-context/nested proof deletion fail before renderer; exact hover and disconnected NULL/missing segments | Extend studySeriesProjection/PriceChart unit tests and controlled renderer browser tests; production source adapter tested separately |
| W3-17 Registration replacement | Pin one verified startup composition; reject complete different Provider/Catalog/numeric-support policy even with unchanged descriptor/implementation via expected full capability fingerprint; unavailable proof not stale; no reload/fallback/private code | New Application capability/admission tests + installed composition and wrong nested provider relation checks |
| W3-18 Security/bounds | Missing authorization, wrong subject/source, extra fields, raw prices, scripts/paths/secrets, bool-as-int, unsupported output/preview, excessive rows/period/body fail before computation; native WS independently versioned AUTH precedes one exact Subscribe, Origin/deadline/frame/capacity bounds and continuous withdrawal; no same-Source HTTP/WS/Command bypass | New HTTP/OpenAPI/WS strict consumer tests + architecture guard; exact route inventory and state machine in the design; unauthorized zero-open, blocked-open/event/response barriers, memory-only Browser generation/secret redaction and real isolated HTTP/WS/Browser proof |
| W3-19 Empty/error/unavailable UI | Scoped input shortage distinct from source corrupt/unavailable; PARTIAL not global READY; main live Bar never appears as closed Study preview | Unit and browser states, no fixture or retry masking |
| W3-20 Warmup/history/viewport/layout | Input scope unchanged by pan; enough declared prefix before cropping; older scope yields new projection; UTC viewport preserved across overlay/pane/removal; responsive chart usable | Existing timeAxis/history tests extended + Browser E2E; long-history expansion separately A4 |
| W3-21 Decimal context/provenance | Exact same binding gives identical output/readiness or failure despite hostile ambient precision, rounding, exponents, clamp, traps/flags; caller context/source unchanged; old SMA manifest cannot claim missing policy; no silent Definition/Provider identity rewrite | New sequential/threaded differential Query tests + plugin/manifest admission tests; compare legacy only under same explicit context |

Zero-write inventory must cover all affected scientific stores (filesystem/object owners as applicable), not just PostgreSQL tables.
Use a stable isolated fixture namespace with no concurrent writer; compare exact IDs/refs/frontiers, not merely counts that could hide
replacement. Catalog/Market Data reads and disposable compute diagnostics are allowed; no business Command/Work is admitted.
At least one browser path must invoke real HTTP/Application/registered backend/owning PG+CH reads, using seeded canonical data;
mock response tests alone cannot close A1. Need an actual admitted stock source/calendar for stock-specific acceptance, or explicit
unsupported-source observation; a crypto example cannot be reported as stock acceptance.

## 3. Independent W6 gates (not W3 prerequisites)

| Gate | Required operational/scientific observation | Negative/fault evidence |
|---|---|---|
| W6-01 Explicit submit/freeze | Formal command permission/idempotency -> original Operation/Preparation/Compilation/frozen Source + Run/Work; independent of transient evaluation | Stale intent rejected, unknown command ACK exact reconciliation; no preview fact transfer |
| W6-02 Exact native publication | Original ACTIVE Attempt/Worker/lease/Work/G -> exact installed Host -> Source issuance -> Result2/Evidence2/Result4/Artifact2 verified by owning readers | Source/context/implementation/duplicate publication mutations; equal transient numbers do not grant publication |
| W6-03 Fenced terminal | Same Attempt and Run commit terminal with final exact scientific refs, durable ACK then original Work release | Lease loss, cancel, expiry/retry/exhaustion, SQL rollback, unknown terminal/release ACK; no blind retry/second identity |
| W6-04 Recovery/re-entry | Crash/restart reconstructs exact history, publication re-entry and no-ACTIVE cancellation/reconciliation, unique release outcome | Local missing file/inventory not historical absence; unavailable/corrupt/complete-different proof distinct; T1/row/history/Work lock graph checked |

These gates describe required future proof, not a replacement for PR118's independently authorized B2-01..20 acceptance matrix.
GENERAL/PRIVATE_STRATEGY and published migrations retain their existing consumers and semantics; no W3 waiver repairs W6 failures.

## 4. Existing official validation entry points and proposed test placement

Use `deploy/run-tests.sh` serially with the existing canonical Compose test profile for Python lanes; the existing browser runner
uses its isolated `web-e2e` profile in the **same sole Compose topology**. Do not run host PostgreSQL, invent DSNs,
restart protected services, introduce a second topology or alter markers/quality policy. Choose lanes from actual impact via
`scripts/verify.py`; commands below are future implementation selection guidance, not A0 results.

| Impact | Existing commands / location | Tests to add or extend |
|---|---|---|
| A0 documents | Constitution checker; docs-only selector; directly related architecture/governance tests via canonical runner | No new test implementation or full Runtime lane required; read-only links/source/boundary review |
| Calculation/Indicator implementation or adapter | `python scripts/test_suite.py calculation`, `research-calculation`; plugin tests in `plugs/onlyalpha-plugin-indicators/tests/` | Extend test_research_characterization.py/test_research_readiness.py; new Application Query tests under `tests/application/` |
| Product boundary/DTO | `tests/architecture/test_market_data_http_contract_boundary.py`, test_calculation_plugin_boundaries.py, test_research_calculation_readiness_boundaries.py; HTTP component tests under `packages/onlyalpha-http-server/tests/` | New transient API/query negative tests there, owning OpenAPI snapshot/governance and generated client updated atomically |
| Web client/config/projection | `python scripts/test_suite.py web-static`, `web-unit`, `web-build`, `web-e2e` | Extend ChartStudies/WorkspacePage/studySeriesProjection/PriceChart tests; production adapter and user flow tests are new |
| Real HTTP/PG/CH/browser vertical slice | `deploy/run-web-e2e.sh` (existing isolated web-e2e profile in canonical Compose topology, used by quality.yml web-product-e2e); `e2e-compose/` browser tests | New closed-data Study path and exact zero-scientific-write inventory using seeded isolated services; controlled fixture renderer is not replacement |
| Actual persistence/read permissions/revision boundary | `python scripts/test_suite.py research-postgres` only when relevant; nearest owning Market Data tests under `tests/market_data/` / `tests/research/postgres/` as appropriate | Targeted PG/CH zero-write/revision tests, not full PG per color edit |
| W6 operational/installed/recovery | Existing `research-execution`, `research-run`, `research-runtime`, `research-postgres` lanes and exact installed-publication tests on independently authorized W6 branch | B2 terminal/native/recovery/release tests, no mock substitute for real PostgreSQL/installed execution |

OpenAPI authority remains `contracts/product-api/v2/openapi.json`, generated web types currently
`packages/onlyalpha-web-console/src/api/research/generated.ts` via `npm run api:generate`. A1 must not create a competing schema or
hand-written permissive network type. Root tests own Core/Application; HTTP/Web/plugin-specific tests stay in component directories.
All proposed new fixtures co-locate with their owning tests; shared vectors belong in `test-data/` with discoverability/generator guards.

Ruff check/format and affected mypy apply to any future Python/API change; frontend static/typecheck/build and exact client generation
apply to relevant Web/OpenAPI changes. Architecture scope follows actual boundary changes, not a new all-repository gate.
Full core/recovery/coverage/build matrices are not ordinary docs-only validation. Coverage is owner-authorized non-blocking, **not PASS**;
historical derived7m/45000ms is FAIL / OWNER-DEFERRED, not a waiver for new failures. No assertion/timeout/selector/workflow change
may be used to turn an implementation failure green. Hosted pending/cancelled evidence cannot be reported as success.

## 5. Approval and implementation boundaries

The owner decision recorded in ADR 0138 approves the exact ADR 0094/0114/0136/0137 scope changes, parallel source family,
registration/composition policy, Query DTO/limits/init/quality semantics and prohibition on evidence promotion, and authorizes
an independent W3-A1 Draft PR. Directly dependent Accepted/L1 amendments must remain atomic; API/consumer implementation must
still prove numeric, authentication/Source entitlement, resource and zero-write admission. Approval is not implementation evidence.
Then A1 closes only when a real user sees correct source-bound values through the formal API and production adapter, required
deterministic/browser/zero-write proofs pass, and bounded independent review finds no Critical/High issue in actual scope.
Any inability to express the design within L0 requires `PLAN_CONFLICT`, not weaker correctness or a Constitution amendment.

No phase completion ledger, CI PASS snapshot, acceptance report or automatic next-task authorization belongs in this plan.
Implementation results and review evidence stay in the task/PR context; this document describes only future dependencies/proofs.
