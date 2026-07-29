"""Deterministic Runtime-scoped Order identity generation."""

from typing import Protocol

from onlyalpha.domain.identifiers import OnlyClientOrderId, OnlyOrderId, OnlyRuntimeId


class OnlyOrderIdGenerator(Protocol):
    def next_id(self) -> OnlyOrderId: ...

    def checkpoint_sequence(self) -> int: ...

    def restore_checkpoint_sequence(self, sequence: int) -> None: ...


class OnlyClientOrderIdGenerator(Protocol):
    def next_id(self) -> OnlyClientOrderId: ...

    def checkpoint_sequence(self) -> int: ...

    def restore_checkpoint_sequence(self, sequence: int) -> None: ...


class OnlySequenceOrderIdGenerator:
    def __init__(self, runtime_id: OnlyRuntimeId, *, initial_sequence: int = 0) -> None:
        if initial_sequence < 0:
            raise ValueError("initial_sequence cannot be negative")
        self._runtime_id = runtime_id
        self._sequence = initial_sequence

    def next_id(self) -> OnlyOrderId:
        self._sequence += 1
        return OnlyOrderId(f"{self._runtime_id}-ORDER-{self._sequence:06d}")

    def checkpoint_sequence(self) -> int:
        return self._sequence

    def restore_checkpoint_sequence(self, sequence: int) -> None:
        if sequence < self._sequence:
            raise ValueError("Order ID sequence cannot regress")
        self._sequence = sequence


class OnlySequenceClientOrderIdGenerator:
    def __init__(self, runtime_id: OnlyRuntimeId, *, initial_sequence: int = 0) -> None:
        if initial_sequence < 0:
            raise ValueError("initial_sequence cannot be negative")
        self._runtime_id = runtime_id
        self._sequence = initial_sequence

    def next_id(self) -> OnlyClientOrderId:
        self._sequence += 1
        return OnlyClientOrderId(f"{self._runtime_id}-CLIENT-{self._sequence:06d}")

    def checkpoint_sequence(self) -> int:
        return self._sequence

    def restore_checkpoint_sequence(self, sequence: int) -> None:
        if sequence < self._sequence:
            raise ValueError("Client Order ID sequence cannot regress")
        self._sequence = sequence
