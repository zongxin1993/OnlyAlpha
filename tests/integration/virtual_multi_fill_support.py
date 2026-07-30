import json
from pathlib import Path

from onlyalpha_plugin_broker_virtual import OnlyVirtualBrokerGateway
from onlyalpha_test_plugin.macd_plugin import OnlyTestMacdFactorSnapshot, OnlyTestMacdStrategy

from onlyalpha.config import OnlyClusterRunConfig, OnlyRuntimePersistenceConfig
from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.execution import OnlyExecutionTransactionOutboxKey
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.checkpoint.model import OnlyRuntimeCheckpoint
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.persistence.factory import (
    OnlyDefaultRuntimePersistenceStoreFactory,
    OnlyRuntimePersistenceStoreCreateRequest,
)
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStorePort
from onlyalpha.strategy.context import OnlyStrategyBarContext
from tests.execution.support.execution_fault_injection import (
    OnlyFailOnceRuntimePersistenceStore,
    OnlyTestRuntimePersistenceFault,
)
from tests.integration.test_engine_continuous_restart import _sqlite_config


class OnlyFirstBarBuyStrategy(OnlyTestMacdStrategy):
    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        self._callback_count += 1
        if self._has_entered:
            return
        factor = context.strategy.factors.require(self.config.required_factor_ids[0], OnlyTestMacdFactorSnapshot)
        assert self.config.trade_quantity is not None
        self._submit(context, OnlyOrderSide.BUY, self.config.trade_quantity, factor, "FIRST_BAR_BUY")
        self._has_entered = True


class OnlyRoundTripLongCloseStrategy(OnlyTestMacdStrategy):
    """Open once, then close the settled Generic-T0 long through the same Broker Fill Plan."""

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        self._callback_count += 1
        factor = context.strategy.factors.require(self.config.required_factor_ids[0], OnlyTestMacdFactorSnapshot)
        assert self.config.instrument_id is not None
        assert self.config.trade_quantity is not None
        allocation = context.strategy.positions.cluster.get(self.config.instrument_id)
        has_open_order = bool(context.strategy.orders.list_open())
        if self._callback_count == 1:
            self._submit(context, OnlyOrderSide.BUY, self.config.trade_quantity, factor, "ROUND_TRIP_OPEN")
            self._has_entered = True
            return
        if (
            allocation is not None
            and allocation.total_quantity.value > 0
            and allocation.available_quantity.value > 0
            and not has_open_order
            and not self._exit_pending
        ):
            self._submit(
                context,
                OnlyOrderSide.SELL,
                allocation.available_quantity,
                factor,
                "ROUND_TRIP_LONG_CLOSE",
            )
            self._exit_pending = True


def only_virtual_multi_fill_config(
    *,
    same_bar: bool = False,
    fill_latency_ns: int = 0,
    long_close: bool = False,
) -> OnlyClusterRunConfig:
    baseline = _sqlite_config()
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["end_time"] = "2026-01-05T02:00:00Z"
    payload["brokers"][0]["extensions"]["matching"]["partial_fill"] = {
        "mode": "SCHEDULE",
        "dispatch_mode": "ALL_DUE" if same_bar else "ONE_PER_BAR",
        "steps": [
            {"bar_offset": 1, "quantity": "300"},
            {"bar_offset": 1 if same_bar else 2, "quantity": "400"},
            {"bar_offset": 2 if same_bar else 3, "quantity": "300"},
        ],
    }
    payload["brokers"][0]["extensions"]["latency"] = {"fill_ns": fill_latency_ns}
    payload["strategy"]["class_path"] = (
        "tests.integration.virtual_multi_fill_support:OnlyRoundTripLongCloseStrategy"
        if long_close
        else "tests.integration.virtual_multi_fill_support:OnlyFirstBarBuyStrategy"
    )
    return OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path)


class OnlyMultiFillFaultStoreFactory:
    def __init__(self, fault: OnlyTestRuntimePersistenceFault, *, fault_after: int = 0) -> None:
        self._delegate = OnlyDefaultRuntimePersistenceStoreFactory()
        self._fault = fault
        self._fault_after = fault_after

    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyFailOnceRuntimePersistenceStore:
        return OnlyFailOnceRuntimePersistenceStore(
            self._delegate.create(request),
            self._fault,
            fault_after=self._fault_after,
        )


class OnlyPlanCursorCheckpointFailureStore:
    def __init__(self, delegate: OnlyRuntimePersistenceStorePort, target_cursor: int, plan_index: int = 0) -> None:
        self._delegate = delegate
        self._target_cursor = target_cursor
        self._plan_index = plan_index
        self._failed = False

    def write_checkpoint(self, checkpoint: OnlyRuntimeCheckpoint, *, retain_last: int) -> None:
        self._delegate.write_checkpoint(checkpoint, retain_last=retain_last)
        broker = next(item for item in checkpoint.components if item.component_id == "broker.virtual")
        payload = json.loads(broker.payload)
        plans = payload.get("fill_plans", [])
        if (
            len(plans) > self._plan_index
            and plans[self._plan_index]["next_step_index"] == self._target_cursor
            and not self._failed
        ):
            self._failed = True
            raise RuntimeError("TEST_MULTI_FILL_CHECKPOINT_CURSOR_FAILURE")

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


class OnlyPlanCursorCheckpointFailureStoreFactory:
    def __init__(self, target_cursor: int, *, plan_index: int = 0) -> None:
        self._delegate = OnlyDefaultRuntimePersistenceStoreFactory()
        self._target_cursor = target_cursor
        self._plan_index = plan_index

    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyRuntimePersistenceStorePort:
        return OnlyPlanCursorCheckpointFailureStore(  # type: ignore[return-value]
            self._delegate.create(request),
            self._target_cursor,
            self._plan_index,
        )


class OnlyOutboxCheckpointFailureStore:
    def __init__(self, delegate: OnlyRuntimePersistenceStorePort, minimum_execution_sequence: int = 1) -> None:
        self._delegate = delegate
        self._minimum_execution_sequence = minimum_execution_sequence

    def mark_published(self, key: OnlyExecutionTransactionOutboxKey, published_at: OnlyTimestamp) -> None:
        if key.execution_sequence >= self._minimum_execution_sequence:
            raise RuntimeError("TEST_MULTI_FILL_OUTBOX_PUBLICATION_FAILURE")
        self._delegate.mark_published(key, published_at)

    def write_checkpoint(self, checkpoint: OnlyRuntimeCheckpoint, *, retain_last: int) -> None:
        if (
            checkpoint.header.pending_outbox_count > 0
            and checkpoint.header.covered_execution_sequence >= self._minimum_execution_sequence
        ):
            raise RuntimeError("TEST_MULTI_FILL_OUTBOX_CHECKPOINT_FAILURE")
        self._delegate.write_checkpoint(checkpoint, retain_last=retain_last)

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


class OnlyOutboxCheckpointFailureStoreFactory:
    def __init__(self, *, minimum_execution_sequence: int = 1) -> None:
        self._delegate = OnlyDefaultRuntimePersistenceStoreFactory()
        self._minimum_execution_sequence = minimum_execution_sequence

    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyRuntimePersistenceStorePort:
        return OnlyOutboxCheckpointFailureStore(  # type: ignore[return-value]
            self._delegate.create(request),
            self._minimum_execution_sequence,
        )


def only_assert_multi_fill_recovery_equivalence(
    tmp_path: Path,
    engine_id: OnlyEngineId,
    *,
    factory: object,
    config: OnlyClusterRunConfig | None = None,
) -> tuple[OnlyEngine, OnlyEngine]:
    selected = config or only_virtual_multi_fill_config()
    engine_a = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(runtime_persistence_store_factory=factory),  # type: ignore[arg-type]
    )
    engine_a.add_cluster(selected)
    failed = engine_a.run()
    assert failed.status == "FAILED"
    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    engine_b.add_cluster(selected)
    recovered = engine_b.run()
    assert recovered.status == "COMPLETED", recovered.failures
    baseline = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path / "baseline"))
    baseline.add_cluster(selected)
    expected = baseline.run()
    assert expected.status == "COMPLETED", expected.failures
    actual_result = recovered.runtime_results[0]
    expected_result = expected.runtime_results[0]
    assert actual_result.orders == expected_result.orders
    assert actual_result.trades == expected_result.trades
    assert actual_result.final_positions == expected_result.final_positions
    assert actual_result.final_allocations == expected_result.final_allocations
    assert actual_result.final_account == expected_result.final_account
    assert actual_result.final_ledgers == expected_result.final_ledgers
    assert actual_result.result_fingerprint == expected_result.result_fingerprint
    assert only_backtest_business_projection(actual_result) == only_backtest_business_projection(expected_result)
    recovered_broker = engine_b.runtime_sessions[0].runtime.broker_gateway
    baseline_broker = baseline.runtime_sessions[0].runtime.broker_gateway
    assert isinstance(recovered_broker, OnlyVirtualBrokerGateway)
    assert isinstance(baseline_broker, OnlyVirtualBrokerGateway)
    assert recovered_broker.capture_checkpoint() == baseline_broker.capture_checkpoint()
    recovered_manifests = tuple(
        path for path in tmp_path.rglob("artifact_manifest.json") if not path.is_relative_to(tmp_path / "baseline")
    )
    baseline_manifests = tuple((tmp_path / "baseline").rglob("artifact_manifest.json"))
    assert len(recovered_manifests) == len(baseline_manifests) == 1
    assert json.loads(recovered_manifests[0].read_text(encoding="utf-8")) == json.loads(
        baseline_manifests[0].read_text(encoding="utf-8")
    )
    return engine_a, engine_b


__all__ = [
    "OnlyFirstBarBuyStrategy",
    "OnlyRoundTripLongCloseStrategy",
    "OnlyMultiFillFaultStoreFactory",
    "OnlyOutboxCheckpointFailureStoreFactory",
    "OnlyPlanCursorCheckpointFailureStoreFactory",
    "only_assert_multi_fill_recovery_equivalence",
    "only_virtual_multi_fill_config",
]
