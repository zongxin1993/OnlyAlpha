from __future__ import annotations

import os
from dataclasses import dataclass

from onlyalpha.domain.identifiers import OnlyAccountId

from onlyalpha_broker_binance.environment import OnlyBinanceBrokerEnvironment
from onlyalpha_broker_binance.private_http import OnlyBinanceCredentials


@dataclass(frozen=True, slots=True, repr=False)
class OnlyBinanceSpotBrokerConfig:
    environment: OnlyBinanceBrokerEnvironment
    account_id: OnlyAccountId
    credentials: OnlyBinanceCredentials
    recv_window_ms: int = 5_000
    timeout_seconds: float = 10.0
    max_response_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        if (
            not 1 <= self.recv_window_ms <= 60_000
            or self.timeout_seconds <= 0
            or self.timeout_seconds > 30
            or self.max_response_bytes <= 0
        ):
            raise ValueError("BINANCE_SPOT_BROKER_CONFIGURATION_INVALID")

    def __repr__(self) -> str:
        return (
            "OnlyBinanceSpotBrokerConfig("
            f"environment={self.environment!r}, account_id={self.account_id!r}, credentials=<redacted>, "
            f"recv_window_ms={self.recv_window_ms}, timeout_seconds={self.timeout_seconds}, "
            f"max_response_bytes={self.max_response_bytes})"
        )

    @classmethod
    def from_environment(
        cls,
        *,
        environment: OnlyBinanceBrokerEnvironment,
        account_id: OnlyAccountId,
        api_key_env: str = "ONLYALPHA_BINANCE_API_KEY",
        secret_key_env: str = "ONLYALPHA_BINANCE_SECRET_KEY",
    ) -> OnlyBinanceSpotBrokerConfig:
        api_key = os.environ.get(api_key_env)
        secret_key = os.environ.get(secret_key_env)
        if not api_key or not secret_key:
            raise ValueError("BINANCE_SPOT_CREDENTIALS_REQUIRED")
        return cls(environment, account_id, OnlyBinanceCredentials(api_key, secret_key))
