"""Serialized lifecycle authority for one streaming Runtime."""

from dataclasses import dataclass
from threading import Condition
from time import monotonic

from .phase import OnlyStreamingPhase


@dataclass(frozen=True, slots=True)
class OnlyStreamingPhaseSnapshot:
    phase: OnlyStreamingPhase
    revision: int


class OnlyStreamingPhaseController:
    def __init__(self, initial: OnlyStreamingPhase = OnlyStreamingPhase.CREATED) -> None:
        self._condition = Condition()
        self._phase = initial
        self._revision = 0

    def snapshot(self) -> OnlyStreamingPhaseSnapshot:
        with self._condition:
            return OnlyStreamingPhaseSnapshot(self._phase, self._revision)

    def transition(
        self,
        expected: frozenset[OnlyStreamingPhase] | set[OnlyStreamingPhase],
        target: OnlyStreamingPhase,
    ) -> bool:
        with self._condition:
            if self._phase not in expected:
                return False
            if self._phase is OnlyStreamingPhase.STOPPING and target not in {
                OnlyStreamingPhase.STOPPED,
                OnlyStreamingPhase.FAILED,
            }:
                return False
            if self._phase in {OnlyStreamingPhase.STOPPED, OnlyStreamingPhase.FAILED}:
                return False
            if self._phase is target:
                return True
            self._phase = target
            self._revision += 1
            self._condition.notify_all()
            return True

    def begin_stop(self) -> bool:
        with self._condition:
            if self._phase in {OnlyStreamingPhase.STOPPING, OnlyStreamingPhase.STOPPED}:
                return False
            if self._phase is OnlyStreamingPhase.FAILED:
                return False
            self._phase = OnlyStreamingPhase.STOPPING
            self._revision += 1
            self._condition.notify_all()
            return True

    def wait_for(
        self,
        target: OnlyStreamingPhase,
        *,
        after_revision: int | None = None,
        timeout: float | None = None,
    ) -> OnlyStreamingPhaseSnapshot | None:
        deadline = None if timeout is None else monotonic() + timeout
        with self._condition:
            while self._phase is not target or (after_revision is not None and self._revision <= after_revision):
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return OnlyStreamingPhaseSnapshot(self._phase, self._revision)

    def wait_for_revision(
        self,
        after_revision: int,
        *,
        timeout: float | None = None,
    ) -> OnlyStreamingPhaseSnapshot | None:
        """Wait for any formal phase transition after ``after_revision``."""

        deadline = None if timeout is None else monotonic() + timeout
        with self._condition:
            while self._revision <= after_revision:
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._condition.wait(remaining)
            return OnlyStreamingPhaseSnapshot(self._phase, self._revision)
