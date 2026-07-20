from collections.abc import Mapping, Sequence

from onlyalpha.plugin.capabilities import OnlyPluginValidationIssue
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest

from ..config import OnlyTushareConfig
from ..descriptor import DATA_CAPABILITIES, DATA_DESCRIPTOR
from .resource import OnlyTushareHistoricalDataSource


class OnlyTushareDataSourceFactory:
    descriptor = DATA_DESCRIPTOR

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyTushareConfig:
        return OnlyTushareConfig.parse(dict(extensions))

    def validate_request(self, request: OnlyDataSourceCreateRequest) -> Sequence[OnlyPluginValidationIssue]:
        issues = [
            OnlyPluginValidationIssue("PLUGIN_CAPABILITY_MISSING", item)
            for item in DATA_CAPABILITIES.missing(request.requested_capabilities)
        ]
        return tuple(issues)

    def create(self, request: OnlyDataSourceCreateRequest) -> OnlyTushareHistoricalDataSource:
        config = (
            request.plugin_config if isinstance(request.plugin_config, OnlyTushareConfig) else self.parse_config({})
        )
        return OnlyTushareHistoricalDataSource(request, config)


factory = OnlyTushareDataSourceFactory()
