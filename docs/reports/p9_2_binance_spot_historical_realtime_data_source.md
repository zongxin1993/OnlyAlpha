# P9.2 Binance Spot Historical & Realtime DataSource

- Task base SHA: `5176c722a28097b1ea9edd589731c887303908e9`
- Implementation HEAD: `5176c722a28097b1ea9edd589731c887303908e9` (working-tree implementation; no commit was requested)
- Scope: Binance Spot public BTCUSDT/ETHUSDT 1m closed Bars, raw Trades, realtime venue reference facts, in-process continuity/recovery, and typed verified acquisition cache
- Status: correctness closure implemented locally; exact-SHA Layered Quality remains `CI REQUIRED`

## Correctness closure — 2026-08-30

- Closure task base SHA: `5d0db9c51c88be36fe4f76708c8d39da28468868`
- Closure SHA: `NOT AVAILABLE` (working tree is not committed)
- Environment: macOS arm64, Python 3.12, uv workspace
- Scope: exact venue-reference semantics, atomic continuity mutation authority, and canonical Binance test collection only

### Root causes closed in the working tree

- Semantic authority drift: Binance `/api/v3/avgPrice` and `@avgPrice` were incorrectly normalized as `VENUE_REFERENCE_PRICE`.
- Multi-writer continuity authority: lifecycle, WebSocket, and recovery threads could observe and mutate coordinator state across non-atomic calls.
- Hidden test import dependency: two Binance tests imported `_bar_type` from a sibling test module and failed under importlib collection.

### Fixes

- REST now uses `/api/v3/referencePrice`; WebSocket subscribes to and dispatches only `@referencePrice`; one strict `only_normalize_reference_price()` maps the REST and stream contracts.
- Explicit reference null remains a canonical unavailable venue fact. Missing, stale, and disconnected evidence remain distinct and cannot trigger Trade fallback. Only explicit unavailable may use the existing Core Trade/VWAP authority, and incomplete Trade coverage still fails closed.
- One coordinator-level reentrant lock protects the complete semantic transition: connection/subscription/baseline evidence, state, buffer, dedup, sequence, gap recovery, failure, and derived READY proof. `ready()` was removed; `complete_recovery()` reaches READY only after its invariant is proven.
- Shared Binance test constructors now come from `conftest.py`; no test module imports another test module.

### Local verification evidence

- Targeted semantic/continuity/architecture closure: `26 passed`.
- Binance importlib collect-only: `47 collected`, PASS.
- Binance offline suite: `46 passed, 1 external deselected`.
- Canonical workspace importlib collection: `3314 collected`, PASS.
- Multi-market/core offline regression: `105 passed, 2 external/environment tests deselected`.
- Architecture lane: `513 passed`.
- Recovery lane: `334 passed`.
- SIM recovery lane: `38 passed`.
- A-share lane: `24 passed`.
- MiniQMT contract lane: `34 passed`.
- Release static: Ruff, Ruff format, root/package Mypy, import contracts, and version graph PASS; root Mypy checked `702 source files`.
- Binance package sdist/wheel build: PASS at workspace version `0.9.8`.
- Budgeted impact run: `LOCAL_PASS_CI_REQUIRED`, 10 local checks PASS, 30 commands deferred, exit code `3` as required. Manifest: `test-results/verification/local-budget/20260830T103017Z-5d0db9c51c88-11281/manifest.json`.

### Bounded independent review

Scope was limited to the closure delta and directly touched Core reference authority. Applicable semantic uniqueness, deterministic normalization, state ownership, fail-closed recovery, provider isolation, and canonical collection invariants have local PASS evidence. No P9.3/P9.4 capability was introduced.

- Critical: `0`
- High: `0`
- Verdict on implementation delta: `GO`

### Remaining closure authority

GitHub authentication is currently invalid, so no exact closure commit or Layered Quality run can be created/observed from this workspace. Current machine policy has no CodeQL gate; CodeQL is therefore `NOT APPLICABLE`, not a fabricated PASS. The impact plan's remaining commands stay `CI REQUIRED`.

Because exact-SHA CI evidence is absent, this report does not declare P9.2 verified and `project-state.toml` remains at P9.1 verified / P9.2 authorized. The canonical P9.2 → P9.3 transition must occur only after Layered Quality succeeds for the final closure SHA.

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
