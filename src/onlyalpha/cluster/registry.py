"""Static cluster type registry."""

from onlyalpha.cluster.base import OnlyCluster
from onlyalpha.core.errors import OnlyDuplicateIdError, OnlyNotFoundError


class OnlyClusterRegistry:
    """Maps stable plugin names to validated cluster classes."""

    def __init__(self) -> None:
        self._types: dict[str, type[OnlyCluster]] = {}

    def register(self, name: str, cluster_type: type[OnlyCluster]) -> None:
        if name in self._types:
            raise OnlyDuplicateIdError(f"cluster type already registered: {name}")
        if not isinstance(cluster_type, type) or not issubclass(cluster_type, OnlyCluster):
            raise TypeError("registered type must derive from OnlyCluster")
        self._types[name] = cluster_type

    def resolve(self, name: str) -> type[OnlyCluster]:
        try:
            return self._types[name]
        except KeyError as exc:
            raise OnlyNotFoundError(f"unknown cluster type: {name}") from exc
