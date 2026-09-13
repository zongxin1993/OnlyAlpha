# `src/onlyalpha` semantic inventory

This is the durable Kernel-package inventory for the Kernel Semantic Graduation.
The machine-readable source of the complete module list is
[`scripts/audit_src_semantic_surface.py`](../../scripts/audit_src_semantic_surface.py).
Run it from the repository root to print every module, its classification, and
production importers. The audit is report-only because dynamic loading and
historical readers require review before deletion.

At the time of this change the inventory contains 773 Python modules. Every
module is classified; there is no `UNKNOWN`, `MAYBE`, or `TEMP_KEEP` category.
The default classification is `CANONICAL`. The following explicit prefixes are
classified as `EXTERNAL_ADAPTER` while their physical relocation remains a
follow-up boundary task:

| Prefix | Ownership evidence | Follow-up target |
|---|---|---|
| `onlyalpha.persistence` | durable store/codec implementation | independently deployable persistence component |
| `onlyalpha.output`, `onlyalpha.storage` | local user-data and storage integration | infrastructure/storage package |
| `onlyalpha.scenario` | deterministic operator/test workload harness | test/operator tooling |
| `onlyalpha.backtest.worker_main`, `onlyalpha.research.worker_main` | process entrypoints and deployment composition | worker/operator packages |

The remaining modules express canonical domain, calculation, research,
strategy, runtime, execution, risk, evidence, identity, or Kernel boundary
semantics. Concrete provider implementations remain under `plugs/` and are not
part of this inventory.

The report currently identifies 13 modules without a direct production inbound
import. This is a review list, not an unexplained deletion list: package
`__init__` entrypoints are reached by submodule imports, `cluster.demo` is the
deterministic Scenario workload used by Runtime tests, `cluster.loader` and
`cluster.registry` are explicit operator/test composition boundaries,
`plugin.testing` is the plugin conformance helper, and the remaining candidates
are public ports, exception/replay/evidence authorities, or package aggregators.
They remain classified and retained until a separate reachability proof and
relocation/deletion decision exists.

## Canonicalization and deletion ledger

| Old surface | Canonical authority | Action | Reason |
|---|---|---|---|
| `OnlyDataSourceFactoryRegistry.require` | `resolve` | deleted | duplicate factory API |
| `OnlyBrokerFactoryRegistry.require` | `resolve` | deleted | duplicate factory API |
| `OnlyRuntimeServices` | `OnlyTradingKernelServices` | deleted and callers migrated | parallel Runtime/Kernel vocabulary |
| `OnlyRuntimeContextView`, `OnlyClusterContext` | `OnlyRuntimeContext` | deleted and callers migrated | one Runtime context authority |
| `OnlyResearchDatasetSourceContract` | `OnlyResearchDatasetSourceContractV1` | deleted and callers migrated | unversioned contract alias |
| `OnlyResearchSubmissionKey` | `OnlyProductCommandId` | deleted and callers migrated | Product Command identity owns the key |
| `only_research_predicate_type_reference` | `only_predicate_type_reference` | deleted and callers migrated | calculation owns neutral Predicate identity |
| `OnlyHistoricalCacheKey` | `OnlyHistoricalBarCacheKey` | deleted and callers migrated | cache key has one explicit data shape |
| `OnlyAgentEvaluationContextReferenceV1` | `OnlySearchEvaluationContextReferenceV1` | deleted and callers migrated | Search experiment owns the identity |
| `OnlyAccountBalance`, `OnlyCancelRequest`, `OnlyOrderQueryView`, `OnlyOrderContextView` | their concrete canonical class | deleted | unused type/entry aliases |
| `OnlyPositionAllocation`, `OnlyPositionFill`, position query/risk aliases | concrete snapshot/query/risk classes | deleted | unused type/entry aliases |
| `OnlyIndicatorDefinition`, `OnlyFactorDefinition` | `OnlyCalculationDefinition` | deleted | calculation definition is the sole authority |
| `OnlyFileReferenceDataSource` | `OnlyInMemoryReferenceDataSource` | deleted | unused source alias |
| `OnlyOrderStatus.INITIALIZED`, `CANCELED`, `DENIED` | `CREATED`, `CANCELLED`, `REJECTED` | deleted | old enum spellings were never current facts |
| `OnlyExecutionSubmissionOutcome.SUBMITTED`, `.REJECTED` | `KNOWN_RESULT`, `NOT_DISPATCHED` | deleted | explicit submission-knowledge semantics |
| `Clock.now` | `Clock.now_utc` | deleted and callers migrated | one time-reading boundary |
| `Calendar.is_open_at` | `Calendar.is_trading_time` | deleted and callers migrated | one session query vocabulary |
| `runtime/research/errors.py`, `plan.py`, `research/definition/primitives.py` | owning modules | deleted | pure compatibility re-exports |

No deletion changes OpenAPI, persistent schema, historical fact reading,
runtime state transitions, strategy semantics, or execution outcomes. Existing
schema readers and migration code containing the word “legacy” are retained
when they are the formal authority for reading durable historical facts.

## Direct test ownership

Graduated semantic units are proved by their nearest stable test boundary:

| Semantic unit | Direct proof |
|---|---|
| Factory resolution | `tests/plugin/test_broker_factory_registry.py` and plugin discovery tests |
| Runtime context and Kernel services | architecture/runtime boundary tests |
| Clock and calendar vocabulary | `tests/unit/test_clock_event.py`, `tests/time_model/` |
| Research source binding and Predicate identity | `tests/research/calculation/`, `tests/research/definition/` |
| Product Command identity | `tests/research/command/`, HTTP contract tests |
| Historical Bar cache key | `tests/cache/test_historical_cache.py`, dataset materializer tests |
| Order submission outcome | order/execution unit and integration tests |

The report lists production-unreachable candidates for bounded human review; it
does not authorize mechanical removal. A candidate may be an entrypoint,
dynamic import target, package export, or test/operator boundary and must be
resolved with evidence before a future deletion.
