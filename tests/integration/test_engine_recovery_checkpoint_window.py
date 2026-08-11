from pathlib import Path
from typing import Protocol

import pytest

from onlyalpha.config import OnlyRuntimePersistenceConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.checkpoint.model import OnlyRuntimeCheckpoint
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.persistence.factory import (
    OnlyDefaultRuntimePersistenceStoreFactory,
    OnlyRuntimePersistenceStoreCreateRequest,
)
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStorePort
from tests.integration.test_engine_continuous_restart import _sqlite_config


class _CheckpointStoreView(Protocol):
    def write_checkpoint(self, checkpoint: OnlyRuntimeCheckpoint, *, retain_last: int) -> None: ...


class OnlyFailAtSecondCheckpointStore:
    def __init__(self, delegate: OnlyRuntimePersistenceStorePort, *, after_commit: bool) -> None:
        self._delegate = delegate
        self._after_commit = after_commit
        self._writes = 0

    def write_checkpoint(self, checkpoint: OnlyRuntimeCheckpoint, *, retain_last: int) -> None:
        self._writes += 1
        if self._writes == 2 and not self._after_commit:
            raise RuntimeError("TEST_FAILURE_AFTER_AUDIT_BEFORE_CHECKPOINT")
        self._delegate.write_checkpoint(checkpoint, retain_last=retain_last)
        if self._writes == 2 and self._after_commit:
            raise RuntimeError("TEST_FAILURE_AFTER_CHECKPOINT_COMMIT")

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


class OnlyCheckpointWindowFaultFactory:
    def __init__(self, *, after_commit: bool) -> None:
        self._delegate = OnlyDefaultRuntimePersistenceStoreFactory()
        self._after_commit = after_commit

    def validate(self, config: OnlyRuntimePersistenceConfig) -> None:
        self._delegate.validate(config)

    def create(self, request: OnlyRuntimePersistenceStoreCreateRequest) -> OnlyRuntimePersistenceStorePort:
        return OnlyFailAtSecondCheckpointStore(
            self._delegate.create(request),
            after_commit=self._after_commit,
        )  # type: ignore[return-value]


@pytest.mark.parametrize("after_commit", (False, True))
def test_audit_checkpoint_windows_replay_each_business_bar_once(tmp_path: Path, after_commit: bool) -> None:
    config = _sqlite_config()
    engine_id = OnlyEngineId(f"checkpoint-window-{after_commit}")
    failed = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(
            runtime_persistence_store_factory=OnlyCheckpointWindowFaultFactory(after_commit=after_commit)
        ),
    )
    failed.add_cluster(config)
    assert failed.run().status == "FAILED"

    recovered = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    recovered.add_cluster(config)
    recovered_result = recovered.run()
    assert recovered_result.status == "COMPLETED"

    baseline = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path / "baseline"))
    baseline.add_cluster(config)
    baseline_result = baseline.run()
    assert baseline_result.status == "COMPLETED"
    assert only_backtest_business_projection(recovered_result.runtime_results[0]) == only_backtest_business_projection(
        baseline_result.runtime_results[0]
    )


def test_checkpoint_barrier_is_after_audit_progress_and_event_drain() -> None:
    runtime = Path("src/onlyalpha/runtime/trading_facade.py").read_text(encoding="utf-8")
    processor = Path("src/onlyalpha/data/processor.py").read_text(encoding="utf-8")
    completion = runtime[
        runtime.index("        def after_market_processing(") : runtime.index("        market_data_processor =")
    ]
    assert completion.index("observe_market_data_result") < completion.index("owned_bus.drain()")
    assert completion.index("owned_bus.drain()") < completion.index("_checkpoint_barrier(completion)")
    finish = processor[processor.index("    def _finish(") :]
    assert finish.index("_audit_store.append") < finish.index("_after_processing(update, result)")
