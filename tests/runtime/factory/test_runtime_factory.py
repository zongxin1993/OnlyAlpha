import json
from collections.abc import Callable
from copy import deepcopy
from typing import Any, cast

import pytest

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.config.document import OnlyClusterConfigError
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.plugin.broker import OnlyBrokerGatewayFactory
from onlyalpha.plugin.capabilities import OnlyBrokerPluginCapabilities, OnlyDataSourceCapabilities
from onlyalpha.plugin.data_source import OnlyDataSourceFactory
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginOrigin, OnlyPluginOriginType, OnlyPluginType
from onlyalpha.plugin.version import ONLYALPHA_PLUGIN_API_VERSION
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.factory import OnlyRuntimeBuildRequest, OnlyRuntimeFactoryRegistry
from onlyalpha.runtime.planning import OnlyRuntimePlanner
from onlyalpha.runtime.research import only_research_runtime_plan
from onlyalpha.runtime.sim.factory import OnlySimRuntimeFactory
from tests.runtime.research.support import workload_case
from tests.runtime_support.market_product import only_generic_market_product


def _plan(runtime_type: str):
    baseline = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["type"] = runtime_type
    payload["cluster"]["runtime_type"] = runtime_type
    config = OnlyClusterRunConfig.from_mapping(payload, source_path="tests/fixtures/legacy_macd/cluster.json")
    binding = only_generic_market_product(config.reference_data.instruments[0])
    return (
        OnlyRuntimePlanner()
        .plan(OnlyEngineId("factory-test"), (config,), {config.cluster_id: binding})
        .runtime_plans[0]
    )


def _sim_plan(change: Callable[[dict[str, Any]], None] | None = None):
    baseline = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    payload: dict[str, Any] = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["type"] = "SIM"
    payload["runtime"]["start_time"] = None
    payload["runtime"]["end_time"] = None
    payload["runtime"]["extensions"] = {"execution_capability": "SIMULATED"}
    payload["cluster"]["runtime_type"] = "SIM"
    payload["data_sources"][0]["plugin"] = "miniqmt"
    if change is not None:
        change(payload)
    config = OnlyClusterRunConfig.from_mapping(payload, source_path="tests/fixtures/legacy_macd/cluster.json")
    binding = only_generic_market_product(config.reference_data.instruments[0])
    return (
        OnlyRuntimePlanner()
        .plan(OnlyEngineId("sim-factory-test"), (config,), {config.cluster_id: binding})
        .runtime_plans[0]
    )


class _DescriptorOnlyFactory:
    def __init__(self, descriptor: OnlyPluginDescriptor) -> None:
        self.descriptor = descriptor

    @staticmethod
    def parse_config(extensions: object) -> object:
        return extensions

    @staticmethod
    def validate_request(request: object) -> tuple[object, ...]:
        del request
        return ()

    @staticmethod
    def create(request: object) -> object:
        del request
        raise AssertionError("SIM P6.2 validation must not create plugin resources")


def _descriptor(
    plugin_id: str,
    plugin_type: OnlyPluginType,
    capabilities: object,
) -> OnlyPluginDescriptor:
    return OnlyPluginDescriptor(
        plugin_id,
        plugin_type,
        "1.0.0",
        ONLYALPHA_PLUGIN_API_VERSION,
        plugin_id,
        "OnlyAlpha Tests",
        capabilities,
    )


def _test_origin() -> OnlyPluginOrigin:
    return OnlyPluginOrigin(OnlyPluginOriginType.TEST, "sim-runtime-contract")


def test_backtest_factory_is_selected_through_runtime_assembler() -> None:
    services = only_default_engine_services()
    build = services.assembler.build(_plan("BACKTEST"))
    assert build.runtime is not None
    assert build.runtime.runtime_type == "BACKTEST"
    build.runtime.close()


def test_default_composition_installs_only_the_verified_cny_policy() -> None:
    first = only_default_engine_services()
    second = only_default_engine_services()
    cny = OnlyCurrency("CNY", 2)

    first_policy = first.assembler.components.fee_reconciliation_policies.require(
        "STANDARD_FEE_RECONCILIATION", "1", cny
    )
    second_policy = second.assembler.components.fee_reconciliation_policies.require(
        "STANDARD_FEE_RECONCILIATION", "1", cny
    )

    assert (
        first.assembler.components.fee_reconciliation_policies
        is not second.assembler.components.fee_reconciliation_policies
    )
    assert first_policy.identity == second_policy.identity
    with pytest.raises(ValueError, match="FEE_RECONCILIATION_POLICY_NOT_INSTALLED"):
        first.assembler.components.fee_reconciliation_policies.require(
            "STANDARD_FEE_RECONCILIATION",
            "1",
            OnlyCurrency("USD", 2),
        )


def test_live_remains_unsupported_and_research_rejects_a_trading_plan() -> None:
    services = only_default_engine_services()
    live = services.assembler.build(_plan("LIVE"))
    assert live.runtime is None
    assert live.failure_code == "UNSUPPORTED_RUNTIME_TYPE"
    research = services.assembler.build(_plan("RESEARCH"))
    assert research.runtime is None
    assert research.failure_code == "RESEARCH_RUNTIME_PLAN_REQUIRED"


def test_research_factory_rejects_invalid_components_and_missing_root(tmp_path: object) -> None:
    services = only_default_engine_services()
    _, workload = workload_case(tmp_path)  # type: ignore[arg-type]
    plan = only_research_runtime_plan(workload)
    factory = services.assembler._runtime_factories.require("RESEARCH")  # type: ignore[attr-defined]
    components = services.assembler.components
    invalid = factory.create(OnlyRuntimeBuildRequest(plan, object(), tmp_path))  # type: ignore[arg-type]
    assert invalid.failure_code == "RESEARCH_RUNTIME_COMPONENTS_INVALID"
    missing = factory.create(OnlyRuntimeBuildRequest(plan, components, None))
    assert missing.failure_code == "RESEARCH_USER_DATA_ROOT_REQUIRED"


@pytest.mark.parametrize("legacy", ("PAPER", "SHADOW"))
def test_legacy_runtime_factory_is_not_available(legacy: str) -> None:
    with pytest.raises(OnlyClusterConfigError, match="unsupported runtime.type"):
        _plan(legacy)


def test_default_runtime_registry_installs_the_sim_factory() -> None:
    registry = OnlyRuntimeFactoryRegistry()
    registry.register(OnlySimRuntimeFactory())

    assert registry.require("SIM").runtime_type == "SIM"


def test_valid_sim_contract_is_operationally_accepted() -> None:
    services = only_default_engine_services()

    validation = services.assembler.validate(_sim_plan())

    assert validation.runtime is None
    assert validation.failure_code is None
    assert validation.failure_message is None


@pytest.mark.parametrize(
    ("capability", "failure_code"),
    (("SHADOW", "RUNTIME_ASSEMBLY_FAILED"), ("LIVE", "SIM_EXECUTION_CAPABILITY_REQUIRED")),
)
def test_sim_rejects_non_simulated_execution_capabilities(capability: str, failure_code: str) -> None:
    def change(payload: dict[str, Any]) -> None:
        payload["runtime"]["extensions"]["execution_capability"] = capability

    build = only_default_engine_services().assembler.validate(_sim_plan(change))

    assert build.failure_code == failure_code


@pytest.mark.parametrize("boundary", ("start_time", "end_time"))
def test_sim_rejects_finite_runtime_ranges(boundary: str) -> None:
    def change(payload: dict[str, Any]) -> None:
        payload["runtime"][boundary] = "2026-01-05T01:30:00Z"

    build = only_default_engine_services().assembler.validate(_sim_plan(change))

    assert build.failure_code == "SIM_FINITE_RANGE_NOT_SUPPORTED"


def test_sim_checkpoint_requires_stable_durable_state_root() -> None:
    def change(payload: dict[str, Any]) -> None:
        payload["runtime"]["persistence"] = {
            "backend": "SQLITE",
            "path": "runtime.sqlite3",
            "checkpoint": {"enabled": True},
        }

    build = only_default_engine_services().assembler.validate(_sim_plan(change))

    assert build.failure_code == "SIM_DURABLE_STATE_ROOT_REQUIRED"


@pytest.mark.parametrize("count", (0, 2))
def test_sim_requires_exactly_one_enabled_data_source(count: int) -> None:
    def change(payload: dict[str, Any]) -> None:
        source = deepcopy(payload["data_sources"][0])
        source["source_id"] = "miniqmt-secondary"
        payload["data_sources"] = [] if count == 0 else [payload["data_sources"][0], source]

    build = only_default_engine_services().assembler.validate(_sim_plan(change))

    assert build.failure_code == "SIM_DATA_SOURCE_COUNT_INVALID"


def test_sim_rejects_historical_only_data_source() -> None:
    def change(payload: dict[str, Any]) -> None:
        payload["data_sources"][0]["plugin"] = "synthetic"

    build = only_default_engine_services().assembler.validate(_sim_plan(change))

    assert build.failure_code == "SIM_DATA_SOURCE_CAPABILITY_REQUIRED"
    assert "live_bars" in str(build.failure_message)


def test_sim_rejects_live_only_data_source() -> None:
    services = only_default_engine_services()
    factory = _DescriptorOnlyFactory(
        _descriptor("live-only", OnlyPluginType.DATA_SOURCE, OnlyDataSourceCapabilities(live_bars=True))
    )
    services.assembler.components.data_sources.register(
        cast(OnlyDataSourceFactory, factory),
        origin=_test_origin(),
    )

    def change(payload: dict[str, Any]) -> None:
        payload["data_sources"][0]["plugin"] = "live-only"

    build = services.assembler.validate(_sim_plan(change))

    assert build.failure_code == "SIM_DATA_SOURCE_CAPABILITY_REQUIRED"
    assert "historical_bars" in str(build.failure_message)


def test_sim_requires_explicit_live_reconnect_capability() -> None:
    services = only_default_engine_services()
    factory = _DescriptorOnlyFactory(
        _descriptor(
            "no-reconnect",
            OnlyPluginType.DATA_SOURCE,
            OnlyDataSourceCapabilities(historical_bars=True, live_bars=True),
        )
    )
    services.assembler.components.data_sources.register(
        cast(OnlyDataSourceFactory, factory),
        origin=_test_origin(),
    )

    def change(payload: dict[str, Any]) -> None:
        payload["data_sources"][0]["plugin"] = "no-reconnect"

    build = services.assembler.validate(_sim_plan(change))

    assert build.failure_code == "SIM_DATA_SOURCE_RECONNECT_CAPABILITY_REQUIRED"
    assert "live_reconnect" in str(build.failure_message)


@pytest.mark.parametrize("count", (0, 2))
def test_sim_requires_exactly_one_enabled_broker(count: int) -> None:
    def change(payload: dict[str, Any]) -> None:
        if count == 0:
            payload["brokers"][0]["enabled"] = False
            return
        broker = deepcopy(payload["brokers"][0])
        broker["gateway_id"] = "virtual-secondary"
        payload["brokers"] = [payload["brokers"][0], broker]

    build = only_default_engine_services().assembler.validate(_sim_plan(change))

    assert build.failure_code == "SIM_BROKER_COUNT_INVALID"


def test_sim_rejects_real_broker_even_when_it_supports_order_operations() -> None:
    def change(payload: dict[str, Any]) -> None:
        payload["brokers"][0]["plugin"] = "miniqmt"

    build = only_default_engine_services().assembler.validate(_sim_plan(change))

    assert build.failure_code == "SIM_SIMULATED_BROKER_REQUIRED"


def test_sim_requires_minimum_simulated_broker_capabilities() -> None:
    services = only_default_engine_services()
    capabilities = OnlyBrokerPluginCapabilities(simulated_execution=True, submit_order=True)
    factory = _DescriptorOnlyFactory(_descriptor("limited-sim", OnlyPluginType.BROKER, capabilities))
    services.assembler.components.brokers.register(
        cast(OnlyBrokerGatewayFactory, factory),
        origin=_test_origin(),
    )

    def change(payload: dict[str, Any]) -> None:
        payload["brokers"][0]["plugin"] = "limited-sim"

    build = services.assembler.validate(_sim_plan(change))

    assert build.failure_code == "SIM_BROKER_CAPABILITY_REQUIRED"
    assert "cancel_order" in str(build.failure_message)
