"""Structured plugin errors shared by discovery, registries, and assembly."""

from __future__ import annotations


class OnlyPluginError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        plugin_id: str | None = None,
        resource_id: str | None = None,
        origin: str | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.plugin_id = plugin_id
        self.resource_id = resource_id
        self.origin = origin
        context = ", ".join(
            f"{key}={value}"
            for key, value in (("plugin_id", plugin_id), ("resource_id", resource_id), ("origin", origin))
            if value is not None
        )
        suffix = f" ({context})" if context else ""
        super().__init__(f"{code}: {message}{suffix}")


class OnlyPluginApiVersionError(OnlyPluginError):
    pass


class OnlyPluginDescriptorError(OnlyPluginError):
    pass


class OnlyPluginRegistryError(OnlyPluginError):
    pass


class OnlyPluginDiscoveryError(OnlyPluginError):
    pass


class OnlyPluginCapabilityError(OnlyPluginError):
    pass


class OnlyPluginLifecycleError(OnlyPluginError):
    pass
