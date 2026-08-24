# ADR 0097: Strategy Revision, Freeze, Execution and Promotion Authority

- Status: Accepted
- Date: 2026-08-24
- Related: ADR 0093, 0095, 0096

## Context

P8 established exact Research Candidate lineage and immutable scientific evidence, while Trading still accepted a Python class path and
configuration path as its Strategy authority. A class import is not a reproducible product identity, cannot bind the exact Research and
TRADING implementations that were admitted, and permits two unrelated execution forms: vectorized Decision Graph evaluation and
arbitrary `OnlyStrategy` subclass callbacks.

## Decision

`strategy_fingerprint` is the only Strategy product identity. It hashes one canonical immutable Strategy Revision containing the exact
Universe, Market Input Contract, Decision Graph, signal-role bindings, and exact Research/TRADING implementation bindings. Market input
semantics are therefore part of identity. Dataset Snapshot, Research Run, Candidate, Research Result, actor, time, catalog labels,
account, capital, risk, broker, fee and execution policy are not Strategy semantics and do not enter the fingerprint.

Candidate becomes Strategy only through the Freeze authority. Freeze re-resolves the Run's canonical Specification, verified-loads the
exact Research Result, Calculation Result and Dataset Snapshot, recomputes Candidate lineage, derives rather than accepts Strategy
semantics, verifies exact Research and TRADING implementation manifests plus explicit equivalence evidence, commits the Revision to the
immutable content-addressed Store, and appends provenance. Freeze is simultaneously Candidate-to-Strategy publication and Trading
Admission. Repeated identical provenance is idempotent; different Candidate provenance may refer to one Strategy.

Calculation semantic identity, implementation identity and equivalence evidence remain distinct. Calculation fingerprints do not gain
code hashes. Each admitted backend instead supplies an explicit closed implementation manifest over its entrypoint, exact resource
bytes and declared semantic dependencies. The Strategy binds both implementation fingerprints; evidence remains outside Strategy
identity.

Runtime configuration contains only `strategy.fingerprint`. Backtest and SIM resolve it through the same verified Strategy Store and
Calculation Registry, then create one immutable execution plan retaining the originating Strategy fingerprint. The Trading Kernel may
use one internal `OnlyRevisionStrategyAdapter`, but it contains no authored rules. Dynamic Strategy import, `OnlyStrategyCreateRequest`,
and arbitrary user `OnlyStrategy` subclass execution are rejected. Old `class_path`, `config_path`, and extensions fail with
`LEGACY_STRATEGY_CONFIGURATION_UNSUPPORTED`; there is no fallback or automatic translation.

Strategy execution consumes finalized BAR observations only and emits only `ELIGIBILITY`, `ENTRY`, and `EXIT` in
`OnlyStrategyDecision`. Order side, quantity, price, account, portfolio allocation, risk and execution algorithm remain downstream
domains. Observation Key identifies the logical bar position; Observation Fingerprint hashes exact finalized bar content while excluding
transport metadata. A correction at an already finalized key fails closed in P9.0 because rollback semantics are out of scope.

Promotion is an append-only evidence chain over `RESEARCH -> BACKTEST -> SIM -> LIVE_ELIGIBLE`. Current stage is derived from verified
records; no mutable status is authoritative. `LIVE_ELIGIBLE` is admission evidence, not deployment or permission to trade.

The Strategy immutable Store lives inside the P8 deployment semantic namespace under `USER_DATA_ROOT/research/strategy`. PostgreSQL
contains only catalog, Freeze provenance and Promotion evidence/index rows. Every deployed adapter verifies that its configured namespace
equals the existing PostgreSQL singleton binding. Startup/read never initializes, adopts, repairs or rebinds a namespace.

## Rejected alternatives

- Git commit, repository tree, installed distribution version, importable module name, or whole environment hash as Strategy identity.
- Caller-authored graph, Universe, implementation fingerprints or signal bindings in Freeze requests.
- Keeping dynamic Python Strategy as a compatibility path or translating arbitrary callbacks into a graph.
- Putting full mutable Strategy JSON or a mutable promotion status in PostgreSQL.
- Letting Candidate, Web DTO, Runtime mode, account, broker or portfolio policy become Strategy semantics.
- Treating Research/TRADING semantic-version equality as implementation equivalence without explicit evidence.

## Consequences

Strategy identity is deterministic and independently verifiable; implementation drift changes identity or prevents resolution. Research
provenance remains auditable without contaminating reusable Strategy semantics. Backtest and SIM execute one admitted graph form and can
be certified against the Research vector path. Existing path-based Strategy documents are intentionally breaking changes at version
`0.9.0` and must be replaced by an explicitly frozen fingerprint and shared semantic namespace.
