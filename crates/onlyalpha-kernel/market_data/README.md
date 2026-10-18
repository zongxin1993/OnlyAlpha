# MarketData

One market-data business boundary with three independently buildable subcrates:

- `state/`: bounded closed-Bar state and immutable Runtime/Cluster views; Domain only.
- `construction/`: exact recipes/lineage, DAG compilation and pure stateful construction; Domain only.
- `delivery/`: explicit subscriptions and scoped delivery planning; Domain + State + Construction.

Private files within each crate separate implementation concerns; they are not additional public modules or deployment units.
No lower crate references a higher one. The root Cargo workspace and canonical `rust-kernel` lane enforce the declared graph
and extracted independent builds. The [owning Contract](../../../docs/market_data_pipeline.md) defines authority and failure
semantics. These libraries do not activate a production Runtime or grant readiness/actual Strategy execution.
