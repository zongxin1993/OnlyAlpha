from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.cache.historical.models import OnlyCachePolicy


class OnlyBinanceMarketEnvironment(StrEnum):
    GLOBAL = "GLOBAL"
    US = "US"
    SPOT_TESTNET = "SPOT_TESTNET"


class OnlyBinanceSpotEndpointProfile(StrEnum):
    DEFAULT = "DEFAULT"
    PUBLIC_MARKET_DATA = "PUBLIC_MARKET_DATA"
    STANDARD = "STANDARD"
    GCP = "GCP"
    API1 = "API1"
    API2 = "API2"
    API3 = "API3"
    API4 = "API4"


@dataclass(frozen=True, slots=True)
class OnlyBinanceEndpointSet:
    rest_base_url: str
    market_stream_base_url: str
    websocket_api_base_url: str
    raw_stream_path: str = "/ws/{stream}"
    combined_stream_path: str = "/stream?streams={streams}"

    def raw_stream_url(self, stream: str) -> str:
        return self.market_stream_base_url + self.raw_stream_path.format(stream=stream)

    def combined_stream_url(self, streams: tuple[str, ...]) -> str:
        return self.market_stream_base_url + self.combined_stream_path.format(streams="/".join(streams))


_GLOBAL_REST_ENDPOINTS = {
    OnlyBinanceSpotEndpointProfile.PUBLIC_MARKET_DATA: "https://data-api.binance.vision",
    OnlyBinanceSpotEndpointProfile.STANDARD: "https://api.binance.com",
    OnlyBinanceSpotEndpointProfile.GCP: "https://api-gcp.binance.com",
    OnlyBinanceSpotEndpointProfile.API1: "https://api1.binance.com",
    OnlyBinanceSpotEndpointProfile.API2: "https://api2.binance.com",
    OnlyBinanceSpotEndpointProfile.API3: "https://api3.binance.com",
    OnlyBinanceSpotEndpointProfile.API4: "https://api4.binance.com",
}


def only_resolve_binance_spot_endpoints(
    environment: OnlyBinanceMarketEnvironment,
    endpoint_profile: OnlyBinanceSpotEndpointProfile,
) -> OnlyBinanceEndpointSet:
    if environment is OnlyBinanceMarketEnvironment.GLOBAL and endpoint_profile in _GLOBAL_REST_ENDPOINTS:
        return OnlyBinanceEndpointSet(
            _GLOBAL_REST_ENDPOINTS[endpoint_profile],
            "wss://stream.binance.com:9443",
            "wss://ws-api.binance.com:443/ws-api/v3",
        )
    if environment is OnlyBinanceMarketEnvironment.US and endpoint_profile is OnlyBinanceSpotEndpointProfile.DEFAULT:
        return OnlyBinanceEndpointSet(
            "https://api.binance.us",
            "wss://stream.binance.us:9443",
            "wss://ws-api.binance.us:443/ws-api/v3",
        )
    if environment is OnlyBinanceMarketEnvironment.SPOT_TESTNET and endpoint_profile in {
        OnlyBinanceSpotEndpointProfile.DEFAULT,
        OnlyBinanceSpotEndpointProfile.GCP,
    }:
        rest = (
            "https://testnet.binance.vision"
            if endpoint_profile is OnlyBinanceSpotEndpointProfile.DEFAULT
            else "https://api1.testnet.binance.vision"
        )
        return OnlyBinanceEndpointSet(
            rest,
            "wss://stream.testnet.binance.vision",
            "wss://ws-api.testnet.binance.vision/ws-api/v3",
        )
    raise ValueError("BINANCE_ENDPOINT_PROFILE_UNSUPPORTED")


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotDataSourceConfig:
    environment: OnlyBinanceMarketEnvironment = OnlyBinanceMarketEnvironment.GLOBAL
    endpoint_profile: OnlyBinanceSpotEndpointProfile = OnlyBinanceSpotEndpointProfile.PUBLIC_MARKET_DATA
    timeout_seconds: float = 10.0
    max_response_bytes: int = 8 * 1024 * 1024
    max_ws_message_bytes: int = 1024 * 1024
    reconnect_initial_seconds: float = 0.5
    reconnect_max_seconds: float = 30.0
    recovery_buffer_max_events: int = 100_000
    rest_page_size: int = 1000
    cache_policy: OnlyCachePolicy = OnlyCachePolicy.PREFER_CACHE

    def __post_init__(self) -> None:
        only_resolve_binance_spot_endpoints(self.environment, self.endpoint_profile)
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError("BINANCE_DATA_TIMEOUT_INVALID")
        if self.max_response_bytes <= 0 or self.max_ws_message_bytes <= 0:
            raise ValueError("BINANCE_DATA_SIZE_BOUND_INVALID")
        if not 0 < self.reconnect_initial_seconds <= self.reconnect_max_seconds <= 300:
            raise ValueError("BINANCE_RECONNECT_BOUND_INVALID")
        if self.recovery_buffer_max_events <= 0 or not 1 <= self.rest_page_size <= 1000:
            raise ValueError("BINANCE_DATA_OPERATION_BOUND_INVALID")

    @classmethod
    def parse(cls, raw: Mapping[str, object]) -> OnlyBinanceSpotDataSourceConfig:
        allowed = {
            "environment",
            "endpoint_profile",
            "timeout_seconds",
            "max_response_bytes",
            "max_ws_message_bytes",
            "reconnect_initial_seconds",
            "reconnect_max_seconds",
            "recovery_buffer_max_events",
            "rest_page_size",
            "cache_policy",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise ValueError(f"BINANCE_DATA_CONFIG_UNKNOWN_FIELDS: {','.join(unknown)}")
        raw_environment = str(raw.get("environment", "GLOBAL")).upper()
        environment = (
            OnlyBinanceMarketEnvironment.GLOBAL
            if raw_environment == "LIVE"
            else OnlyBinanceMarketEnvironment(raw_environment)
        )
        default_profile = {
            OnlyBinanceMarketEnvironment.GLOBAL: (
                OnlyBinanceSpotEndpointProfile.STANDARD
                if raw_environment == "LIVE"
                else OnlyBinanceSpotEndpointProfile.PUBLIC_MARKET_DATA
            ),
            OnlyBinanceMarketEnvironment.US: OnlyBinanceSpotEndpointProfile.DEFAULT,
            OnlyBinanceMarketEnvironment.SPOT_TESTNET: OnlyBinanceSpotEndpointProfile.DEFAULT,
        }[environment]
        return cls(
            environment=environment,
            endpoint_profile=OnlyBinanceSpotEndpointProfile(
                str(raw.get("endpoint_profile", default_profile.value)).upper()
            ),
            timeout_seconds=float(str(raw.get("timeout_seconds", 10.0))),
            max_response_bytes=int(str(raw.get("max_response_bytes", 8 * 1024 * 1024))),
            max_ws_message_bytes=int(str(raw.get("max_ws_message_bytes", 1024 * 1024))),
            reconnect_initial_seconds=float(str(raw.get("reconnect_initial_seconds", 0.5))),
            reconnect_max_seconds=float(str(raw.get("reconnect_max_seconds", 30.0))),
            recovery_buffer_max_events=int(str(raw.get("recovery_buffer_max_events", 100_000))),
            rest_page_size=int(str(raw.get("rest_page_size", 1000))),
            cache_policy=OnlyCachePolicy(str(raw.get("cache_policy", "prefer_cache"))),
        )

    @property
    def endpoints(self) -> OnlyBinanceEndpointSet:
        return only_resolve_binance_spot_endpoints(self.environment, self.endpoint_profile)
