# P5.3 CN A-share Full Authority Migration and Trading Runtime Cutover

Date: 2026-08-11

Scope: production composition migration only. This change does not rewrite the Durable Trading Kernel, add SIM/LIVE/RESEARCH, or broaden the certified product boundary.

Acceptance status: **NOT YET ACCEPTED**. All executable local semantic, recovery, architecture, type, format, lock, and diff gates pass; the required isolated `uv build --all-packages` gate is externally blocked because the sandbox denied PyPI access and the subsequent network escalation was rejected by the platform usage limit. The status remains fail closed until that exact build succeeds.

## 1. Current production authority audit

Before P5.3, Core still owned Profile registry/version resolution, A-share reference records and lookup, A-share rules, concrete market fee packs, and Runtime concrete-market assembly branches. Market Product contracts existed, but Generic was only a replacement candidate and Trading Runtime did not consume one resolved binding end to end.

## 2. CN A-share Plugin architecture

`onlyalpha-market-cn-ashare` is an independent workspace distribution and `onlyalpha.market_products` provider. It depends downward on Core contracts and contains no Runtime, Broker, DataSource, Risk, Order, Position, Account, Execution, Transaction, Engine, or mutable trading authority.

## 3. A-share Reference ownership migration

Typed exchange, board, security type, source, effective-dated instrument reference, validation error, and deterministic reference authority moved to the plugin. Resolution remains keyed by `InstrumentId + TradingDay`, rejects missing/ambiguous/overlapping records, and never infers board from a symbol prefix. Core's A-share reference implementation and query were deleted.

## 4. A-share Compiler migration

The plugin-owned pure compiler resolves one reference record and emits canonical Core Market IR. It freezes compiler authority identity/fingerprint and has no Runtime-mode or execution-simulation input.

## 5. Session / Price / Quantity / Settlement semantics

The compiler preserves the certified SSE/SZSE sessions, suspension and lifecycle rejection, board/ST price limits, previous-close authority, tick and lot rules, buy/sell quantity rules, position constraints, long/netting shape, and T+1 settlement instruction. Failure ordering remains deterministic and fail closed.

## 6. A-share Market Fee ownership

The A-share production market fee pack, schedule versions, formulas, applicability scope, and official source evidence now live in the plugin. Broker fee contracts remain separate, while Core retains the neutral fee engine, accrual, ledger, reconciliation, and application authorities.

## 7. Product Factory / Binding

The plugin factory validates `plugin_id/product_id/product_version/config`, builds plugin-owned reference/compiler/fee authorities, and returns immutable `OnlyResolvedMarketProductBinding`. Provider identity and economic product identity remain separate; composition identity is derived from effective resolved authorities.

## 8. Config migration

The only Runtime market envelope is now `market.plugin_id`, `product_id`, `product_version`, and `config`. Legacy `profile`, `version`, `overrides`, and `fee_pack` inputs fail closed. Generic config has no A-share field; A-share records are plugin config rather than `reference_data.ashare_*`.

## 9. Reference Resource composition

The resolution context exposes market-neutral calendars/instruments and resource ports only. Generic constructs its own neutral reference authority from Core instruments; A-share constructs its typed authority from plugin config. Core does not introduce a universal concrete reference framework.

## 10. Resolve-exactly-once design

`OnlyClusterComposition.plan()` performs factory lookup and resolution above Runtime planning. The resolved binding travels through Runtime plan/build request into Backtest or Paper. Runtime factories and `OnlyMarketRuleEngine` never resolve or reinterpret a product.

## 11. Runtime Environment migration

Environment equality and grouping carry Market Product provider/product evidence plus effective composition fingerprint. The old `CN_A_SHARE_REFERENCE` versus `GENERIC_REFERENCE` selection and concrete market branches are gone.

## 12. Persistence / Recovery identity migration

Persistence identity records `market_composition_fingerprint`. Rule-engine checkpoint schema v5 records and validates the effective composition fingerprint and canonical policy identity. A mismatch fails closed before recovered execution continues.

## 13. MarketRuleEngine refactor

`OnlyMarketRuleEngine` accepts only the resolved binding, obtains reference and compiler behavior through ports, and emits restricted decisions/instructions from canonical IR. Profile registry/request, Runtime-mode economic identity, matching, slippage, liquidity, latency, and fill planning are absent.

## 14. Backtest cutover

Backtest assembly consumes `RuntimeBuildRequest.market_product` and uses the binding for rules, fees, environment evidence, persistence identity, result evidence, and artifacts. There is no Generic/A-share dispatch inside the Backtest factory.

## 15. Paper cutover

Legacy Paper streaming assembly consumes the same binding path and has no concrete market resolution or branch. This does not upgrade Paper to target SIM or change its read-only observation plus shadow-execution product boundary.

## 16. Legacy production APIs deleted

Deleted production implementations include Core market profiles/registry/conformance, Core A-share rules/reference/query, and Core concrete Generic/A-share/futures/crypto market fee packs. Profile CLI commands and legacy market-config parsing were removed without alias, adapter, wrapper, or fallback.

## 17. Profile framework final disposition

Profile is no longer a production market composition authority. Historical durable/result field names that encode previously committed schema are not used for selection or behavior; their values are populated from product evidence. Session and risk profiles are separate domain concepts and remain unchanged.

## 18. Experimental Futures/Crypto disposition

No production Futures/Crypto Market Product was invented. Their scenario identities are explicit test-only, uninstalled providers and therefore fail closed at factory lookup. They do not block Generic/A-share cutover and receive no implicit Generic fallback.

## 19. Generic runtime semantic regression

Generic T0 preserves its fractional quantity, price/tick, T0 settlement, cash-long/netting, fee, scenario, vertical-slice, and deterministic replay behavior through its plugin-owned binding. A tests-only T+2 product continues to prove the canonical IR has no Generic branch.

## 20. CN A-share semantic regression

Plugin contract tests cover typed config rejection, effective-dated references, no-overlap resolution, session/price/quantity/T+1 compilation, suspension, fees, deterministic identity, and factory mismatch failure. Certified A-share lifecycle conformance covers SSE/SZSE, BUY OPEN, T+1 SELL CLOSE, whole/partial/multi-fill, cancel/reject/expire, and fee accumulation.

## 21. CN_A_SHARE_DURABLE_BACKTEST_V1 result

The finite certified contract remains `CN_A_SHARE_DURABLE_BACKTEST_V1@1`. The sealed semantic oracle and lifecycle assertions pass through the new plugin/binding path. This migration does not claim broad A-share, SIM, LIVE, broker-account, or all-profile readiness.

## 22. Recovery / determinism result

Memory/SQLite economic equivalence, uninterrupted versus multi-instance SQLite forward recovery, checkpoint compatibility, duplicate/ordered projection, result/artifact determinism, and composition-mismatch fail-closed checks are retained. Structural composition fingerprints changed intentionally because the authority graph changed; business economics did not.

## 23. Architecture guards

Static guards enforce: Core imports no concrete Market Product package; concrete plugins do not import Runtime/mutable trading authorities; Core contains no active `OnlyAshare`, `ashare_rules`, legacy Profile authority, or concrete market package import; product IDs and Runtime types are not economic behavior selectors; simulation concepts do not enter canonical Market IR.

## 24. Validation commands/results

- PASS — `uv sync --frozen --all-packages --all-groups`: 74 packages audited.
- PASS — Ruff check: all checks passed.
- PASS — Ruff format check: 1141 files already formatted.
- PASS — Core strict mypy: 496 source files.
- PASS — CN A-share plugin strict mypy: 7 source files.
- PASS — package version synchronization: all distributions at `0.3.6`.
- PASS — `core-full`: 1232 passed, 1 skipped.
- PASS — `ashare`: 24 passed.
- PASS — `recovery`: 306 passed.
- PASS — focused Market Product/plugin/runtime-rule/architecture suite: 63 passed.
- PASS — recovery baseline failure subset after formal regeneration: 11 passed.
- PASS — required Core/static legacy searches: zero matches for all forbidden targets.
- PASS — workflow YAML parsing and `git diff --check`.
- BLOCKED — `uv build --all-packages`: isolated build attempted to resolve `hatchling>=1.26,<2`; sandbox network access was denied. The required escalation was then rejected by the platform usage limit, so no workaround or non-isolated substitute was used.

No remote same-SHA certification is asserted by this report. Acceptance remains fail closed until the exact build command passes.

## 25. Remaining work explicitly belonging to P5.4/P6/P8

P5.4 owns further identity hardening and any new release/certification procedure. P6 owns migration from legacy Paper spelling/infrastructure to full SIM with Virtual Broker and Trading Kernel closure. P8 owns LIVE, real-broker synchronization/reconciliation/recovery, operational readiness, and any corresponding product certification. None is implemented or implied here.

## Required final answers

1. Can `onlyalpha-market-hk-equity` be added with only a new package, Reference, Compiler, Fee, Factory, Entry Point, and tests—without changing Backtest/Paper/Sim factories, Environment, MarketRuleEngine, Execution, Transaction, Position, or Account? **YES**.
2. Does the same `CN_A_SHARE_CASH@2025.1` and Reference Authority produce the same Market Economic Identity in Backtest, Paper/future SIM, and future LIVE? **YES**.
3. After deleting Core concrete A-share Reference, A-share Rules, and Generic/A-share Profile composition, do Generic and A-share Runtime paths still run normally? **YES**.
