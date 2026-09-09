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

### LEAN

Relevant domains:

- mature multi-market engine behavior;
- brokerage adapters;
- backtest/live parity pressure;
- scheduling, calendar, corporate-action and data normalization problems;
- long-lived production issue history.

Useful for:

- finding real-world brokerage / market-data edge cases;
- comparing market-specific behavior against a market-agnostic core.

Not Authority for:

- OnlyAlpha module boundaries;
- strategy semantics;
- data or execution facts.

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
- null controls;
- multiple-testing governance;
- deflated performance statistics;
- falsification / pre-registration.

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
