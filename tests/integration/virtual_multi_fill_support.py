import json
from dataclasses import replace
from pathlib import Path

from onlyalpha_plugin_broker_virtual import OnlyVirtualBrokerGateway

from onlyalpha.config import OnlyClusterRunConfig, OnlyRuntimePersistenceConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.execution import OnlyRuntimeTransactionOutboxKey
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.checkpoint.model import OnlyRuntimeCheckpoint
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.persistence.factory import (
    OnlyDefaultRuntimePersistenceStoreFactory,
    OnlyRuntimePersistenceStoreCreateRequest,
)
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStorePort
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind
from tests.execution.support.execution_fault_injection import (
    OnlyFailOnceRuntimePersistenceStore,
    OnlyTestRuntimePersistenceFault,
)
from tests.runtime_runner import only_copy_cluster_strategy_revision, only_migrate_cluster_to_strategy
from tests.support.canonical import canonical_value
from tests.support.recovery_baselines import assert_recovery_equivalent, load_recovery_baseline


def only_virtual_multi_fill_config(
    user_data_root: Path,
    *,
    same_bar: bool = False,
    fill_latency_ns: int = 0,
    long_close: bool = False,
) -> OnlyClusterRunConfig:
    baseline = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["persistence"] = {
        "backend": "SQLITE",
        "checkpoint": {"enabled": True, "retain_last": 2},
    }
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
    config = only_migrate_cluster_to_strategy(
        OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path), user_data_root
    )
    actions = [
        {
            "action_id": "OPEN",
            "sequence": 1,
            "type": "SUBMIT_ORDER",
            "instrument_id": "TESTETF.XSHG",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": "1000",
            "price": "10.00",
            "offset": "OPEN",
        }
    ]
    if long_close:
        actions.append(
            {
                "action_id": "CLOSE",
                "sequence": 5,
                "type": "SUBMIT_ORDER",
                "instrument_id": "TESTETF.XSHG",
                "side": "SELL",
                "order_type": "LIMIT",
                "quantity": "1000",
                "price": "0.01",
                "offset": "CLOSE",
            }
        )
    return replace(config, cluster=replace(config.cluster, scenario_actions=tuple(actions)))  # type: ignore[arg-type]


def only_terminal_after_partial_fill_config(user_data_root: Path) -> OnlyClusterRunConfig:
    config = only_virtual_multi_fill_config(user_data_root)
    actions = config.cluster.scenario_actions + (
        {
            "action_id": "CANCEL",
            "sequence": 3,
            "type": "CANCEL_ORDER",
            "target_action_id": "OPEN",
        },
    )
    return replace(config, cluster=replace(config.cluster, scenario_actions=actions))


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
            operation_kind=OnlyRuntimeOperationKind.TRADE_FILL,
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

    def mark_published(self, key: OnlyRuntimeTransactionOutboxKey, published_at: OnlyTimestamp) -> None:
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
    baseline_id: str | None = None,
) -> tuple[OnlyEngine, OnlyEngine]:
    selected = config or only_virtual_multi_fill_config(tmp_path)
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
    actual_result = recovered.runtime_results[0]
    recovered_broker = engine_b.runtime_sessions[0].runtime.broker_gateway
    assert isinstance(recovered_broker, OnlyVirtualBrokerGateway)
    if baseline_id is not None:
        baseline_fixture = load_recovery_baseline(baseline_id)
        assert_recovery_equivalent(baseline_fixture, actual_result)
        assert canonical_value(recovered_broker.capture_checkpoint()) == canonical_value(
            baseline_fixture.manifest["broker_checkpoint"]
        )
    else:
        baseline_root = tmp_path / "baseline"
        baseline = OnlyEngine(OnlyEngineConfig(engine_id, baseline_root))
        baseline.add_cluster(only_copy_cluster_strategy_revision(selected, tmp_path, baseline_root))
        expected = baseline.run()
        assert expected.status == "COMPLETED", expected.failures
        expected_result = expected.runtime_results[0]
        assert actual_result.result_fingerprint == expected_result.result_fingerprint
        assert only_backtest_business_projection(actual_result) == only_backtest_business_projection(expected_result)
        baseline_broker = baseline.runtime_sessions[0].runtime.broker_gateway
        assert isinstance(baseline_broker, OnlyVirtualBrokerGateway)
        assert recovered_broker.capture_checkpoint() == baseline_broker.capture_checkpoint()
    return engine_a, engine_b


__all__ = [
    "OnlyMultiFillFaultStoreFactory",
    "OnlyOutboxCheckpointFailureStoreFactory",
    "OnlyPlanCursorCheckpointFailureStoreFactory",
    "only_assert_multi_fill_recovery_equivalence",
    "only_terminal_after_partial_fill_config",
    "only_virtual_multi_fill_config",
]
