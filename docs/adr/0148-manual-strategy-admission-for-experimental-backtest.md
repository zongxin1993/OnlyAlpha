# ADR 0148: Manual strategy admission for experimental Backtest

- Status: Accepted
- Decision: owner explicitly approved the normal Backtest path without a Research report on 2026-11-02.
- Constitution Impact: NO
- Related: ADRs 0097, 0098, 0099, 0118, 0133, 0141, 0142.
- Owning contract: [Manual Backtest strategy validation](../manual-backtest-strategy-validation.md).

## Decision

An owner may select a published exact Factor Revision, define a Strategy and prepare an experimental BACKTEST without first creating a Research Run or Research Result. Research Candidate Freeze remains supported, but is no longer the exclusive source of a frozen Strategy. This refines only the Research-exclusive Backtest prerequisites in the related ADRs; it does not change Strategy semantic identity or introduce another Freeze, Qualification, Promotion or execution authority.

The existing Backtest preparation task first pins the exact authoring revisions, immutable Dataset and Runtime Generation. The existing numerical and native calculation owners validate the complete decision graph, exact RESEARCH/TRADING implementations, required P9 corpus and checkpoint restoration. Positive termination of every original numerical child precedes publication of real strategy execution-validation evidence. This technical verification creates no Research Run, Target, Statistics, confidence interval, profitability claim or simulated trading result.

The same Freeze publisher consumes an opaque verified validation proof and records a `MANUAL_BACKTEST` origin outside the unchanged Strategy fingerprint. The same Qualification evaluator consumes typed `STRATEGY_VALIDATION` evidence under `MANUAL_STRATEGY_TO_BACKTEST`; the same Promotion ledger grants only BACKTEST admission. A manual origin cannot claim a RESEARCH predecessor or obtain SIM/LIVE admission. Existing Research facts retain their exact meanings and are not translated into manual evidence.

Accepting preparation is not accepting a Backtest Run. The task may materialize inputs and validate executable semantics before trading admission. READY requires the original validation, Freeze, Qualification, Promotion, Dataset, model and Runtime proofs. A separate normal Web confirmation creates the original reserved Backtest Run. Cancellation or an uncertain outcome never permits a replacement identity or discards already published immutable facts.

## Evidence and reuse

Validation has one immutable artifact owner and an append-only publication-occurrence reference to the original preparation. The reference authenticates publication by the actual joined producer; an orphan file or a JSON assertion of successful termination is insufficient. Historical readers re-open the exact original authoring, Dataset, implementation, Runtime and physical witnesses. Preparation output JSON is progress metadata rather than a grant.

The canonical Qualification source inventory fully verifies manual evidence. A manual rejection is not a Research-result failure and does not invent a Research novelty facet. Reusing an existing BACKTEST admission requires its actual owning proofs and exact immutable Strategy; a repeated preparation does not invent a BACKTEST-to-BACKTEST promotion.

This slice reuses the Rust backend and Trading Kernel, existing calculation SDK, PostgreSQL/immutable stores, Ant Design and ECharts. It introduces no alternative Backtest engine, numerical engine, environment or external service. The initial product scope remains the approved single-instrument BTCUSDT one-minute profile. Research product improvements and SIM/LIVE are outside this delivery.
