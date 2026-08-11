# P5.2 Generic T0 Cash Market Product Implementation Report

- Date: 2026-08-11
- Implementation baseline: `68cd48c4f929090fc9ebc04fb67fd9e2f6829365`
- Scope: Generic T0 replacement candidate and Canonical Market IR authority closure
- Runtime cutover: intentionally not performed

## 1. Current implementation audited

The audit covered the P5.1 Market Product contract, legacy Generic Profile/compiler/fee pack, plugin discovery and composition registries, Runtime assembly, Settlement and Fee boundaries, and the Virtual Broker package.

The current production authority remains the legacy chain:

```text
Market Config
→ Profile Registry / Version Resolver
→ Instrument Reference
→ Legacy Rule Compiler
→ Runtime Rule Engine
```

The Trading Runtime owns mutable Order, Position, Account, Reservation, Fee application, Settlement projection and durable execution state. The Transaction Store remains the durable trade authority. P5.2 changes none of those authorities or their recovery equivalence.

## 2. Canonical Market IR authority problems found

P5.1's new `OnlyCompiledMarketPolicy` copied `liquidity_policy`, `slippage_policy` and `matching_policy` from the legacy Profile model. Those values answer how a simulated Broker fills an order; they are not market economic rules. Leaving them in the target IR would duplicate Virtual Broker authority and make product semantics depend on an execution driver.

The new IR also lacked a minimal standard projection of opaque reference facts needed by Core after concrete references move into plugins.

## 3. Market vs Virtual Broker boundary corrections

The corrected ownership is:

| Authority | Owner |
|---|---|
| Instrument lifecycle interpretation, sessions, price/quantity legality, position/short/margin regime, settlement policy, Market Fee definition | Market Product |
| Matching, slippage, latency, fill plan/schedule, simulated bar liquidity | Virtual Broker / Execution Simulation |
| Order, Position, Account, Risk, Reservation, Fee application, Settlement execution and recovery | Core Trading Runtime |
| Broker commission | Broker Fee Contract |

No Virtual Broker algorithm was changed. Its matching/slippage/liquidity behavior remains independent and can be replaced by a real Broker without changing `GENERIC_T0_CASH@1`.

## 4. Final Canonical Market IR

`OnlyCompiledMarketPolicy` now contains:

```text
identity
instrument_terms
session_policy
price_policy
quantity_policy
position_policy
short_policy
settlement_policy
margin_policy
```

`OnlyCompiledInstrumentMarketTerms` contains only settlement currency, contract multiplier and canonical trading status. `OnlyInstrumentTradingStatus` normalizes concrete lifecycle data to `TRADABLE`, `SUSPENDED` or `INACTIVE`. Concrete Reference remains opaque to Core; no universal market reference DTO was introduced.

The removed simulation fields are not optional, deprecated or aliased. Policy fingerprints now cover only canonical market economics.

## 5. Generic T0 package structure

The new formal distribution is:

```text
packages/market/onlyalpha-market-generic-t0-cash/
├── pyproject.toml
├── README.md
├── src/onlyalpha_market_generic_t0_cash/
│   ├── config.py
│   ├── reference.py
│   ├── compiler.py
│   ├── fee_pack.py
│   └── factory.py
└── tests/
```

Provider identity is `onlyalpha-market-generic-t0-cash`; economic product identity is `GENERIC_T0_CASH@1`. The package exports only its typed config and factory.

## 6. Generic typed config

`OnlyGenericT0CashConfig` has one field: `reference_resource_id`. Unknown fields fail closed, so config cannot override settlement, position, short, margin, fee, matching or slippage semantics. The raw resource alias is not an economic identity input; the resolved authority identity is.

## 7. Generic Reference Authority

`OnlyGenericT0CashReference` is plugin-owned and contains only facts needed by the Generic compiler: typed instrument and asset class, settlement currency, contract multiplier, tick, quantity bounds/increment, effective range and lifecycle flags.

`OnlyGenericT0CashReferenceAuthority` is frozen and deterministic. Its identity covers authority ID/version and ordered effective content fingerprints. Resolution by `Instrument + TradingDay` requires exactly one effective record: zero matches and ambiguity both fail closed. Object address, `repr` and Python identity never enter fingerprints.

## 8. Generic Policy Compiler

`OnlyGenericT0CashPolicyCompiler` independently implements `GENERIC_T0_CASH@1`; it does not call the legacy Generic helpers or instantiate a legacy Profile. Its fixed product semantics are:

- Generic UTC day session;
- reference tick, no daily price limit and no previous-close dependency;
- reference minimum/step/maximum quantity with fractional quantities allowed;
- long-only, short disabled, no margin;
- immediate T0 settlement;
- canonical instrument status, settlement currency and multiplier.

Compilation reads only the supplied reference authority and is deterministic for the same product version, reference and trading day.

## 9. Generic Market Fee ownership

The concrete Generic Market Fee definition now exists in the package as an immutable `OnlyMarketFeePack`. Its schedule, rule, rate, rounding, calculation scope and resulting formula are equal to the current legacy Generic pack. Core Fee Engine, accrual, ledger, application and reconciliation were not changed.

Broker fee remains a separate Broker Fee Contract; the Generic pack contains no Broker authority rule.

## 10. Product Factory and Binding implementation

The factory validates exact provider, product and version identities, parses the minimal config, resolves the effective reference authority, supplies its plugin-owned fee pack and creates the existing immutable `OnlyResolvedMarketProductBinding`.

Composition identity uses product, resolved reference, compiler, fee pack and empty effective economic config identities. Two raw resource aliases resolving the same effective authority produce the same identity; a changed reference authority changes it.

## 11. Market Product discovery integration

Discovery now includes the `onlyalpha.market_products` entry-point group. `OnlyComponentFactoryRegistries` carries the neutral `OnlyMarketProductFactoryRegistry`, and the default composition root asks discovery to populate it. The Generic distribution declares:

```text
generic-t0-cash
→ onlyalpha_market_generic_t0_cash.factory:OnlyGenericT0CashMarketProductFactory
```

Discovery sorting is deterministic. Conflicting providers and unknown registry lookup fail closed. There is no import-time self-registration, Core concrete registration or missing-plugin fallback.

## 12. Dependency-direction proof

Automated AST guards prove:

- `src/onlyalpha` does not import `onlyalpha_market_generic_t0_cash`;
- the Generic implementation imports no Runtime, Broker, Risk, Order, Position, Account, Execution, Transaction, A-share, legacy Profile or legacy compiler modules;
- the new IR imports none of the simulation model types;
- product identity is not a Core behavior selector.

Static searches for the concrete package in Core, simulation model types in `market/product`, and Runtime/A-share vocabulary in the Generic source all returned no matches.

## 13. Legacy-vs-new semantic conformance

Tests freeze equivalence for Generic session, reference-driven tick and quantity semantics, no price limit, fractional quantity, long-only, short disabled, T0 settlement, no margin, instrument lifecycle projection, settlement currency and contract multiplier.

The plugin Market Fee Pack equals the legacy pack structurally and produces the same fee formula result for the same basis. Matching, slippage and simulation liquidity are deliberately excluded from conformance because they are not Market Product economics.

## 14. Third Market extension proof

A tests-only `TEST_T2_MARKET` registers and resolves through the unchanged Core registry, then compiles tick `0.25`, quantity step `7` and T+2 settlement through the same canonical IR. No Core product branch is needed.

## 15. Architecture guards

The guards cover Core dependency direction, Generic forbidden imports/vocabulary, absence of simulation fields from the canonical dataclass, product-ID non-dispatch, immutable binding boundaries, deterministic discovery and duplicate discovery conflict handling. CI and the formal release lane now include the new package's Ruff, mypy, tests, version sync and build.

## 16. APIs deliberately removed from the new Contract

The new Market Product contract has no matching, slippage or simulation-liquidity field, including no optional/deprecated variant. It adds no legacy adapter, Profile-to-Product wrapper, alias, fallback, universal DSL, Runtime hook, mutable manager or Generic Runtime branch.

## 17. Legacy production code intentionally retained for P5.3

The following remain because they still own current production behavior:

- `only_generic_t0_cash_profile()`;
- legacy Generic compiler branch/helpers;
- legacy `OnlyCompiledMarketRules` including match-time simulation fields;
- Core legacy Generic fee-pack registration;
- Profile-based Runtime market composition.

They are migration debt, not a second target contract. P5.2 does not run the new and old authority simultaneously inside a Runtime.

## 18. Validation commands and results

All required local gates passed:

| Command | Result |
|---|---|
| `uv sync --frozen --all-packages --all-groups` | PASS |
| `uv run ruff check src tests examples packages scripts` | PASS |
| `uv run ruff format --check src tests examples packages scripts` | PASS |
| `uv run mypy src/onlyalpha` | PASS, 509 files |
| Generic package mypy | PASS, 6 files |
| P5.2 targeted contract/architecture/discovery/package tests | PASS, 50 |
| `uv build --all-packages` | PASS, 5 sdists and 5 wheels |
| `scripts/test_suite.py core-full` | PASS, 1224 passed / 1 skipped |
| `scripts/test_suite.py ashare` | PASS, 24 passed |
| `scripts/test_suite.py recovery` | PASS, 306 passed |
| `scripts/version_sync.py check` | PASS |
| required static searches | PASS, no forbidden matches |
| `git diff --check` | PASS |

The lane output contained existing performance warnings, but no gate failure. No test was skipped, retried or weakened by this change; the one `core-full` skip is the lane's existing selected-suite result.

## 19. Remaining P5.3 migration debt

P5.3 must implement CN A-share through the same fixed contract, prepare both Generic and A-share bindings, atomically cut Trading Runtime composition over to the Market Product registry, and then delete superseded Profile-specific composition and Core concrete fee ownership. It must not add market-name dispatch, a Generic fallback or a partial per-market Runtime cutover.

Generic T0 is now an ordinary concrete Market Product because its Reference, compiler and Market Fee authority live in a discoverable external distribution and Core knows only the neutral contract/registry. Matching, slippage and simulation liquidity cannot re-enter Market Product authority without changing the canonical dataclass shape, violating ADR 0070 and failing automated architecture guards.

The two P5.2 acceptance questions are therefore answered **yes**: replacing Virtual Broker with a real Broker requires no Generic product change, and a CN A-share plugin can reuse this contract/IR without adding an A-share branch to Core.
