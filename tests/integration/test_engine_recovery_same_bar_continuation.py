import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from onlyalpha_plugin_broker_virtual import OnlyVirtualBrokerFactory, OnlyVirtualBrokerGateway
from onlyalpha_plugin_broker_virtual.factory import OnlyVirtualBrokerPluginConfig
from onlyalpha_test_plugin.macd_plugin import (
    OnlyTestMacdFactorSnapshot,
    OnlyTestMacdStrategy,
    OnlyTestMacdStrategyConfig,
)

from onlyalpha.config import OnlyClusterRunConfig, OnlyRuntimePersistenceConfig
from onlyalpha.domain.enums import OnlyOrderSide, OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.execution import (
    OnlyExecutionEventDeliveryMode,
    OnlyExecutionMutationStatus,
    OnlyExecutionProcessingResult,
    OnlyExecutionProcessingStatus,
)
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.plugin.api import (
    ONLYALPHA_PLUGIN_API_VERSION,
    OnlyBrokerComponent,
    OnlyBrokerCreateRequest,
    OnlyBrokerPluginCapabilities,
    OnlyCheckpointCapability,
    OnlyPluginDescriptor,
    OnlyPluginType,
    OnlyPluginValidationIssue,
)
from onlyalpha.plugin.descriptor import OnlyPluginOrigin, OnlyPluginOriginType
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.defaults import OnlyEngineServices, only_default_engine_services
from onlyalpha.runtime.persistence.factory import (
    OnlyDefaultRuntimePersistenceStoreFactory,
    OnlyRuntimePersistenceStoreCreateRequest,
)
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from onlyalpha.strategy.context import OnlyStrategyBarContext
from tests.execution.support.execution_fault_injection import (
    OnlyFailOnceRuntimePersistenceStore,
    OnlyTestRuntimePersistenceFault,
)
from tests.integration.test_engine_continuous_restart import _sqlite_config

_SAME_BAR_DESCRIPTOR = OnlyPluginDescriptor(
    "test-same-bar-broker",
    OnlyPluginType.BROKER,
    "0.1.0",
    ONLYALPHA_PLUGIN_API_VERSION,
    "OnlyAlpha Same-Bar Recovery Test Broker",
    "OnlyAlpha Tests",
    OnlyBrokerPluginCapabilities(
        submit_order=True,
        cancel_order=True,
        query_orders=True,
        query_trades=True,
        query_account=True,
        query_positions=True,
        simulated_execution=True,
        supports_runtime_checkpoint=OnlyCheckpointCapability.CHECKPOINTABLE,
        checkpoint_schema_version=1,
    ),
)


class OnlySameBarContinuationTestBrokerGateway(OnlyVirtualBrokerGateway):
    """Keep the first fill next-bar, then fill newly accepted orders after Strategy."""

    @property
    def plugin_descriptor(self) -> OnlyPluginDescriptor:
        return _SAME_BAR_DESCRIPTOR

    def run_due(self) -> int:
        processed = super().run_due()
        if self._trade_sequence == 0:
            return processed
        for order in self.order_store.open(self.config.account_id):
            if order.status is not OnlyOrderStatus.ACCEPTED:
                continue
            if self._accepted_bar.get(order.order_id) != self._bar_sequence:
                continue
            bar = self._latest_bars.get(order.instrument_id)
            if bar is None:
                continue
            remaining = type(order.quantity)(
                order.quantity.value - order.filled_quantity.value,
                order.quantity.precision,
            )
            self._execute(order, bar.close, remaining, OnlyTimestamp.from_datetime(bar.ts_event))
        return processed + super().run_due()


class OnlySameBarContinuationTestBrokerFactory:
    def __init__(self) -> None:
        self._delegate = OnlyVirtualBrokerFactory()

    @property
    def descriptor(self) -> OnlyPluginDescriptor:
        return _SAME_BAR_DESCRIPTOR

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyVirtualBrokerPluginConfig:
        return self._delegate.parse_config(extensions)

    def validate_request(self, request: OnlyBrokerCreateRequest) -> Sequence[OnlyPluginValidationIssue]:
        return self._delegate.validate_request(request)

    def create(self, request: OnlyBrokerCreateRequest) -> OnlyBrokerComponent:
        component = self._delegate.create(request)
        gateway = component.gateway
        if not isinstance(gateway, OnlyVirtualBrokerGateway):
            raise TypeError("same-Bar test Broker delegate returned an unexpected gateway")
        test_gateway = OnlySameBarContinuationTestBrokerGateway(
            gateway.config,
            request.runtime_id,
            request.clock,
            request.broker_inbound_queue.put,
        )
        return OnlyBrokerComponent(test_gateway, test_gateway, test_gateway)


class OnlyPositionTriggeredContinuationStrategy(OnlyTestMacdStrategy):
    def __init__(self, config: OnlyTestMacdStrategyConfig) -> None:
        super().__init__(config)
        self._continuation_submitted = False

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        self._callback_count += 1
        factor = context.strategy.factors.require(self.config.required_factor_ids[0], OnlyTestMacdFactorSnapshot)
        assert self.config.instrument_id is not None
        assert self.config.trade_quantity is not None
        allocation = context.strategy.positions.cluster.get(self.config.instrument_id)
        has_position = allocation is not None and allocation.total_quantity.value > 0
        if self._callback_count == 1:
            self._submit(context, OnlyOrderSide.BUY, self.config.trade_quantity, factor, "INITIAL_ORDER")
            self._has_entered = True
        elif has_position and not self._continuation_submitted and not context.strategy.orders.list_open():
            self._submit(context, OnlyOrderSide.BUY, self.config.trade_quantity, factor, "POSITION_CONTINUATION")
            self._continuation_submitted = True

    def capture_checkpoint(self) -> object:
        parent = super().capture_checkpoint()
        assert isinstance(parent, dict)
        return {**parent, "continuation_submitted": self._continuation_submitted}

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            raise ValueError("same-Bar continuation Strategy checkpoint must be an object")
        super().restore_checkpoint(payload)
        self._continuation_submitted = bool(payload["continuation_submitted"])


class OnlyFirstCommitTailFaultFactory:
    def __init__(self) -> None:
        self._delegate = OnlyDefaultRuntimePersistenceStoreFactory()

    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyFailOnceRuntimePersistenceStore:
        return OnlyFailOnceRuntimePersistenceStore(
            self._delegate.create(request),
            OnlyTestRuntimePersistenceFault.AFTER_COMMIT,
        )


def _same_bar_config() -> OnlyClusterRunConfig:
    baseline = _sqlite_config()
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["end_time"] = "2026-01-05T01:40:00Z"
    payload["brokers"][0]["plugin"] = _SAME_BAR_DESCRIPTOR.plugin_id
    payload["strategy"]["class_path"] = (
        "tests.integration.test_engine_recovery_same_bar_continuation:OnlyPositionTriggeredContinuationStrategy"
    )
    return OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path)


def _services(*, with_fault: bool = False) -> OnlyEngineServices:
    services = only_default_engine_services(
        runtime_persistence_store_factory=OnlyFirstCommitTailFaultFactory() if with_fault else None
    )
    services.brokers.register(
        OnlySameBarContinuationTestBrokerFactory(),
        origin=OnlyPluginOrigin(OnlyPluginOriginType.TEST, __name__),
    )
    return services


def test_engine_recovers_tail_then_commits_same_bar_continuation(tmp_path: Path) -> None:
    config = _same_bar_config()
    engine_id = OnlyEngineId("same-bar-continuation")
    engine_a = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services(with_fault=True))
    engine_a.add_cluster(config)
    assert engine_a.run().status == "FAILED"

    runtime_id = engine_a.runtime_sessions[0].runtime_id
    state_path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)
    reader = OnlySqliteRuntimePersistenceStore(state_path)
    original_tail = reader.records(runtime_id)
    assert len(original_tail) == 1
    original_transaction_id = original_tail[0].transaction_id
    reader.close()

    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services())
    engine_b.add_cluster(config)
    recovered = engine_b.run()
    assert recovered.status == "COMPLETED", recovered.failures

    reopened = OnlySqliteRuntimePersistenceStore(state_path)
    transactions = reopened.records(runtime_id)
    assert tuple(item.execution_sequence for item in transactions[:2]) == (1, 2)
    assert transactions[0].transaction_id == original_transaction_id
    assert transactions[1].projection_ready
    continuation_outbox = tuple(
        item for item in reopened.outbox_records(runtime_id) if item.key.execution_sequence == 2
    )
    assert continuation_outbox
    reopened.close()
    continuation_result = next(
        item
        for item in engine_b.runtime_sessions[0].runtime.broker_results
        if isinstance(item, OnlyExecutionProcessingResult) and item.update_id == transactions[1].fact.broker_update_id
    )
    assert continuation_result.status is OnlyExecutionProcessingStatus.APPLIED
    assert continuation_result.delivery_intent.mode is OnlyExecutionEventDeliveryMode.NONE
    assert all(item.status is OnlyExecutionMutationStatus.APPLIED for item in continuation_result.mutation_bundle.steps)
    diagnostic = engine_b.runtime_sessions[0].runtime.runtime_recovery_diagnostics[-1]
    assert diagnostic.continuation_transaction_count == 1

    baseline_engine = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path / "baseline"), services=_services())
    baseline_engine.add_cluster(config)
    baseline = baseline_engine.run()
    assert baseline.status == "COMPLETED"
    assert only_backtest_business_projection(recovered.runtime_results[0]) == only_backtest_business_projection(
        baseline.runtime_results[0]
    )
