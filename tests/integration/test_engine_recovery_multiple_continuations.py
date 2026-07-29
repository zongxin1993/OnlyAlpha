import json
from collections.abc import Mapping
from pathlib import Path

from onlyalpha_test_plugin.macd_plugin import OnlyTestMacdFactorSnapshot, OnlyTestMacdStrategyConfig

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.persistence.store import OnlySqliteRuntimePersistenceStore
from onlyalpha.strategy.context import OnlyStrategyBarContext
from tests.integration.test_engine_recovery_same_bar_continuation import (
    OnlyPositionTriggeredContinuationStrategy,
    _same_bar_config,
    _services,
)


class OnlyThreeContinuationStrategy(OnlyPositionTriggeredContinuationStrategy):
    def __init__(self, config: OnlyTestMacdStrategyConfig) -> None:
        super().__init__(config)
        self._continuation_count = 0

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
        elif has_position and self._continuation_count == 0 and not context.strategy.orders.list_open():
            for index in range(1, 4):
                self._submit(
                    context,
                    OnlyOrderSide.BUY,
                    self.config.trade_quantity,
                    factor,
                    f"POSITION_CONTINUATION_{index}",
                )
                self._continuation_count += 1
            self._continuation_submitted = True

    def capture_checkpoint(self) -> object:
        parent = super().capture_checkpoint()
        assert isinstance(parent, dict)
        return {**parent, "continuation_count": self._continuation_count}

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, Mapping):
            raise ValueError("three-continuation Strategy checkpoint must be an object")
        super().restore_checkpoint(payload)
        self._continuation_count = int(payload["continuation_count"])


def test_engine_commits_three_contiguous_continuations_in_recovery_boundary(tmp_path: Path) -> None:
    baseline_config = _same_bar_config()
    payload = json.loads(json.dumps(dict(baseline_config.normalized_payload)))
    payload["strategy"]["class_path"] = (
        "tests.integration.test_engine_recovery_multiple_continuations:OnlyThreeContinuationStrategy"
    )
    config = type(baseline_config).from_mapping(payload, source_path=baseline_config.source_path)
    engine_id = OnlyEngineId("three-recovery-continuations")

    engine_a = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services(with_fault=True))
    engine_a.add_cluster(config)
    assert engine_a.run().status == "FAILED"

    engine_b = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path), services=_services())
    engine_b.add_cluster(config)
    recovered = engine_b.run()
    assert recovered.status == "COMPLETED", recovered.failures
    diagnostic = engine_b.runtime_sessions[0].runtime.runtime_recovery_diagnostics[-1]
    assert diagnostic.continuation_transaction_count == 3

    runtime_id = engine_b.runtime_sessions[0].runtime_id
    state_path = OnlyUserDataLayout(tmp_path).runtime_persistence_path(engine_id, runtime_id)
    reader = OnlySqliteRuntimePersistenceStore(state_path)
    transactions = reader.records(runtime_id)
    assert tuple(item.execution_sequence for item in transactions[:4]) == (1, 2, 3, 4)
    assert all(item.projection_ready for item in transactions[:4])
    reader.close()

    baseline_engine = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path / "baseline"), services=_services())
    baseline_engine.add_cluster(config)
    baseline = baseline_engine.run()
    assert baseline.status == "COMPLETED"
    assert recovered.runtime_results[0].orders == baseline.runtime_results[0].orders
    assert recovered.runtime_results[0].trades == baseline.runtime_results[0].trades
    assert only_backtest_business_projection(recovered.runtime_results[0]) == only_backtest_business_projection(
        baseline.runtime_results[0]
    )
