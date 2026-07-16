# ADR 0019: Runtime-agnostic configuration, factories and result output

- Status: Accepted
- Date: 2026-07-16
- Modules: config, runtime, data, broker, strategy, output, application

## Context

ADR 0018 proved a product Backtest, but its public entry, full configuration model, assembler and result writer were all
Backtest-owned. That boundary could not select PAPER, LIVE, SHADOW or RESEARCH without duplicating configuration and allowing
application code to depend on Runtime subclass APIs.

## Decision

- The only full document model is `OnlyRunConfig` under `onlyalpha.config`; `runtime.type` accepts BACKTEST, PAPER, LIVE,
  SHADOW and RESEARCH. Common parsing preserves opaque `extensions` and never imports concrete implementations.
- `OnlyEngineRunAssembler` selects a factory through `OnlyRuntimeFactoryRegistry` and returns the `OnlyRuntime` parent type.
- DataSource, Broker and Strategy components have separate typed Factory registries. Concrete extension parsing stays inside
  `data/synthetic`, `broker/virtual` and `strategy/macd` factories.
- Backtest Replay and RunPlan are owned by `OnlyBacktestRuntime.run()`. Application code does not call replay, drain or private
  binding methods and does not use `isinstance` to select Runtime behavior.
- PAPER, LIVE, SHADOW and RESEARCH have registered factories returning `UNSUPPORTED_RUNTIME_TYPE` until their loops exist.
- `OnlyRuntimeResultExporter` is the only filesystem result writer. It uses the deterministic
  `root/engine_id/runtime_id/run_id` layout; output paths are excluded from the business fingerprint.
- Concrete implementations live in mode/type subdirectories below their parent component packages.

## Consequences

The previous `OnlyBacktestConfig`, `OnlyBacktestRuntime.from_config` and `OnlyBacktestResult.save` entry points are removed.
This is an intentional pre-stabilization breaking change. Backtest business semantics, formal MarketData/Execution chains and
the deterministic fingerprint remain unchanged. Other Runtime types are selectable and report a structured unsupported result
without pretending that live or paper execution exists.

## Validation

Validation covers YAML/JSON equivalence, all five Runtime types, all four registries, static import boundaries, directory
placement, standard output layout, the historical Vertical Slice, full test suite, Ruff, strict Mypy and 100 deterministic
Backtest replays.
