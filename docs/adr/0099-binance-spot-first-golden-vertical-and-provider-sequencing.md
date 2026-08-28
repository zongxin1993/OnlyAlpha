# ADR 0099 — Binance Spot First Golden Vertical and Provider Sequencing

- Status: **ACCEPTED**
- Date: 2026-08-28
- Scope: P9.1+ implementation sequencing and first production vertical
- Supersedes: the parts of `docs/p9_production_trading_vertical_architecture.md` that require Binance Spot and USDⓈ-M Futures to be completed in the same first P9 production-closure sequence
- Does not supersede: P9.0 Strategy Revision/Promotion semantics, provider-neutral Core boundaries, authority rules, determinism rules, recovery rules, or the long-term requirement to support Binance Futures

## Context

P9 was originally frozen with Binance Spot and Binance USDⓈ-M Perpetual Futures both inside the first production trading milestone. After P9.0 completion and P9.K Stateful Kernel / protocol-boundary closure, the next authorized engineering increment is P9.1.

The implementation objective is no longer to maximize provider/product breadth before proving the first complete product path. The immediate objective is to prove one exact, production-shaped vertical end to end:

```text
Market Reference
→ Historical + Realtime Market Data
→ Durable Market Data Platform
→ Immutable Dataset Snapshot
→ Research
→ Research Candidate
→ Explicit Freeze
→ Immutable Strategy Revision
→ Backtest
→ Human Promotion
→ SIM
→ Human Promotion
→ LIVE_ELIGIBLE(TESTNET)
→ LIVE Observation
→ Explicit Execution Permission
→ Binance Spot Testnet Broker
→ External Order / Fill / Balance Facts
→ Recovery / Reconciliation / Certification
```

At the same time, the physical PostgreSQL and ClickHouse deployments are now ready to move from deployment preparation into the authoritative production data path. The first complete vertical must therefore prove both trading semantics and durable data semantics.

QMT integration constraints have also changed. The supported future QMT integration model is not MiniQMT plus an external modern Python SDK process. QMT integration must execute inside the QMT application-provided Python environment, currently Python 3.6.8. This makes QMT an intentionally isolated external-runtime bridge and strengthens the need to prove the provider-neutral OnlyAlpha side first.

## Decision

### 1. Binance Spot is the first Golden Vertical

The next implementation sequence MUST complete Binance Spot before Binance Futures is allowed to expand the active product scope.

Initial reference instruments remain intentionally small:

```text
BTCUSDT
ETHUSDT
```

The first vertical certification environment is Binance Spot Testnet. Mainnet capability may be architecturally supported, but Mainnet execution is not an automatic completion criterion and MUST remain behind explicit human deployment approval and LIVE execution permission.

### 2. P9.1–P9.7 current execution scope is Spot-only

For the currently authorized P9.1+ sequence, the completion target is:

```text
P9.1  Binance Spot Market Product & Reference Authority
P9.2  Binance Spot Historical & Realtime DataSource
P9.3  Production Data Foundation / Durable Market Data Platform
P9.4  Binance Spot Real Broker
P9.5  LIVE Runtime Composition & Safety
P9.6  Research → Backtest → SIM → LIVE Spot Vertical
P9.7  Spot Fault / Recovery / Certification Closure
```

Any Futures-capable abstractions already required for provider-neutral Core correctness may exist, but Binance USDⓈ-M provider implementation MUST NOT become a prerequisite for closing the first Spot Golden Vertical.

### 3. Production databases become part of the active product path now

The first Spot vertical MUST use the production persistence architecture rather than temporary CSV/in-memory substitutes.

Authority split:

```text
ClickHouse
→ high-volume market facts
→ raw provider evidence where appropriate
→ canonical Trade / Bar / Quote / Book families

PostgreSQL
→ capture/control metadata
→ coverage manifests
→ segment metadata
→ market-data revisions
→ seal/recovery records
→ schema/provenance/catalog state

Append-only WAL
→ durable ingestion buffer
→ crash boundary between provider ingress and database commit

Immutable Semantic Store
→ Dataset Snapshot
→ Strategy Revision
→ immutable Research/Backtest/Promotion evidence
```

A mutable database query MUST NOT become Research or Backtest semantic truth. Research/Backtest consume immutable Dataset Snapshots materialized from a verified market-data revision.

### 4. Database maintenance is implementation scope, not post-project operations work

Starting with P9.3, the implementation MUST establish and test:

- schema migration/version discipline;
- idempotent ingestion;
- append-only correction/backfill semantics;
- coverage verification;
- revision and seal semantics;
- WAL recovery;
- ClickHouse HOT/COLD lifecycle;
- PostgreSQL backup and restore;
- critical ClickHouse/manifest backup policy;
- integrity checks and operational metrics;
- restart/recovery behaviour.

Historical market facts MUST NOT be silently repaired by destructive overwrite merely for convenience. Corrections/backfills produce new evidence/revisions while preserving prior evidence.

### 5. One Strategy Revision crosses Backtest, SIM and LIVE

The first Golden Vertical MUST prove that one immutable Strategy Revision fingerprint crosses the runtime boundary unchanged.

A deliberately simple reference strategy SHOULD be used, for example:

```text
BTCUSDT
1m closed bars
EMA20 / EMA60
cross-up → ENTRY
cross-down → EXIT
```

The goal is semantic continuity and recovery correctness, not alpha quality.

Runtime-specific capital, fee, portfolio, execution and broker profiles may differ and MUST be fingerprinted separately. They MUST NOT alter Strategy Revision identity.

### 6. LIVE completion is stronger than “one order succeeded”

Spot LIVE is not complete until the runtime proves at least:

- exact Strategy Revision loading;
- verified market reference binding;
- market-data continuity/warmup;
- broker connection/authentication;
- reconciliation before execution readiness;
- observation-only mode;
- explicit execution-permission transition;
- deterministic client-order identity/idempotency;
- `UNKNOWN` submit-result handling without blind resubmission;
- user-stream loss degradation;
- fail-closed new-risk behaviour;
- crash/restart recovery;
- order/fill/balance convergence;
- durable certification evidence.

### 7. QMT becomes the second provider validation, not the first Golden Vertical

After Binance Spot Golden Vertical closure, the next provider-oriented validation SHOULD be QMT Market Data Bridge for A-share/ETF data.

QMT constraints are frozen as follows:

```text
QMT software internal Python environment
Python 3.6.8
no MiniQMT-based external integration assumption
```

The QMT bridge MUST be isolated from OnlyAlpha Core:

```text
QMT internal Python 3.6.8
→ minimal QMT adapter / bridge
→ versioned wire DTO/protocol
→ OnlyAlpha provider gateway
→ canonical OnlyAlpha domain
```

The QMT-side process MUST NOT import the modern OnlyAlpha Core package as an architectural dependency. It should remain small, dependency-light and independently deployable.

### 8. Provider/product sequencing after Spot closure

The preferred sequence after Spot Golden Vertical is:

```text
1. Binance Spot Full Golden Vertical
2. QMT Market Data Bridge (A-share / ETF; historical + realtime)
3. Binance USDⓈ-M Futures full vertical extension
4. QMT Broker / LIVE extension
5. CTP provider integration
```

This sequencing may be changed later only by an explicit accepted ADR/current execution-plan update.

## Rationale

Binance Spot is the smallest environment that can prove the complete architecture without simultaneously introducing derivative semantics or a constrained external Python runtime.

Completing Spot first reduces ambiguity during failures: provider protocol, Broker, LIVE Runtime, recovery, persistence and Strategy semantics can be debugged in an environment fully controlled by the OnlyAlpha runtime architecture.

QMT is still strategically important, but its Python 3.6.8 in-application execution constraint makes it a better second-provider boundary test after the canonical server-side platform is proven.

Binance USDⓈ-M Futures remains required long-term, but leverage, margin mode, position mode, funding, mark price, reduce-only and long/short semantics should be introduced after the common Spot trading/recovery path is already certified.

## Consequences

### Positive

- one concrete first production-shaped vertical;
- earlier usable Binance Spot capability;
- production database construction is driven by real traffic and real consumer requirements;
- QMT integration cannot contaminate Core with Python 3.6 compatibility constraints;
- Futures work becomes a semantic extension instead of a simultaneous platform rewrite;
- failure domains are easier to isolate and certify.

### Costs

- full Binance Futures support is delayed until after the Spot Golden Vertical and QMT market-data bridge sequencing point;
- some provider-neutral contracts may need to anticipate future derivatives without implementing the Futures provider immediately;
- Spot closure requires real database/WAL/backup/recovery work rather than temporary storage shortcuts.

## Enforcement

Future P9.1+ implementation prompts, Codex tasks, reviews and acceptance reports MUST use `docs/p9_binance_spot_golden_vertical_execution_plan.md` as the current execution plan.

Where that execution plan or this ADR conflicts with the older simultaneous Spot+Futures sequencing in `docs/p9_production_trading_vertical_architecture.md`, this ADR has precedence for current implementation scope and order.

Architecture invariants from the original P9 document remain binding unless explicitly changed here.