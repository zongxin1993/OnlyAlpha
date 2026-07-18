from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from onlyalpha.plugin import (
    ONLYALPHA_PLUGIN_API_VERSION,
    OnlyDataSourceCapabilities,
    OnlyPluginDescriptor,
    OnlyPluginType,
    OnlyPluginValidationIssue,
)


@dataclass
class OnlyTestFactory:
    descriptor: OnlyPluginDescriptor

    def parse_config(self, extensions: Mapping[str, object]) -> object:
        return dict(extensions)

    def validate_request(self, request: object) -> Sequence[OnlyPluginValidationIssue]:
        del request
        return ()

    def create(self, request: object) -> object:
        return request


def only_test_descriptor(
    plugin_id: str = "unit-data",
    plugin_type: OnlyPluginType = OnlyPluginType.DATA_SOURCE,
) -> OnlyPluginDescriptor:
    return OnlyPluginDescriptor(
        plugin_id,
        plugin_type,
        "1.0.0",
        ONLYALPHA_PLUGIN_API_VERSION,
        "Unit Plugin",
        "OnlyAlpha Tests",
        OnlyDataSourceCapabilities(historical_bars=True),
    )
