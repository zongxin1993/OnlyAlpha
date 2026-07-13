"""Durable storage interface."""

from abc import ABC, abstractmethod


class OnlyStorage(ABC):
    """Reliable byte-oriented storage contract for initial state snapshots."""

    @abstractmethod
    def put(self, namespace: str, key: str, value: bytes) -> None: ...

    @abstractmethod
    def get(self, namespace: str, key: str) -> bytes | None: ...

    @abstractmethod
    def delete(self, namespace: str, key: str) -> bool: ...

    @abstractmethod
    def close(self) -> None: ...
