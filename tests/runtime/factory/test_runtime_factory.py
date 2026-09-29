import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event
from types import MappingProxyType
from typing import Any, cast

import pytest

from onlyalpha.application.integration_configuration import OnlyIntegrationId
from onlyalpha.application.integration_runtime import (
    OnlyIntegrationRuntimeBindingV1,
    OnlyIntegrationRuntimeError,
    OnlyResolvedIntegrationRuntimeConfiguration,
    OnlyResolvedIntegrationSecrets,
)
from onlyalpha.cluster.factory import only_strategy_market_data_graph
from onlyalpha.config import OnlyClusterRunConfig, OnlyStrategyReferenceConfig
from onlyalpha.config.document import OnlyClusterConfigError
from onlyalpha.config.models import OnlyRuntimeConfigurationMode
from onlyalpha.config.persistence import (
    OnlyRuntimeCheckpointConfig,
    OnlyRuntimePersistenceBackend,
    OnlyRuntimePersistenceConfig,
)
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyOrderSide, OnlySessionType
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId
from onlyalpha.domain.market import (
    OnlyBarSemantic,
    OnlyBarType,
    OnlyTickCountBarFormation,
    OnlyTradeInputType,
    OnlyTradeSemantic,
)
from onlyalpha.domain.value import OnlyCurrency, OnlyPrice, OnlyQuantity
from onlyalpha.market_data.resolution import OnlyBarConstructionRecipe, OnlyBarConstructionRequirement
from onlyalpha.plugin.broker import OnlyBrokerGatewayFactory
from onlyalpha.plugin.capabilities import (
    OnlyBrokerPluginCapabilities,
    OnlyCheckpointCapability,
    OnlyDataSourceCapabilities,
)
from onlyalpha.plugin.data_source import OnlyDataSourceFactory
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginOrigin, OnlyPluginOriginType, OnlyPluginType
from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationConfigurationContractV1,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationTypeId,
    only_integration_capability_ids,
)
from onlyalpha.plugin.version import ONLYALPHA_PLUGIN_API_VERSION
from onlyalpha.runtime.backtest.factory import OnlyBacktestRuntimeFactory
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.factory import OnlyRuntimeBuildRequest, OnlyRuntimeFactoryRegistry
from onlyalpha.runtime.planning import OnlyRuntimePlanner
from onlyalpha.runtime.research import only_research_runtime_plan
from onlyalpha.runtime.sim.factory import OnlySimRuntimeFactory
from onlyalpha.strategy.revision import OnlyStrategyMarketInputContract
from onlyalpha.strategy.store import OnlyFrozenStrategyRevisionStore
from tests.runtime.research.support import workload_case
from tests.runtime_support.market_product import only_generic_market_product
from tests.runtime_support.runner import only_migrate_cluster_to_strategy
from tests.strategy.product_support import publish_frozen_strategy_for_execution_test


def _plan(runtime_type: str, user_data_root: Path | None = None):
    baseline = OnlyClusterRunConfig.load("test-data/legacy_macd/cluster.json")
    if user_data_root is not None:
        baseline = only_migrate_cluster_to_strategy(baseline, user_data_root)
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["strategy"] = {"fingerprint": baseline.strategy.fingerprint}
    payload["factors"] = []
    payload["runtime"]["type"] = runtime_type
    payload["cluster"]["runtime_type"] = runtime_type
    config = OnlyClusterRunConfig.from_mapping(payload, source_path="test-data/legacy_macd/cluster.json")
    binding = only_generic_market_product(config.reference_data.instruments[0])
    return (
        OnlyRuntimePlanner()
        .plan(OnlyEngineId("factory-test"), (config,), {config.cluster_id: binding})
        .runtime_plans[0]
    )


def _sim_plan(
    change: Callable[[dict[str, Any]], None] | None = None,
    user_data_root: Path | None = None,
):
    baseline = OnlyClusterRunConfig.load("test-data/legacy_macd/cluster.json")
    if user_data_root is not None:
        baseline = only_migrate_cluster_to_strategy(baseline, user_data_root)
    payload: dict[str, Any] = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["strategy"] = {"fingerprint": baseline.strategy.fingerprint}
    payload["factors"] = []
    payload["runtime"]["type"] = "SIM"
    payload["runtime"]["start_time"] = None
    payload["runtime"]["end_time"] = None
    payload["runtime"]["extensions"] = {"execution_capability": "SIMULATED"}
    payload["cluster"]["runtime_type"] = "SIM"
    payload["data_sources"][0]["plugin"] = "miniqmt"
    if change is not None:
        change(payload)
    config = OnlyClusterRunConfig.from_mapping(payload, source_path="test-data/legacy_macd/cluster.json")
    binding = only_generic_market_product(config.reference_data.instruments[0])
    return (
        OnlyRuntimePlanner()
        .plan(OnlyEngineId("sim-factory-test"), (config,), {config.cluster_id: binding})
        .runtime_plans[0]
    )


def _trade_root_plan(runtime_type: str, user_data_root: Path):
    plan = (
        _plan("BACKTEST", user_data_root)
        if runtime_type == "BACKTEST"
        else _sim_plan(
            lambda payload: payload["runtime"]["extensions"].update({"streaming": {"bootstrap_bars": 1}}),
            user_data_root=user_data_root,
        )
    )
    store = OnlyFrozenStrategyRevisionStore(user_data_root / "research")
    native = store.load_verified(plan.assembly_plan.clusters[0].strategy.fingerprint)
    target = OnlyBarSemantic(OnlyTickCountBarFormation(3))
    revision = replace(
        native,
        market_input_contract=OnlyStrategyMarketInputContract(
            target,
            OnlyBarConstructionRequirement.exact(
                OnlyBarConstructionRecipe.derived(target, OnlyTradeSemantic(), algorithm_id="TICK_BAR")
            ),
        ),
    )
    publish_frozen_strategy_for_execution_test(user_data_root / "research", revision)
    cluster = replace(
        plan.assembly_plan.clusters[0],
        strategy=OnlyStrategyReferenceConfig(str(revision.strategy_fingerprint)),
    )
    return replace(plan, assembly_plan=replace(plan.assembly_plan, clusters=(cluster,))), revision


class _TickCountExecutor:
    def __init__(self, edge) -> None:  # type: ignore[no-untyped-def]
        self.target_bar_type = edge.target
        self._trades = []

    @staticmethod
    def accepts(fact: object) -> bool:
        from onlyalpha.domain.market import OnlyTradeTick

        return isinstance(fact, OnlyTradeTick)

    def process(self, fact):  # type: ignore[no-untyped-def]
        from onlyalpha.domain.market import OnlyBar

        self._trades.append(fact)
        if len(self._trades) < 3:
            return ()
        trades, self._trades = self._trades, []
        prices = [item.price for item in trades]
        quantity = sum((item.quantity.value for item in trades), Decimal(0))
        return (
            OnlyBar(
                bar_type=self.target_bar_type,
                open=prices[0],
                high=max(prices, key=lambda item: item.value),
                low=min(prices, key=lambda item: item.value),
                close=prices[-1],
                volume=OnlyQuantity(quantity, trades[0].quantity.precision),
                quote_volume=None,
                turnover=None,
                trade_count=len(trades),
                open_interest=None,
                bar_start=trades[0].ts_event,
                bar_end=trades[-1].ts_event,
                ts_event=trades[-1].ts_event,
                ts_init=trades[-1].ts_init,
                is_closed=True,
                revision=0,
                adjustment_type=OnlyAdjustmentType.RAW,
                trading_day=trades[-1].ts_event.date(),
                session_type=OnlySessionType.CONTINUOUS,
            ),
        )

    def capture_checkpoint(self) -> object:
        return {"pending_trades": [item.to_dict() for item in self._trades]}

    def restore_checkpoint(self, payload: object) -> None:
        from onlyalpha.domain.market import OnlyTradeTick

        if not isinstance(payload, dict) or not isinstance(payload.get("pending_trades"), list):
            raise ValueError("invalid test executor checkpoint")
        self._trades = [OnlyTradeTick.from_dict(item) for item in payload["pending_trades"]]


class _TradeDataSource:
    def __init__(self, request, descriptor: OnlyPluginDescriptor) -> None:  # type: ignore[no-untyped-def]
        from onlyalpha.plugin.lifecycle import OnlyPluginLifecycleState

        self.request = request
        self.plugin_descriptor = descriptor
        self.plugin_resource_id = f"{descriptor.plugin_id}:{request.source_id}"
        self.source_id = request.source_id
        self.state = OnlyPluginLifecycleState.CREATED
        self.recovery_updates = ()
        self.load_bar_calls = 0
        self.load_trade_calls = []
        self._connected = False

    def initialize(self) -> None:
        from onlyalpha.plugin.lifecycle import OnlyPluginLifecycleState

        self.state = OnlyPluginLifecycleState.INITIALIZED

    def connect(self):  # type: ignore[no-untyped-def]
        from onlyalpha.data.enums import OnlyMarketDataConnectionState, OnlyMarketDataRequestStatus
        from onlyalpha.data.identifiers import OnlyMarketDataGatewayId
        from onlyalpha.data.models import OnlyMarketDataConnectionResult, OnlyMarketDataConnectionSnapshot
        from onlyalpha.plugin.lifecycle import OnlyPluginLifecycleState

        self.state = OnlyPluginLifecycleState.CONNECTED
        self._connected = True
        return OnlyMarketDataConnectionResult(
            OnlyMarketDataRequestStatus.ACCEPTED,
            OnlyMarketDataConnectionSnapshot(
                OnlyMarketDataGatewayId(f"gateway-{self.source_id}"),
                OnlyMarketDataConnectionState.CONNECTED,
            ),
        )

    def start(self) -> None:
        from onlyalpha.plugin.lifecycle import OnlyPluginLifecycleState

        self.state = OnlyPluginLifecycleState.RUNNING

    def stop(self) -> None:
        from onlyalpha.plugin.lifecycle import OnlyPluginLifecycleState

        self.state = OnlyPluginLifecycleState.STOPPED
        self._connected = False

    def close(self) -> None:
        from onlyalpha.plugin.lifecycle import OnlyPluginLifecycleState

        self.state = OnlyPluginLifecycleState.STOPPED
        self._connected = False

    def load_bars(self, request):  # type: ignore[no-untyped-def]
        self.load_bar_calls += 1
        raise AssertionError(f"Trade-root Runtime requested provider Bars: {request}")

    def load_trades(self, request):  # type: ignore[no-untyped-def]
        from onlyalpha.data.models import OnlyHistoricalDataStream

        self.load_trade_calls.append(request)
        if request.request_id.startswith("recovery-"):
            return OnlyHistoricalDataStream(self.recovery_updates, request.batch_size)
        end = request.data_range.end_time
        return OnlyHistoricalDataStream(self._updates(end - timedelta(seconds=4), 1), request.batch_size)

    def load_quotes(self, request):  # type: ignore[no-untyped-def]
        from onlyalpha.data.models import OnlyHistoricalDataStream

        return OnlyHistoricalDataStream((), request.batch_size)

    def load_facts(self, request):  # type: ignore[no-untyped-def]
        from onlyalpha.data.models import OnlyHistoricalDataStream

        return OnlyHistoricalDataStream((), request.batch_size)

    def authenticate(self):  # type: ignore[no-untyped-def]
        from onlyalpha.data.enums import OnlyMarketDataConnectionState, OnlyMarketDataRequestStatus
        from onlyalpha.data.identifiers import OnlyMarketDataGatewayId
        from onlyalpha.data.models import OnlyMarketDataConnectionResult, OnlyMarketDataConnectionSnapshot

        return OnlyMarketDataConnectionResult(
            OnlyMarketDataRequestStatus.ACCEPTED,
            OnlyMarketDataConnectionSnapshot(
                OnlyMarketDataGatewayId(f"gateway-{self.source_id}"),
                OnlyMarketDataConnectionState.READY,
            ),
        )

    def disconnect(self):  # type: ignore[no-untyped-def]
        from onlyalpha.data.enums import OnlyMarketDataRequestStatus
        from onlyalpha.data.models import OnlyMarketDataConnectionResult

        self._connected = False
        return OnlyMarketDataConnectionResult(OnlyMarketDataRequestStatus.ACCEPTED, self.connection_snapshot())

    def connection_snapshot(self):  # type: ignore[no-untyped-def]
        from onlyalpha.data.enums import OnlyMarketDataConnectionState
        from onlyalpha.data.identifiers import OnlyMarketDataGatewayId
        from onlyalpha.data.models import OnlyMarketDataConnectionSnapshot

        return OnlyMarketDataConnectionSnapshot(
            OnlyMarketDataGatewayId(f"gateway-{self.source_id}"),
            OnlyMarketDataConnectionState.READY if self._connected else OnlyMarketDataConnectionState.DISCONNECTED,
        )

    def subscribe(self, request):  # type: ignore[no-untyped-def]
        from onlyalpha.data.enums import OnlyMarketDataRequestStatus, OnlyMarketDataType
        from onlyalpha.data.models import OnlyMarketDataSubscriptionResult

        assert request.data_types == frozenset({OnlyMarketDataType.TRADE})
        assert request.bar_types == frozenset()
        self.subscription = request
        return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.ACCEPTED, "trades")

    def unsubscribe(self, request):  # type: ignore[no-untyped-def]
        del request

    def emit_live(self, *, sequence: int = 4, count: int = 3) -> None:
        now = self.request.clock.now_utc()
        for update in self._updates(now - timedelta(seconds=count), sequence)[:count]:
            assert self.request.market_data_sink is not None
            self.request.market_data_sink(update)

    def _updates(self, start, sequence: int):  # type: ignore[no-untyped-def]
        from onlyalpha.data.enums import OnlyDataSequenceSemantics, OnlyMarketDataType
        from onlyalpha.data.identifiers import OnlyDataSequence
        from onlyalpha.data.identity import only_trade_update_id
        from onlyalpha.data.models import OnlyMarketDataInboundUpdate, OnlyTradeTickUpdate
        from onlyalpha.domain.identifiers import OnlyTradeId
        from onlyalpha.domain.market import OnlyTradeTick
        from onlyalpha.domain.time import OnlyTimestamp

        instrument_id = next(iter(self.request.instruments))
        result = []
        for offset in range(3):
            event = start + timedelta(seconds=offset + 1)
            trade = OnlyTradeTick(
                instrument_id,
                event,
                event,
                sequence + offset,
                str(self.source_id),
                OnlyPrice(Decimal(10 + offset), 2),
                OnlyQuantity(Decimal(1), 0),
                OnlyOrderSide.BUY,
                OnlyTradeId(f"trade-{sequence + offset}"),
            )
            timestamp = OnlyTimestamp.from_datetime(event)
            result.append(
                OnlyMarketDataInboundUpdate(
                    only_trade_update_id(self.source_id, instrument_id, trade.trade_id, self.request.data_version),
                    self.request.runtime_id,
                    self.source_id,
                    OnlyDataSequence(sequence + offset),
                    self.request.data_version,
                    instrument_id,
                    OnlyMarketDataType.TRADE,
                    OnlyTradeTickUpdate(trade),
                    timestamp,
                    timestamp,
                    sequence_semantics=OnlyDataSequenceSemantics.CONTIGUOUS,
                )
            )
        return tuple(result)


class _TradeDataSourceFactory:
    def __init__(self, plugin_id: str, *, live: bool) -> None:
        self.descriptor = OnlyPluginDescriptor(
            plugin_id,
            OnlyPluginType.DATA_SOURCE,
            "1.0.0",
            ONLYALPHA_PLUGIN_API_VERSION,
            plugin_id,
            "OnlyAlpha Tests",
            OnlyDataSourceCapabilities(
                historical_ticks=True,
                live_ticks=live,
                live_reconnect=live,
                supports_runtime_checkpoint=OnlyCheckpointCapability.STATELESS,
            ),
        )
        self.integration_type = OnlyIntegrationTypeDescriptorV1(
            OnlyIntegrationTypeId(f"test.{plugin_id.replace('-', '_')}"),
            OnlyIntegrationCategory.DATA_SOURCE,
            plugin_id,
            "Trade DataSource for tests.",
            "tests",
            plugin_id,
            self.descriptor.plugin_version,
            str(self.descriptor.api_version),
            only_integration_capability_ids(self.descriptor.capabilities),
            OnlyIntegrationConfigurationContractV1(()),
        )
        self.created: list[_TradeDataSource] = []

    @staticmethod
    def parse_config(extensions: object) -> object:
        return extensions

    @staticmethod
    def parse_runtime_integration_config(public: object, secrets: object) -> object:
        del secrets
        return public

    @staticmethod
    def validate_request(request: object) -> tuple[object, ...]:
        del request
        return ()

    def create(self, request):  # type: ignore[no-untyped-def]
        source = _TradeDataSource(request, self.descriptor)
        self.created.append(source)
        return source


class _IntegrationResolver:
    def __init__(self, factory: _TradeDataSourceFactory) -> None:
        self.factory = factory
        self.binding = OnlyIntegrationRuntimeBindingV1(
            OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac"),
            "a" * 64,
            factory.integration_type.type_id.value,
            OnlyIntegrationCategory.DATA_SOURCE,
            factory.integration_type.fingerprint,
            "b" * 64,
        )
        self.calls: list[tuple[str, ...]] = []

    def resolve(self, binding: object, *, expected_category: object, required_capabilities: object) -> object:
        assert binding == self.binding
        assert expected_category is OnlyIntegrationCategory.DATA_SOURCE
        required = tuple(cast(tuple[str, ...], required_capabilities))
        self.calls.append(required)
        if not set(required).issubset(self.factory.integration_type.capabilities):
            raise OnlyIntegrationRuntimeError("INTEGRATION_RUNTIME_CAPABILITY_MISSING")
        return OnlyResolvedIntegrationRuntimeConfiguration(
            self.binding,
            self.factory.integration_type,
            MappingProxyType({}),
            OnlyResolvedIntegrationSecrets({}),
        )


def _install_test_tick_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    from onlyalpha.market_data.resolution import OnlyBarConstructionAlgorithmRegistry

    original = OnlyBarConstructionAlgorithmRegistry.__init__

    def initialize(registry) -> None:  # type: ignore[no-untyped-def]
        original(registry)
        registry.register_factory("TICK_BAR", 1, "TRADE", "BAR", lambda edge, *_: _TickCountExecutor(edge))

    monkeypatch.setattr(OnlyBarConstructionAlgorithmRegistry, "__init__", initialize)


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
        raise AssertionError("SIM validation must not create plugin resources")


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


def test_backtest_factory_is_selected_through_runtime_assembler(tmp_path: Path) -> None:
    services = only_default_engine_services()
    build = services.assembler.build(_plan("BACKTEST", tmp_path), tmp_path)
    assert build.runtime is not None
    assert build.runtime.runtime_type == "BACKTEST"
    build.runtime.close()


@pytest.mark.parametrize("target_minutes", (7, 15))
def test_derived_backtest_loads_only_provider_one_minute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_minutes: int
) -> None:
    plan = _plan("BACKTEST", tmp_path)
    native = OnlyFrozenStrategyRevisionStore(tmp_path / "research").load_verified(
        plan.assembly_plan.clusters[0].strategy.fingerprint
    )
    base = native.market_input_contract.bar_semantic
    target = OnlyBarSemantic.fixed_duration(target_minutes, alignment=base.formation.alignment)
    derived = replace(
        native,
        market_input_contract=OnlyStrategyMarketInputContract(
            target,
            OnlyBarConstructionRequirement.exact(
                OnlyBarConstructionRecipe.derived(target, base, algorithm_id="TIME_BAR")
            ),
        ),
    )
    publish_frozen_strategy_for_execution_test(tmp_path / "research", derived)
    cluster = replace(
        plan.assembly_plan.clusters[0], strategy=OnlyStrategyReferenceConfig(str(derived.strategy_fingerprint))
    )
    plan = replace(plan, assembly_plan=replace(plan.assembly_plan, clusters=(cluster,)))
    build = only_default_engine_services().assembler.build(plan, tmp_path)
    assert build.runtime is not None, build.failure_message
    runtime = build.runtime
    try:
        run_plan = runtime._run_plan._plan  # type: ignore[attr-defined]
        (historical,) = run_plan._input_plan.bar_requests
        assert {bar.semantic.window_minutes for bar in historical.bar_types} == {1}
        source = run_plan._source
        original_load = source.load_bars
        observed: list[frozenset[OnlyBarType]] = []

        def load_only_provider_input(request):
            observed.append(request.bar_types)
            if any(bar.semantic.window_minutes == target_minutes for bar in request.bar_types):
                raise AssertionError("Provider rejects derived Bars")
            return original_load(request)

        monkeypatch.setattr(source, "load_bars", load_only_provider_input)
        runtime.initialize()
        runtime.start()
        result = runtime.run()
        assert result.status == "COMPLETED"
        assert observed and all({bar.semantic.window_minutes for bar in bars} == {1} for bars in observed)
        assert (
            runtime._services.market_data_cache.latest_closed(  # type: ignore[attr-defined]
                OnlyBarType(native.universe.instruments[0], target)
            )
            is not None
        )
    finally:
        runtime.close()


def test_native_fifteen_minute_backtest_requests_fifteen_minutes(tmp_path: Path) -> None:
    plan = _plan("BACKTEST", tmp_path)
    native = OnlyFrozenStrategyRevisionStore(tmp_path / "research").load_verified(
        plan.assembly_plan.clusters[0].strategy.fingerprint
    )
    fifteen = OnlyBarSemantic.fixed_duration(
        15, alignment=native.market_input_contract.bar_semantic.formation.alignment
    )
    revision = replace(
        native,
        market_input_contract=OnlyStrategyMarketInputContract(
            fifteen, OnlyBarConstructionRequirement.exact(OnlyBarConstructionRecipe.provider_native(fifteen))
        ),
    )
    publish_frozen_strategy_for_execution_test(tmp_path / "research", revision)
    cluster = replace(
        plan.assembly_plan.clusters[0], strategy=OnlyStrategyReferenceConfig(str(revision.strategy_fingerprint))
    )
    plan = replace(plan, assembly_plan=replace(plan.assembly_plan, clusters=(cluster,)))
    build = only_default_engine_services().assembler.build(plan, tmp_path)
    assert build.runtime is not None, build.failure_message
    try:
        (historical,) = build.runtime._run_plan._plan._input_plan.bar_requests  # type: ignore[attr-defined]
        assert {bar.semantic.window_minutes for bar in historical.bar_types} == {15}
        build.runtime.initialize()
        build.runtime.start()
        assert build.runtime.run().status == "COMPLETED"
    finally:
        build.runtime.close()


def test_mixed_cluster_backtest_unions_only_provider_inputs(tmp_path: Path) -> None:
    plan = _plan("BACKTEST", tmp_path)
    native = OnlyFrozenStrategyRevisionStore(tmp_path / "research").load_verified(
        plan.assembly_plan.clusters[0].strategy.fingerprint
    )
    one = native.market_input_contract.bar_semantic
    seven = OnlyBarSemantic.fixed_duration(7, alignment=one.formation.alignment)
    fifteen = OnlyBarSemantic.fixed_duration(15, alignment=one.formation.alignment)
    recipes = (
        OnlyBarConstructionRecipe.provider_native(one),
        OnlyBarConstructionRecipe.derived(seven, one, algorithm_id="TIME_BAR"),
        OnlyBarConstructionRecipe.provider_native(fifteen),
    )
    clusters = []
    for index, recipe in enumerate(recipes):
        revision = replace(
            native,
            market_input_contract=OnlyStrategyMarketInputContract(
                recipe.target_semantic, OnlyBarConstructionRequirement.exact(recipe)
            ),
        )
        publish_frozen_strategy_for_execution_test(tmp_path / "research", revision)
        clusters.append(
            replace(
                plan.assembly_plan.clusters[0],
                cluster_id=OnlyClusterId(f"mixed-{index}"),
                strategy=OnlyStrategyReferenceConfig(str(revision.strategy_fingerprint)),
            )
        )
    plan = replace(plan, assembly_plan=replace(plan.assembly_plan, clusters=tuple(clusters)))
    build = only_default_engine_services().assembler.build(plan, tmp_path)
    assert build.runtime is not None, build.failure_message
    try:
        (historical,) = build.runtime._run_plan._plan._input_plan.bar_requests  # type: ignore[attr-defined]
        assert {bar.semantic.window_minutes for bar in historical.bar_types} == {1, 15}
    finally:
        build.runtime.close()


def test_trade_root_strategy_remains_bar_delivery_and_projects_historical_ticks(tmp_path: Path) -> None:
    plan, revision = _trade_root_plan("BACKTEST", tmp_path)
    graph = only_strategy_market_data_graph(revision)
    assert revision.market_input_contract.data_kind.value == "BAR"
    assert graph.provider_inputs == (OnlyTradeInputType(revision.universe.instruments[0]),)

    services = only_default_engine_services()
    services.assembler.components.data_sources.register(
        cast(
            OnlyDataSourceFactory,
            _DescriptorOnlyFactory(
                _descriptor(
                    "historical-ticks",
                    OnlyPluginType.DATA_SOURCE,
                    OnlyDataSourceCapabilities(historical_ticks=True),
                )
            ),
        ),
        origin=_test_origin(),
    )
    source = replace(plan.assembly_plan.data_sources[0], plugin_id="historical-ticks")
    plan = replace(plan, assembly_plan=replace(plan.assembly_plan, data_sources=(source,)))
    factory = OnlyBacktestRuntimeFactory()
    plugin_plan = factory._plugin_plan(  # noqa: SLF001
        OnlyRuntimeBuildRequest(plan, services.assembler.components, tmp_path)
    )
    assert plugin_plan.data_request.requested_capabilities.historical_ticks
    assert not plugin_plan.data_request.requested_capabilities.historical_bars
    assert plugin_plan.data_request.bar_types == {}


def test_trade_root_backtest_rejects_source_without_historical_ticks(tmp_path: Path) -> None:
    plan, _ = _trade_root_plan("BACKTEST", tmp_path)
    services = only_default_engine_services()
    services.assembler.components.data_sources.register(
        cast(
            OnlyDataSourceFactory,
            _DescriptorOnlyFactory(
                _descriptor(
                    "bar-history-only",
                    OnlyPluginType.DATA_SOURCE,
                    OnlyDataSourceCapabilities(historical_bars=True),
                )
            ),
        ),
        origin=_test_origin(),
    )
    source = replace(plan.assembly_plan.data_sources[0], plugin_id="bar-history-only")
    plan = replace(plan, assembly_plan=replace(plan.assembly_plan, data_sources=(source,)))

    with pytest.raises(ValueError, match="historical_ticks"):
        OnlyBacktestRuntimeFactory()._plugin_plan(  # noqa: SLF001
            OnlyRuntimeBuildRequest(plan, services.assembler.components, tmp_path)
        )


def test_trade_root_sim_projects_exact_tick_capabilities_and_instrument_scope(tmp_path: Path) -> None:
    services = only_default_engine_services()
    services.assembler.components.data_sources.register(
        cast(
            OnlyDataSourceFactory,
            _DescriptorOnlyFactory(
                _descriptor(
                    "tick-only",
                    OnlyPluginType.DATA_SOURCE,
                    OnlyDataSourceCapabilities(
                        historical_ticks=True,
                        live_ticks=True,
                        live_reconnect=True,
                    ),
                )
            ),
        ),
        origin=_test_origin(),
    )
    plan, revision = _trade_root_plan("SIM", tmp_path)
    source = replace(plan.assembly_plan.data_sources[0], plugin_id="tick-only")
    plan = replace(plan, assembly_plan=replace(plan.assembly_plan, data_sources=(source,)))
    request = OnlyRuntimeBuildRequest(plan, services.assembler.components, tmp_path)

    _, _, _, graph, capabilities = OnlySimRuntimeFactory()._validate(request)  # noqa: SLF001

    assert graph is not None
    assert {item.instrument_id for item in graph.provider_inputs} == set(revision.universe.instruments)
    assert capabilities == OnlyDataSourceCapabilities(
        historical_ticks=True,
        live_ticks=True,
        live_reconnect=True,
    )


@pytest.mark.parametrize(
    ("capabilities", "missing"),
    (
        (OnlyDataSourceCapabilities(live_ticks=True, live_reconnect=True), "historical_ticks"),
        (OnlyDataSourceCapabilities(historical_ticks=True, live_reconnect=True), "live_ticks"),
    ),
)
def test_trade_root_sim_rejects_missing_tick_capability(
    tmp_path: Path,
    capabilities: OnlyDataSourceCapabilities,
    missing: str,
) -> None:
    services = only_default_engine_services()
    services.assembler.components.data_sources.register(
        cast(
            OnlyDataSourceFactory,
            _DescriptorOnlyFactory(_descriptor("incomplete-ticks", OnlyPluginType.DATA_SOURCE, capabilities)),
        ),
        origin=_test_origin(),
    )
    plan, _ = _trade_root_plan("SIM", tmp_path)
    source = replace(plan.assembly_plan.data_sources[0], plugin_id="incomplete-ticks")
    plan = replace(plan, assembly_plan=replace(plan.assembly_plan, data_sources=(source,)))

    build = services.assembler.validate(plan, tmp_path)

    assert build.failure_code == "SIM_DATA_SOURCE_CAPABILITY_REQUIRED"
    assert missing in str(build.failure_message)


def test_trade_root_backtest_runs_provider_trades_to_strategy_deterministically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_test_tick_executor(monkeypatch)
    plan, _ = _trade_root_plan("BACKTEST", tmp_path)
    services = only_default_engine_services()
    source_factory = _TradeDataSourceFactory("trade-history", live=False)
    services.assembler.components.data_sources.register(
        cast(OnlyDataSourceFactory, source_factory),
        origin=_test_origin(),
    )
    source = replace(plan.assembly_plan.data_sources[0], plugin_id="trade-history")
    plan = replace(plan, assembly_plan=replace(plan.assembly_plan, data_sources=(source,)))

    fingerprints = []
    for _ in range(2):
        build = services.assembler.build(plan, tmp_path)
        assert build.runtime is not None, build.failure_message
        runtime = build.runtime
        try:
            input_plan = runtime._run_plan._plan._input_plan  # type: ignore[attr-defined]
            assert input_plan.bar_requests == ()
            assert len(input_plan.trade_requests) == 1
            runtime.initialize()
            runtime.start()
            result = runtime.run()
            assert result.status == "COMPLETED", runtime.market_data_audit_store.records()
            assert runtime.clusters[0].last_pipeline_result is not None
            fingerprints.append(result.determinism_fingerprint)
        finally:
            runtime.close()
    assert fingerprints[0] == fingerprints[1]


def test_trade_root_sim_bootstraps_and_continues_from_live_trades(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onlyalpha.market_data.pipeline import OnlyTradeConstructionUpdateResult

    _install_test_tick_executor(monkeypatch)
    plan, _ = _trade_root_plan("SIM", tmp_path)
    services = only_default_engine_services()
    source_factory = _TradeDataSourceFactory("trade-stream", live=True)
    services.assembler.components.data_sources.register(
        cast(OnlyDataSourceFactory, source_factory),
        origin=_test_origin(),
    )
    source = replace(plan.assembly_plan.data_sources[0], plugin_id="trade-stream")
    plan = replace(plan, assembly_plan=replace(plan.assembly_plan, data_sources=(source,)))
    build = services.assembler.build(plan, tmp_path)
    assert build.runtime is not None, build.failure_message
    runtime = build.runtime
    live_closed = Event()
    processor = runtime.market_data_processor
    original_after = processor._after_processing  # noqa: SLF001

    def observe(update, result) -> None:  # type: ignore[no-untyped-def]
        original_after(update, result)
        if isinstance(result.pipeline_result, OnlyTradeConstructionUpdateResult):
            live_closed.set()

    processor._after_processing = observe  # type: ignore[attr-defined]  # noqa: SLF001
    try:
        runtime.initialize()
        runtime.start()
        assert runtime.clusters[0].last_pipeline_result is not None
        bootstrap_result = runtime.clusters[0].last_pipeline_result
        subscription = runtime._streaming_subscription  # type: ignore[attr-defined]
        assert subscription.instrument_ids
        assert subscription.bar_types == frozenset()
        live_closed.clear()
        source_factory.created[-1].emit_live()
        assert live_closed.wait(2), "live Trade construction did not close a Bar"
        assert runtime.clusters[0].last_pipeline_result is not bootstrap_result
    finally:
        runtime.stop()
        runtime.close()


def test_trade_root_sim_uses_exact_integration_revision_data_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_test_tick_executor(monkeypatch)
    plan, _ = _trade_root_plan("SIM", tmp_path)
    factory = _TradeDataSourceFactory("trade-integration", live=True)
    resolver = _IntegrationResolver(factory)
    services = only_default_engine_services(integration_runtime_resolver=resolver)  # type: ignore[arg-type]
    services.assembler.components.data_sources.register(
        cast(OnlyDataSourceFactory, factory),
        origin=_test_origin(),
    )
    source = replace(
        plan.assembly_plan.data_sources[0],
        plugin_id="",
        extensions=MappingProxyType({}),
        configuration_mode=OnlyRuntimeConfigurationMode.INTEGRATION_REVISION,
        integration_binding=MappingProxyType(resolver.binding.to_dict()),
    )
    plan = replace(plan, assembly_plan=replace(plan.assembly_plan, data_sources=(source,)))

    build = services.assembler.build(plan, tmp_path)

    assert build.runtime is not None, build.failure_message
    runtime = build.runtime
    try:
        runtime.initialize()
        runtime.start()
        assert factory.created[-1].request.plugin_config == {}
        assert set(resolver.calls[-1]) == {"HISTORICAL_TICKS", "LIVE_TICKS", "LIVE_RECONNECT"}
    finally:
        runtime.stop()
        runtime.close()


@pytest.mark.parametrize(
    "capabilities",
    (
        OnlyDataSourceCapabilities(live_ticks=True, live_reconnect=True),
        OnlyDataSourceCapabilities(historical_ticks=True, live_reconnect=True),
    ),
)
def test_trade_root_sim_integration_revision_missing_tick_capability_fails_closed(
    tmp_path: Path,
    capabilities: OnlyDataSourceCapabilities,
) -> None:
    plan, _ = _trade_root_plan("SIM", tmp_path)
    factory = _TradeDataSourceFactory("trade-integration-incomplete", live=True)
    factory.descriptor = replace(factory.descriptor, capabilities=capabilities)
    factory.integration_type = replace(
        factory.integration_type,
        capabilities=only_integration_capability_ids(capabilities),
    )
    resolver = _IntegrationResolver(factory)
    services = only_default_engine_services(integration_runtime_resolver=resolver)  # type: ignore[arg-type]
    services.assembler.components.data_sources.register(
        cast(OnlyDataSourceFactory, factory),
        origin=_test_origin(),
    )
    source = replace(
        plan.assembly_plan.data_sources[0],
        plugin_id="",
        extensions=MappingProxyType({}),
        configuration_mode=OnlyRuntimeConfigurationMode.INTEGRATION_REVISION,
        integration_binding=MappingProxyType(resolver.binding.to_dict()),
    )
    plan = replace(plan, assembly_plan=replace(plan.assembly_plan, data_sources=(source,)))

    result = services.assembler.validate(plan, tmp_path)

    assert result.failure_code == "INTEGRATION_RUNTIME_CAPABILITY_MISSING"


def test_trade_root_sim_integration_revision_never_falls_back_without_resolver(tmp_path: Path) -> None:
    plan, _ = _trade_root_plan("SIM", tmp_path)
    factory = _TradeDataSourceFactory("trade-integration-no-resolver", live=True)
    binding = _IntegrationResolver(factory).binding
    services = only_default_engine_services()
    services.assembler.components.data_sources.register(
        cast(OnlyDataSourceFactory, factory),
        origin=_test_origin(),
    )
    source = replace(
        plan.assembly_plan.data_sources[0],
        plugin_id="",
        extensions=MappingProxyType({}),
        configuration_mode=OnlyRuntimeConfigurationMode.INTEGRATION_REVISION,
        integration_binding=MappingProxyType(binding.to_dict()),
    )
    plan = replace(plan, assembly_plan=replace(plan.assembly_plan, data_sources=(source,)))

    result = services.assembler.validate(plan, tmp_path)

    assert result.failure_code == "INTEGRATION_RUNTIME_RESOLVER_UNAVAILABLE"
    assert factory.created == []


def test_trade_root_sim_disconnect_recovers_provider_trade_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onlyalpha.runtime.streaming.phase import OnlyStreamingDataState, OnlyStreamingPhase

    _install_test_tick_executor(monkeypatch)
    plan, _ = _trade_root_plan("SIM", tmp_path)
    services = only_default_engine_services()
    source_factory = _TradeDataSourceFactory("trade-recovery", live=True)
    services.assembler.components.data_sources.register(
        cast(OnlyDataSourceFactory, source_factory),
        origin=_test_origin(),
    )
    source_config = replace(plan.assembly_plan.data_sources[0], plugin_id="trade-recovery")
    plan = replace(plan, assembly_plan=replace(plan.assembly_plan, data_sources=(source_config,)))
    build = services.assembler.build(plan, tmp_path)
    assert build.runtime is not None, build.failure_message
    runtime = build.runtime
    processed = Event()
    original_after = runtime.market_data_processor._after_processing  # noqa: SLF001

    def observe(update, result) -> None:  # type: ignore[no-untyped-def]
        original_after(update, result)
        if int(update.source_sequence) == 5:
            processed.set()

    runtime.market_data_processor._after_processing = observe  # type: ignore[attr-defined]  # noqa: SLF001
    try:
        runtime.initialize()
        runtime.start()
        source = source_factory.created[-1]
        source.emit_live(sequence=4, count=2)
        assert processed.wait(2), "live Trade prefix was not processed"
        before = runtime.clusters[0].last_pipeline_result
        source.recovery_updates = source._updates(source.request.clock.now_utc() - timedelta(seconds=1), 6)  # noqa: SLF001
        source.disconnect()

        runtime._recover_stale_or_disconnect(OnlyStreamingDataState.DISCONNECTED)  # noqa: SLF001

        assert runtime.streaming_phase is OnlyStreamingPhase.LIVE, (
            runtime.recovery_failure,
            runtime.processing_results[-1].failure,
        )
        assert runtime.recovery_failure is None
        assert runtime.clusters[0].last_pipeline_result is not before
        assert source.load_bar_calls == 0
        assert any(request.request_id.startswith("recovery-") for request in source.load_trade_calls)
        recovered_sequences = tuple(
            item.source_sequence for item in runtime.market_data_audit_store.records() if item.source_sequence == 6
        )
        assert recovered_sequences == (6,)
    finally:
        runtime.stop()
        runtime.close()


def test_trade_root_sim_restart_restores_pending_executor_and_trade_frontier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onlyalpha.market_data.pipeline import OnlyTradeConstructionUpdateResult

    _install_test_tick_executor(monkeypatch)
    plan, _ = _trade_root_plan("SIM", tmp_path)
    persistence = OnlyRuntimePersistenceConfig(
        OnlyRuntimePersistenceBackend.SQLITE,
        "trade-root.sqlite3",
        OnlyRuntimeCheckpointConfig(True),
    )
    plan = replace(
        plan,
        assembly_plan=replace(
            plan.assembly_plan,
            runtime=replace(plan.assembly_plan.runtime, persistence=persistence),
        ),
    )
    services = only_default_engine_services()
    source_factory = _TradeDataSourceFactory("trade-restart", live=True)
    services.assembler.components.data_sources.register(
        cast(OnlyDataSourceFactory, source_factory),
        origin=_test_origin(),
    )
    source_config = replace(plan.assembly_plan.data_sources[0], plugin_id="trade-restart")
    plan = replace(plan, assembly_plan=replace(plan.assembly_plan, data_sources=(source_config,)))

    first_build = services.assembler.build(plan, tmp_path)
    assert first_build.runtime is not None, first_build.failure_message
    first = first_build.runtime
    prefix_processed = Event()
    original_after = first.market_data_processor._after_processing  # noqa: SLF001

    def observe(update, result) -> None:  # type: ignore[no-untyped-def]
        original_after(update, result)
        if int(update.source_sequence) == 5:
            prefix_processed.set()

    first.market_data_processor._after_processing = observe  # type: ignore[attr-defined]  # noqa: SLF001
    first.initialize()
    first.start()
    source_factory.created[-1].emit_live(sequence=4, count=2)
    assert prefix_processed.wait(2), "partial TickBar prefix was not processed"
    checkpoint = first._semantic_lane.execute(first._create_verified_streaming_checkpoint)  # noqa: SLF001
    assert checkpoint.started
    first.stop()
    first.close()

    second_build = services.assembler.build(plan, tmp_path)
    assert second_build.runtime is not None, second_build.failure_message
    second = second_build.runtime
    source = source_factory.created[-1]
    source.recovery_updates = source._updates(source.request.clock.now_utc() - timedelta(seconds=1), 6)  # noqa: SLF001
    try:
        second.initialize()
        second.start()
        pipeline = next(
            item.pipeline_result
            for item in second.processing_results
            if isinstance(item.pipeline_result, OnlyTradeConstructionUpdateResult)
        )
        assert pipeline.input_trade.sequence == 6
        assert pipeline.constructed_bars[0].trade_count == 3
        assert tuple(
            item.source_sequence for item in second.market_data_audit_store.records() if item.source_sequence == 6
        ) == (6,)
    finally:
        second.stop()
        second.close()


@pytest.mark.parametrize(
    "code",
    (
        "INTEGRATION_RUNTIME_CATEGORY_MISMATCH",
        "INTEGRATION_RUNTIME_IMPLEMENTATION_MISMATCH",
        "INTEGRATION_RUNTIME_SECRET_UNAVAILABLE",
    ),
)
def test_backtest_factory_preserves_integration_runtime_error_codes(code: str) -> None:
    result = OnlyBacktestRuntimeFactory._failure(OnlyIntegrationRuntimeError(code))
    assert result.failure_code == code


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


def test_valid_sim_contract_is_operationally_accepted(tmp_path: Path) -> None:
    services = only_default_engine_services()

    validation = services.assembler.validate(_sim_plan(user_data_root=tmp_path), tmp_path)

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


def test_sim_rejects_historical_only_data_source(tmp_path: Path) -> None:
    def change(payload: dict[str, Any]) -> None:
        payload["data_sources"][0]["plugin"] = "synthetic"

    build = only_default_engine_services().assembler.validate(_sim_plan(change, tmp_path), tmp_path)

    assert build.failure_code == "SIM_DATA_SOURCE_CAPABILITY_REQUIRED"
    assert "live_bars" in str(build.failure_message)


def test_sim_rejects_live_only_data_source(tmp_path: Path) -> None:
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

    build = services.assembler.validate(_sim_plan(change, tmp_path), tmp_path)

    assert build.failure_code == "SIM_DATA_SOURCE_CAPABILITY_REQUIRED"
    assert "historical_bars" in str(build.failure_message)


def test_sim_requires_explicit_live_reconnect_capability(tmp_path: Path) -> None:
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

    build = services.assembler.validate(_sim_plan(change, tmp_path), tmp_path)

    assert build.failure_code == "SIM_DATA_SOURCE_RECONNECT_CAPABILITY_REQUIRED"
    assert "live_reconnect" in str(build.failure_message)


def test_trade_reference_profile_requires_live_trade_capability(tmp_path: Path) -> None:
    services = only_default_engine_services()
    factory = _DescriptorOnlyFactory(
        _descriptor(
            "bar-only-source",
            OnlyPluginType.DATA_SOURCE,
            OnlyDataSourceCapabilities(
                historical_bars=True,
                live_bars=True,
                live_reconnect=True,
            ),
        )
    )
    services.assembler.components.data_sources.register(
        cast(OnlyDataSourceFactory, factory),
        origin=_test_origin(),
    )

    def change(payload: dict[str, Any]) -> None:
        payload["data_sources"][0]["plugin"] = "bar-only-source"
        payload["runtime"]["extensions"]["execution_reference"] = {
            "profile_id": "last-trade-v1",
            "policy_version": 1,
            "kind": "LAST_TRADE",
            "fallback": "NONE",
        }

    build = services.assembler.validate(_sim_plan(change, tmp_path), tmp_path)

    assert build.failure_code == "SIM_DATA_SOURCE_CAPABILITY_REQUIRED"
    assert "live_ticks" in str(build.failure_message)


def test_trade_reference_profile_accepts_provider_neutral_live_trade_capability(tmp_path: Path) -> None:
    services = only_default_engine_services()
    factory = _DescriptorOnlyFactory(
        _descriptor(
            "canonical-trade-source",
            OnlyPluginType.DATA_SOURCE,
            OnlyDataSourceCapabilities(
                historical_bars=True,
                live_bars=True,
                live_ticks=True,
                live_reconnect=True,
            ),
        )
    )
    services.assembler.components.data_sources.register(
        cast(OnlyDataSourceFactory, factory),
        origin=_test_origin(),
    )

    def change(payload: dict[str, Any]) -> None:
        payload["data_sources"][0]["plugin"] = "canonical-trade-source"
        payload["runtime"]["extensions"]["execution_reference"] = {
            "profile_id": "last-trade-v1",
            "policy_version": 1,
            "kind": "LAST_TRADE",
            "fallback": "NONE",
            "maximum_deviation_rate": "0.05",
        }

    plan = _sim_plan(change, tmp_path)
    build = services.assembler.validate(plan, tmp_path)

    assert build.failure_code is None
    *_, capabilities = OnlySimRuntimeFactory()._validate(  # noqa: SLF001
        OnlyRuntimeBuildRequest(plan, services.assembler.components, tmp_path)
    )
    assert capabilities == OnlyDataSourceCapabilities(
        historical_bars=True,
        live_bars=True,
        live_ticks=True,
        live_reconnect=True,
    )


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
