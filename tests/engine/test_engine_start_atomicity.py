from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId, OnlyRuntimeId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.engine.models import (
    OnlyClusterHandle,
    OnlyClusterSession,
    OnlyEngineClusterStatus,
    OnlyEngineState,
    OnlyRuntimeSession,
)


def _ready_engine(tmp_path, *runtimes: Mock) -> OnlyEngine:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("atomic-start"), tmp_path))
    engine.state = OnlyEngineState.READY
    for index, runtime in enumerate(runtimes):
        runtime_id = OnlyRuntimeId(f"runtime-{index}")
        cluster_id = OnlyClusterId(f"cluster-{index}")
        engine._runtime_sessions[str(runtime_id)] = OnlyRuntimeSession(  # type: ignore[attr-defined]
            runtime_id,
            runtime,
            SimpleNamespace(),  # type: ignore[arg-type]
            (cluster_id,),
            "READY",
        )
        engine._cluster_sessions[cluster_id] = OnlyClusterSession(  # type: ignore[attr-defined]
            cluster_id,
            SimpleNamespace(),  # type: ignore[arg-type]
            runtime_id,
            OnlyEngineClusterStatus.READY,
            (),
            f"fingerprint-{index}",
        )
        engine._handles[cluster_id] = OnlyClusterHandle(  # type: ignore[attr-defined]
            cluster_id,
            runtime_id,
            OnlyEngineClusterStatus.READY,
            f"fingerprint-{index}",
        )
    return engine


def test_all_runtimes_start_or_engine_converges_to_failed(tmp_path) -> None:
    trace: list[str] = []
    first, second = Mock(), Mock()
    first.start.side_effect = lambda: trace.append("first.start")
    first.close.side_effect = lambda: trace.append("first.close")
    second.start.side_effect = RuntimeError("second start failed")
    second.close.side_effect = lambda: trace.append("second.close")
    engine = _ready_engine(tmp_path, first, second)

    with pytest.raises(RuntimeError, match="second start failed"):
        engine.start()

    assert trace == ["first.start", "second.close", "first.close"]
    assert engine.state is OnlyEngineState.FAILED
    assert {session.state for session in engine.runtime_sessions} == {"FAILED"}
    assert {session.state for session in engine.cluster_sessions} == {OnlyEngineClusterStatus.FAILED}
    assert {handle.status for handle in engine.cluster_handles} == {OnlyEngineClusterStatus.FAILED}
    engine.stop()
    engine.close()
    assert first.close.call_count == second.close.call_count == 1


def test_cleanup_failures_are_notes_on_original_start_failure_and_do_not_stop_cleanup(tmp_path) -> None:
    first, second = Mock(), Mock()
    second.start.side_effect = RuntimeError("primary start failure")
    second.close.side_effect = RuntimeError("second cleanup failure")
    first.close.side_effect = RuntimeError("first cleanup failure")
    engine = _ready_engine(tmp_path, first, second)

    with pytest.raises(RuntimeError, match="primary start failure") as raised:
        engine.start()

    assert first.mock_calls == [call.start(), call.close()]
    assert second.mock_calls == [call.start(), call.close()]
    assert raised.value.__notes__ == [
        "Runtime startup cleanup also failed for runtime-1: RuntimeError: second cleanup failure",
        "Runtime startup cleanup also failed for runtime-0: RuntimeError: first cleanup failure",
    ]
    assert engine.state is OnlyEngineState.FAILED


def test_first_runtime_start_failure_still_closes_every_initialized_runtime(tmp_path) -> None:
    first, second = Mock(), Mock()
    first.start.side_effect = RuntimeError("first start failed")
    engine = _ready_engine(tmp_path, first, second)

    with pytest.raises(RuntimeError, match="first start failed"):
        engine.start()

    first.close.assert_called_once_with()
    second.start.assert_not_called()
    second.close.assert_called_once_with()
    assert engine.state is OnlyEngineState.FAILED
