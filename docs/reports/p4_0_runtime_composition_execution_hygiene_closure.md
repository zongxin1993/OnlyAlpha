# P4-0 Runtime Composition & Execution Hygiene Closure

## Baseline

- Prompt baseline: `7604b0a2e3cc36cfe581d7fcec263369471fdd66`.
- Actual implementation baseline after fetching `origin/master`: `7604b0a2e3cc36cfe581d7fcec263369471fdd66`.
- Tested implementation commit before this report: `700d163`.
- Baseline differences: none. Every audited issue in the Prompt remained present.
- The user-provided untracked Prompt file was preserved and not committed.

## Root problems and before architecture

`OnlyRuntimeCompatibilityKey` and `OnlyInfrastructureRegistry` separately interpreted Cluster config. Planner omitted DataSource
plugin/coverage/extensions and Account reconciliation policy; Infrastructure omitted Account Broker contract. One logical Account
could therefore become multiple mutable authorities by being split into different Runtimes.

`OnlyEngineServices` and `OnlyEngineRunAssembler` exposed two component-registry graphs. Default construction happened to pass
the same instances, but custom construction could diverge. `add_cluster()` installed inline Broker contracts before extension and
resource validation, leaving append-only authority residue after failure. Execution production source retained two large
triple-quoted removed implementations and a `LEGACY_UNMIGRATED` state with no executable route.

## Canonical Runtime Environment model

`OnlyRuntimeEnvironmentBuilder` is pure and owns all shared semantics. It builds structured, frozen identities for:

- Runtime type, time range, clock, replay, runtime extensions, and base currency;
- DataSource ID/plugin/enabled/data version/coverage/batch/extensions;
- Broker gateway/plugin/enabled/extensions;
- Account gateway, initial cash/currency, Broker contract selection, and reconciliation policy selection/currency;
- Market profile/version/overrides, Market Fee Pack, generic or A-share Reference authority, and universes;
- Persistence backend/path/checkpoint semantics.

Mappings are key-sorted, semantic collections are stable-sorted, Decimal is a canonical string, Enum uses value, date/time uses
ISO, and SHA-256 is calculated from canonical JSON. Structured components remain available for audit; fingerprints are proof,
not replacement domain state.

Runtime ID is `<runtime-type>-<first 16 characters of environment fingerprint>`. Cluster ID, Strategy, Factor, Indicator, and
cluster-local allocation metadata do not affect the environment. Planner only groups identities, verifies every group member,
sorts clusters deterministically, and builds the existing assembly DTO.

## Resource identity and global mutable identity policy

The same builder produces `OnlyResourceClaim(resource_type, resource_key, fingerprint)`. Infrastructure imports no config DTO
and only performs key existence, fingerprint conflict, reference increment, and zero-reference release.

Different Runtime environments are legal and create different Runtime IDs. A repeated `account:<account-id>`,
`broker:<gateway-id>`, or `data_source:<source-id>` with a different fingerprint is globally illegal. Conflict messages include
the resource key plus existing/requested fingerprints without raw extensions or secrets. Tests prove same Account + different
Broker contract and same Account + different reconciliation policy both fail closed; identical resources share/refcount.

## Registry ownership and atomic composition

`OnlyEngineServices` now has only `assembler` and `plugin_discovery`. The assembler owns the only
`OnlyComponentFactoryRegistries` graph through `assembler.components`; all callers were migrated and no compatibility property
was retained.

`OnlyClusterComposition.plan()` builds environment, claims, resolves plugins and selected authorities, validates fee-pack/profile
compatibility, validates Broker contract/account compatibility, validates reconciliation policy currency, and stages only new
Broker contract snapshots without mutation. `commit()` revalidates, atomically swaps the validated Contract batch, and acquires
resource claims through a copy/apply/swap registry update. Engine inserts the already-built handle/config only after commit.
There is no unregister/rollback authority API.

The atomicity regression proves: a new Contract followed by extension-load failure installs nothing; no Cluster/resource remains;
a corrected submission with the same ID/version but a different valid fingerprint succeeds.

## Deleted interfaces and dead code

- Removed `OnlyRuntimeCompatibilityKey` and Planner-local `_fingerprint`.
- Removed Infrastructure config projection/fingerprint helpers.
- Removed EngineServices DataSource, Broker, Market Fee Pack, Broker Contract, and reconciliation registry fields.
- Removed `_unmigrated_trade` and its entire retained historical mutation body.
- Removed `_position_trade`, `_removed_fee_resolution_path`, `_notional`, and the retained fee/trade conversion body.
- Removed `OnlyExecutionCapability.LEGACY_UNMIGRATED`; unsupported shapes now resolve to `UNSUPPORTED`.
- Removed all compatibility aliases/properties for these surfaces.

Architecture guards prevent these source tokens and duplicated semantic readers from returning. `CN_A_SHARE_CASH` was not added
to Durable Trade capability.

## CI determinism changes

All setup-uv uses in `ci.yml`, `quality.yml`, `nightly.yml`, and `miniqmt-local.yml` pin `uv 0.10.5`. The project-level TUNA
default index was removed and `uv.lock` was rebuilt against canonical PyPI. Local mirrors remain a developer configuration.
Every workflow keeps `uv sync --frozen`.

Remote baseline Layered Quality run #22 (`7604b0a`) was Failure. Static/build and three main lanes produced results; Recovery
exited before producing metrics. Public annotations identify the Recovery command exit and missing metrics, but logs require
authentication and `gh` is unavailable locally. This is recorded as dependency infrastructure failure / Recovery NOT RUN, not
a business-test failure. GitHub Actions was not triggered for local commits because this implementation was not pushed.

## Schema changes

No checkpoint or Runtime persistence schema was changed. Canonical Runtime identity replaces an internal planning object and is
now emitted in runtime artifact summary as `runtime_environment` plus `runtime_environment_fingerprint`. Because Runtime IDs
changed intentionally, all four immutable Recovery baselines were regenerated through
`scripts/regenerate_recovery_baselines.py`; comparison logic and economic assertions were unchanged. Baseline metadata now records
OnlyAlpha 0.3.5.

## Test matrix

New tests cover DataSource plugin/enabled/version/coverage/extensions, Broker extensions, Account Broker contract and policy,
Market version/Fee Pack, Persistence backend/checkpoint, same-version provider counterexamples, Cluster-local negative cases,
registration-order determinism, Runtime ID derivation, Account global conflicts, refcount lifecycle, composition residue/retry,
single registry ownership, Planner/Infrastructure dependency guards, and Execution dead-source guards.

The first Recovery run was `286 passed, 9 failed`; every failure's first difference was the expected old vs new Runtime ID in
fixed baselines. After formal regeneration, focused baseline checks passed and the complete Recovery lane passed.

## Exact gate results

Tested commit: `700d163` (plus no production changes in this report commit).

```text
uv sync --frozen --all-packages --all-groups: PASS
ruff check src tests examples packages scripts: PASS
ruff format --check src tests examples packages scripts: PASS (1104 files)
core mypy: PASS (494 source files)
tushare provider mypy: PASS (15 source files)
miniqmt provider mypy: PASS (36 source files)
version sync: PASS (0.3.5)

fast: 1018 passed, 1 skipped (1019 collected)
integration: 130 passed
core-full: 1148 passed, 1 skipped (1149 collected)
recovery: 295 passed
ashare: 5 passed
miniqmt-contract: 32 passed
exhaustive: 112 passed

uv build --all-packages: PASS
  onlyalpha sdist/wheel
  virtual Broker plugin sdist/wheel
  Tushare plugin sdist/wheel
  MiniQMT plugin sdist/wheel

GitHub Actions final Quality Gate: NOT RUN for local implementation commits (not pushed)
Baseline GitHub Actions #22: FAILED before this implementation; Recovery NOT RUN due dependency infrastructure
```

Performance warnings remained advisory and did not change lane status or budgets.

## Not implemented in P4-0

- CN A-share Durable Execution enablement;
- capability-driven execution resolver redesign;
- profile-neutral Trade Planner;
- A-share BUY OPEN / SELL CLOSE product slices and T+1 durable conformance;
- Market Reference Provider neutralization;
- Paper checkpoint/restart, reconnect, and realtime gap recovery;
- Live Runtime and durable Broker outbound commands;
- Broker account/order/trade/position synchronization;
- multi-account, multi-broker, and multi-data-source products;
- Futures/Margin durable product;
- vectorized or distributed backtest.

The next phase is P4 — CN A-Share Durable Execution Product Closure.
