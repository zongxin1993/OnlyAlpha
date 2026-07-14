"""Lazy public Cluster exports which avoid Cluster/Runtime import cycles."""

from importlib import import_module

_EXPORTS = {
    "OnlyBarContext": "onlyalpha.cluster.bar_context",
    "OnlyCluster": "onlyalpha.cluster.base",
    "OnlyClusterConfig": "onlyalpha.cluster.base",
    "OnlyClusterContext": "onlyalpha.cluster.base",
    "OnlyClusterState": "onlyalpha.cluster.base",
    "OnlyClusterManager": "onlyalpha.cluster.manager",
    "OnlyClusterStatus": "onlyalpha.cluster.manager",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> object:
    try:
        module_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value: object = getattr(import_module(module_name), name)
    globals()[name] = value
    return value
