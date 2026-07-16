# Runtime configuration and factory gap analysis

## Before

The product flow was `OnlyBacktestConfig → OnlyBacktestRuntime.from_config → private runner binding`. The Backtest assembler
instantiated Synthetic data, Virtual Broker, MACD indicator and strategy directly. `OnlyBacktestResult.save()` owned a flat
example output directory. PAPER/LIVE/RESEARCH marker classes had no configuration-selection boundary and SHADOW was absent.

## Required boundary changes

- move the full document to `onlyalpha.config` and preserve concrete parameters as `extensions`;
- expose a single `OnlyRuntime` lifecycle/run/snapshot surface;
- select Runtime, DataSource, Broker and Strategy through typed registries;
- keep Replay/RunPlan inside Backtest;
- register structured unsupported factories for future Runtime modes;
- move concrete implementations below parent-component subdirectories;
- move filesystem output to a common exporter and stable scoped layout;
- retain the exact historical execution chain and deterministic result.

## Migration risk

The public Backtest-specific entry is deliberately removed. Component-level fixtures may still exercise Runtime management
ports directly, but product/application code uses only the common run service. The highest regression risks are import cycles,
configuration semantic drift, output-path contamination of fingerprints and bypassing Replay or ExecutionProcessor.
