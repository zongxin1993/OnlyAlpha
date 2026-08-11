# P5 Market Product Composition Final Certification

Date: 2026-08-11

## Certification record

| Field | Value |
|---|---|
| Stage | P5 — Market Product Composition Authority Neutralization |
| Implementation baselines | P5.1 `68cd48c4f929090fc9ebc04fb67fd9e2f6829365`; P5.2 `7e76ac1c485cdc31ded5471280555322aa967493`; P5.3 `d25247a5f9692a7b6751118fabeaa55c03c4b2ac`; P5.4 `6682d36860ed2d06c14869d0f3c778c01d8ca8f4` |
| Release-graph closure | `e67bb4eedcdcd953c18713d6babbc8a1051fe637` |
| Certification candidate | The final commit containing this report and the P6 roadmap transition |
| Required remote evidence | `Layered Quality`: `static`, `build`, `core-full`, `recovery`, `ashare`, `miniqmt-contract`, and `quality-gate` all successful on that exact candidate SHA |
| Verdict | **P5 DONE / CERTIFIED**, effective only after the required same-SHA remote evidence succeeds; until then **REMOTE CERTIFICATION PENDING** |
| Next stage | P6 — Sim Streaming Runtime Closure |

This is a final audit report, not a new architecture decision. It does not rewrite the historical P5.3 report: that report's
`NOT YET ACCEPTED` state was correct when its isolated build was externally blocked. Later evidence closes that gap without
claiming that it had already passed at the earlier point in time.

## 1. P5 scope

P5 replaced concrete market composition inside Core with one market-neutral Trading-plane contract and one immutable,
resolve-once binding path. It moved Generic T0 and CN A-share market knowledge into concrete plugins while preserving Core as
the sole mutable owner of Risk, Order, Position, Allocation, Account, Ledger, Fee application, Settlement, durable transaction,
projection, checkpoint, and recovery state.

P5 did not implement SIM, RESEARCH, LIVE, real Broker synchronization, streaming recovery, or a broader A-share product. It did
not change Trading economics.

## 2. P5.1 — Core Market Product Contract

P5.1 established the accepted ADR 0069 contract:

```text
OnlyMarketProductConfig
-> OnlyMarketProductFactoryRegistry
-> OnlyMarketProductFactory.resolve(...)
-> OnlyResolvedMarketProductBinding
-> Trading Runtime composition
```

Provider identity and economic product identity are distinct. The explicit registry performs exact fail-closed lookup; the
factory owns concrete config/reference/compiler/fee resolution; the immutable binding carries effective authority evidence.
Core retains all mutable Trading authorities, and Research does not load this Trading composition for structural symmetry.

## 3. P5.2 — Generic T0 and Canonical Market IR

P5.2 reduced `OnlyCompiledMarketPolicy` to canonical market economics: instrument terms, session, price, quantity, position,
short, settlement, and margin. Matching, slippage, latency, fill planning, and simulation liquidity remain Virtual Broker
authorities and are absent from Market Product identity.

`onlyalpha-market-generic-t0-cash` owns `GENERIC_T0_CASH@1` reference, pure compiler, Market Fee Pack, and entry-point factory.
It preserves Generic T0 Cash-Long behavior without a Core Generic branch. A tests-only T+2 market proves the fixed Core IR is
not a Generic-specific framework.

## 4. P5.3 — CN A-share migration and Runtime cutover

P5.3 moved typed effective-dated A-share Reference, SSE/SZSE policy compilation, and production Market Fee Pack into
`onlyalpha-market-cn-ashare`. Generic and CN A-share both use the same binding path. Cluster composition resolves a product
exactly once before Runtime build; Backtest and legacy Paper consume the resolved binding without re-resolution or concrete
market dispatch.

Core Profile registry, Core A-share rules/reference, concrete fee-pack selection, legacy market config, and Runtime
Generic/A-share branches were removed without alias, adapter, wrapper, or implicit fallback. Environment, persistence,
checkpoint, Result, and Artifact evidence carry the effective composition identity/fingerprint.

## 5. P5.4 — Strict identity and recovery identity

P5.4 replaced permissive/magic authority serialization with the single strict formal identity entry point. Composition identity
is created only by `OnlyResolvedMarketProductBinding` from effective product, reference, compiler, fee, and config authorities.
Product IDs are evidence, never Core behavior selectors; Runtime type vocabulary is absent from market economic identity
sources.

Checkpoint and recovery bind the effective market-composition fingerprint. Product version, reference semantics, compiler,
fee pack, or effective config mismatch fails before any mutable authority restore. Recovery never silently accepts a different
market composition.

## 6. Final authority map

| Concern | Final authority |
|---|---|
| Workspace distribution membership | root `[tool.uv.workspace].members` |
| Release version | root `project.version` |
| Internal release dependency edge | exact `==root project.version`, validated by `scripts/version_sync.py` |
| Market Product provider lookup | `OnlyMarketProductFactoryRegistry` |
| Concrete market config/reference/compiler/Market Fee definition | selected concrete Market Product plugin |
| Effective market composition identity | immutable `OnlyResolvedMarketProductBinding` |
| Pre-trade market legality/instruction | `OnlyMarketRuleEngine` consuming the resolved binding |
| Mutable trading state and economics | Core Trading Runtime authorities |
| Durable trade truth | Runtime Transaction Store |
| Recovery composition compatibility | persisted effective composition fingerprint checked before restore |

No second formal package registry remains. Future exact members added to root workspace metadata enter the release graph without a
package-name-specific code change.

## 7. Final architecture invariants

- Concrete Market Product plugins depend on Core contracts; Core imports neither concrete package.
- Registry lookup is explicit; unknown, duplicate, mismatch, and ambiguous resolution fail closed.
- Binding is immutable and contains no mutable Trading manager or service hook.
- Product identity participates in evidence/fingerprint/compatibility, not behavior dispatch or execution permission.
- Runtime type does not participate in market economic identity.
- Canonical Market IR contains no execution-simulation authority.
- No implicit Generic fallback or Core hard registration exists.
- Backtest and legacy Paper consume the same resolved market binding; this does not certify Paper or implement SIM.
- Recovery validates the effective composition before mutable restore.
- Release graph membership has one authority, and internal pins use Python packaging semantics.

## 8. Core concrete-market leakage result

`test_market_product_core_contract_has_no_concrete_market_or_runtime_dependency`,
`test_core_does_not_import_concrete_market_product_plugins`, and
`test_retired_core_market_authorities_have_zero_active_implementation` pass. Core has no active concrete Generic/CN A-share
plugin import, A-share rules/reference authority, or Profile production registry.

## 9. Product-ID behavioral dispatch result

`test_product_identity_is_not_a_core_behavior_selector` passes. Static AST inspection finds no Core `if` or `match` decision on
`product_id`/`product_version`. Product identity remains evidence only.

## 10. Runtime-mode economic identity result

`test_market_economic_identity_sources_have_no_runtime_mode_vocabulary` passes across Core Market Product contracts and both
concrete plugins. `OnlyRuntimeMode`, `runtime_type`, `BACKTEST`, `PAPER`, `SIM`, and `LIVE` do not define market economics.

## 11. Generic fallback result

There is no missing-plugin or unknown-product fallback to Generic. Unsupported test Futures/Crypto identities remain explicit
uninstalled providers and fail at registry lookup. P5 added no alias, compatibility bridge, or Core hard registration.

## 12. Recovery composition validation

`tests/runtime/recovery/test_market_composition_pre_restore.py` proves that changed product version, reference semantics,
compiler version, Market Fee Pack version, or effective config fails with
`CHECKPOINT_MARKET_COMPOSITION_FINGERPRINT_MISMATCH` before a mutable participant restore. Provider/environment mismatch fails
at the separate configuration fingerprint boundary. The complete recovery lane passes unchanged.

## 13. Generic T0 regression

The formal `core-full` lane retains Generic fractional quantity, tick/price, T0 settlement, Cash-Long/Netting, fee, scenario,
vertical-slice, deterministic replay, plugin discovery, and tests-only third-market coverage through the production binding.
No Generic-specific Runtime or MarketRuleEngine branch was reintroduced.

## 14. `CN_A_SHARE_DURABLE_BACKTEST_V1`

The previously certified finite contract remains certified through the plugin/binding cutover. The `ashare` lane covers its
sealed XSHG/XSHE ordinary CNY Cash-Long surface, BUY OPEN, same-day SELL rejection, durable T+1 maturity, SELL CLOSE,
Whole/Partial/Multi-Fill, cumulative minimum commission, durable Reject/Expire/Cancel, Memory/SQLite equivalence, A-to-B-to-C
forward recovery, and deterministic Result/Artifact.

This does not certify every A-share instrument/regime, `CN_A_SHARE_CASH@2026.07`, ETFs, BSE, Margin, Short, Paper, SIM, LIVE, or
real Broker operation. The full finite boundary remains in
`docs/reports/p4_3_cn_a_share_production_durable_product_conformance.md`.

## 15. Release dependency graph closure

The `0.3.7` provider distributions initially contained stale internal edges to
`onlyalpha-market-cn-ashare==0.3.6`. The former script manually listed formal packages and recognized only `onlyalpha` with
string-prefix matching, so CI checked node versions but not the full distribution graph.

The closure removes `FORMAL_PACKAGES`, derives root plus every formal member from root workspace metadata, canonicalizes
distribution identity, parses requirements and versions with `packaging`, and validates both `project.dependencies` and every
`project.optional-dependencies` group. An internal direct URL, range, missing pin, stale pin, duplicate canonical name, missing
member project, invalid requirement/name/version, or stale fixture reference fails closed with a locating diagnostic.
`dependency-groups` remain outside the release graph. `set VERSION` rewrites every formal node and internal edge plus README and
fixture references, preserves external requirements/extras/markers, runs `uv lock --python 3.12`, and performs the complete
graph check.

Both stale provider edges are now `==0.3.7`. PyPI returned 404 for both exact provider `0.3.7` release endpoints before the fix,
so the repository correctly repaired the unpublished current version rather than attempting to replace a published artifact or
creating an unnecessary `0.3.8` release. `uv.lock` was regenerated and required no textual change.

## 16. Local validation results

All commands ran from the release candidate worktree without skipped/xfail/relaxed assertions, retries, sleeps, reduced
coverage, altered worker policy, or changed Trading semantics.

| Gate | Result |
|---|---|
| `uv sync --frozen --all-packages --all-groups` | PASS |
| `uv run pytest tests/tools/test_version_sync.py -q` | PASS, 19 passed |
| `uv run python scripts/version_sync.py check` | PASS, workspace graph consistent at `0.3.7` |
| `uv lock --check --python 3.12` | PASS, 78 packages resolved |
| Ruff check | PASS |
| Ruff format check | PASS, 1145 files |
| Core strict mypy | PASS, 497 source files |
| Generic Market Product strict mypy | PASS, 6 source files |
| CN A-share Market Product strict mypy | PASS, 7 source files |
| Tushare provider strict mypy | PASS, 15 source files |
| MiniQMT provider strict mypy | PASS, 36 source files |
| `core-full` | PASS, 1271 passed / 1 skipped |
| `recovery` | PASS, 312 passed |
| `ashare` | PASS, 24 passed |
| `miniqmt-contract` | PASS, 32 passed |
| `uv build --all-packages` | PASS, 6 sdists and 6 wheels at `0.3.7` |
| stale `onlyalpha-market-cn-ashare==0.3.6` search | PASS, zero active matches |
| `git diff --check` | PASS |

The first sandboxed sync and final isolated-build attempts failed only because DNS access to PyPI was unavailable. The exact
commands then passed in the approved network environment; no test retry or acceptance workaround was used. Existing
performance-budget diagnostics remained warnings and were not changed.

## 17. Same-SHA GitHub quality result and final verdict

The only remote certification authority is the existing `Layered Quality` workflow. This report deliberately does not inherit a
green run from any earlier P5 implementation commit. The certification candidate is the final commit containing this report and
the roadmap transition. Its workflow head SHA must equal that exact commit, and `static`, `build`, `core-full`, `recovery`,
`ashare`, `miniqmt-contract`, and `quality-gate` must all finish successfully.

Therefore the verdict is fail closed:

```text
before matching workflow success:
P5 IMPLEMENTATION COMPLETE / REMOTE CERTIFICATION PENDING

after matching workflow success:
P5 DONE / CERTIFIED
```

No local result can activate the second state. The final implementation report must record the actual candidate SHA, workflow
run, and job results.

## 18. Next stage

The current stage is P6 — Sim Streaming Runtime Closure. This P0 closure did not add `OnlyRuntimeMode.SIM`, a Sim Runtime or
Factory, Virtual Broker SIM wiring, streaming checkpoint/reconnect/gap recovery, or PAPER/SHADOW deletion. Those remain P6 work.

Required final answers:

1. Will a future `onlyalpha-market-hk-equity` exact member be discovered without changing `FORMAL_PACKAGES`? **YES**.
2. Will CI reject a future formal plugin edge pinned to an old formal market-package version? **YES**.
3. Are external requirements such as pandas, tushare, xtquant, and tzdata untouched by internal graph rewrite? **YES**.
4. Did this closure implement SIM? **NO**.
