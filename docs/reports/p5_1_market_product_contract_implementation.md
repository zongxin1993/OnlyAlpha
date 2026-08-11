# P5.1 Core Market Product Contract Implementation Report

Date: 2026-08-11

## 1. Current architecture facts inspected

The current Trading product still composes `OnlyMarketConfig`, Market Profile Registry, A-share reference, `OnlyMarketRuleCompiler`, Market Fee Pack and Runtime rules inside Core. `OnlyRuntimeEnvironmentBuilder` still projects concrete profile/reference identity, and the current compiler identity still contains legacy Runtime-mode state. Fee Pack is already an immutable, versioned market-fee authority; Settlement Instruction and Core settlement mutation are already separated. ADR 0068 keeps Research outside the Trading authority model.

P5.1 does not replace these current production owners. It establishes the target contract that P5.2/P5.3 will implement and cut over.

## 2. First-principles problem definition

A Trading Runtime needs one deterministic answer for which authorities decide instrument/day reference, market legality, canonical trading policy, settlement semantics and market fees. Strategy, Broker, DataSource, Risk and mutable Runtime managers cannot independently discover or recreate that composition. The missing owner was a Market Product Composition Authority that resolves concrete market knowledge before Runtime trading begins.

## 3. Final ownership model

Configuration selects a plugin and economic product. The explicit Registry selects exactly one Factory. The concrete plugin Factory validates plugin-owned config and resolves effective authorities. The immutable Binding delivers those authorities to Trading Runtime composition. Runtime Core remains the sole owner of mutable Order, Position, Allocation, Account, Ledger, Risk, Reservation, Execution, Fee application and Settlement projection state.

## 4. New Core Market Product contracts

`onlyalpha.market.product` defines:

- typed provider, product and authority identities;
- an immutable canonical transport payload and market-neutral config envelope;
- reference authority and policy compiler ports;
- a minimal composition resource resolver and resolution context;
- the Market Product Factory protocol;
- the resolved Binding;
- a thin Factory Registry;
- fail-closed composition exceptions.

These types are available to external plugins through `onlyalpha.plugin.api`. Internal helpers are not exported merely for convenience.

## 5. Identity model

`OnlyMarketProductPluginId` identifies the provider. `OnlyMarketProductIdentity(product_id, product_version)` identifies the economic product. They are intentionally separate. `OnlyMarketProductCompositionIdentity` captures effective product, reference, policy compiler, fee-pack and effective plugin-config identities. Its SHA-256 fingerprint uses the project canonical serializer extracted from Runtime environment composition into the shared `onlyalpha.canonical` module; no parallel Market Product canonicalizer was added.

Product identity is evidence. Core contains no product-ID behavior dispatch.

## 6. Factory model

`OnlyMarketProductFactory.resolve(config, context)` is the single product-composition entry. The selected plugin owns parsing and validation of its payload, supported product/version checks, authority compatibility and effective-config projection. It returns a binding or raises a typed fail-closed error; `None` is invalid. This Factory is distinct from Runtime Factory and owns no mutable Runtime state.

## 7. Registry model

`OnlyMarketProductFactoryRegistry` registers, requires, enumerates and invokes factories. It performs no config parsing, market compilation, settlement, Runtime construction or market-specific branching. Exact re-registration of the same factory object is idempotent; conflicting registration, unknown provider, invalid/mismatched identity and invalid factory output fail closed. Registration order is not selection policy.

## 8. Resolved Binding model

`OnlyResolvedMarketProductBinding` is frozen and carries provider/product evidence, reference port, pure compiler port, immutable Market Fee Pack and composition identity. Construction re-derives identity from the supplied authorities and rejects conflicts. It exposes no order submission, trade application, position mutation, PnL or general hook API.

## 9. Reference, policy and fee boundaries

The Reference port resolves an opaque product-owned reference snapshot by `Instrument + TradingDay`; Core does not define a universal world-market DTO. The Policy Compiler receives a mode-neutral canonical request and produces `OnlyCompiledMarketPolicy`, a minimal Core IR composed from the existing session/price/quantity/position/short/settlement/margin/liquidity/slippage/matching models. Its identity contains no Runtime mode. The Binding reuses `OnlyMarketFeePack`; the Core Fee Engine and fee application authorities remain unchanged. Plugins compile settlement semantics into canonical policy/instruction, while Core retains settlement mutation authority.

## 10. Research and Trading boundary

Market Product Binding is a Trading dependency for target Backtest, Sim and Live. It is absent from the Research package and from the universal Runtime base contract. Research can continue consuming data, instrument, calendar and reference metadata without loading Broker, Risk, Account, trading fee or durable transaction authorities.

## 11. Dependency direction

The permanent direction is `Concrete Market Plugin -> onlyalpha.market.product Core Contract`. New contract modules import no A-share rule/reference implementation, concrete profile implementation, Runtime implementation or provider SDK. Market Product, Broker and DataSource remain orthogonal plugin dimensions.

Generic T0, CN A-share and a third market can each implement the same Factory, reference and compiler ports; their differences remain behind plugin-owned config and opaque reference resolution. Core consumes the same compiled rule and fee authority forms and therefore needs no `if Generic`, `if A-share` or future-market branch.

## 12. Architecture guards

Static tests enforce:

- no concrete market, concrete plugin or Runtime dependency in the new contract;
- no Runtime-mode or mutable-manager leakage;
- Research does not import the Trading Market Product contract;
- Product ID/version are not Core conditional selectors;
- Binding does not acquire trading-service methods.

AGENTS.md additionally freezes no implicit fallback, no global registration side effect and no compatibility bridge.

## 13. Tests added

Contract tests cover explicit provider resolution, immutable Binding and authorities, deterministic semantic identity, ignored raw field behavior, product/reference/config identity changes, unknown provider, unsupported product/version, invalid config, missing/ambiguous resource, conflicting/invalid registration, idempotent registration and registration-order independence. Existing Backtest product tests are retained unchanged as regression evidence.

## 14. Validation commands and results

Validated in the implementing worktree:

- focused Market Product, architecture-cycle and boundary tests: `17 passed`;
- focused contract plus current synthetic MACD Backtest regression: `33 passed` before the final additional registry test;
- FAST lane: `1076 passed, 1 skipped`;
- CORE-FULL lane after repairing the detected static import cycle: `1206 passed, 1 skipped`;
- Recovery lane: `306 passed`;
- A-share conformance lane: `24 passed`;
- MiniQMT contract lane: `32 passed`;
- Ruff check: passed across `src tests examples packages scripts`;
- Ruff format check: `1135 files already formatted`;
- Mypy: Core `509`, Tushare `15`, MiniQMT `36` source files passed;
- package version synchronization: all packages at `0.3.6`;
- all-package sdist/wheel build: passed for Core, Virtual Broker, Tushare and MiniQMT;
- static concrete-market/runtime dependency search and `git diff --check`: passed.

The first CORE-FULL run rejected a static `contracts <-> binding` import cycle. The boundary was corrected by introducing a one-way `ports` module; the cycle test and complete lane then passed. No test, assertion or business semantic was weakened for acceptance.

## 15. Concrete-market debt intentionally retained for P5.2/P5.3

- `OnlyMarketConfig` still exposes Profile/Fee Pack and Core parser ownership.
- `OnlyReferenceDataConfig` still exposes A-share records and registry.
- Runtime environment and factories still compose Profile/A-share/reference/fee authorities.
- Current `OnlyMarketRuleCompiler` and compiled identity retain legacy Runtime-mode debt.
- Existing Generic and A-share implementations still live in Core.

P5.2 owns Generic T0 plugin plus canonical market IR. P5.3 owns A-share migration, Trading Runtime cutover and deletion of superseded composition. P5.4 owns broader identity hardening and dead API deletion.

## 16. APIs deliberately not added

No universal market framework, DSL, hook graph, universal reference DTO, Market Settlement Manager, Market Risk API, Broker/DataSource coupling, runtime-mode argument, dynamic discovery, hot reload, marketplace, compatibility adapter, deprecated alias, implicit Generic fallback or import-string constructor was added.

## 17. Remaining risks before P5.2

P5.2 must prove that the existing Generic policy can be expressed through the fixed opaque-reference/compiler/fee binding and mode-neutral compiled policy without widening Core. It must implement and cut over Generic semantics while preserving current `OnlyMarketRuleEngine` behavior and Settlement Instructions. Runtime composition must not adopt the Binding until a concrete product replacement is authoritative, and it must never retain old/new fallback logic after cutover.
