"""Process-signal policy for long-lived product applications."""

from __future__ import annotations

import os
import signal
from collections.abc import Callable
from enum import StrEnum
from threading import Event, Lock
from types import FrameType
from typing import NoReturn, Protocol


class OnlyApplicationShutdownReason(StrEnum):
    SIGINT = "SIGINT"
    SIGTERM = "SIGTERM"
    SIGBREAK = "SIGBREAK"
    KEYBOARD_INTERRUPT = "KEYBOARD_INTERRUPT"


class OnlyForcedExitPort(Protocol):
    def exit(self, code: int) -> NoReturn: ...


class OnlyProcessForcedExit:
    """Production forced-exit boundary used only after a second interrupt."""

    def exit(self, code: int) -> NoReturn:
        os.write(2, b"Second interrupt received; forcing process termination.\n")
        os._exit(code)


type OnlySignalHandler = Callable[[int, FrameType | None], object] | int | None


class OnlyApplicationStopController:
    """Own process handlers and translate interrupts into a lightweight stop request."""

    def __init__(self, forced_exit: OnlyForcedExitPort | None = None) -> None:
        self._forced_exit = forced_exit or OnlyProcessForcedExit()
        self._stop_requested = Event()
        self._lock = Lock()
        self._interruption_count = 0
        self._reason: OnlyApplicationShutdownReason | None = None
        self._handlers: dict[signal.Signals, OnlySignalHandler] = {}

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested.is_set()

    @property
    def interruption_count(self) -> int:
        with self._lock:
            return self._interruption_count

    @property
    def shutdown_reason(self) -> OnlyApplicationShutdownReason | None:
        with self._lock:
            return self._reason

    @property
    def exit_code(self) -> int:
        reason = self.shutdown_reason
        return 143 if reason is OnlyApplicationShutdownReason.SIGTERM else 130 if reason is not None else 0

    def request_stop(self, reason: OnlyApplicationShutdownReason) -> None:
        force = False
        with self._lock:
            self._interruption_count += 1
            if self._reason is None:
                self._reason = reason
            self._stop_requested.set()
            force = self._interruption_count >= 2
        if force:
            self._forced_exit.exit(self.exit_code)

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for a stop request without exposing the mutable process event."""

        return self._stop_requested.wait(timeout)

    def install(self) -> None:
        if self._handlers:
            return
        installed: list[signal.Signals] = []
        try:
            for signum in self._supported_signals():
                self._handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, self._handle_signal)
                installed.append(signum)
        except BaseException:
            for signum in reversed(installed):
                signal.signal(signum, self._handlers[signum])
            self._handlers.clear()
            raise

    def restore(self) -> None:
        handlers, self._handlers = self._handlers, {}
        for signum, handler in handlers.items():
            signal.signal(signum, handler)

    @staticmethod
    def _supported_signals() -> tuple[signal.Signals, ...]:
        selected = [signal.SIGINT, signal.SIGTERM]
        sigbreak = getattr(signal, "SIGBREAK", None)
        if sigbreak is not None:
            selected.append(sigbreak)
        return tuple(selected)

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
        del frame
        signal_value = signal.Signals(signum)
        reason = (
            OnlyApplicationShutdownReason.SIGTERM
            if signal_value is signal.SIGTERM
            else OnlyApplicationShutdownReason.SIGBREAK
            if signal_value is getattr(signal, "SIGBREAK", None)
            else OnlyApplicationShutdownReason.SIGINT
        )
        self.request_stop(reason)
