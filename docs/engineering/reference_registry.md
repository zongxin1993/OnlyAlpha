# OnlyAlpha Engineering Reference Registry

## Purpose

This registry maps mature external projects to the narrow engineering questions for which they are useful references.

It is not a dependency list, product roadmap, endorsement ranking or Authority hierarchy. All entries are subordinate to `PROJECT_CONSTITUTION.md`, OnlyAlpha Architecture / Contracts / ADRs and current implementation truth.

Use this registry to answer:

```text
Which mature projects have already faced a problem similar to the one we are designing?
What should we inspect before freezing our own design?
Which external behavior must we explicitly avoid copying as Authority?
```

The registry is deliberately problem-oriented. A project is retained only when it contributes a concrete architecture lesson, failure family, test strategy, research-integrity method, provider/gateway lesson, or performance implementation pattern relevant to OnlyAlpha.

## Reference matrix

### NautilusTrader

Relevant domains:

- event-driven Trading Kernel;
- Backtest / Live semantic alignment;
- strong domain types;
- market-data adapters;
- order / execution state;
- Tick / Quote / Book handling;
- replay and runtime lifecycle.

Useful for:

- challenging Trading Kernel design;
- identifying reconnect, sequencing, order-state and replay failure families;
- differential reasoning about adapter boundaries.

Not Authority for:

- OnlyAlpha canonical domain identity;
- StrategyRevision;
- execution truth;
- promotion;
- OnlyAlpha persistence model.

### Barter-rs

Relevant domains:

- strongly typed multi-venue trading engine;
- separate Instrument / Data / Execution / Integration libraries;
- mock MarketStream / Execution substitution for backtest and paper trading;
- centralized engine state;
- audit streams and non-hot-path state replicas;
- externally controlled trading enable/disable while market/account observation continues.

Useful for:

- LIVE runtime separation between observation and execution permission;
- projection / monitoring design that does not become Trading Authority;
- testing shared trading semantics with real versus mock external adapters;
- comparing modular Rust hot-path designs after semantics are already stable.

Not Authority for:

- OnlyAlpha Trading Kernel state machine;
- LIVE permission semantics;
- OnlyAlpha execution facts;
- persistence / promotion Authority;
- a requirement to rewrite Core in Rust.

### WonderTrader

Relevant domains:

- strategy signal versus execution separation;
- theoretical strategy positions versus aggregated execution positions;
- multi-account execution;
- target-position aggregation;
- trading/risk clutch mechanisms;
- market-data service and real-time execution architecture;
- long-lived Chinese broker/provider integration history.

Useful for:

- challenging Portfolio / Execution boundaries;
- LIVE observation-versus-execution safety design;
- identifying reconnect, resubscription, partial-cancel and session-identity failures;
- future QMT/CTP/XTP gateway certification.

Not Authority for:

- OnlyAlpha StrategyRevision;
- Portfolio truth;
- Broker state machine;
- LIVE safety policy;
- provider-neutral Core semantics.

### VeighNa / vn.py

Relevant domains:

- gateway/plugin ecosystem across Chinese and overseas brokers;
- App versus Gateway separation;
- CTA / portfolio / algorithmic / options trading modules;
- QMT/XTP/CTP integration experience;
- `vnpy.alpha` factor-expression and ML research workflow;
- data and execution operational patterns.

Useful for:

- plugin / gateway boundary review;
- QMT and CTP provider design;
- Chinese-market order/risk edge cases;
- comparing Alpha-expression ergonomics without transferring Research Authority;
- mining long-lived issue history for reconnect and provider defects.

Not Authority for:

- OnlyAlpha canonical domain;
- Calculation identity;
- Research Evidence;
- StrategyRevision;
- LIVE execution truth.

### TqSdk

Relevant domains:

- market-data and trading gateways;
- Diff-style state synchronization;
- Tick/Kline replay and backtest;
- reconnect/resubscribe behavior;
- multi-account trading;
- long-running Chinese futures sessions;
- Agent/Codex skill packaging and compact machine-facing documentation.

Useful for:

- Data Plane synchronization design;
- reconnect readiness and stale-state failure research;
- future CTP/futures certification;
- Agent documentation ergonomics;
- differential tests for Tick/Kline semantics where contracts align.

Not Authority for:

- OnlyAlpha runtime readiness;
- event identity;
- order replay semantics;
- Research/Backtest truth.

### QUANTAXIS

Relevant domains:

- QIFI-style unified account representation;
- QMT / CTP integration;
- Tick / L2 Order / Transaction data;
- ClickHouse market-data storage;
- Arrow / zero-copy / shared-memory transport;
- Python/Rust/C++ execution compatibility;
- factor expressions and distributed calculation.

Useful for:

- multi-language contract design after canonical semantics are frozen;
- QMT/CTP account and market-data comparison;
- future Arrow/shared-memory performance work;
- market-data schema and account-projection review.

Not Authority for:

- OnlyAlpha account identity;
- Market Data Revision;
- Trading Kernel implementation language;
- database integration boundaries.

### AKQuant

Relevant domains:

- Rust core with Python authoring surface;
- factor expression engine;
- walk-forward ML validation;
- complex orders such as OCO / bracket;
- streaming backtest output;
- golden tests for market/business semantics;
- performance-oriented calculation implementation.

Useful for:

- domain golden-test design for T+1, price limits, margin, options and order semantics;
- differential expression/calculation tests;
- later profiling-driven hot-path optimization;
- checking complex-order helper semantics against OnlyAlpha order-group contracts.

Not Authority for:

- OnlyAlpha Calculation truth;
- complex-order canonical identity;
- Strategy semantics;
- a requirement to use Rust.

### Qlib

Relevant domains:

- expression-oriented quantitative calculation;
- data / research / workflow separation;
- standardized research pipelines;
- factor and model research ergonomics.

Useful for:

- Calculation Graph / feature expression design;
- research workflow comparison;
- large-scale quantitative experimentation patterns.

Not Authority for:

- OnlyAlpha Research Evidence;
- Dataset identity;
- Qualification;
- Backtest or LIVE truth.

### KunQuant

Relevant domains:

- financial-expression graph optimization;
- code generation;
- common-subexpression elimination across factors;
- operator fusion and temporary-buffer reduction;
- SIMD / multithread execution;
- batch and streaming inputs;
- CPU/GPU backends.

Useful for:

- post-correctness physical optimization of large B3 candidate sets;
- preserving N logical Candidate identities while sharing physical calculation work;
- graph compiler / execution-plan research;
- profiling future Calculation hot paths.

Not Authority for:

- Candidate identity;
- Calculation semantics;
- Research Evidence;
- justification for premature JIT/GPU/compiler complexity.

### AlphaGen

Relevant domains:

- constrained symbolic alpha search;
- operator / feature search spaces;
- search/evaluator separation;
- factor-pool optimization.

Useful for:

- B3 symbolic factor search;
- search-space design;
- avoiding one-Python-file-per-formula designs;
- future factor-pool research.

Not Authority for:

- Candidate identity;
- Research metrics;
- Qualification outcomes;
- production factor admission.

### RD-Agent

Relevant domains:

- hypothesis → experiment → feedback research loops;
- specialized research roles;
- failure feedback;
- automated research iteration.

Useful for:

- Agent orchestration design;
- Experiment / Iteration lineage;
- structured research feedback loops.

Not Authority for:

- OnlyAlpha Experiment truth;
- Evidence;
- Qualification;
- LIVE progression.

### Vibe-Trading

Relevant domains:

- hypothesis-oriented research workflow;
- metadata-first Agent capability discovery;
- research registries;
- centralized data/factor guards;
- Agent context efficiency;
- research progress ergonomics.

Useful for:

- compact Agent-facing capability projections;
- B3 memory / novelty / progress design;
- centralized validation ideas.

Not Authority for:

- OnlyAlpha state machines;
- Evidence values;
- mutable factor/hypothesis status;
- LIVE control.

### AlphaEvo

Relevant domains:

- strategy mutation / retest loops;
- bounded mutation of a readable strategy representation;
- train/validation/test gap checks;
- walk-forward anti-overfit gates;
- full evolution-tree / trajectory records;
- explicit stop when generalization does not improve.

Useful for:

- B3 parameter-feedback and Agent-search ergonomics;
- controlled single-variable/small-scope mutation design;
- research-loop provenance and anti-overfit stop conditions;
- challenging a design in which an LLM rewrites an entire strategy every round.

Not Authority for:

- OnlyAlpha StrategyRevision;
- combined score/confidence/champion labels;
- Qualification PASS/FAIL;
- Agent promotion authority.

### AlphaSift

Relevant domains:

- deterministic screening plus optional LLM ranking;
- explicit data-source fallback chains;
- stale/fallback/source-quality metadata;
- saved-run T+N evaluation;
- read-only Agent/API surfaces;
- Agent-facing `SKILL.md` capability descriptions.

Useful for:

- external-data provenance and fallback semantics;
- Agent context / metadata design;
- ensuring stale cached data is not presented as current provider truth;
- later experiment-memory evaluation ergonomics.

Not Authority for:

- OnlyAlpha Dataset truth;
- freshness policy;
- LLM ranking truth;
- strategy/promotion decisions.

### QuantMind

Relevant domains:

- Qlib + RD-Agent + QMT product integration;
- factor mining and model training UX;
- Windows QMT Agent / WebSocket bridge architecture;
- Web/API/Engine/Trade/Stream product separation;
- production monitoring and preflight checks.

Useful for:

- competitor/product workflow comparison;
- Web productization;
- QMT gateway UX and operational design review;
- identifying where tightly integrated systems blur Research/Trading Authority so OnlyAlpha can avoid doing so.

Not Authority for:

- OnlyAlpha Research Engine;
- factor admission;
- QMT execution truth;
- service boundaries.

### Alphalens-family factor analysis

Relevant domains:

- IC / RankIC analysis;
- returns / quantile analysis;
- turnover and grouped analysis;
- factor diagnostics.

Useful for:

- Research Statistics coverage review;
- factor report completeness;
- validating analytical vocabulary.

Not Authority for:

- OnlyAlpha typed Statistics;
- Research Result membership;
- Qualification decisions.

### AlphaPurify

Relevant domains:

- factor preprocessing;
- winsorization / neutralization / standardization;
- IC / RankIC and quantile backtests;
- factor exposure / return attribution;
- factor correlation;
- cross-sectional weight/return traceability;
- high-throughput factor analysis.

Useful for:

- future Factor Preprocessing contracts;
- B3 Evidence vocabulary completeness;
- differential/oracle-style tests for neutralization and factor attribution;
- factor-pool / exposure analysis research.

Not Authority for:

- OnlyAlpha Research Statistics;
- preprocessing semantics unless explicitly adopted in a canonical contract;
- Qualification;
- backtest truth.

### Macrosynergy

Relevant domains:

- quantamental panel research;
- information-state-aware financial data conventions;
- out-of-sample signal/return research;
- panel normalization / z-score methods;
- signal, PnL and portfolio analysis separation.

Useful for:

- Research Integrity / temporal-availability design;
- future macro/fundamental/news data with `available_at` / vintage semantics;
- cross-sectional/panel research and OOS methodology review.

Not Authority for:

- OnlyAlpha Dataset temporal semantics;
- Point-in-Time truth;
- signal or PnL evidence.

### RQAlpha

Relevant domains:

- event-driven Chinese-market backtesting;
- modular account/risk/simulation/transaction-cost components;
- Point-in-Time financial data integration;
- A-share market rules and corporate actions;
- long-lived issue history containing data, persistence, adjustment and Instrument-model defects.

Useful for:

- historical failure research;
- A-share market-rule tests;
- corporate-action / adjustment immutability tests;
- transaction-cost-aware sizing tests;
- challenging provider-neutral Instrument and DataSource boundaries.

Not Authority for:

- OnlyAlpha Instrument model;
- adjusted historical data;
- portfolio persistence;
- trading cost semantics.

### QF-Lib

Relevant domains:

- event-driven strategy backtesting;
- tools to prevent look-ahead bias;
- flexible data-source selection;
- research summary/report generation.

Useful for:

- Research Integrity comparisons;
- look-ahead test design;
- report/projection separation ideas.

Not Authority for:

- OnlyAlpha temporal availability;
- Research Evidence;
- report metrics.

### RedTorch

Relevant domains:

- trading-management core and provider gateway separation;
- fault tolerance and long-running gateway operation;
- deliberate removal of unstable/nonessential one-stop features;
- master/slave gateway isolation;
- operational experience with bad provider timestamps and reconnect behavior.

Useful for:

- Core scope discipline;
- QMT/CTP gateway fault-domain design;
- provider-timestamp validation failure research;
- studying how a mature system reduces change surface after operational experience.

Not Authority for:

- OnlyAlpha node topology;
- provider timestamp truth;
- security/persistence implementation choices;
- a mandate to remove OnlyAlpha product capabilities.

### OpenCTP / CTPBee

Relevant domains:

- CTP-compatible provider surfaces across multiple simulated/real backends;
- extension of product/exchange enums while preserving protocol shape;
- small-core CTP trading/gateway integration;
- plugin/tool registration and backtest/live gateway usage.

Useful for:

- CTP provider compatibility research;
- testing how provider-specific enum extensions terminate at the plugin boundary;
- future CTP simulation/certification fixtures.

Not Authority for:

- OnlyAlpha canonical market enums;
- order state;
- Instrument identity.

### ZVT

Relevant domains:

- schema/domain-oriented record/query APIs;
- incremental data recording;
- REST API and standalone UI separation;
- QMT tick/data workflows;
- multi-market entity models.

Useful for:

- Web/API product ergonomics;
- data-recording workflow comparison;
- provider/data-source integration review.

Not Authority for:

- OnlyAlpha persistence model;
- public API contract;
- entity identity.

### vectorbt

Relevant domains:

- large candidate / parameter batch evaluation;
- vectorized execution;
- parameter broadcast and computational reuse.

Useful for:

- future physical execution optimization after B3 correctness is closed;
- identifying opportunities for shared subgraph / batch calculation.

Not Authority for:

- Candidate semantics;
- Research Evidence;
- Trading Kernel execution semantics.

### skfolio / Riskfolio-Lib

Relevant domains:

- portfolio construction;
- risk measures;
- turnover and transaction-cost constraints;
- walk-forward / purged validation patterns;
- factor-model-based portfolio research.

Useful for:

- future Portfolio Research and Risk validation.

Not Authority for:

- OnlyAlpha Portfolio state;
- live risk permission;
- execution state.

### Tardis and venue-native market-data specifications

Relevant domains:

- exchange-native Tick / Trade / Depth replay;
- historical feed reconstruction;
- provider sequence semantics.

Useful for:

- independent Binance/Tick certification datasets;
- replay / order-book reconstruction testing.

Not Authority for:

- OnlyAlpha Market Data Revision;
- canonical facts;
- Dataset Snapshot.

### exchange_calendars / pandas_market_calendars

Relevant domains:

- exchange sessions;
- holidays;
- trading-day boundaries.

Useful for:

- differential calendar certification when semantics are compatible.

Not Authority for:

- runtime Market Reference Snapshot;
- provider-specific trading permissions.

### Research-integrity references

This family includes projects and literature focused on:

- point-in-time data;
- look-ahead prevention;
- corporate-action/vintage handling;
- information-state-aware research data;
- null controls;
- multiple-testing governance;
- deflated performance statistics;
- falsification / pre-registration.

Current useful examples include `factor-qc`-style quality gates, look-ahead/PIT test projects, Macrosynergy, QF-Lib and null-control/falsification test references.

Useful for:

- Research Integrity closure;
- B3 search governance;
- leakage certification;
- negative-control tests;
- sealed-holdout governance.

Not Authority for:

- OnlyAlpha Dataset semantics;
- Statistics values;
- Qualification outcomes.

## How to extend this registry

Add a reference only when at least one concrete domain question is identified.

Each new entry should state:

```text
Relevant domains
Useful for
Not Authority for
```

Do not add projects merely because they are popular or adjacent to quantitative finance.

When a reference produces a durable failure lesson, summarize the lesson in `docs/engineering/failure_patterns/` rather than growing this registry into an issue archive.