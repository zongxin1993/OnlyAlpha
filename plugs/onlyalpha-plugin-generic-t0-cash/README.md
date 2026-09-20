# OnlyAlpha Generic T0 Cash Market Product

Concrete `GENERIC_T0_CASH@1` market-semantics plugin for OnlyAlpha.

The package owns Generic T0 reference interpretation, canonical market-policy compilation, and its Market Fee Pack. It does not own matching, slippage, simulated liquidity, Broker behavior, Risk, settlement mutation, or any Runtime trading state.

It is discovered through the `onlyalpha.market_products` entry-point group and is not a Core default or fallback. It is the conformance-validated generic T+0 cash implementation selected by typed market-product composition.
