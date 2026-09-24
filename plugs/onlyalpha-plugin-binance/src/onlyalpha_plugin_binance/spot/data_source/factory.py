import time
from collections.abc import Mapping, Sequence

from onlyalpha.plugin.capabilities import OnlyPluginValidationIssue
from onlyalpha.plugin.data_source import (
    OnlyDataSourceCreateRequest,
    OnlyDataSourceInstrumentCatalogRequestV1,
    OnlyDataSourceInstrumentV1,
    OnlyDataSourceMarketIdentityV1,
)
from onlyalpha.plugin.integration_probe import OnlyIntegrationProbeRequest, OnlyIntegrationProbeResult

from ...common.http import OnlyBinancePublicHttpClient
from ...descriptor import DATA_CAPABILITIES, DATA_DESCRIPTOR, SPOT_DATA_INTEGRATION_TYPE
from ..reference.client import OnlyBinanceSpotReferenceClient
from .config import OnlyBinanceSpotDataSourceConfig
from .historical import OnlyBinanceSpotHistoricalClient
from .instrument_catalog import MARKET, VENUE, OnlyBinanceSpotInstrumentCatalog
from .probe import OnlyBinanceSpotProbe
from .resource import OnlyBinanceSpotDataSource
from .websocket import OnlyBinanceWebSocketTransport


class OnlyBinanceSpotDataSourceFactory:
    descriptor = DATA_DESCRIPTOR
    integration_type = SPOT_DATA_INTEGRATION_TYPE

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyBinanceSpotDataSourceConfig:
        return OnlyBinanceSpotDataSourceConfig.parse(extensions)

    def parse_runtime_integration_config(
        self, public_configuration: Mapping[str, object], resolved_secrets: Mapping[str, str]
    ) -> OnlyBinanceSpotDataSourceConfig:
        return self.parse_config(public_configuration)

    def list_instruments(
        self, request: OnlyDataSourceInstrumentCatalogRequestV1
    ) -> tuple[OnlyDataSourceInstrumentV1, ...]:
        return OnlyBinanceSpotInstrumentCatalog().list_instruments(request)

    def market_identity(self, plugin_config: object) -> OnlyDataSourceMarketIdentityV1:
        if not isinstance(plugin_config, OnlyBinanceSpotDataSourceConfig):
            raise ValueError("BINANCE_PLUGIN_CONFIG_INVALID")
        return OnlyDataSourceMarketIdentityV1(VENUE, MARKET)

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
        if request.durable_recording_required and request.provider_evidence_sink is None:
            issues.append(
                OnlyPluginValidationIssue(
                    "DURABLE_MARKET_DATA_RECORDER_REQUIRED",
                    "production durable market data requires a recorder",
                )
            )
        return tuple(issues)

    def create(self, request: OnlyDataSourceCreateRequest) -> OnlyBinanceSpotDataSource:
        if not isinstance(request.plugin_config, OnlyBinanceSpotDataSourceConfig):
            raise TypeError("Binance DataSource requires OnlyBinanceSpotDataSourceConfig")
        if request.durable_recording_required and request.provider_evidence_sink is None:
            raise RuntimeError("DURABLE_MARKET_DATA_RECORDER_REQUIRED")
        return OnlyBinanceSpotDataSource(request, request.plugin_config)

    def probe(self, request: OnlyIntegrationProbeRequest) -> OnlyIntegrationProbeResult:
        config = self.parse_config(request.public_configuration)
        remaining = request.deadline_monotonic - time.monotonic()
        timeout = min(config.timeout_seconds, request.policy.per_check_timeout_seconds, remaining)
        if timeout <= 0:
            timeout = 0.001
        http = OnlyBinancePublicHttpClient(
            config.environment.rest_base_url,
            timeout_seconds=timeout,
            max_response_bytes=config.max_response_bytes,
            deadline_monotonic=request.deadline_monotonic,
        )
        websocket = OnlyBinanceWebSocketTransport(
            timeout_seconds=timeout,
            max_message_bytes=config.max_ws_message_bytes,
            deadline_monotonic=request.deadline_monotonic,
        )

        def bind_deadline(deadline_monotonic: float) -> None:
            http.bind_deadline(deadline_monotonic)
            websocket.bind_deadline(deadline_monotonic)

        return OnlyBinanceSpotProbe(
            OnlyBinanceSpotReferenceClient(http),
            OnlyBinanceSpotHistoricalClient(http),
            websocket,
            websocket_base_url=config.environment.websocket_base_url,
            bind_deadline=bind_deadline,
        ).probe(request)


factory = OnlyBinanceSpotDataSourceFactory()
