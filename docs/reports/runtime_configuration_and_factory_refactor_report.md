# Runtime configuration and Factory refactor integration report

## Conclusion

`ACCEPTED`

The generic configuration, typed Factory composition, common Runtime entry, Backtest-owned RunPlan and standard result output
are integrated into the existing formal Vertical Slice. No veto condition remains and the next component may proceed.

## Original configuration architecture

The previous public chain was `OnlyBacktestConfig → OnlyBacktestRuntime.from_config → private runner binding`. Its assembler
directly instantiated the Backtest Runtime, Synthetic source, Virtual Broker, MACD indicator and MACD Cluster. Result writing
was attached to `OnlyBacktestResult.save()` and used a flat example directory.

## New generic configuration architecture

- `onlyalpha.config.OnlyRunConfig` is the only full YAML/JSON document model.
- `onlyalpha.config.OnlyRuntimeConfig` contains engine/runtime identity, type, optional UTC range, base currency and opaque
  `extensions`; the Runtime-internal construction object is explicitly named `OnlyRuntimeAssemblyConfig`.
- Common parsing accepts BACKTEST, PAPER, LIVE, SHADOW and RESEARCH and does not interpret Runtime, DataSource, Broker or
  Strategy private extension fields.
- YAML and JSON example documents normalize to equal typed configurations.

## Runtime types and common interface

- BACKTEST is fully implemented.
- PAPER, LIVE, SHADOW and RESEARCH each have a mode subdirectory and a registered formal Factory.
- Unimplemented modes return `UNSUPPORTED_RUNTIME_TYPE` through `OnlyUnsupportedRuntimeResult`; they do not throw a plain
  `NotImplementedError` or enter a partial run.
- The application use case holds `OnlyRuntime` and calls only `initialize()`, `run()` and `close()`. Lifecycle callers can also
  use `pause()`, `resume()`, `stop()` and `snapshot()` from the parent interface.

## Factory registries and assembly

- `OnlyRuntimeFactoryRegistry` selects the Runtime from `runtime.type`.
- `OnlyDataSourceFactoryRegistry` selects `OnlySyntheticDataSourceFactory` behind `OnlyHistoricalDataSource`.
- `OnlyBrokerFactoryRegistry` selects `OnlyVirtualBrokerFactory`; Virtual-specific matching, commission and slippage parsing
  remains in its factory.
- `OnlyStrategyFactoryRegistry` selects `OnlyMacdStrategyFactory`; MACD periods, warmup and trade parameters remain private to
  that factory.
- `OnlyEngineRunAssembler` imports no concrete Runtime, source, Broker, strategy or indicator implementation.
- The trusted local composition root registers built-ins without weakening the generic assembler boundary.

## Backtest encapsulation and directory refactor

Backtest Runtime, extension config, Factory, RunPlan and result now live under `runtime/backtest/`. The product caller no longer
uses `from_config`, `replay_historical_bars`, `drain_broker_inbound` or a private runner binding. Replay and final result building
execute inside `OnlyBacktestRuntime.run()`.

Concrete implementations were moved to:

- `runtime/backtest`, `runtime/paper`, `runtime/live`, `runtime/shadow`, `runtime/research`;
- `data/synthetic`;
- `broker/virtual`;
- `indicator/macd`.

The old full Backtest config package, flat Synthetic/MACD modules and `broker/virtual_broker` implementation directory were
removed. Component-level integration fixtures still use explicit Runtime management ports to test their direct behavior; the
product/application flow does not.

## Result and output

`OnlyBacktestResult` implements the common `OnlyRuntimeResult` view. `OnlyRuntimeResultExporter` is the filesystem writer and
uses:

```text
root_directory/<engine_id>/<runtime_id>/run-<business-fingerprint>/
├── config
├── runtime
├── market_data
├── execution
├── portfolio
├── strategies/<cluster_id>
├── reports
└── logs
```

The stable `run_id` derives from the business fingerprint. Output path changes therefore do not change the Backtest
fingerprint. Runtime and Runtime Result classes do not write files. The old flat example output was removed.

## Unified CLI and examples

The CLI entry is `onlyalpha run --config <yaml-or-json>`. The YAML and JSON MACD examples use the same schema and differ only in
serialization syntax. `runtime.type` is the only Runtime selector.

## Vertical Slice integration position

The change replaces only the product configuration/assembly/output edges. The formal business path remains:

```text
OnlyRunConfig → OnlyEngineRunService → OnlyRuntimeFactoryRegistry → OnlyBacktestRuntime.run
→ HistoricalDataSource → ReplayService → BacktestClock → MarketDataProcessor → Pipeline
→ MACD → Cluster → Risk → Order → Virtual Broker → Broker Queue → ExecutionProcessor
→ Position → Allocation → Strategy Ledger → Account → OnlyRuntimeResultExporter
```

Existing Managers, ReplayService, MarketDataProcessor, Risk, ExecutionProcessor, Position, Allocation, Ledger and Account were
reused. No direct Manager mutation, Pipeline bypass or fabricated normal fill was introduced.

## Tests and verification

- New configuration tests: YAML/JSON equivalence and all five Runtime types with opaque extensions.
- New Factory tests: BACKTEST selection and structured PAPER/LIVE/SHADOW/RESEARCH unsupported results.
- New static architecture tests: common import boundaries, concrete directory placement and common product entry.
- Direct product integration: MACD Backtest and standard output manifest/layout.
- Historical and new full suite: `271 passed in 100.44s`.
- Complete Vertical Slice: all scenarios `001` through `034` passed.
- Deterministic Backtest replay: 100 identical replays passed; the preserved baseline fingerprint is
  `9a001bcf340a1c155453804ffe2dd90a85883094a9bb3ca445c68d31a49b3f22`.
- Ruff lint: passed.
- Ruff format check: 447 files passed.
- Strict Mypy: 226 source files passed.
- Production import graph cycle test: passed.

## Key invariant checks

- Runtime and Cluster scopes remain isolated.
- Replay remains the only product path advancing the Backtest Clock.
- MarketData and Broker queues remain separate.
- Risk rejection and execution failure paths remain fail-closed.
- Order/Trade IDs, event order, audit, snapshots and business fingerprint remain deterministic.
- Account equity and Ledger dual views reconcile.
- No active reservation or blocking reconciliation remains after the product run.
- Output layout and output root do not affect the business fingerprint.

## Placeholder and unsupported boundaries

Virtual Broker remains the explicitly named deterministic external implementation used by BACKTEST. PAPER, LIVE, SHADOW and
RESEARCH factories are explicit unsupported placeholders only; no real SDK, real account or real trading capability was used.

## Known limits

The first Backtest Factory currently accepts one Account, Broker and HistoricalDataSource, and its specialized result builder
supports the MACD example strategy. Multi-account/source product assembly, generic multi-strategy result providers, real
Paper/Live loops, recovery and reconciliation startup are future components behind the established registries.

## Veto audit

- Full config is not Backtest-owned: pass.
- Common parser does not import or parse concrete extensions: pass.
- Common assembler directly instantiates no concrete implementation: pass.
- Product caller uses no Runtime subclass/private method: pass.
- Concrete implementations use parent-component subdirectories: pass.
- Runtime writes no result files: pass.
- YAML/JSON semantics are equal: pass.
- Historical Vertical Slice passes: pass.
- Deterministic replay passes: pass.

Final decision: `ACCEPTED`.
