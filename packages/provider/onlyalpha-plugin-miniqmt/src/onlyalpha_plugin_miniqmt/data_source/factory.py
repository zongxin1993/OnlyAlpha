from collections.abc import Mapping, Sequence

from onlyalpha.plugin.capabilities import OnlyPluginValidationIssue
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest

from ..config import OnlyMiniQmtConfig
from ..descriptor import DATA_CAPABILITIES, DATA_DESCRIPTOR
from ..sdk.loader import load_xtquant
from .resource import OnlyMiniQmtDataSource


class OnlyMiniQmtDataSourceFactory:
    descriptor = DATA_DESCRIPTOR

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyMiniQmtConfig:
        return OnlyMiniQmtConfig.parse(dict(extensions))

    def validate_request(self, request: OnlyDataSourceCreateRequest) -> Sequence[OnlyPluginValidationIssue]:
        return tuple(
            OnlyPluginValidationIssue("PLUGIN_CAPABILITY_MISSING", item)
            for item in DATA_CAPABILITIES.missing(request.requested_capabilities)
        )

    def create(self, request: OnlyDataSourceCreateRequest) -> OnlyMiniQmtDataSource:
        config = (
            request.plugin_config if isinstance(request.plugin_config, OnlyMiniQmtConfig) else self.parse_config({})
        )
        config.require_path()
        sdk = load_xtquant()
        return OnlyMiniQmtDataSource(request, config, sdk.xtdata)


factory = OnlyMiniQmtDataSourceFactory()
