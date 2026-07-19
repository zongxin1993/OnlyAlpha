# Repository Guidelines

## Project Structure & Module Organization

OnlyAlpha is a Python 3.12+ quantitative-trading framework. Production code lives in `src/onlyalpha/`, organized by responsibility: `domain/` contains immutable financial models, `runtime/` and `engine/` coordinate execution, while `result/`, `analytics/`, `artifact/`, and reporting modules consume completed run facts. Tests mirror these boundaries under `tests/`; cross-component scenarios belong in `tests/integration/` and `tests/integration_demo/`. Architecture decisions and component guidance live in `docs/` and `docs/adr/`. Example strategies and vendor adapters are maintained in sibling repositories `../OnlyAlpha-examples/` and `../OnlyAlpha-plugins/`.

## Build, Test, and Development Commands

Use the workspace virtual environment or `uv`:

```bash
uv run pytest -q                 # run the complete test suite
uv run ruff check .              # lint and validate imports
uv run ruff format --check .     # verify formatting
uv run mypy                      # strict type-check src/onlyalpha
uv run onlyalpha run --config path/to/config.yaml --user-data /tmp/onlyalpha
```

Run focused tests while developing, for example `uv run pytest -q tests/analytics`. Before handoff, run the full suite and `git diff --check`.

## Coding Style & Naming Conventions

Use four-space indentation, 120-character lines, double quotes, complete type annotations, and immutable dataclasses for result/domain facts. Ruff controls formatting and import order; Mypy runs in strict mode. Public OnlyAlpha classes, protocols, enums, exceptions, and identifiers must start with `Only`; functions and variables use `snake_case`, constants use `UPPER_SNAKE_CASE`. Preserve dependency direction: domain code must not import runtimes, plugins, databases, CLI, or presentation layers. Never use `float` as the source of truth for prices, quantities, money, fees, or PnL; use `Decimal`-backed domain values.

## Testing Guidelines

Pytest discovers `test_*.py` under `tests/`. Add unit tests for invariants and failure paths, direct integration tests for neighboring components, and a deterministic vertical-slice regression for behavior crossing Runtime boundaries. Use fixed clocks, input data, and expected fingerprints. Do not weaken assertions, delete historical scenarios, or hide failures with `skip`.

## Multi-Market Simulation Rules

Market-specific behavior belongs in versioned `onlyalpha.market` profiles and Instrument Reference, never in generic Order,
Position, Account, Broker, Engine, Analytics, or Report code. Keep settlement, availability, position mode, short/borrow,
margin, session, price, quantity, fee, liquidity, slippage, and matching as orthogonal rules. Reuse existing Instrument,
Calendar, Position Side/Mode, ExecutionProcessor, and Result types; do not create parallel financial models. New public
market types use the `Only` prefix, Decimal semantics, effective intervals, stable fingerprints, explainable decisions, and
tests proving both an A-share case and a non-A-share Generic case. Do not describe a reserved interface as production
support; preserve Legacy configs unless a profile is explicitly selected.

Profile family and version are separate identities. Register versions through `OnlyMarketProfileRegistry`; effective
intervals are left-closed/right-open and may not overlap. Ordinary overrides are limited by
`OnlyMarketProfileOverridePolicy`; changing settlement, position mode, short selling, or margin requires a custom
profile. A profile may be marked Stable only when every enabled capability is covered by its Engine-based conformance
pack. Scenario runners must traverse Engine, Risk, Virtual Broker, ExecutionProcessor, and Results and must never forge
fills or mutate account/position state for assertions.

Scenario code belongs in `onlyalpha.scenario`. Parser and Assertion code must not import Broker, Risk, Runtime managers,
or Profile rule implementations. PAPER/LIVE/SHADOW capability gaps must be explicit; never translate their actions into a
hidden BACKTEST path. Parser/planner tests are not evidence that an Engine scenario or Conformance Pack passes.

Conformance Runner may call only the public Scenario Runner. Capability coverage must come from required Scenario PASSED
results; query services are read-only and CLI adapters must not access Runtime or Manager internals.

## Commit & Pull Request Guidelines

History uses concise prefixes such as `Feat:` and `Fix:`. Keep commits scoped to one boundary and write imperative summaries, for example `Fix: preserve replay root failure`. Pull requests should explain the behavior change, architecture impact, tests executed, and known limitations; link related issues or ADRs. Include screenshots only for user-facing output changes, and never commit credentials, tokens, generated `user_data`, caches, or run artifacts.
