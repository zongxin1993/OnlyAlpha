# P4-0 Runtime Composition Pre-Implementation Audit

## Baseline

- Prompt baseline: `7604b0a2e3cc36cfe581d7fcec263369471fdd66`.
- Actual implementation baseline after `git fetch origin master`: the same commit.
- Local pre-existing state: only the untracked Prompt file
  `prompts/RuntimeCompositionExecutionHygieneClosure.md`; it is preserved and excluded from implementation changes.
- Relevant accepted decisions: ADR 0001, 0021, 0029, 0057, 0060–0063.

## Authority answers

- Runtime owns every mutable trading Manager and durable transaction state.
- Engine composition owns Cluster definitions and global shared-resource claims.
- Component registries own installed factories and versioned fee authorities; Runtime factories only resolve them.
- Transaction Store remains durable execution authority. This work does not change that kernel.
- Composition failure occurs before commit; forward recovery semantics remain unchanged.

## Current model before implementation

- `OnlyRuntimeCompatibilityKey.from_config()` independently hashes time, replay, only DataSource `data_version`, Broker config,
  Account initial cash plus Broker contract, Market fee pack/reference, and persistence.
- `OnlyInfrastructureRegistry._resource_projections()` separately hashes full DataSource config and Account initial cash plus
  reconciliation policy, but omits Broker contract.
- Runtime ID is `<runtime-type>-<first 16 chars of compatibility hash>` and assembly uses `configs[0]` without rebuilding every
  member identity.
- Same Account ID can be split into different Runtimes to avoid the incomplete grouping key, creating two mutable authorities.

## Ownership and lifecycle before implementation

- `OnlyEngineServices` exposes DataSource, Broker, Market fee-pack, Broker contract, and reconciliation registries while
  `OnlyEngineRunAssembler` separately holds `OnlyComponentFactoryRegistries`.
- Default construction passes the same instances by convention; custom services can construct divergent graphs.
- `OnlyEngine.add_cluster()` installs inline Broker contracts, acquires infrastructure, validates extension types, then inserts
  Cluster state. Resource acquisition is compensated on failure, but the append-only Contract installation is not.
- Remove Cluster decrements every acquired key; shared resources remain until the final reference is removed.

## Execution and CI before implementation

- `execution/processor.py` contains a raising `_unmigrated_trade()` followed by a triple-quoted historical mutation body and a
  second triple-quoted fee/trade conversion path.
- `OnlyExecutionCapability.LEGACY_UNMIGRATED` names a removed route and resolves unsupported futures/margin/short/parity cases.
- Repository default dependency source is TUNA and all GitHub workflows use unpinned setup-uv.
- Remote Layered Quality run #22 for baseline `7604b0a` is Failure. Recovery produced no metrics; public annotations distinguish
  this from lanes that produced artifacts, but authenticated logs are unavailable locally. It is classified as dependency
  infrastructure / test not run, not a Recovery regression.

## Roadmap drift

The roadmap simultaneously says P3 is incomplete, P3 is complete, and several older PR4 stages are next/current. It is an
accumulated historical log rather than one current product truth.

## Interfaces selected for deletion

- `OnlyRuntimeCompatibilityKey` and its private `_fingerprint` helper.
- Infrastructure `_resource_projections`, `_source_projection`, `_broker_projection`, `_account_projection`, and fingerprint.
- `OnlyEngineServices` registry fields.
- `OnlyExecutionProcessor._unmigrated_trade`, `_position_trade`, `_removed_fee_resolution_path`, `_notional`, and their retained
  triple-quoted bodies where they have no current caller.
- `OnlyExecutionCapability.LEGACY_UNMIGRATED`.

No persisted Runtime identity schema exists on this baseline, so this migration does not require checkpoint schema changes.
