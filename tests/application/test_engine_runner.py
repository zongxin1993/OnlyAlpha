from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from onlyalpha.application.engine_runner import (
    OnlyEngineApplicationRunner,
    OnlyRuntimeLifecycleKind,
    only_engine_lifecycle_kind,
)


def _engine(*modes: str) -> Mock:
    engine = Mock()
    engine.cluster_definitions = tuple(SimpleNamespace(runtime=SimpleNamespace(runtime_type=mode)) for mode in modes)
    return engine


def test_lifecycle_kind_rejects_mixed_finite_and_long_lived() -> None:
    assert only_engine_lifecycle_kind(_engine("BACKTEST")) is OnlyRuntimeLifecycleKind.FINITE  # type: ignore[arg-type]
    assert only_engine_lifecycle_kind(_engine("PAPER")) is OnlyRuntimeLifecycleKind.LONG_LIVED  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cannot share"):
        only_engine_lifecycle_kind(_engine("BACKTEST", "PAPER"))  # type: ignore[arg-type]


def test_long_lived_runner_stops_after_keyboard_interrupt() -> None:
    engine = _engine("PAPER")
    engine.wait.side_effect = KeyboardInterrupt
    assert OnlyEngineApplicationRunner().execute(engine) == 0  # type: ignore[arg-type]
    engine.initialize.assert_called_once_with()
    engine.start.assert_called_once_with()
    engine.wait.assert_called_once_with()
    engine.stop.assert_called_once_with()


def test_finite_runner_uses_engine_run_only() -> None:
    engine = _engine("BACKTEST")
    engine.run.return_value = SimpleNamespace(exit_code=0)
    assert OnlyEngineApplicationRunner().execute(engine) == 0  # type: ignore[arg-type]
    engine.run.assert_called_once_with()
    engine.initialize.assert_not_called()
    engine.wait.assert_not_called()
