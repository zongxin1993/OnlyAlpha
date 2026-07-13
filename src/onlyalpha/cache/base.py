"""Cache interface separated from durable storage."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OnlyCacheKey:
    """Namespaced cache key preserving runtime and cluster isolation."""

    engine_id: str
    runtime_id: str
    cluster_id: str
    data_type: str
    name: str
    version: int = 1


class OnlyCache(ABC):
    """Rebuildable key-value cache contract."""

    @abstractmethod
    def get(self, key: OnlyCacheKey) -> object | None: ...

    @abstractmethod
    def set(self, key: OnlyCacheKey, value: object) -> None: ...

    @abstractmethod
    def delete(self, key: OnlyCacheKey) -> bool: ...

    @abstractmethod
    def clear_namespace(self, engine_id: str, runtime_id: str, cluster_id: str) -> int: ...
