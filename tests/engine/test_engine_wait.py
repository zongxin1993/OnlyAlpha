from __future__ import annotations

from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.engine.models import OnlyEngineState


def _waiting_engine(tmp_path: object, *runtimes: object) -> OnlyEngine:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("wait-budget"), tmp_path))  # type: ignore[arg-type]
    engine.state = OnlyEngineState.RUNNING
    engine._runtime_sessions = {  # type: ignore[attr-defined]
        str(index): SimpleNamespace(runtime=runtime) for index, runtime in enumerate(runtimes)
    }
    return engine


def _runtime() -> Mock:
    runtime = Mock()
    runtime.runtime_type = "SIM"
    return runtime


def test_single_runtime_receives_timeout(tmp_path: object) -> None:
    runtime = _runtime()
    _waiting_engine(tmp_path, runtime).wait(0.2)
    received = runtime.wait.call_args.args[0]
    assert 0 <= received <= 0.2


def test_multiple_runtimes_share_one_total_timeout_budget(tmp_path: object) -> None:
    first, second = _runtime(), _runtime()
    first.wait.side_effect = lambda timeout: sleep(timeout)
    started = monotonic()

    _waiting_engine(tmp_path, first, second).wait(0.05)

    assert monotonic() - started < 0.09
    assert second.wait.call_args.args[0] < 0.01


def test_zero_timeout_is_non_blocking_for_every_runtime(tmp_path: object) -> None:
    first, second = _runtime(), _runtime()
    _waiting_engine(tmp_path, first, second).wait(0)
    assert first.wait.call_args.args == (0.0,)
    assert second.wait.call_args.args == (0.0,)


def test_none_timeout_retains_unbounded_runtime_contract(tmp_path: object) -> None:
    first, second = _runtime(), _runtime()
    _waiting_engine(tmp_path, first, second).wait(None)
    first.wait.assert_called_once_with(None)
    second.wait.assert_called_once_with(None)


def test_early_runtime_completion_leaves_budget_for_following_runtime(tmp_path: object) -> None:
    first, second = _runtime(), _runtime()
    _waiting_engine(tmp_path, first, second).wait(0.1)
    assert 0 < second.wait.call_args.args[0] <= 0.1


def test_runtime_wait_failure_is_propagated_and_stops_iteration(tmp_path: object) -> None:
    first, second = _runtime(), _runtime()
    first.wait.side_effect = RuntimeError("worker failed")
    with pytest.raises(RuntimeError, match="worker failed"):
        _waiting_engine(tmp_path, first, second).wait(0.1)
    second.wait.assert_not_called()
