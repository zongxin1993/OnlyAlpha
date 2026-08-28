"""Thin, long-lived Product Kernel composition and lifecycle host."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from .lifecycle import (
    OnlyKernelFailure,
    OnlyKernelFailurePhase,
    OnlyKernelLifecycle,
    OnlyKernelLifecycleError,
    OnlyKernelState,
    OnlyKernelStatus,
)


@dataclass(frozen=True, slots=True)
class OnlyKernelLifecycleStep:
    name: str
    execute: Callable[[], None]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Kernel lifecycle step name must be non-empty")
        if not callable(self.execute):
            raise TypeError("Kernel lifecycle step execute capability must be callable")


class OnlyKernelHostError(RuntimeError):
    def __init__(self, failure: OnlyKernelFailure) -> None:
        self.failure = failure
        super().__init__(f"Product Kernel {failure.phase} failed at {failure.step}: {failure.reason}")


class OnlyKernelAuthorityError(RuntimeError):
    """The mutation-capable Product Kernel authority is unavailable or lost."""


class OnlyKernelAuthorityAlreadyHeld(OnlyKernelAuthorityError):
    def __init__(self) -> None:
        super().__init__("Product Kernel mutation authority is already held by another process")


class OnlyKernelAuthorityGuard(Protocol):
    def acquire(self) -> None: ...

    def assert_held(self) -> None: ...

    def release(self) -> None: ...


class _OnlyKernelStepExecutionError(RuntimeError):
    def __init__(self, step: str, cause: Exception) -> None:
        self.step = step
        self.cause = cause
        super().__init__(step)


class OnlyAlphaKernelHost:
    """Own Product lifecycle while composing existing narrow capabilities."""

    def __init__(
        self,
        *,
        booters: tuple[OnlyKernelLifecycleStep, ...] = (),
        verifiers: tuple[OnlyKernelLifecycleStep, ...] = (),
        recoverers: tuple[OnlyKernelLifecycleStep, ...] = (),
        drainers: tuple[OnlyKernelLifecycleStep, ...] = (),
        authority_guard: OnlyKernelAuthorityGuard | None = None,
    ) -> None:
        self._booters = _validated_steps("booters", booters)
        self._verifiers = _validated_steps("verifiers", verifiers)
        self._recoverers = _validated_steps("recoverers", recoverers)
        self._drainers = _validated_steps("drainers", drainers)
        self._authority_guard = authority_guard
        self._lifecycle = OnlyKernelLifecycle()
        self._operation_lock = Lock()
        self._active_operation: str | None = None

    @property
    def state(self) -> OnlyKernelState:
        return self._lifecycle.state

    @property
    def status(self) -> OnlyKernelStatus:
        return self._lifecycle.status

    def start(self) -> OnlyKernelStatus:
        self._begin_operation("start", required_state=OnlyKernelState.CREATED)
        phase = OnlyKernelFailurePhase.BOOTING
        step_name = "lifecycle-transition"
        try:
            self._lifecycle.transition(OnlyKernelState.BOOTING)
            self._execute(self._booters)
            phase = OnlyKernelFailurePhase.VERIFYING
            step_name = "lifecycle-transition"
            self._lifecycle.transition(OnlyKernelState.VERIFYING)
            self._execute(self._verifiers)
            phase = OnlyKernelFailurePhase.RECOVERING
            step_name = "mutation-authority-acquire"
            if self._authority_guard is not None:
                self._authority_guard.acquire()
            step_name = "lifecycle-transition"
            self._lifecycle.transition(OnlyKernelState.RECOVERING)
            self._execute(self._recoverers)
            self._lifecycle.transition(OnlyKernelState.READY)
            return self.status
        except Exception as error:
            cause = error.cause if isinstance(error, _OnlyKernelStepExecutionError) else error
            failed_step = error.step if isinstance(error, _OnlyKernelStepExecutionError) else step_name
            failure = OnlyKernelFailure(phase=phase, step=failed_step, reason=type(cause).__name__)
            if self.state is not OnlyKernelState.FAILED:
                self._lifecycle.fail(failure)
            if self._authority_guard is not None:
                try:
                    self._authority_guard.release()
                except Exception:
                    pass
            raise OnlyKernelHostError(failure) from cause
        finally:
            self._end_operation("start")

    def stop(self) -> OnlyKernelStatus:
        self._begin_operation("stop", required_state=OnlyKernelState.READY)
        step_name = "lifecycle-transition"
        try:
            self._lifecycle.transition(OnlyKernelState.DRAINING)
            self._execute(self._drainers)
            step_name = "mutation-authority-release"
            if self._authority_guard is not None:
                self._authority_guard.release()
            step_name = "lifecycle-transition"
            self._lifecycle.transition(OnlyKernelState.STOPPED)
            return self.status
        except Exception as error:
            cause = error.cause if isinstance(error, _OnlyKernelStepExecutionError) else error
            failed_step = error.step if isinstance(error, _OnlyKernelStepExecutionError) else step_name
            failure = OnlyKernelFailure(
                phase=OnlyKernelFailurePhase.DRAINING,
                step=failed_step,
                reason=type(cause).__name__,
            )
            if self._authority_guard is not None:
                try:
                    self._authority_guard.release()
                except Exception:
                    pass
            if self.state is not OnlyKernelState.FAILED:
                self._lifecycle.fail(failure)
            raise OnlyKernelHostError(failure) from cause
        finally:
            self._end_operation("stop")

    def assert_mutation_ready(self) -> None:
        self._lifecycle.assert_mutation_ready()
        if self._authority_guard is not None:
            self._authority_guard.assert_held()

    def _begin_operation(self, operation: str, *, required_state: OnlyKernelState) -> None:
        with self._operation_lock:
            if self._active_operation is not None:
                raise OnlyKernelLifecycleError(
                    f"Product Kernel lifecycle operation {self._active_operation} is already active"
                )
            current = self.state
            if current is not required_state:
                raise OnlyKernelLifecycleError(
                    f"Product Kernel {operation} requires {required_state}; current state is {current}"
                )
            self._active_operation = operation

    def _end_operation(self, operation: str) -> None:
        with self._operation_lock:
            if self._active_operation == operation:
                self._active_operation = None

    @staticmethod
    def _execute(steps: tuple[OnlyKernelLifecycleStep, ...]) -> None:
        for step in steps:
            try:
                step.execute()
            except Exception as error:
                raise _OnlyKernelStepExecutionError(step.name, error) from error


def _validated_steps(label: str, steps: tuple[OnlyKernelLifecycleStep, ...]) -> tuple[OnlyKernelLifecycleStep, ...]:
    if not isinstance(steps, tuple):
        raise TypeError(f"Kernel {label} must be an explicitly ordered tuple")
    if not all(isinstance(step, OnlyKernelLifecycleStep) for step in steps):
        raise TypeError(f"Kernel {label} must contain OnlyKernelLifecycleStep values")
    names = tuple(step.name for step in steps)
    if len(names) != len(set(names)):
        raise ValueError(f"Kernel {label} step names must be unique")
    return steps


__all__ = [name for name in globals() if name.startswith("Only")]
