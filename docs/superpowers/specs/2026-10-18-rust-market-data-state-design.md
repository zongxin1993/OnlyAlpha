# Rust Market Data State design

Status: OWNER-APPROVED DESIGN — the owner reviewed this written design and requested continuation.
This specifies a library construction, not implementation completion, Runtime admission or Python retirement.
The Constitution, [MarketData Contract](../../market_data_pipeline.md), ADRs
[0003](../../adr/0003-cache-storage-separation.md), [0009](../../adr/0009-event-and-primary-bar-delivery.md),
[0020](../../adr/0020-cluster-strategy-factor-indicator-model.md),
[0139](../../adr/0139-linux-first-rust-trading-kernel-migration.md) and
[0140](../../adr/0140-domain-determinism-and-cross-language-contract.md) remain authoritative.

## Owner-facing summary

实现完整的行情状态职责：有限 closed-Bar 历史、精确版本、不可变行情快照、受限 Cluster 视图与原子恢复。
使用 Kernel 总目录下的独立 `market_data_state/` crate，只依赖 Domain 和已准入的精确整数/JSON 库。
Python 是临时参考，不按旧目录和缺陷逐行翻译。指标状态归 Cluster；行情状态不拥有指标计算、交易准备就绪或历史行情持久化。
先完成库和交叉验证，留给 Owner 人工审查；本轮不接入 Runtime、不转换既有数据、不推送、不升版。

## Goal, ownership and explicit exclusions

Create `crates/onlyalpha-kernel/market_data/state/`, package `onlyalpha-market-data-state`.
A Runtime owns one mutable state instance. Its existing synchronous Pipeline supplies already admitted Domain Bars and explicit
initialization time; this module atomically accepts a closed-Bar batch and returns an immutable Runtime snapshot. Cluster views
are filtered immutable values. Neither consumers nor Event observers obtain the mutable owner.

The complete functional unit includes admission to this state, bounded per-type retention, exact versions, queries, snapshot
construction/filtering, strict records and checkpoint capture/restore. It is not the whole Python `market_data/` package.
Cache is reconstructible Runtime state, not the authoritative durable source of market history.

Outside this unit: Source/gateway acquisition, streaming deduplication/sequence/gap tracking, Construction graph compilation and
execution, Calendar policy selection, Pipeline/Dispatcher/Strategy execution, Indicator/Factor calculations or worker protocols,
WAL/Segment/Dataset/DB/Parquet/history-store implementations, Runtime checkpoint coordination/admission and Python activation.
The generic `cache/` key-value interface and `cache/historical/` are separate responsibilities and are not translated here.
Constitution impact: NO. No authority, deterministic behavior, immutable history or recovery obligation is weakened.

## Reference audit and responsibility map

| Python source / real consumer | Selected Rust responsibility |
|---|---|
| `market_data/cache.py`: OnlyBarCache / OnlyMarketDataCache | One mutable state owner; no empty alias subclass |
| `market_data/snapshot.py`: OnlyBarSnapshot / OnlyMarketDataSnapshot | Private validated series plus one immutable snapshot/query surface |
| `market_data/pipeline.py`: `_commit_bars` | Atomic state batch and snapshot only; Pipeline orchestration stays outside |
| `market_data/dispatcher.py`: `restrict` consumer | Immutable subscription-filtered Cluster view; no dispatch scheduling |
| `runtime/trading_facade.py`: `market-data.cache` participant | Strict component payload; existing outer Runtime coordinator remains separate |
| `cluster/bar_context.py`, Risk snapshot consumers | Read-only values; no cache mutation or new risk authority |

The admitted Python reference has the following deterministically reproduced deviations:

- `restore_checkpoint` replaces closed history and partials before decoding versions; a later failure leaves partial changes.
- Restore accepts a map key whose nested Bar has a different BarType, coerces bool to an integer version and bypasses history_limit.
- Snapshot restriction can select a primary type outside its allowed set, leaving primary absent from the returned histories.
- Snapshot construction accepts mismatched instrument and initialization-before-event; record reading accepts unknown schema,
  extra fields, string counters and inconsistent future history/latest values.
- The snapshot/Pipeline still carry indicator values although the current MarketData Contract and ADR 0020 place algorithms
  and indicator state under Cluster/Factor ownership. The Rust module must not acquire a calculation dependency for symmetry.

These are reference deviations, not Rust acceptance targets. Invalid direct inputs do not prove that ordinary production
callers currently produce them; the actual caller chain and its safeguards must remain distinguished from public-value validation.
Current correct FIFO/per-BarType ordering, bounded update retention, history queries, versions and ordinary snapshot views are
common-reference behavior. Python production is not structurally cleaned up here. A demonstrated necessary official-execution
safety fix needs its own nearest stable impact boundary; known deviations cannot be represented as complete Python/Rust parity.

## Organization and dependencies

Use one library, with private `model.rs` (scope/config/errors), `state.rs` (owner/series/admission), `snapshot.rs` (views/queries)
and `record.rs` (current records/checkpoint validation), plus `lib.rs` and tests. Do not scaffold future aggregation or worker modules.

The only local dependency is `onlyalpha-domain`. Direct numerical/JSON packages reuse the already reviewed exact versions/features:
`num-bigint = 0.4.8`, `default-features=false, features=["std"]`; `serde_json = 1.0.154`,
`default-features=false, features=["std","arbitrary_precision"]`. No registry nodes are added. Clock/Event/Predicate/Runtime,
application, storage and plugins are absent from the isolated build closure; lower modules cannot depend on this module.

Use std collections and immutable shared ownership. A non-Clone owner exposes mutation only through `&mut self`; it has no global
registry, interior-mutability view, worker, lock or callback. Immutable snapshots may be shared across threads. No artificial
thread marker is needed: Rust exclusive borrowing prevents concurrent mutation; moving ownership is not concurrent access.
Use bounded `VecDeque` histories and immutable shared Bar values; reuse unchanged immutable series when constructing snapshots.
Never deep-clone all Domain facts merely to protect aliases. Atomic staging must not expose mutable references to shared data.

BarType is the existing Domain semantic identity. Internal lookup/order may derive a canonical key from its current Domain record;
that key is not a new public ID, hash or construction identity. Domain validates Bars, Decimal values, BarType and time records.
State-specific admission adds its own constraints instead of modifying Domain's valid broader fact vocabulary.

## Inputs, admission and atomic state transition

Construction takes explicit strong Engine/Runtime IDs and a positive per-BarType `history_limit` (default 1024). Scope and limit
are immutable for this owner. Market/Provider/Construction binding and Runtime Generation remain external owning facts; this
library cannot infer them from a BarType or claim to validate them from a cache record.

An operation supplies a nonempty ordered batch of Domain Bars, an explicit primary BarType present in that batch, exact Domain
`ts_init` and ordered string quality flags. No clock read, UUID creation, subscription lookup or implicit primary selection occurs.

Validate the whole operation before changing the owner:

1. Every Bar is closed, revision zero and `ts_event == bar_end`; no implicit correction, replacement, gap fill or partial is enabled.
2. A batch contains at most one Bar per BarType. A type's `bar_end` strictly exceeds its retained latest end. Duplicate/late values
   reject the entire operation; identical duplicates are not silently treated as successful updates.
3. The primary exists in the batch; its end defines snapshot event time. Initialization does not precede that event time. Bar initialization remains its own Domain fact; a later historical-acquisition
   timestamp must not be confused with a Backtest logical snapshot clock. All included/retained Bars end no later than snapshot event time; stale anchors cannot expose future data.
4. All scope/value/record relationships and required query metadata are valid before staging publishes anything.

Stage per-type history/version changes, trim the oldest Bars beyond the configured limit, and construct the complete immutable
Runtime snapshot. Increment each changed type's arbitrary nonnegative integer version once. Rejected operations change no
history, version or observable snapshot. Only after staging and snapshot validation succeed may one owner replacement commit.
No EventBus callback, external I/O or user code executes within this operation. This atomic boundary covers this state/snapshot
only; it does not claim rollback across future Construction, Indicator or durable Runtime participants.

Runtime state may retain multiple instruments; a global snapshot's primary instrument is its anchor, not a claim that every
retained series has that instrument. A Cluster's selected BarTypes remain single-instrument under the existing subscription Contract.
Missing intervals are not filled or certified absent. Each history is bounded; registered type counts and inbound batch budgets
remain the owning Runtime's responsibility, so this does not claim a global memory-byte bound.

## Immutable snapshots and query semantics

Store each series once as validated BarType, positive exact version and nonempty chronological retained history. Latest is the
history tail; primary Bar, instrument, TradingDay and SessionType derive from the selected primary, never independent mutable maps.
The snapshot owns immutable data and explicit Engine/Runtime/optional Cluster scope, exact event/init times, visible BarTypes,
updated BarTypes, series and quality flags. Old snapshots are unchanged by later updates or restore.

Retain the complete query responsibilities: latest/required latest, positive-count suffix history, per-type version, updated test,
required same-event-time latest, complete immutable visible series access and current_partial. Current_partial returns no value;
partial creation/transport is unsupported and nonclosed facts reject. Unknown series has empty history/version zero only as a
local cache miss. Required missing series/time mismatch is an explicit error; no query proves durable historical absence.

A Runtime snapshot can derive independent Cluster views. Require a nonempty duplicate-free, single-instrument allowed set and a
primary member of that set whose latest closes at the parent event time. Allowed-but-not-yet-materialized series remain visible
as local misses; updated is filtered to the allowed set. Remove every unselected series from memory/record access through the view.
A restricted Cluster view may only narrow its current set for the same Cluster; it cannot change Runtime, select a sibling Cluster,
widen visibility or retrieve its unfiltered parent. An out-of-view query returns Scope error rather than a false missing-data claim.
Snapshot DTO construction is not cryptographic authorization and grants no Runtime execution capability.

Indicator values/versions and their accessors are absent. Snapshot construction and checkpoint success do not assert Indicator,
Factor, subscription, Source continuity or Strategy readiness; the existing higher-level barrier remains the owner of those proofs.

## Current records and checkpoint restoration

The owner-selected language-neutral format is schema 2 for both owning records. These are explicit development Contract
changes, not per-language format families. No official Python writer/reader is replaced in this library construction.

Checkpoint payload fields are exactly `schema_version`, `engine_id`, `runtime_id`, `history_limit`, `series`.
Each series has exactly `bar_type`, `version`, `history`, reusing current strict Domain records. Empty state uses an empty series
array, not empty materialized rows or version-only entries. Versions are JSON integer tokens, preserved with arbitrary precision;
strings, bools, fractions and negative values reject. Limits/counts are positive resource integers that must fit allocation indexes.

Snapshot payload fields are exactly `schema_version`, `engine_id`, `runtime_id`, `cluster_id`, `ts_event_ns`, `ts_init_ns`,
`primary_bar_type`, `visible_bar_types`, `updated_bar_types`, `series`, `quality_flags`. Anchor Bar/instrument/day/session/latest
remain derived from the validated series. Scope and visibility are complete even when a selected secondary series is still missing.
No indicator, partial or duplicate primary/history truth is serialized. A record's exact required fields/types, primary membership,
updated membership, nested BarType consistency, closed/revision/time/order, visible-series closure and positive-version relations
are revalidated. For each materialized series, `version >= retained history length`; history length cannot exceed checkpoint limit.
A snapshot does not claim the complete historical retention limit can be inferred from its retained lengths.

Writers order map-like arrays by canonical Domain BarType key; chronological histories and quality flags retain their order.
Readers may normalize map-like array order but reject repeated BarType/visibility/update entries rather than silently deduplicate.
No record digest or byte-level execution identity is invented. JSON integer facts and nanoseconds never pass through f64.

Restore parses and validates into a temporary complete state, checks exact owner scope and history_limit against the receiving
instance, then swaps once. A malformed late entry leaves the original fully intact. Restore is replacement, never union/append;
repeating the same valid restore gives the same values/versions. Do not regenerate counters, trim invalid imported histories,
coerce types or overwrite identity mismatches. Newly constructed and valid-restored state must obey the same invariants.

The actual Python Runtime currently registers `market-data.cache` component schema 1 in `runtime/trading_facade.py`; its outer
checkpoint binding, retained artifacts and historical reader stay unchanged. Rust schema 2 is not admitted into that registry.
Before a future activation, inventory actual stored schema-1 bodies and references, define any authorized deterministic migration,
and prove outer Runtime Generation/Source/Construction binding, restart and upgrade. A cache-only restore cannot establish them.
No unknown/legacy fallback, compatibility alias, automatic translation, business-data deletion or reader substitution is added.

## Proof obligations and acceptance design

Re-derive the owning state space: empty state; populated types with differing histories/versions; Runtime/global and Cluster views;
accepted single/multi-type batch; denied duplicate/late/revision/nonclosed/wrong-scope/malformed inputs; valid restore; rejected
restore; immutable old views. Missing secondary data is a local miss, out-of-scope is denial, malformed relevant proof is an error.
There is no async UNKNOWN operation or LIVE transition here; outer transaction/lifecycle authorities remain outside this unit.

| Dimension / relation | Required proof |
|---|---|
| Owner -> record -> nested series | Exact Engine/Runtime scope; mismatch/missing/malformed never selects another owner |
| BarType -> history -> latest/primary | Nested type equality, ordered closed facts, unique series and primary closure |
| Version -> retained history | Exact positive counter, no coercion, adequate length, invariant maintained across trimming |
| Event/init -> anchor/all histories | No initialization-before-fact or future history; same-event-time query is explicit |
| Runtime view -> Cluster visible set | Single instrument, valid primary, no widening/cross-Cluster/hidden record escape |
| Restore -> replacement | Complete validation before mutation, deterministic retry and no partial state |

Mutation tests cover missing/whole context, wrong owner, swapped nested key, foreign source/context assumptions, invalid Bar,
duplicate owner/series/type, wrong record family, same-time-but-different primary, and a complete different valid owner. The
module does not expose Source/Generation certification; tests must not infer such proof from cache fields or timestamps.

Shared independent `test-data/market-data-state/` operation/record vectors describe common valid state semantics. The Python
consumer uses its existing public objects and recorded explicit inputs; it does not fabricate enforcement of fields Python never
owned. Schema-1/schema-2 layout differences and diagnosed malformed-input/reference deviations stay explicit. Compare common exact
Bar identities/values, retained histories, counters and available snapshot fields; never claim full wire/module parity from that subset.
Rust-specific adversarial tests cover all corrected invariants, atomic multi-type failure and restore, filtering, empty/missing,
large exact counters, precision/time boundaries, immutable aliases and deterministic replay from fresh/restored instances.

Implementation validation uses the sole frozen-source Linux dev entry: targeted state/consumer/guard/version checks, affected
Ruff/mypy, Cargo fmt/Clippy, debug/release tests/builds and isolated State+Domain closure. Extend guards to reject reverse edges,
Clock/Event/Runtime/Provider imports, hidden includes/build scripts, OS time/randomness and undeclared dependency features.
Prove Domain still builds without State. Complete one bounded independent correctness/simplicity review; unresolved scoped
Critical/High blocks library acceptance. Library evidence cannot certify a Shipping UI path, Runtime recovery or latency improvement.
Version stays 0.10.10 until a separately authorized mainline publication.

## Relevant failure history and rejected approaches

First-principles requirements above are reinforced by the curated engineering references:

- [FP-DATA-002](../../engineering/failure_patterns/FP-DATA-002-authoritative-history-mutated-by-transform.md) and
  [RQAlpha #632](https://github.com/ricequant/rqalpha/issues/632): a cached historical array was adjusted in place and repeated
  queries differed. Derive tests for detached immutable old snapshots, independent consumers and unchanged source Bars after transforms.
- [FP-RUNTIME-002](../../engineering/failure_patterns/FP-RUNTIME-002-reconnected-does-not-mean-ready.md) and
  [TqSdk #491](https://github.com/shinnytech/tqsdk-python/issues/491): reconnected transport remained waiting for completion.
  Do not equate restored cache or nonempty snapshot with Source/Indicator/Factor/Runtime readiness; test the absence of such capability.
- [FP-STORAGE-001](../../engineering/failure_patterns/FP-STORAGE-001-trading-projection-without-durable-history.md): a current
  projection cannot replace causal history. State records remain component state; missing outer binding/history proof blocks activation.

Reject line-by-line Python translation that copies coercive/non-atomic behavior; folding mutable Runtime state into Domain;
rewriting all MarketData/durable storage to obtain directory symmetry; and adding async/FFI/worker frameworks or new registry
packages before a real consumer. Preserve the existing Construction-before-Cache and external readiness boundaries.
