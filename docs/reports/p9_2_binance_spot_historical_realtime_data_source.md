# P9.2 Binance Spot Historical & Realtime DataSource

- Task base SHA: `5176c722a28097b1ea9edd589731c887303908e9`
- Implementation HEAD: `5176c722a28097b1ea9edd589731c887303908e9` (working-tree implementation; no commit was requested)
- Scope: Binance Spot public BTCUSDT/ETHUSDT 1m closed Bars, raw Trades, realtime venue reference facts, in-process continuity/recovery, and typed verified acquisition cache
- Status: implementation complete; required CI proof remains pending

## Core changes

### Stable market-fact identity

Canonical update identity is now independent from processing order. Bar identity is derived from source, instrument, Bar type, Bar start and DataVersion; Trade identity uses the venue Trade identity; Market Reference identity uses kind and venue event time. REST, WebSocket, recovery and replay therefore converge on the same identity for the same fact. The deduplicator accepts `update_id` as its sole new identity authority while retaining read compatibility for legacy Bar checkpoints.

### Explicit sequence semantics

`OnlyDataSequenceSemantics` distinguishes `UNKNOWN`, `MONOTONIC` and `CONTIGUOUS`. `OnlyDataSequenceScope` isolates Trade continuity by source/instrument/family and Bar continuity additionally by Bar type. The envelope uses schema version 2 while reading schema version 1. Sequence checkpoints preserve explicit scope and migrate the legacy `(source, family)` representation on commit.

### Typed historical cache

The cache exposes typed Bar and Trade keys and `load_bars`/`load_trades` paths. DataVersion participates in identity; Binance Bars use Bar-open timestamp semantics; Trade partitions are monthly. Both families share manifest verification, partition hashes, content fingerprints, atomic replacement, exact resolved-range inspection and fail-closed corruption handling. The existing Bar `load`/key API remains as a compatibility path.

### Realtime market reference

Core gained provider-neutral `OnlyMarketReferenceKind`, `OnlyMarketReferenceTick`, envelope support, and `OnlyRealtimeMarketReferenceAuthority`. It consumes the P9.1 `OnlyCompiledDynamicPriceRequirement`, resolves a venue reference when present, uses the previous Trade for a zero-minute fallback, computes deterministic VWAP only with complete proven window coverage, and distinguishes an explicit unavailable reference from a missing fact. The Binance plugin supplies only provider-neutral facts; it does not own or evaluate the Core authority.

## Binance DataSource

### Historical Bar

The public REST path pages bounded 1m Klines, rejects invalid order, duplicates, no progress and out-of-range rows, normalizes mathematical `[bar_start, bar_end)` intervals, and publishes only closed Bars. Current open Bars cannot close cache coverage. BTCUSDT and ETHUSDT are selected through OnlyAlpha composition, not provider config.

### Historical Trade

The time-range locator uses aggregate Trades only to locate raw IDs. Canonical facts come exclusively from `/api/v3/historicalTrades`, are paged with contiguous raw Trade-ID validation, normalized to `OnlyTradeTick`, and filtered to exact `[start, end)`. Empty past ranges may be explicitly resolved; unproven current/future tails remain incomplete.

### Realtime Bar, Trade and Market Reference

The bounded WebSocket transport handles combined public streams without normalization logic. The adapter emits only closed Klines (`x=true`), raw Trades and `VENUE_REFERENCE_PRICE` facts. Venue event time is `ts_event`; Core ingress observation time is the envelope `ts_init`. Public authentication is an accepted no-op and no credential surface exists.

### Continuity and recovery

The connection model separates `CONNECTED`, `RECOVERING` and `READY`. Startup begins realtime buffering before baseline acquisition. Duplicate and stale facts are suppressed by canonical identity and scoped sequence; contiguous gaps enter recovery, use the same REST normalizers, validate the exact expected sequence tuple, reconcile the bounded buffer in deterministic order, and return to READY only after proof. Recovery failure remains not ready; buffer overflow fails closed. Reconnect uses bounded exponential backoff. Runtime checkpoint capability remains `STATELESS`; durable cursors/WAL are deferred to P9.3.

## Architecture and compatibility

- Binance payloads and protocol field names terminate inside `onlyalpha_plugin_binance.spot.data_source`.
- Stable Core does not import `onlyalpha_plugin_binance` and contains no BTCUSDT/ETHUSDT branches.
- The provider is registered through the existing `onlyalpha.data_sources` SPI.
- MiniQMT and Tushare now emit fact-derived IDs while retaining their own `MONOTONIC` sequence semantics.
- Scenario, Synthetic, compatibility replay and streaming warmup no longer derive canonical IDs from processing order.
- No second Engine, Runtime, MarketDataManager, durable market-data authority or private Binance API was added.

## Verification evidence

### Local PASS

- Core identity/cache/reference/data: `28 passed`
- Binance offline suite: `39 passed, 1 external deselected`
- Runtime/SIM/Synthetic identity regression: `24 passed`
- Generic T0, CN A-share, Binance Market Product and Runtime market-rule regression: `58 passed`
- MiniQMT offline: `34 passed, 1 external deselected`
- Tushare offline: `18 passed, 1 skipped`
- Targeted architecture/plugin boundaries: `8 passed`
- Post-format continuity/cache/SIM regression: `28 passed`
- Ruff affected check: PASS
- Ruff affected format check: PASS
- Mypy affected surface: `Success: no issues found in 106 source files`
- Workspace version graph: PASS at `0.9.8`
- Binance package sdist/wheel build: PASS

### NOT EXECUTED

- External Binance public contract test (network-dependent)
- Final-SHA or release certification (not part of the current local Task workflow)

### CI REQUIRED

Canonical impact authority selected a fail-closed full required plan of 40 commands / 129 cost units. The budgeted local run returned `LOCAL_PASS_CI_REQUIRED`: all 10 selected release-static checks passed and 30 commands were deferred. Deferred proof includes web static/unit/build/E2E, kernel and strategy, Research/calculation lanes, `core-full`, recovery, sim-recovery, A-share, MiniQMT contract and all-packages build. Manifest: `test-results/verification/local-budget/20260829T025901Z-5176c722a280-22179/manifest.json`.

These gates remain `CI REQUIRED` until GitHub CI reports PASS; none is represented as a local or CI PASS. CodeQL and the layered GitHub quality workflow are likewise not proven in this uncommitted local working tree.

## Deferred scope

- P9.3: durable Market Data Revision, WAL, database schema, crash-restart cursor and HOT/COLD lifecycle
- P9.4: API keys, signatures, private REST/WebSocket, account, balance, position, orders and reconciliation
- Binance Futures, depth/L2, distributed sharding and bulk archive ingestion

## Project state

`project-state.toml` remains at P9.1 verified / P9.2 authorized until all required impact gates are green. The canonical project-state transition to P9.2 verified / P9.3 implementation ready must not occur while required CI evidence is pending.
