"""Plugin identity, type, and registration origin models."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.plugin.errors import OnlyPluginDescriptorError
from onlyalpha.plugin.version import OnlyPluginApiVersion

_PLUGIN_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")


class OnlyPluginType(StrEnum):
    DATA_SOURCE = "DATA_SOURCE"
    BROKER = "BROKER"


class OnlyPluginOriginType(StrEnum):
    BUILTIN = "BUILTIN"
    ENTRY_POINT = "ENTRY_POINT"
    TEST = "TEST"


@dataclass(frozen=True, slots=True)
class OnlyPluginOrigin:
    origin_type: OnlyPluginOriginType
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("plugin origin value is required")

    def __str__(self) -> str:
        return f"{self.origin_type.value}:{self.value}"


@dataclass(frozen=True, slots=True)
class OnlyPluginDescriptor:
    plugin_id: str
    plugin_type: OnlyPluginType
    plugin_version: str
    api_version: OnlyPluginApiVersion
    display_name: str
    provider: str | None
    capabilities: object

    def __post_init__(self) -> None:
        if not _PLUGIN_ID.fullmatch(self.plugin_id):
            raise OnlyPluginDescriptorError(
                "PLUGIN_DESCRIPTOR_INVALID",
                "plugin_id must be a stable lowercase identifier",
                plugin_id=self.plugin_id or None,
            )
        if not self.plugin_version.strip() or not self.display_name.strip():
            raise OnlyPluginDescriptorError(
                "PLUGIN_DESCRIPTOR_INVALID",
                "plugin_version and display_name are required",
                plugin_id=self.plugin_id,
            )
