"""DataSource plugin Factory Registry."""

from __future__ import annotations

from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest, OnlyDataSourceFactory
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginOrigin, OnlyPluginOriginType, OnlyPluginType
from onlyalpha.plugin.errors import OnlyPluginRegistryError
from onlyalpha.plugin.registry import OnlyPluginFactoryRecord, only_register_plugin_factory


class OnlyDataSourceFactoryRegistry:
    def __init__(self) -> None:
        self._records: dict[str, OnlyPluginFactoryRecord] = {}

    def register(
        self,
        factory: OnlyDataSourceFactory,
        *,
        origin: OnlyPluginOrigin | None = None,
    ) -> None:
        only_register_plugin_factory(
            self._records,
            factory,
            origin or OnlyPluginOrigin(OnlyPluginOriginType.BUILTIN, "onlyalpha"),
            OnlyPluginType.DATA_SOURCE,
        )

    def resolve(self, plugin_id: str) -> OnlyDataSourceFactory:
        try:
            return self._records[plugin_id.lower()].factory  # type: ignore[return-value]
        except KeyError as exc:
            raise OnlyPluginRegistryError(
                "PLUGIN_NOT_FOUND",
                "DataSource plugin is not registered",
                plugin_id=plugin_id,
            ) from exc

    def require(self, plugin_id: str) -> OnlyDataSourceFactory:
        """Deprecated alias for resolve()."""

        return self.resolve(plugin_id)

    def descriptors(self) -> tuple[OnlyPluginDescriptor, ...]:
        return tuple(self._records[key].descriptor for key in sorted(self._records))

    def records(self) -> tuple[OnlyPluginFactoryRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))


__all__ = [
    "OnlyDataSourceCreateRequest",
    "OnlyDataSourceFactory",
    "OnlyDataSourceFactoryRegistry",
]
