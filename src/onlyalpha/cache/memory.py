"""Thread-safe in-memory cache implementation."""

from threading import RLock

from onlyalpha.cache.base import OnlyCache, OnlyCacheKey


class OnlyMemoryCache(OnlyCache):
    """Process-local cache suitable for tests and the minimal skeleton."""

    def __init__(self) -> None:
        self._values: dict[OnlyCacheKey, object] = {}
        self._lock = RLock()

    def get(self, key: OnlyCacheKey) -> object | None:
        with self._lock:
            return self._values.get(key)

    def set(self, key: OnlyCacheKey, value: object) -> None:
        with self._lock:
            self._values[key] = value

    def delete(self, key: OnlyCacheKey) -> bool:
        with self._lock:
            return self._values.pop(key, None) is not None

    def clear_namespace(self, engine_id: str, runtime_id: str, cluster_id: str) -> int:
        with self._lock:
            keys = [
                key
                for key in self._values
                if (key.engine_id, key.runtime_id, key.cluster_id) == (engine_id, runtime_id, cluster_id)
            ]
            for key in keys:
                del self._values[key]
            return len(keys)
