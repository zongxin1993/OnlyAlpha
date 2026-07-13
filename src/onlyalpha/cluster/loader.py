"""Explicit module-based dynamic cluster loader."""

from importlib import import_module

from onlyalpha.cluster.base import OnlyCluster


class OnlyClusterLoader:
    """Loads a named cluster class without scanning or executing arbitrary directories."""

    def load(self, module_name: str, class_name: str) -> type[OnlyCluster]:
        candidate = getattr(import_module(module_name), class_name)
        if not isinstance(candidate, type) or not issubclass(candidate, OnlyCluster):
            raise TypeError(f"{module_name}.{class_name} is not an OnlyCluster type")
        return candidate
