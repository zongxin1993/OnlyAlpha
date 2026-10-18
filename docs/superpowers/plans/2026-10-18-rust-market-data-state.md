# Rust Market Data State Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan inline in the current session. Use one bounded independent correctness/simplicity review after initial validation. Checkboxes are planned actions, not a repository progress ledger; keep execution notes only under ignored `test-results/`.

**Goal:** Build the complete isolated Rust行情状态 module: atomic closed-Bar state, immutable scoped snapshots and strict atomic checkpoint replacement.

**Architecture:** One non-Clone mutable owner stages a whole batch and validated Runtime snapshot before committing. Immutable shared series support queries and Cluster restriction. The sole local edge is State -> Domain; durable source history and Runtime orchestration remain outside.

**Tech Stack:** Pinned Rust 1.99.1, std collections/Arc, `onlyalpha-domain`, `num-bigint = 0.4.8`, `serde_json = 1.0.154`, the sole frozen-source Linux dev verification service.

**Spec:** [Owner-approved Market Data State design](../specs/2026-10-18-rust-market-data-state-design.md). The Constitution, owning MarketData Contract and Accepted ADRs remain normative.

## Global constraints

- Keep release `0.10.10`; no Python production restructure, Runtime activation, official reader replacement, history migration/deletion, push or Release.
- Create only `crates/onlyalpha-kernel/market_data/state/`, package `onlyalpha-market-data-state`; no service or per-Python-file crates.
- The only local dependency is Domain. Clock/Event/Predicate/Runtime/application/storage/plugins are excluded from the independent closure; reverse/undeclared edges fail.
- Reuse exact admitted `num-bigint` with `default-features=false, features=["std"]`; `serde_json` with `default-features=false, features=["std","arbitrary_precision"]`. Add no registry nodes; retain reviewed 40-node registry digest `5b640f52cbcb0afc623fd1755692efee625a444ec9dbd17e0869eafba4f6a03f`.
- Scope, primary, initialization time and quality flags are explicit inputs; versions/nanoseconds are exact integers. No OS time, randomness, f64 evaluation, implicit primary choice or calculation dependency.
- Default history_limit is 1024 and must be positive. It bounds each type's retained history; do not claim a global byte/type-count bound.
- Closed, unrevised Bars only; no partial producer, gap fill, correction, silent deduplication, version coercion, legacy fallback or compatibility alias.
- Schema 2 is the selected language-neutral cache/snapshot record. Existing Python Runtime `market-data.cache` schema-1 registration/history/artifacts remain unchanged and are not admitted to the new reader.
- All formal local checks use `scripts/dev_verification.py`, frozen source, the unique `onlyalpha-dev` topology, serial Cargo/pytest workers and retained `test-results/` logs. Rebuild fixed dev tools only for environment-input changes, not ordinary source edits.
- Independent expected vectors define correctness. Classify Python reference deviations instead of changing expected results or claiming unsupported complete parity.
- Constitution impact NO. Stop on genuine higher-level conflict; never amend the Constitution or relax required behavior to obtain PASS.

## Review focus

1. A valid first Bar followed by an invalid second type must leave all histories/versions unchanged, including snapshot-construction failure (Task 1).
2. Historical Bar acquisition init may follow a Backtest logical snapshot init; compare snapshot init to event time, not ingestion time (Tasks 1/3).
3. A Cluster selecting an unmaterialized secondary type gets a local miss, while an out-of-view type gets denial; narrowing cannot recover parent/sibling data (Task 2).
4. A malformed late checkpoint entry or a complete different owner/config must not partially replace a populated state (Task 3).
5. Cache records/available snapshots must not imply Source/Construction/Generation proof, durable historical absence or Indicator/Strategy readiness (Tasks 2/4).

## File and fixture conventions

All short `module/` paths below mean `crates/onlyalpha-kernel/market_data/state/`. Create private `src/{model,state,snapshot,record}.rs` and public reexports in `src/lib.rs` only as their task consumes them.

Rust `tests/support/mod.rs` supplies explicit deterministic fixtures:
`scope(engine:&str,runtime:&str)`, `state(limit:usize)`, `stamp(minute:u32)->OnlyTimestamp`,
`bar(instrument:&str,window:u32,end_minute:u32)->Arc<OnlyBar>`. Here minute is an offset from
`2026-01-05T01:30:00Z`, `window <= end_minute <= 10`; Bar interval length is window minutes, event/init equal end,
revision 0, closed true, RAW/CONTINUOUS, day `2026-01-05`, OHLC `10.00/10.10/9.90/10.05` precision 2,
volume `100` precision 0 and trade_count 1. A1/A3 mean `600000.XSHG` windows 1/3; B1 means `BTCUSD.TEST` window 1.
Build these with current Domain readers from explicit records; do not add direct Jiff or financial/time reimplementations.
Tests may alter valid Domain record inputs before construction for permitted broader Domain facts such as revisions or acquisition time.

## Task 1: Atomic state admission and immutable Runtime snapshots

**Files:** create `module/Cargo.toml`, `module/src/{lib,model,state,snapshot}.rs`, `module/tests/{state,atomic}.rs`,
`module/tests/support/mod.rs`; modify root Cargo manifest/lock, `scripts/{rust_kernel_check,version_sync}.py` and their existing tool fixtures.

**Interfaces:**
- `OnlyMarketDataStateScope::new(OnlyEngineId, OnlyRuntimeId) -> Self`; private IDs with immutable `engine_id/runtime_id` accessors.
- `OnlyMarketDataStateConfig { history_limit: usize }`, default 1024.
- `OnlyMarketDataStateError`: Configuration, Validation(String), Sequence, Scope, MissingData, Time, Record(String); no success for missing/malformed mandatory proof.
- `OnlyMarketDataState::new(scope,config) -> Result<Self,OnlyMarketDataStateError>`; non-Clone, private state, mutation requires `&mut self`.
- `apply_closed(&mut self,bars:&[Arc<OnlyBar>],primary:&OnlyBarType,ts_init:OnlyTimestamp,quality_flags:Vec<String>) -> Result<OnlyMarketDataSnapshot,OnlyMarketDataStateError>`.
- Owner `scope()->&OnlyMarketDataStateScope`, `history_limit()->usize`, `latest_closed(&OnlyBarType)->Option<&OnlyBar>`,
  `history(&OnlyBarType,usize)->Result<Vec<Arc<OnlyBar>>,OnlyMarketDataStateError>`, `version(&OnlyBarType)->BigUint`,
  `bar_types()->Vec<OnlyBarType>`, `current_partial(&OnlyBarType)->Option<&OnlyBar>` (always None).
- Immutable `OnlyMarketDataSeriesSnapshot` has `bar_type()->&OnlyBarType`, `version()->&BigUint`, `history()->&VecDeque<Arc<OnlyBar>>`, `latest()->&OnlyBar`; fields/constructors stay private.
- Snapshot core: `scope`, optional `cluster_id`, exact `ts_event/ts_init`, `primary_bar_type`, derived `primary_bar`, ordered `quality_flags`, and immutable shared series. Task 2 finishes its filtered query API.

- [ ] Write `state_defaults_and_local_misses`: limit 0 -> Configuration; default limit 1024; empty state's version 0/latest None/history empty, count 0 -> Configuration. No partial value exists.
- [ ] Write `bounded_history_keeps_exact_lifetime_version`: limit 2, apply A1 ends 1,2,3; retained ends `[2,3]`, version `3`, latest end 3. A snapshot saved after end 1 still has end/version 1; original Arc Bar content remains unchanged.
- [ ] Write `failed_batch_or_snapshot_is_not_a_prefix_commit`: start with A1 end 3 and A3 end 3. Apply valid A1 end 4 followed by duplicate A3 end 3; Sequence and both prior values/versions remain. Repeat with missing primary, empty batch, duplicate type, nonclosed/revised input and initialization `event - 1ns`; every rejection preserves the same detached baseline.
- [ ] Write `logical_init_and_multinstrument_anchor`: a Bar acquired on `2026-10-01` may enter a Jan-5 logical snapshot initialized `event + 17ns`. Runtime state may retain A1 and B1. An earlier primary exposing an already-retained future B1 rejects atomically; a valid later anchor preserves both instruments.
- [ ] Observe missing-package/interface/behavior RED through the dev entry before implementing. Introduce only the minimum package/manifest needed to make the selected test failure meaningful; no production code before plan approval.
- [ ] Implement in `model.rs/state.rs/snapshot.rs`: validate batch and primary, exact event/init/order rules, stage affected VecDeque histories and BigUint versions, trim only accepted updates, build the full immutable Runtime snapshot, then replace the owner once. Do not expose a successful prefix, independent mutable latest map or partially initialized snapshot.
- [ ] Admit the fifth local package in Cargo, `validate_workspace`, exact dependency checks, version graph and fake-manifest tests. Keep lower-module reverse-edge rejection and all existing registry protections. Add no public reexport of mutable state from Domain.
- [ ] Rebuild/prepare the fixed dev image once if manifest/lock admission requires it. Run package tests via `python scripts/dev_verification.py run -- cargo test -p onlyalpha-market-data-state --frozen --offline -j1 --test state --test atomic -- --test-threads=1`, using the admitted writable Cargo cache environment as existing Rust checks do. Run affected version/manifest tests; expected exit 0.
- [ ] Commit this independently tested deliverable locally; do not push or change release metadata.

## Task 2: Complete immutable query and Cluster visibility behavior

**Files:** extend `module/src/snapshot.rs` and `model.rs` only for consumed types; create `module/tests/{snapshots,capabilities}.rs`; extend support fixtures.

**Consumes:** Task 1's owner, scope, immutable series and successful apply snapshots.

**Produces:** `OnlyMarketDataSnapshot` immutable methods:
- `scope()->&OnlyMarketDataStateScope`, `cluster_id()->Option<&OnlyClusterId>`, `ts_event/ts_init()->&OnlyTimestamp`,
  `primary_bar_type()->&OnlyBarType`, `primary_bar()->&OnlyBar`, `quality_flags()->&[String]`.
- `visible_bar_types/updated_bar_types()->Vec<OnlyBarType>`, `series()->Vec<Arc<OnlyMarketDataSeriesSnapshot>>` in canonical BarType order.
- `latest_closed(&OnlyBarType)->Result<Option<&OnlyBar>,OnlyMarketDataStateError>`, `require_latest_closed/require_same_event_time(&OnlyBarType)->Result<&OnlyBar,OnlyMarketDataStateError>`.
- `history(&OnlyBarType,usize)->Result<Vec<Arc<OnlyBar>>,OnlyMarketDataStateError>`, `version(&OnlyBarType)->Result<BigUint,OnlyMarketDataStateError>`, `was_updated(&OnlyBarType)->Result<bool,OnlyMarketDataStateError>`, `current_partial(&OnlyBarType)->Result<Option<&OnlyBar>,OnlyMarketDataStateError>` (None after scope check).
- `restrict(&self,cluster_id:OnlyClusterId,allowed:&[OnlyBarType],primary:&OnlyBarType)->Result<Self,OnlyMarketDataStateError>`.
- Primary instrument/day/session metadata is available through the primary Domain Bar's own getters; add no direct calendar-library edge or duplicate stored metadata merely to mirror Python accessors.

- [ ] Write `query_scope_is_distinct_from_local_miss`: a Runtime snapshot with A1 may derive a Cluster view allowing A1/A3 with primary A1; absent A3 returns None/empty/0/false. B1 and any unselected type return Scope, including current_partial and was_updated. Required A3 returns MissingData; count 0 returns Configuration; same-event-time on a retained older secondary returns Time.
- [ ] Write `restrict_never_widens_or_changes_owner`: reject empty/duplicate/mixed-instrument allowed sets, primary outside allowed, absent primary or wrong-time primary. A Cluster view can only narrow for its original Cluster; widening or sibling Cluster returns Scope, and Engine/Runtime never changes. Sibling views from the original Runtime value remain independent.
- [ ] Write `snapshot_survives_updates_without_alias`: old views and original Bars remain equal after later owner operations; returned vectors/maps cannot change later queries. Successful views expose only selected series through every enumeration/query path. Task 3 adds the record-path assertion after serialization exists.
- [ ] Add compile-fail doctests forbidding mutation of private owner/series/snapshot fields and obtaining a mutable owner through a snapshot. A compile assertion requires immutable Snapshot `Send + Sync`; another compile-fail case rejects a fabricated Snapshot `.is_ready()` trading-readiness capability. No worker/lock/unsafe marker is added just for these tests.
- [ ] Run these tests to RED through dev, then implement methods in `snapshot.rs` with one validation/filtering path. Runtime-root restriction may include an unmaterialized same-instrument secondary; only already-restricted Cluster views must be subsets of their parent visible set.
- [ ] Run `cargo test -p onlyalpha-market-data-state --frozen --offline -j1 -- --test-threads=1` in the dev entry, including Task 1 and doctests; expected all PASS. Commit locally.

## Task 3: Strict schema-2 records and atomic checkpoint replacement

**Files:** create `module/src/record.rs`, `module/tests/{records,recovery}.rs`; extend prior private constructors/validation only as required.

**Interfaces:**
- Owner `capture_checkpoint(&self)->serde_json::Value`, `restore_checkpoint(&mut self,&serde_json::Value)->Result<(),OnlyMarketDataStateError>`.
- Snapshot `to_record(&self)->Value`, `from_record(&Value)->Result<Self,OnlyMarketDataStateError>`, `to_json()->Result<String,OnlyMarketDataStateError>`, `from_json(&str)->Result<Self,OnlyMarketDataStateError>`.
- Record parsing rejects malformed shape/types as Record; receiver owner mismatch is Scope; a valid but different history_limit is Configuration. Record/schema defects are never None/zero/empty-success. No Python reader change or legacy decoder is produced.

- [ ] Write `current_records_preserve_exact_fields`: checkpoint fields exactly `schema_version,engine_id,runtime_id,history_limit,series`; series exactly `bar_type,version,history`. Snapshot fields exactly `schema_version,engine_id,runtime_id,cluster_id,ts_event_ns,ts_init_ns,primary_bar_type,visible_bar_types,updated_bar_types,series,quality_flags`, as spec. Round-trip exact times, Bars, scope, visible-but-missing A3, versions and ordered quality flags.
- [ ] Write `large_versions_restore_and_increment_without_loss`: seed a valid one-Bar series with version `18446744073709551616`; restore into matching limit/scope, apply the next Bar, expect `18446744073709551617`. Serialize integer tokens and separately test a primary Bar ending at `-1000ns` (1969-12-31T23:59:59.999999Z) with snapshot init `-999ns`, using exact Domain values; do not evaluate floats or infer snapshot logical time from historical acquisition init.
- [ ] Write `late_restore_failure_preserves_populated_state`: start with nonempty A1/A3. Mutate the final nested BarType, history order/closed/revision, bool/string/fraction/negative version, version below retained length, oversized history or duplicate series. Each failure leaves every old value/version intact. Test a complete different valid owner and valid different limit separately; do not silently rebind, trim or union.
- [ ] Write `restore_replaces_and_replay_matches_fresh`: empty/populated records restore deterministically, repeated restore is identical, old-only types disappear, subsequent ordered operations produce the same state/snapshots as an independently specified uninterrupted sequence. Saved old snapshots remain unchanged. Do not label this real service restart/upgrade evidence.
- [ ] Write `snapshot_reader_revalidates_relations`: reject schema 1/unknown schema, missing/extra fields, duplicate visible/updated/series entries, wrong record family, primary absent/outside view, wrong nested type, future data, init before event and inconsistent version/history. Accept harmless map-like row reordering and emit canonical order; never sort history to hide bad chronology. Cluster record output excludes every unselected row and all indicator/partial/duplicate primary truth.
- [ ] Observe RED through dev before implementing strict record helpers. Reuse Domain `OnlyDomainModel` and exact serde_json integer tokens; validate a temporary complete state and receiver constraints, then perform one replacement. Reuse the same series invariants for newly applied and restored state.
- [ ] Run all module tests plus affected manifest/version/consumer tests in dev, then module `--release`; expected PASS, same exact semantic outcomes in debug/release. Commit locally.

## Task 4: Independent conformance, enforced isolation and final review

**Files:** create `test-data/market-data-state/{README.md,operations-v1.jsonl,records-v2.jsonl}`, `module/tests/conformance.rs`,
`tests/market_data/test_rust_market_data_state_vectors.py`, `tests/tools/test_rust_market_data_state_boundary.py`;
modify `scripts/rust_kernel_check.py`, affected existing tool fixtures, `docs/{market_data_pipeline,rust-kernel-development,rust-kernel-migration-work-program}.md`, `test-data/README.md`.

**Interfaces:**
- `validate_market_data_state_sources(root:Path)->None` rejects undeclared native/hidden inputs using the existing guard pattern; allow only the two explicitly named new corpus `include_str!` paths in tests.
- `isolated_market_data_state(root:Path,destination:Path)->Path` materializes Domain plus State, excludes the rest, and selects package `onlyalpha-market-data-state`.
- Existing `_isolated_modules` must map directory suffix underscores to package/data suffix hyphens when deriving local names: directory `market_data_state`, package `onlyalpha-market-data-state`, corpus `test-data/market-data-state`. Domain/Clock/Event behavior remains unchanged. This is internal naming, not an identity alias/compatibility reader.

- [ ] Hand-author common operation vectors for empty/query/retention, single/multi-type updates, exact counters, normal valid restore/replay and snapshot filtering; write independent full schema-2 expected records. Include separate corrected adversarial cases and document Python deviations. Neither implementation generates the other's expected data.
- [ ] Implement Python/Rust common consumers using the existing public objects and explicit inputs. Compare exact Bar identities/values, histories, counters and available snapshot fields. Do not invent Python Engine binding, schema-2 support, atomic restore or visibility enforcement; do not strip real fields and call the result whole-module parity. No production shim is added.
- [ ] Write negative guard tests for reverse/local edges, dependency alias/features/build scripts, hidden include/path/cfg_attr/env inputs, OS time/random/thread/network/filesystem effects and production calculation imports. Add positive cases for allowed compile-fail documentation and named fixture includes. Observe RED, then extend the guard and invoke it in the canonical Rust lane.
- [ ] Write isolated extraction assertions: exact members Domain+State, exact local lock nodes, corpus paths present, and no Clock/Event/Predicate/Runtime/Python/plugin tree. Implement the naming adjustment and `isolated_market_data_state`, retaining all existing Domain/Clock/Event isolation and registry tests.
- [ ] Update only the owning Contract's Rust construction/schema/history boundary and module correspondence/navigation. Preserve the current Python registration and state the new library's unadmitted boundary explicitly. Submit no PASS/status/audit ledger, no duplicate Authority and no speculative follow-on framework.
- [ ] Run initial affected baseline: all State tests/doctests, `tests/market_data/test_rust_market_data_state_vectors.py`, the three audited consumers `test_pipeline_dispatch.py`, `test_construction_runtime.py`, `test_realtime_trade_state.py`, boundary/manifest/version tools, affected Ruff check/format and mypy. Run bounded simplicity review, APPLY actual simplifications or explain essential constraints in session only.
- [ ] Complete one independent correctness/simplicity review over this diff and direct impact. Re-derive owner/state/identity/version/time/visibility/recovery relations; fix scoped Critical/High with deterministic regressions and rerun affected checks. Do not expand to an ecosystem/all-repo cleanup or confuse Python reference findings with accepted Rust behavior.
- [ ] With source stable, run `python scripts/dev_verification.py run -- uv run python scripts/test_suite.py rust-kernel`. Expected `RUST_KERNEL_OFFLINE_DEBUG_RELEASE: PASS`, all five workspace packages and independent Domain/Clock/Event/State debug/release closures, exact frozen-source agreement. Keep serial execution/logs; do not rerun unrelated suites without a new reason.
- [ ] Verify Constitution fingerprint, unchanged release 0.10.10 and clean scoped diff; retain formal receipts. Leave the implementation local for Owner manual review. No Runtime admission, production data change, push, bump or Release follows from module acceptance.

## Execution handoff

Recommended method: inline implementation in this session, then one bounded independent final review. Tasks share the same state/snapshot/record invariants; per-task implementation agents would repeat context without isolating independent work.
The Owner reviews this written plan before implementation. Subsequent execution notes and test evidence remain ignored local artifacts; the plan is not checked off into a repository progress registry.
