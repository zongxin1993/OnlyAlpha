"""Read-only Integration Type projection over existing Plugin registries."""

from __future__ import annotations

from onlyalpha.broker.factory import OnlyBrokerFactoryRegistry
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginType
from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationTypeProvider,
    only_integration_capability_ids,
)


class OnlyIntegrationTypeCatalogError(LookupError):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")


class OnlyIntegrationTypeCatalog:
    def __init__(
        self,
        data_sources: OnlyDataSourceFactoryRegistry,
        brokers: OnlyBrokerFactoryRegistry,
    ) -> None:
        descriptors: dict[str, OnlyIntegrationTypeDescriptorV1] = {}
        for record in (*data_sources.records(), *brokers.records()):
            if not isinstance(record.factory, OnlyIntegrationTypeProvider):
                continue
            declared = record.factory.integration_type
            if not isinstance(declared, OnlyIntegrationTypeDescriptorV1):
                self._invalid(record.descriptor, "factory integration_type has an invalid contract")
            self._validate_projection(record.descriptor, declared)
            type_id = declared.type_id.value
            if type_id in descriptors:
                self._invalid(record.descriptor, f"duplicate Integration Type {type_id}")
            descriptors[type_id] = declared
        self._descriptors = descriptors

    def list(self, category: OnlyIntegrationCategory | None = None) -> tuple[OnlyIntegrationTypeDescriptorV1, ...]:
        return tuple(
            descriptor
            for type_id, descriptor in sorted(self._descriptors.items())
            if category is None or descriptor.category is category
        )

    def require(self, type_id: str) -> OnlyIntegrationTypeDescriptorV1:
        try:
            return self._descriptors[type_id]
        except KeyError as exc:
            raise OnlyIntegrationTypeCatalogError(
                "INTEGRATION_TYPE_NOT_FOUND", "Integration Type is not available"
            ) from exc

    @staticmethod
    def _validate_projection(
        plugin: OnlyPluginDescriptor,
        integration: OnlyIntegrationTypeDescriptorV1,
    ) -> None:
        expected_category = {
            OnlyPluginType.DATA_SOURCE: OnlyIntegrationCategory.DATA_SOURCE,
            OnlyPluginType.BROKER: OnlyIntegrationCategory.BROKER,
        }[plugin.plugin_type]
        valid = (
            integration.category is expected_category
            and integration.implementation_id == plugin.plugin_id
            and integration.implementation_version == plugin.plugin_version
            and integration.public_api_version == str(plugin.api_version)
            and integration.capabilities == only_integration_capability_ids(plugin.capabilities)
        )
        if not valid:
            OnlyIntegrationTypeCatalog._invalid(plugin, "Integration Type does not match Plugin descriptor")

    @staticmethod
    def _invalid(plugin: OnlyPluginDescriptor, detail: str) -> None:
        raise OnlyIntegrationTypeCatalogError("INTEGRATION_TYPE_CONTRACT_INVALID", f"{plugin.plugin_id}: {detail}")


__all__ = ["OnlyIntegrationTypeCatalog", "OnlyIntegrationTypeCatalogError"]
