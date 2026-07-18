"""External deterministic historical DataSource plugin."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from onlyalpha.plugin.api import (
    ONLYALPHA_PLUGIN_API_VERSION,
    OnlyDataSourceCapabilities,
    OnlyDataSourceCreateRequest,
    OnlyPluginDescriptor,
    OnlyPluginType,
    OnlyPluginValidationIssue,
)
from onlyalpha.plugin.testing import (
    OnlySyntheticDataSourceFactory,
    OnlySyntheticHistoricalDataSource,
    OnlySyntheticPluginConfig,
)

_DESCRIPTOR = OnlyPluginDescriptor(
    "test-external-data",
    OnlyPluginType.DATA_SOURCE,
    "0.1.0",
    ONLYALPHA_PLUGIN_API_VERSION,
    "OnlyAlpha External Test DataSource",
    "OnlyAlpha Tests",
    OnlyDataSourceCapabilities(historical_bars=True),
)


class OnlyExternalTestHistoricalDataSource(OnlySyntheticHistoricalDataSource):
    @property
    def plugin_descriptor(self) -> OnlyPluginDescriptor:
        return _DESCRIPTOR


class OnlyExternalTestDataSourceFactory:
    def __init__(self) -> None:
        self._delegate = OnlySyntheticDataSourceFactory()

    @property
    def descriptor(self) -> OnlyPluginDescriptor:
        return _DESCRIPTOR

    def parse_config(self, extensions: Mapping[str, object]) -> OnlySyntheticPluginConfig:
        return self._delegate.parse_config(extensions)

    def validate_request(self, request: OnlyDataSourceCreateRequest) -> Sequence[OnlyPluginValidationIssue]:
        return self._delegate.validate_request(request)

    def create(self, request: OnlyDataSourceCreateRequest) -> OnlyExternalTestHistoricalDataSource:
        source = self._delegate.create(request)
        return OnlyExternalTestHistoricalDataSource(source.config)


def factory() -> OnlyExternalTestDataSourceFactory:
    return OnlyExternalTestDataSourceFactory()
