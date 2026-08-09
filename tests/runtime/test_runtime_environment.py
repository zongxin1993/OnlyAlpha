from dataclasses import replace
from decimal import Decimal
from types import MappingProxyType

import pytest

from onlyalpha.config import (
    OnlyBrokerFeeContractConfig,
    OnlyClusterCapitalConfig,
    OnlyClusterCapitalMode,
    OnlyClusterRunConfig,
    OnlyFeeReconciliationPolicyConfig,
    OnlyRuntimeCheckpointConfig,
    OnlyRuntimePersistenceBackend,
    OnlyRuntimePersistenceConfig,
)
from onlyalpha.config.models import OnlyDataSourceCoverageConfig
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.runtime.environment import OnlyRuntimeEnvironmentBuilder
from onlyalpha.runtime.planning import OnlyRuntimePlanner


def _config():  # type: ignore[no-untyped-def]
    return OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")


def test_runtime_environment_is_order_independent_and_excludes_cluster_local_config() -> None:
    config = _config()
    builder = OnlyRuntimeEnvironmentBuilder()
    local_change = replace(
        config,
        cluster=replace(config.cluster, cluster_id=type(config.cluster_id)("other-cluster")),
        strategy=replace(
            config.strategy,
            extensions=MappingProxyType({**config.strategy.extensions, "trade_quantity": "2000"}),
        ),
    )
    assert builder.build(config) == builder.build(local_change)
    assert builder.build(config).fingerprint == builder.build(local_change).fingerprint


@pytest.mark.parametrize(
    "changed",
    (
        lambda config: replace(
            config,
            data_sources=(replace(config.data_sources[0], plugin_id="other-provider"),),
        ),
        lambda config: replace(
            config,
            data_sources=(replace(config.data_sources[0], enabled=False),),
        ),
        lambda config: replace(
            config,
            data_sources=(
                replace(config.data_sources[0], data_version=type(config.data_sources[0].data_version)("v2")),
            ),
        ),
        lambda config: replace(
            config,
            data_sources=(
                replace(
                    config.data_sources[0],
                    coverage=OnlyDataSourceCoverageConfig(instrument_ids=(OnlyInstrumentId.parse("TESTETF.XSHG"),)),
                ),
            ),
        ),
        lambda config: replace(
            config,
            data_sources=(replace(config.data_sources[0], extensions=MappingProxyType({"random_seed": 2})),),
        ),
        lambda config: replace(
            config,
            brokers=(replace(config.brokers[0], extensions=MappingProxyType({"endpoint": "paper"})),),
        ),
        lambda config: replace(
            config,
            accounts=(
                replace(
                    config.accounts[0],
                    broker_fee_contract=OnlyBrokerFeeContractConfig("OTHER_CONTRACT", "1"),
                ),
            ),
        ),
        lambda config: replace(
            config,
            accounts=(
                replace(
                    config.accounts[0],
                    fee_reconciliation_policy=OnlyFeeReconciliationPolicyConfig("OTHER_POLICY", "1"),
                ),
            ),
        ),
        lambda config: replace(
            config,
            market=replace(config.market, version="2099.1"),
        ),
        lambda config: replace(
            config,
            market=replace(
                config.market,
                fee_pack=replace(config.market.fee_pack, pack_version="2"),
            ),
        ),
        lambda config: replace(
            config,
            runtime=replace(
                config.runtime,
                persistence=OnlyRuntimePersistenceConfig(
                    OnlyRuntimePersistenceBackend.SQLITE,
                    "state.sqlite3",
                    OnlyRuntimeCheckpointConfig(True),
                ),
            ),
        ),
    ),
)
def test_each_shared_semantic_change_changes_environment_fingerprint(changed) -> None:  # type: ignore[no-untyped-def]
    config = _config()
    builder = OnlyRuntimeEnvironmentBuilder()
    assert builder.build(config).fingerprint != builder.build(changed(config)).fingerprint


def test_runtime_id_is_derived_from_environment_and_registration_order_is_stable() -> None:
    first = _config()
    capital = OnlyClusterCapitalConfig(
        OnlyClusterCapitalMode.FIXED_CAPITAL,
        OnlyMoney(Decimal("500000.00"), first.accounts[0].initial_cash.currency),
    )
    first = replace(first, cluster=replace(first.cluster, capital=capital))
    second = replace(
        first,
        cluster=replace(first.cluster, cluster_id=type(first.cluster_id)("other-cluster")),
    )
    planner = OnlyRuntimePlanner()
    left = planner.plan(first.runtime.engine_id, (first, second))
    right = planner.plan(first.runtime.engine_id, (second, first))
    assert len(left.runtime_plans) == 1
    assert left.runtime_plans[0].environment == right.runtime_plans[0].environment
    assert left.runtime_plans[0].runtime_id == right.runtime_plans[0].runtime_id


def test_same_data_version_with_different_provider_or_coverage_is_not_compatible() -> None:
    config = _config()
    provider = replace(config, data_sources=(replace(config.data_sources[0], plugin_id="miniqmt"),))
    coverage = replace(
        config,
        data_sources=(
            replace(
                config.data_sources[0],
                coverage=OnlyDataSourceCoverageConfig(instrument_ids=(OnlyInstrumentId.parse("TESTETF.XSHG"),)),
            ),
        ),
    )
    builder = OnlyRuntimeEnvironmentBuilder()
    assert builder.build(config) != builder.build(provider)
    assert builder.build(config) != builder.build(coverage)
