# ADR 0064: Runtime Environment and Composition Authority

Status: Accepted

Date: 2026-08-09

Historical scope note: the statement below that CN A-share durable execution remained unsupported records this ADR's decision-time scope. [ADR 0067](0067-cn-a-share-production-durable-backtest-product.md) later accepted the finite product contract, and the [P4.3 conformance report](../reports/p4_3_cn_a_share_production_durable_product_conformance.md) records its certification; this note does not rewrite the original decision.

## Context

Runtime planning and infrastructure refcounting independently projected Cluster config into fingerprints. The projections
disagreed about DataSource coverage, Broker fee contracts, and fee reconciliation policies. `OnlyEngineServices` also exposed
a second registry graph beside the assembler. Inline Broker contract installation occurred before later Cluster validation, so
a failed load could leave an append-only authority residue.

## Decision

`OnlyRuntimeEnvironmentBuilder` is the sole definition of Runtime-shared semantics. It produces structured immutable identities
for clock/replay, DataSource, Broker, Account, Market/fee-pack/reference, and persistence, plus canonical shared-resource claims.
Canonical payloads normalize Decimal, Enum, date/time, mapping, set, sequence, dataclass, and value objects before SHA-256.

`OnlyRuntimePlanner` only groups equal environments, derives Runtime ID from runtime type plus environment fingerprint, checks
the representative-config invariant, and creates the existing assembly DTO. A different environment normally creates a
separate Runtime. A repeated mutable global key (`account`, `broker`, or `data_source`) with a different canonical fingerprint
is forbidden even when Runtime environments differ.

`OnlyInfrastructureRegistry` only validates claims, detects deterministic key/fingerprint conflicts, counts references, and
releases at zero. It does not import or interpret configuration DTOs. `OnlyEngineRunAssembler.components` owns the sole
component-registry graph; `OnlyEngineServices` contains only the assembler and plugin-discovery report.

Cluster composition follows parse/normalize (configuration), resolve/validate/stage (`OnlyClusterComposition.plan`), then one
commit boundary. Inline Broker contracts are validated and staged without mutation. Commit installs a prevalidated batch and
atomically swaps the resource-claim state. No unregister or authority rollback API is introduced.

## Shared and global identities

- Runtime-shared environment: time/clock/replay, runtime extensions/base currency, data sources, brokers, accounts, market,
  reference/universe authority, and persistence.
- Cluster-local: cluster ID, strategy, factors, indicators, and allocation metadata when they do not alter shared resources.
- Mutable global keys: `account:<id>`, `broker:<gateway-id>`, and `data_source:<source-id>`.
- Account economics include gateway, initial cash/currency, Broker contract ID/version, and reconciliation policy
  ID/version/currency.

## Consequences

Collection and registration order cannot change Runtime identity. Same Account ID with a different Broker contract or
reconciliation policy fails closed with existing/requested fingerprints. Failed composition leaves no Contract, resource, or
Cluster residue. The Runtime environment fingerprint is written to artifacts but is not a checkpoint schema field, so no
persistence schema version changes.

CN A-share durable execution remains unsupported. Reference-provider neutralization, capability-driven execution redesign,
Paper recovery, Live, and multi-account/multi-broker/multi-source products remain out of scope.

## Rejected alternatives

- Duplicated Planner and Infrastructure projections drift by construction.
- Compatibility properties keep two registry ownership surfaces alive.
- Register-then-unregister makes append-only authority correctness depend on rollback.
- Treating a conflicting Account as a second Runtime creates multiple mutable authorities for one logical identity.
