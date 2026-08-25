"""Pure Product Kernel lifecycle facts and transition authority."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from threading import Lock


class OnlyKernelState(StrEnum):
    CREATED = "CREATED"
    BOOTING = "BOOTING"
    VERIFYING = "VERIFYING"
    RECOVERING = "RECOVERING"
    READY = "READY"
    DRAINING = "DRAINING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class OnlyKernelFailurePhase(StrEnum):
    BOOTING = "BOOTING"
    VERIFYING = "VERIFYING"
    RECOVERING = "RECOVERING"
    READY = "READY"
    DRAINING = "DRAINING"


@dataclass(frozen=True, slots=True)
class OnlyKernelFailure:
    phase: OnlyKernelFailurePhase
    step: str
    reason: str

    def __post_init__(self) -> None:
        if not self.step:
            raise ValueError("Kernel failure step must be non-empty")
        if not self.reason:
            raise ValueError("Kernel failure reason must be non-empty")


@dataclass(frozen=True, slots=True)
class OnlyKernelStatus:
    state: OnlyKernelState
    live: bool
    ready: bool
    failure: OnlyKernelFailure | None


class OnlyKernelLifecycleError(RuntimeError):
    """A requested Product Kernel lifecycle operation is illegal."""


class OnlyKernelMutationRejected(OnlyKernelLifecycleError):
    """Product mutation was requested outside READY."""


_LEGAL_TRANSITIONS: dict[OnlyKernelState, frozenset[OnlyKernelState]] = {
    OnlyKernelState.CREATED: frozenset({OnlyKernelState.BOOTING}),
    OnlyKernelState.BOOTING: frozenset({OnlyKernelState.VERIFYING}),
    OnlyKernelState.VERIFYING: frozenset({OnlyKernelState.RECOVERING}),
    OnlyKernelState.RECOVERING: frozenset({OnlyKernelState.READY}),
    OnlyKernelState.READY: frozenset({OnlyKernelState.DRAINING}),
    OnlyKernelState.DRAINING: frozenset({OnlyKernelState.STOPPED}),
    OnlyKernelState.STOPPED: frozenset(),
    OnlyKernelState.FAILED: frozenset(),
}
_FAILURE_PHASE_BY_STATE = {
    OnlyKernelState.BOOTING: OnlyKernelFailurePhase.BOOTING,
    OnlyKernelState.VERIFYING: OnlyKernelFailurePhase.VERIFYING,
    OnlyKernelState.RECOVERING: OnlyKernelFailurePhase.RECOVERING,
    OnlyKernelState.READY: OnlyKernelFailurePhase.READY,
    OnlyKernelState.DRAINING: OnlyKernelFailurePhase.DRAINING,
}


class OnlyKernelLifecycle:
    """The single validated transition authority for one Product Kernel Host."""

    def __init__(self) -> None:
        self._state = OnlyKernelState.CREATED
        self._failure: OnlyKernelFailure | None = None
        self._lock = Lock()

    @property
    def state(self) -> OnlyKernelState:
        with self._lock:
            return self._state

    @property
    def status(self) -> OnlyKernelStatus:
        with self._lock:
            state = self._state
            return OnlyKernelStatus(
                state=state,
                live=state is not OnlyKernelState.STOPPED,
                ready=state is OnlyKernelState.READY,
                failure=self._failure,
            )

    def transition(self, target: OnlyKernelState) -> OnlyKernelStatus:
        if not isinstance(target, OnlyKernelState):
            raise TypeError("Kernel lifecycle target must be OnlyKernelState")
        with self._lock:
            current = self._state
            if target not in _LEGAL_TRANSITIONS[current]:
                raise OnlyKernelLifecycleError(f"Illegal Product Kernel lifecycle transition: {current} -> {target}")
            self._state = target
            return self._status_locked()

    def fail(self, failure: OnlyKernelFailure) -> OnlyKernelStatus:
        if not isinstance(failure, OnlyKernelFailure):
            raise TypeError("Kernel lifecycle failure must be OnlyKernelFailure")
        with self._lock:
            current = self._state
            expected_phase = _FAILURE_PHASE_BY_STATE.get(current)
            if expected_phase is None or failure.phase is not expected_phase:
                raise OnlyKernelLifecycleError(
                    f"Illegal Product Kernel failure transition: {current} -> {OnlyKernelState.FAILED}"
                )
            self._failure = failure
            self._state = OnlyKernelState.FAILED
            return self._status_locked()

    def assert_mutation_ready(self) -> None:
        with self._lock:
            state = self._state
        if state is not OnlyKernelState.READY:
            raise OnlyKernelMutationRejected(f"Product mutation requires READY; current state is {state}")

    def _status_locked(self) -> OnlyKernelStatus:
        state = self._state
        return OnlyKernelStatus(
            state=state,
            live=state is not OnlyKernelState.STOPPED,
            ready=state is OnlyKernelState.READY,
            failure=self._failure,
        )


__all__ = [
    "OnlyKernelFailure",
    "OnlyKernelFailurePhase",
    "OnlyKernelLifecycle",
    "OnlyKernelLifecycleError",
    "OnlyKernelMutationRejected",
    "OnlyKernelState",
    "OnlyKernelStatus",
]
