from onlyalpha.cache.base import OnlyCacheKey
from onlyalpha.cache.memory import OnlyMemoryCache
from onlyalpha.storage.sqlite import OnlySqliteStorage


def test_cache_namespace_and_sqlite_recovery(tmp_path) -> None:
    cache = OnlyMemoryCache()
    key = OnlyCacheKey("e", "r", "c", "bar", "x")
    cache.set(key, "cached")
    assert cache.get(key) == "cached"
    assert cache.clear_namespace("e", "r", "c") == 1

    path = tmp_path / "state.sqlite"
    storage = OnlySqliteStorage(path)
    storage.put("runtime:r", "state", b"running")
    storage.close()
    restored = OnlySqliteStorage(path)
    assert restored.get("runtime:r", "state") == b"running"
    restored.close()
