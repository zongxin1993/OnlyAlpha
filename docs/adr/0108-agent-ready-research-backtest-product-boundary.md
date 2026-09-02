# ADR 0108: Agent-Ready Research to Backtest Product Boundary

- Status: Accepted
- Date: 2026-09-02
- Decision maker: repository owner through the A0 implementation authorization
- Related: ADR 0072, 0089–0091, 0097–0098, 0101, 0103–0104, 0106–0107

## Context

OnlyAlpha already owns durable Research Runs, immutable Research Evidence, verified Strategy Freeze and Revision authorities,
an append-only Promotion ledger, and one internal Backtest Engine using the Trading Kernel.  The formal Product API ends after
Research, however.  A Web, SDK or Agent would therefore have to import internal Python services to Freeze, Promote and Backtest.
That violates the Product API and Agent boundaries even though the underlying semantic authorities already exist.

Freeze also crosses two persistence domains.  The immutable Strategy authority is filesystem-backed while Product Command
receipts and operational projections are PostgreSQL-backed.  Treating publication and receipt insertion as one transaction would
claim atomicity that does not exist.

## Decision

1. The v2 Product API is the only external Research-to-Backtest control surface.  Existing Research routes and operation IDs remain
   backward compatible.  Strategy and Backtest routes are added to the same application and OpenAPI family.
2. A client submits only Freeze intent: exact Research Run, Candidate, actor and comment.  The existing Strategy Freeze service
   remains the sole Strategy Revision and Freeze authority.
3. Freeze uses a typed PostgreSQL admission record keyed by the global Product Command ID and canonical intent fingerprint.  It is
   persisted before immutable publication.  Retry or Kernel recovery re-executes the deterministic Freeze, verified-loads the one
   authoritative outcome, then records the receipt/projection.  A command ID bound to another kind or intent fails closed.
4. Promotion uses the existing append-only Promotion authority.  The A0 API admits only `RESEARCH -> BACKTEST`, requires a verified
   Freeze relation reference, and atomically persists the Promotion record with its Product Command receipt.
5. `OnlyBacktestSpecification` is a strict portable product-intent document.  It references one Strategy fingerprint, one immutable
   Dataset economic-binding fingerprint, one resolved Market Product composition fingerprint, versioned Portfolio/Risk/Execution
   profiles, exact initial capital/base currency, and deterministic runtime options.  It contains no Engine, worker, queue,
   database, path, YAML or HTTP detail.
6. Specification identity and Run identity are distinct.  Admission resolves and verifies the exact Strategy Revision, Promotion
   stage, Dataset/economic facts, Market Product and profiles, producing a separate admission-resolution fingerprint.
7. Backtest Run is the durable user execution intent.  Backtest Attempt is lease/fencing-governed worker ownership.  Worker loss
   creates another Attempt for the same Run, never another Run.  PostgreSQL is their sole operational authority.
8. HTTP admission returns after `QUEUED` and receipt commit.  HTTP transport never calls `OnlyEngine.run()`.
9. The worker is the only Product adapter allowed to assemble the internal Engine.  It verified-loads and re-resolves admission,
   then executes the same Trading Kernel used by other Trading Runtimes.  Cancellation is checked at deterministic ordered-fact
   boundaries.
10. The existing Backtest result and determinism fingerprints remain authoritative.  A Product Evidence manifest binds them to the
    Run, specification, admission, Strategy Revision, Dataset/economic binding, Market Product, exact implementations and artifact
    hashes.  Publication is content-addressed, staged, read-back verified and never overwrites corrupt content.
11. The existing Dataset Snapshot identity is not forked.  `OnlyResearchDatasetEconomicBinding` is persisted as the immutable
    Spot/Futures Backtest input closure.  Missing required Mark, Funding or Settlement evidence fails admission.
12. The canonical v2 projection moves from `contracts/research-api/v2/openapi.json` to
    `contracts/product-api/v2/openapi.json`.  Routes and DTOs remain the authoring authority; only one canonical projection is kept.
13. Compose reuses the existing PostgreSQL 18.6 and ClickHouse deployment.  Deterministic acceptance uses frozen Binance-derived
    datasets and an external HTTP-only client that neither installs nor imports `onlyalpha`.  Online Binance acquisition and
    certification is a separate explicit lane.

## Failure and retry semantics

- The same Product Command ID and canonical intent converges to the same authoritative resource.
- The same Product Command ID with another kind or intent fails closed.
- A dangling, malformed or mismatched receipt/admission is corruption; it is never replaced silently.
- Database failure before durable admission returns failure, never a provisional success.
- A stale/fenced Attempt cannot finalize a Run or publish its Evidence reference.
- If verified Evidence exists but the terminal PostgreSQL projection is absent, reconciliation may only project that verified truth
  forward; PostgreSQL never repairs or overwrites immutable Evidence.

## Consequences

- Future Agent, Web and SDK clients can complete Research → Evidence → Freeze → Promotion → Backtest → Evidence using only HTTP.
- Strategy, Dataset, Promotion, Trading Kernel and Backtest result identities remain unique.
- A0 adds operational schema and worker complexity, but does not add a second Engine or provider-specific Core branch.
- SIM, LIVE, Web Backtest UI, autonomous Agent implementation and LIVE authorization remain outside this decision.

## Rejected alternatives

- Client-authored Strategy Revision, Evidence or arbitrary implementation bindings.
- Synchronous Backtest execution inside an HTTP request.
- Backtest admission from mutable database queries, `latest` aliases or YAML paths.
- A generic workflow engine or receipt lifecycle state machine.
- A second Strategy, Dataset, result fingerprint, Backtest Engine or Binance-specific Kernel path.
- Treating the filesystem and PostgreSQL as one atomic transaction.
