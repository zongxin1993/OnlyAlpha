from __future__ import annotations

import signal
from types import SimpleNamespace
from typing import NoReturn
from unittest.mock import Mock

import pytest

from onlyalpha.application.engine_runner import (
    OnlyEngineApplicationRunner,
    OnlyRuntimeLifecycleKind,
    only_engine_lifecycle_kind,
)
from onlyalpha.application.stop_controller import (
    OnlyApplicationStopController,
)


def _engine(*modes: str) -> Mock:
    engine = Mock()
    engine.engine_id = "application-test"
    engine.cluster_definitions = tuple(SimpleNamespace(runtime=SimpleNamespace(runtime_type=mode)) for mode in modes)
    return engine


def test_lifecycle_kind_rejects_mixed_finite_and_long_lived() -> None:
    assert only_engine_lifecycle_kind(_engine("BACKTEST")) is OnlyRuntimeLifecycleKind.FINITE  # type: ignore[arg-type]
    assert only_engine_lifecycle_kind(_engine("SIM")) is OnlyRuntimeLifecycleKind.LONG_LIVED  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cannot share"):
        only_engine_lifecycle_kind(_engine("BACKTEST", "SIM"))  # type: ignore[arg-type]


def test_long_lived_runner_uses_finite_wait_and_stops_once_after_keyboard_interrupt() -> None:
    engine = _engine("SIM")
    engine.wait.side_effect = KeyboardInterrupt
    messages: list[str] = []

    assert OnlyEngineApplicationRunner(message_writer=messages.append).execute(engine) == 130  # type: ignore[arg-type]

    engine.initialize.assert_called_once_with()
    engine.start.assert_called_once_with()
    engine.wait.assert_called_once_with(timeout=0.25)
    engine.stop.assert_called_once_with()
    assert messages[-1] == "OnlyAlpha shutdown completed"


@pytest.mark.parametrize(("signum", "expected"), ((signal.SIGINT, 130), (signal.SIGTERM, 143)))
def test_real_signal_handler_requests_shutdown_and_is_restored(signum: signal.Signals, expected: int) -> None:
    engine = _engine("SIM")
    previous = signal.getsignal(signum)

    def wait(*, timeout: float) -> None:
        assert 0.1 <= timeout <= 0.5
        signal.raise_signal(signum)

    engine.wait.side_effect = wait
    assert OnlyEngineApplicationRunner(message_writer=lambda message: None).execute(engine) == expected  # type: ignore[arg-type]
    assert signal.getsignal(signum) is previous
    engine.stop.assert_called_once_with()


class _ForcedExit(BaseException):
    pass


class _RecordingForcedExit:
    def __init__(self) -> None:
        self.codes: list[int] = []

    def exit(self, code: int) -> NoReturn:
        self.codes.append(code)
        raise _ForcedExit


def test_second_interrupt_during_blocked_shutdown_forces_exit_without_repeating_stop() -> None:
    engine = _engine("SIM")
    forced = _RecordingForcedExit()
    engine.wait.side_effect = KeyboardInterrupt
    engine.stop.side_effect = KeyboardInterrupt

    with pytest.raises(_ForcedExit):
        OnlyEngineApplicationRunner(
            forced_exit=forced,
            message_writer=lambda message: None,
        ).execute(engine)  # type: ignore[arg-type]

    assert forced.codes == [130]
    engine.stop.assert_called_once_with()


def test_controller_supports_windows_break_when_available() -> None:
    supported = OnlyApplicationStopController._supported_signals()
    sigbreak = getattr(signal, "SIGBREAK", None)
    assert (sigbreak in supported) is (sigbreak is not None)


@pytest.mark.parametrize("operation", ("initialize", "start"))
def test_startup_failure_preserves_primary_error_and_still_cleans_up(operation: str) -> None:
    engine = _engine("SIM")
    getattr(engine, operation).side_effect = RuntimeError(f"{operation} failed")
    engine.stop.side_effect = RuntimeError("cleanup failed")

    with pytest.raises(RuntimeError, match=f"{operation} failed") as raised:
        OnlyEngineApplicationRunner(message_writer=lambda message: None).execute(engine)  # type: ignore[arg-type]

    engine.stop.assert_called_once_with()
    assert raised.value.__notes__ == ["Engine shutdown also failed: RuntimeError: cleanup failed"]


def test_runtime_worker_failure_is_not_hidden_by_polling() -> None:
    engine = _engine("SIM")
    engine.wait.side_effect = RuntimeError("streaming market-data worker failed")

    with pytest.raises(RuntimeError, match="streaming market-data worker failed"):
        OnlyEngineApplicationRunner(message_writer=lambda message: None).execute(engine)  # type: ignore[arg-type]

    engine.stop.assert_called_once_with()


def test_interrupt_during_initialize_does_not_start_business_processing() -> None:
    engine = _engine("SIM")
    engine.initialize.side_effect = lambda: signal.raise_signal(signal.SIGINT)

    assert OnlyEngineApplicationRunner(message_writer=lambda message: None).execute(engine) == 130  # type: ignore[arg-type]

    engine.start.assert_not_called()
    engine.wait.assert_not_called()
    engine.stop.assert_called_once_with()


def test_finite_runner_uses_engine_run_only() -> None:
    engine = _engine("BACKTEST")
    engine.run.return_value = SimpleNamespace(exit_code=0)
    assert OnlyEngineApplicationRunner().execute(engine) == 0  # type: ignore[arg-type]
    engine.run.assert_called_once_with()
    engine.initialize.assert_not_called()
    engine.wait.assert_not_called()
