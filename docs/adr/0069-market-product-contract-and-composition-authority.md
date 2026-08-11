# ADR 0069: Market Product Contract and Composition Authority

- Status: Accepted
- Date: 2026-08-11
- Scope: Trading Market Product composition contract

## Context

Trading Runtime needs one answer for the effective reference, market-policy and market-fee authorities used by an execution. Those authorities are currently composed through Core-owned Market Profile, A-share reference and fee paths. This is valid current implementation but cannot be the extension model for Generic T0, CN A-share and later markets: adding a market must not add a market-name branch to Core.

Market Product is not a Runtime, Broker, DataSource, Risk policy or mutable trading service. It is the composition authority that resolves concrete market knowledge into an immutable bundle consumed by the Trading Plane. Research may consume instruments, calendars, datasets and reference metadata independently, but does not load trading market rules, settlement or fee authorities.

## Decision

Core defines the public `onlyalpha.market.product` contract:

```text
OnlyMarketProductConfig
→ OnlyMarketProductFactoryRegistry.require(plugin_id)
→ OnlyMarketProductFactory.resolve(config, context)
→ OnlyResolvedMarketProductBinding
→ Trading Runtime composition
```

Concrete Market Product plugins implement the contract and depend on Core; Core never imports a concrete market plugin. Registration is explicit and has no import-time side effect or implicit Generic fallback.

Provider identity (`OnlyMarketProductPluginId`) and economic product identity (`product_id@product_version`) are separate. Product identity is evidence for audit, artifacts, fingerprints and compatibility proof; it is not a behavior selector. Runtime type is absent from the factory input, binding and composition identity.

The resolved binding is frozen and contains only:

- provider and product evidence;
- a read-only reference authority port;
- a pure market-policy compiler port;
- the existing immutable `OnlyMarketFeePack` authority;
- a deterministic effective composition identity.

The policy compiler returns the Core canonical, mode-neutral `OnlyCompiledMarketPolicy`. Its policies cover the current session, price, quantity, position, short-sale, settlement, margin, liquidity, slippage and matching semantic dimensions. Its identity contains instrument/day, reference and compiler evidence, but never Runtime type. The legacy production `OnlyCompiledMarketRules` remains unchanged until P5.2/P5.3 cutover.

Composition identity is calculated after resolution from the product identity, reference authority identity, policy compiler identity, market fee-pack identity and effective plugin configuration identity. Raw YAML and unused transport fields are not economic identity inputs merely because they were present.

The resolution context exposes only composition-time reference and fee-pack resource ports. It does not expose Runtime, Engine, Order, Position, Account, Risk, Execution or recovery authorities. The plugin calculates market semantics; Core remains the sole owner of mutable trading state and settlement projection.

## Boundaries

- Market Product decides market legality and compiles settlement semantics; Execution Support independently decides whether the Kernel implements the normalized economic shape.
- Market Product does not define account exposure, risk budget or position limits.
- Broker owns external communication; DataSource supplies normalized market facts. Neither becomes market-semantics authority.
- Market fee policy is supplied by the product through the existing fee-pack authority. The Core Fee Engine continues to execute fee semantics.
- Binding is an authority bundle, not a service façade. It cannot submit orders, apply trades, mutate positions or calculate PnL.
- Research does not depend on this Trading Plane contract.

## Registry Semantics

The registry only registers, requires and enumerates factories, then delegates resolution. Re-registering the exact same factory object is idempotent. A different factory with the same plugin ID, an unknown plugin, an invalid factory identity, a mismatched resolved identity, unsupported product/version, invalid plugin config or ambiguous/missing authority fails closed.

## Migration

P5.1 establishes the target contract but does not cut over current production composition. Existing Generic/Profile/A-share composition remains current authority until replacement exists:

1. P5.2 implements Generic T0 Cash as a Market Product plugin and canonical market IR.
2. P5.3 implements CN A-share through the same fixed contract, cuts Trading Runtime over to resolved bindings and removes the superseded Core composition branches.
3. P5.4 hardens cross-artifact identity and deletes dead APIs.

No bridge, compatibility adapter, deprecated alias or reverse fallback is introduced during this interval.

## Rejected Alternatives

1. Core dispatches on product/profile ID.
2. Registry selects the first provider or silently falls back to Generic.
3. Runtime Factory also acts as Market Product Factory.
4. Binding exposes a universal hook/service framework or mutable managers.
5. A universal reference DTO accumulates every market-specific field.
6. Broker or DataSource becomes the owner of market semantics.
7. Research loads the Trading Market Product solely for structural symmetry.
8. Raw configuration bytes define effective economic identity.

## Consequences

Generic T0, CN A-share and a future third market can implement one stable Core contract without adding market-specific Core dispatch. The temporary cost is that the new contract and the current authoritative composition coexist until P5.2/P5.3 cutover; documentation and architecture guards must keep that state explicit and prevent new concrete-market debt.
