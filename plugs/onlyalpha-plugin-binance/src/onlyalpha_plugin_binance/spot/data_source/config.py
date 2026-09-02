from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from onlyalpha.cache.historical.models import OnlyCachePolicy
from onlyalpha_plugin_binance.common.environment import OnlyBinanceEnvironment


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotDataSourceConfig:
    environment: OnlyBinanceEnvironment = OnlyBinanceEnvironment.LIVE
    timeout_seconds: float = 10.0
    max_response_bytes: int = 8 * 1024 * 1024
    max_ws_message_bytes: int = 1024 * 1024
    reconnect_initial_seconds: float = 0.5
    reconnect_max_seconds: float = 30.0
    recovery_buffer_max_events: int = 100_000
    rest_page_size: int = 1000
    cache_policy: OnlyCachePolicy = OnlyCachePolicy.PREFER_CACHE

    def __post_init__(self) -> None:
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
        return cls(
            environment=OnlyBinanceEnvironment(str(raw.get("environment", "LIVE"))),
            timeout_seconds=float(str(raw.get("timeout_seconds", 10.0))),
            max_response_bytes=int(str(raw.get("max_response_bytes", 8 * 1024 * 1024))),
            max_ws_message_bytes=int(str(raw.get("max_ws_message_bytes", 1024 * 1024))),
            reconnect_initial_seconds=float(str(raw.get("reconnect_initial_seconds", 0.5))),
            reconnect_max_seconds=float(str(raw.get("reconnect_max_seconds", 30.0))),
            recovery_buffer_max_events=int(str(raw.get("recovery_buffer_max_events", 100_000))),
            rest_page_size=int(str(raw.get("rest_page_size", 1000))),
            cache_policy=OnlyCachePolicy(str(raw.get("cache_policy", "prefer_cache"))),
        )
