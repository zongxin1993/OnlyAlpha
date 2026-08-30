from collections.abc import Mapping, Sequence

from onlyalpha.plugin.capabilities import OnlyPluginValidationIssue
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest

from ...descriptor import DATA_CAPABILITIES, DATA_DESCRIPTOR
from .config import OnlyBinanceSpotDataSourceConfig
from .resource import OnlyBinanceSpotDataSource


class OnlyBinanceSpotDataSourceFactory:
    descriptor = DATA_DESCRIPTOR

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyBinanceSpotDataSourceConfig:
        return OnlyBinanceSpotDataSourceConfig.parse(extensions)

    def validate_request(self, request: OnlyDataSourceCreateRequest) -> Sequence[OnlyPluginValidationIssue]:
        issues = [
            OnlyPluginValidationIssue("PLUGIN_CAPABILITY_MISSING", item)
            for item in DATA_CAPABILITIES.missing(request.requested_capabilities)
        ]
        if not isinstance(request.plugin_config, OnlyBinanceSpotDataSourceConfig):
            issues.append(
                OnlyPluginValidationIssue("BINANCE_PLUGIN_CONFIG_INVALID", "parsed Binance config is required")
            )
        if request.market_data_sink is None and (
            request.requested_capabilities.live_bars or request.requested_capabilities.live_ticks
        ):
            issues.append(OnlyPluginValidationIssue("BINANCE_MARKET_DATA_SINK_REQUIRED", "live sink is required"))
        if request.historical_cache_service is None and (
            request.requested_capabilities.historical_bars or request.requested_capabilities.historical_ticks
        ):
            issues.append(
                OnlyPluginValidationIssue("BINANCE_HISTORICAL_CACHE_REQUIRED", "historical cache is required")
            )
        return tuple(issues)

    def create(self, request: OnlyDataSourceCreateRequest) -> OnlyBinanceSpotDataSource:
        if not isinstance(request.plugin_config, OnlyBinanceSpotDataSourceConfig):
            raise TypeError("Binance DataSource requires OnlyBinanceSpotDataSourceConfig")
        return OnlyBinanceSpotDataSource(request, request.plugin_config)


factory = OnlyBinanceSpotDataSourceFactory()
