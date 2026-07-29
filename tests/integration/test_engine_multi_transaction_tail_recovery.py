import json
from collections.abc import Mapping
from pathlib import Path

from onlyalpha_test_plugin.macd_plugin import (
    OnlyTestMacdFactorSnapshot,
    OnlyTestMacdStrategy,
    OnlyTestMacdStrategyConfig,
)

from onlyalpha.config import OnlyClusterRunConfig, OnlyRuntimePersistenceConfig
from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.defaults import only_default_engine_services
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


class OnlyMultiOrderCheckpointStrategy(OnlyTestMacdStrategy):
    def __init__(self, config: OnlyTestMacdStrategyConfig) -> None:
        super().__init__(config)
        self._second_order_submitted = False
        self._continuation_order_submitted = False
        self._new_transaction_submitted = False

    def on_bar(self, context: OnlyStrategyBarContext) -> None:
        previous = self._request_sequence
        super().on_bar(context)
        if self._request_sequence == previous + 1 and not self._second_order_submitted:
            factor = context.strategy.factors.require(self.config.required_factor_ids[0], OnlyTestMacdFactorSnapshot)
            assert self.config.trade_quantity is not None
            self._submit(context, OnlyOrderSide.BUY, self.config.trade_quantity, factor, "GOLDEN_CROSS_SECOND")
            self._second_order_submitted = True
        if (
            self._callback_count == 30
            and not self._continuation_order_submitted
            and not context.strategy.orders.list_open()
        ):
            factor = context.strategy.factors.require(self.config.required_factor_ids[0], OnlyTestMacdFactorSnapshot)
            assert self.config.instrument_id is not None
            allocation = context.strategy.positions.cluster.get(self.config.instrument_id)
            assert allocation is not None
            self._submit(
                context,
                OnlyOrderSide.SELL,
                allocation.available_quantity,
                factor,
                "CONTINUATION_ORDER",
            )
            self._continuation_order_submitted = True
        if (
            self._callback_count == 35
            and not self._new_transaction_submitted
            and not context.strategy.orders.list_open()
        ):
            assert self.config.instrument_id is not None
            allocation = context.strategy.positions.cluster.get(self.config.instrument_id)
            if allocation is not None and allocation.total_quantity.value > 0:
                return
            factor = context.strategy.factors.require(self.config.required_factor_ids[0], OnlyTestMacdFactorSnapshot)
            assert self.config.trade_quantity is not None
            self._submit(context, OnlyOrderSide.BUY, self.config.trade_quantity, factor, "POST_RECOVERY_BUY")
            self._new_transaction_submitted = True

    def capture_checkpoint(self) -> object:
        parent = super().capture_checkpoint()
        assert isinstance(parent, dict)
        return {
            **parent,
            "continuation_order_submitted": self._continuation_order_submitted,
            "new_transaction_submitted": self._new_transaction_submitted,
            "second_order_submitted": self._second_order_submitted,
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            raise ValueError("multi-order Strategy checkpoint must be an object")
        super().restore_checkpoint(payload)
        self._continuation_order_submitted = bool(payload["continuation_order_submitted"])
        self._new_transaction_submitted = bool(payload["new_transaction_submitted"])
        self._second_order_submitted = bool(payload["second_order_submitted"])


class OnlySecondCommitFaultFactory:
    def __init__(self) -> None:
        self._delegate = OnlyDefaultRuntimePersistenceStoreFactory()

    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyFailOnceRuntimePersistenceStore:
        return OnlyFailOnceRuntimePersistenceStore(
            self._delegate.create(request),
            OnlyTestRuntimePersistenceFault.AFTER_COMMIT,
            fault_after=1,
        )


def _multi_order_config() -> OnlyClusterRunConfig:
    baseline = _sqlite_config()
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["end_time"] = "2026-01-05T02:30:00Z"
    payload["strategy"]["class_path"] = (
        "tests.integration.test_engine_multi_transaction_tail_recovery:OnlyMultiOrderCheckpointStrategy"
    )
    return OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path)


def test_engine_recovers_ready_prefix_and_unprojected_suffix_then_continues(tmp_path: Path) -> None:
    config = _multi_order_config()
    engine_id = OnlyEngineId("multi-tail-restart")
    engine_a = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(runtime_persistence_store_factory=OnlySecondCommitFaultFactory()),
    )
    engine_a.add_cluster(config)
    assert engine_a.run().status == "FAILED"
    failed_runtime = engine_a.runtime_sessions[0].runtime
    assert failed_runtime.historical_replay_service.events
    assert failed_runtime.historical_replay_service.events[-1].result.status.value == "APPLIED"
    assert failed_runtime.result_progress.snapshot().processed_bar_count > 0
    assert config.end_time is not None
    assert failed_runtime.historical_replay_service.events[-1].update.ts_event.to_datetime() < config.end_time
    runtime_id = engine_a.runtime_sessions[0].runtime_id
    path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)
    reader = OnlySqliteRuntimePersistenceStore(path)
    tail = reader.records(runtime_id)
    assert tuple(item.execution_sequence for item in tail) == (1, 2)
    assert tuple(item.projection_ready for item in tail) == (True, False)
    reader.close()

    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    engine_b.add_cluster(config)
    recovered = engine_b.run()
    replay_errors = tuple(
        dispatch.error_message
        for event in engine_b.runtime_sessions[0].runtime.historical_replay_service.events
        for dispatch in event.result.dispatches
        if dispatch.error_message is not None
    )
    diagnostic_messages = tuple(
        failure.message for item in recovered.runtime_results for failure in item.diagnostics.failures
    )
    assert not diagnostic_messages, "\n".join(diagnostic_messages)
    assert recovered.status == "COMPLETED", (
        recovered.failures,
        replay_errors,
    )
    diagnostic = engine_b.runtime_sessions[0].runtime.runtime_recovery_diagnostics[-1]
    assert diagnostic.rehydrated_transaction_count == 1
    assert diagnostic.recovered_transaction_count == 1
    assert len(recovered.runtime_results[0].trades) > 2

    baseline_engine = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path / "baseline"))
    baseline_engine.add_cluster(config)
    baseline = baseline_engine.run()
    assert baseline.status == "COMPLETED"
    assert recovered.runtime_results[0].trades == baseline.runtime_results[0].trades
    assert recovered.runtime_results[0].result_fingerprint == baseline.runtime_results[0].result_fingerprint
    assert only_backtest_business_projection(recovered.runtime_results[0]) == only_backtest_business_projection(
        baseline.runtime_results[0]
    )
