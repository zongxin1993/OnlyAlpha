from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from onlyalpha_plugin_broker_virtual import OnlyVirtualBrokerFactory, OnlyVirtualBrokerGateway
from onlyalpha_plugin_broker_virtual.factory import OnlyVirtualBrokerPluginConfig

from onlyalpha.config import OnlyBrokerFeeContractConfig, OnlyClusterRunConfig, OnlyRuntimePersistenceConfig
from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.execution import (
    OnlyExecutionEventDeliveryMode,
    OnlyExecutionMutationStatus,
    OnlyExecutionProcessingResult,
    OnlyExecutionProcessingStatus,
)
from onlyalpha.fee.broker_contract import only_simulation_zero_broker_fee_contract
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
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
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


class OnlyFirstCommitTailFaultFactory:
    def __init__(self) -> None:
        self._delegate = OnlyDefaultRuntimePersistenceStoreFactory()

    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyFailOnceRuntimePersistenceStore:
        return OnlyFailOnceRuntimePersistenceStore(
            self._delegate.create(request),
            OnlyTestRuntimePersistenceFault.AFTER_COMMIT,
            operation_kind=OnlyRuntimeOperationKind.TRADE_FILL,
        )


def _same_bar_config(user_data_root: Path) -> OnlyClusterRunConfig:
    baseline = _sqlite_config(user_data_root)
    actions = (
        {
            "action_id": "INITIAL_ORDER",
            "sequence": 1,
            "type": "SUBMIT_ORDER",
            "instrument_id": "TESTETF.XSHG",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": "100",
            "price": "1000.00",
            "offset": "OPEN",
        },
        {
            "action_id": "POSITION_CONTINUATION",
            "sequence": 2,
            "type": "SUBMIT_ORDER",
            "instrument_id": "TESTETF.XSHG",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": "100",
            "price": "1000.00",
            "offset": "OPEN",
        },
    )
    return replace(
        baseline,
        runtime=replace(baseline.runtime, end_time=baseline.runtime.start_time.replace(minute=40)),  # type: ignore[union-attr]
        brokers=(replace(baseline.brokers[0], plugin_id=_SAME_BAR_DESCRIPTOR.plugin_id),),
        accounts=(
            replace(
                baseline.accounts[0],
                broker_fee_contract=OnlyBrokerFeeContractConfig(
                    "TEST_SAME_BAR_BROKER_SIMULATION_ZERO_BROKER_FEES", "1"
                ),
            ),
        ),
        cluster=replace(baseline.cluster, scenario_actions=actions),  # type: ignore[arg-type]
    )


def _services(*, with_fault: bool = False) -> OnlyEngineServices:
    services = only_default_engine_services(
        runtime_persistence_store_factory=OnlyFirstCommitTailFaultFactory() if with_fault else None
    )
    services.assembler.components.brokers.register(
        OnlySameBarContinuationTestBrokerFactory(),
        origin=OnlyPluginOrigin(OnlyPluginOriginType.TEST, __name__),
    )
    services.assembler.components.broker_fee_contracts.register(
        only_simulation_zero_broker_fee_contract(_SAME_BAR_DESCRIPTOR.plugin_id)
    )
    return services


def test_engine_recovers_tail_then_commits_same_bar_continuation(tmp_path: Path) -> None:
    config = _same_bar_config(tmp_path)
    engine_id = OnlyEngineId("same-bar-continuation")
    engine_a = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services(with_fault=True))
    engine_a.add_cluster(config)
    assert engine_a.run().status == "FAILED"

    runtime_id = engine_a.runtime_sessions[0].runtime_id
    state_path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)
    reader = OnlySqliteRuntimePersistenceStore(state_path)
    original_tail = reader.records(runtime_id)
    assert len(original_tail) == 3
    assert original_tail[0].operation_kind is OnlyRuntimeOperationKind.ORDER_INTENT
    assert original_tail[0].projection_ready
    assert original_tail[1].operation_kind is OnlyRuntimeOperationKind.ORDER_ACCEPTED
    assert original_tail[1].projection_ready
    assert original_tail[2].operation_kind is OnlyRuntimeOperationKind.TRADE_FILL
    assert not original_tail[2].projection_ready
    original_transaction_id = original_tail[2].transaction_id
    reader.close()

    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services())
    engine_b.add_cluster(config)
    recovered = engine_b.run()
    assert recovered.status == "COMPLETED", recovered.failures

    reopened = OnlySqliteRuntimePersistenceStore(state_path)
    transactions = reopened.records(runtime_id)
    assert tuple(item.execution_sequence for item in transactions[:6]) == (1, 2, 3, 4, 5, 6)
    assert transactions[2].transaction_id == original_transaction_id
    assert all(item.projection_ready for item in transactions[:6])
    continuation_outbox = tuple(
        item for item in reopened.outbox_records(runtime_id) if item.key.execution_sequence in {5, 6}
    )
    assert continuation_outbox
    reopened.close()
    continuation_results = tuple(
        item
        for item in engine_b.runtime_sessions[0].runtime.broker_results
        if isinstance(item, OnlyExecutionProcessingResult)
        and item.update_id in {transactions[4].fact.broker_update_id, transactions[5].fact.broker_update_id}
    )
    assert len(continuation_results) == 2
    assert all(item.status is OnlyExecutionProcessingStatus.APPLIED for item in continuation_results)
    assert all(item.delivery_intent.mode is OnlyExecutionEventDeliveryMode.NONE for item in continuation_results)
    assert all(
        step.status is OnlyExecutionMutationStatus.APPLIED
        for item in continuation_results
        for step in item.mutation_bundle.steps
    )
    diagnostic = engine_b.runtime_sessions[0].runtime.runtime_recovery_diagnostics[-1]
    assert diagnostic.continuation_transaction_count == 3

    baseline_root = tmp_path / "baseline"
    baseline_engine = OnlyEngine(OnlyEngineConfig(engine_id, baseline_root), services=_services())
    baseline_engine.add_cluster(_same_bar_config(baseline_root))
    baseline = baseline_engine.run()
    assert baseline.status == "COMPLETED"
    assert only_backtest_business_projection(recovered.runtime_results[0]) == only_backtest_business_projection(
        baseline.runtime_results[0]
    )
