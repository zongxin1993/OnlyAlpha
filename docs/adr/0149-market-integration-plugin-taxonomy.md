# ADR 0149: Market Integration Plugin Taxonomy

Status: Accepted

The Indicator and Operator placement and distribution provisions are superseded by
[ADR 0150](0150-product-layout-and-programmable-quant-assets.md). The market, broker and data source taxonomy remains in effect.

Date: 2026-11-04

## Decision

Organize `plugs/` around three independent responsibilities. Align each
project directory and its applicable Cargo package and Python distribution
names with the following patterns.

| Responsibility | Name |
| --- | --- |
| Market rules | `onlyalpha-market-<market-family>` |
| Broker access | `onlyalpha-broker-<provider>` |
| External data access | `onlyalpha-data-source-<provider>` |

Market rule libraries are organized by market family. Use one
`onlyalpha-market-crypto` package with spot and derivatives modules. Reuse
common rule implementations. Represent exchange and instrument differences
with parameters carrying source and version. Separate behavior only where
parameters cannot represent a demonstrated difference. Keep each Market
Product's semantic identity. Retire the Generic T0 Cash project and its
remaining active references while preserving the exact artifacts required
by historical bindings.

Keep Binance broker and data source integration in separate provider
packages. Broker integration owns private account and execution protocol
handling. Data source integration owns retrieval and decoding of public
market and reference data. Market rules interpret those inputs and apply
the applicable versioned policies. The data source category also covers
fundamentals, financial statements and macroeconomic data.

Place Indicators and Operators under `packages/onlyalpha-indicators` and
`packages/onlyalpha-operators`. Their existing distributions, imports,
registration keys and asset identities are retained. Place the Research
Target implementation inside `onlyalpha-backend-algorithms`, retaining
its separate module, registration and semantic type
`onlyalpha.target.forward_return@1`. Bind new implementation artifacts
according to their actual contents. Historical runs keep their original
exact artifact bindings.

## Scope of supersession

This decision supersedes the distribution naming rule in ADR 0107 and
the affected placement provisions of ADR 0142. It also updates the
Targets distribution placement in ADR 0110. Existing protocol, semantic
identity, dependency direction, execution authority and exact recovery
requirements continue to apply. This decision defines the target layout
and does not attest that migration or artifact recovery has completed.
