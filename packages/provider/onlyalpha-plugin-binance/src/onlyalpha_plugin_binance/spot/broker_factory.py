"""Canonical Broker SPI composition for Binance Spot."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import urlparse

from onlyalpha.broker.reconciliation import (
    OnlyBrokerReadinessAuthority,
    OnlyBrokerReconciliationCoordinator,
)
from onlyalpha.domain.enums import OnlyCurrencyType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency
from onlyalpha.plugin.broker import OnlyBrokerComponent, OnlyBrokerCreateRequest
from onlyalpha.plugin.capabilities import OnlyBrokerPluginCapabilities, OnlyPluginValidationIssue
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor
from onlyalpha.plugin.lifecycle import (
    OnlyPluginHealth,
    OnlyPluginHealthStatus,
    OnlyPluginLifecycleState,
)
from onlyalpha_plugin_binance.common.environment import OnlyBinanceEnvironment
from onlyalpha_plugin_binance.common.private_http import (
    OnlyBinanceCredentials,
    OnlyBinancePrivateHttpClient,
    OnlyBinancePrivateTransport,
)
from onlyalpha_plugin_binance.descriptor import BROKER_DESCRIPTOR
from onlyalpha_plugin_binance.spot.broker.discovery import OnlyBinanceSpotVenueDiscovery
from onlyalpha_plugin_binance.spot.broker.gateway import OnlyBinanceSpotBrokerGateway
from onlyalpha_plugin_binance.spot.broker.rest import OnlyBinanceSpotPrivateRestClient
from onlyalpha_plugin_binance.spot.broker.stream import (
    OnlyBinanceSpotUserStream,
    OnlyBinanceSpotUserStreamNormalizer,
    OnlyBinanceThreadedUserStreamTransport,
    OnlyBinanceUserStreamTransport,
)


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotBrokerPluginConfig:
    environment: OnlyBinanceEnvironment
    api_key_env: str
    api_secret_env: str
    rest_base_url: str
    websocket_api_base_url: str
    currencies: tuple[tuple[str, int], ...]
    recv_window_ms: int = 5_000
    timeout_seconds: float = 10.0
    max_response_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        if (
            not self.api_key_env.startswith("ONLYALPHA_BINANCE_")
            or not self.api_secret_env.startswith("ONLYALPHA_BINANCE_")
            or not self.currencies
            or len({code for code, _precision in self.currencies}) != len(self.currencies)
            or any(not code.isalnum() or code != code.upper() or precision < 0 for code, precision in self.currencies)
            or not 1 <= self.recv_window_ms <= 60_000
            or self.timeout_seconds <= 0
            or self.timeout_seconds > 30
            or self.max_response_bytes <= 0
        ):
            raise ValueError("BINANCE_SPOT_BROKER_PLUGIN_CONFIGURATION_INVALID")
        if self.environment is OnlyBinanceEnvironment.SPOT_TESTNET and (
            not self.api_key_env.startswith("ONLYALPHA_BINANCE_TESTNET_")
            or not self.api_secret_env.startswith("ONLYALPHA_BINANCE_TESTNET_")
        ):
            raise ValueError("BINANCE_TESTNET_DEDICATED_CREDENTIAL_ENV_REQUIRED")
        _validate_environment_hosts(self.environment, self.rest_base_url, self.websocket_api_base_url)


def _validate_environment_hosts(environment: OnlyBinanceEnvironment, rest_url: str, websocket_url: str) -> None:
    rest = urlparse(rest_url)
    websocket = urlparse(websocket_url)
    if rest.scheme != "https" or websocket.scheme != "wss" or not rest.hostname or not websocket.hostname:
        raise ValueError("BINANCE_BROKER_ENDPOINT_INVALID")
    if environment is OnlyBinanceEnvironment.SPOT_TESTNET:
        if rest.hostname != "testnet.binance.vision" or websocket.hostname != "ws-api.testnet.binance.vision":
            raise ValueError("BINANCE_TESTNET_MAINNET_ENDPOINT_FORBIDDEN")


def _integer_extension(extensions: Mapping[str, object], name: str, default: int) -> int:
    value = extensions.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"BINANCE_SPOT_BROKER_{name.upper()}_INVALID")
    return value


def _float_extension(extensions: Mapping[str, object], name: str, default: float) -> float:
    value = extensions.get(name, default)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"BINANCE_SPOT_BROKER_{name.upper()}_INVALID")
    return float(value)


class OnlyBinanceSpotBrokerResource:
    def __init__(
        self,
        gateway: OnlyBinanceSpotBrokerGateway,
        stream: OnlyBinanceSpotUserStream,
        reconciliation: OnlyBrokerReconciliationCoordinator,
    ) -> None:
        self.gateway = gateway
        self.stream = stream
        self.reconciliation = reconciliation
        self._state = OnlyPluginLifecycleState.CREATED

    @property
    def plugin_descriptor(self) -> OnlyPluginDescriptor:
        return BROKER_DESCRIPTOR

    @property
    def plugin_resource_id(self) -> str:
        return str(self.gateway.connection_snapshot().gateway_id)

    @property
    def state(self) -> OnlyPluginLifecycleState:
        return self._state

    def initialize(self) -> None:
        if self._state is not OnlyPluginLifecycleState.CREATED:
            raise RuntimeError("BINANCE_BROKER_RESOURCE_INITIALIZE_STATE_INVALID")
        self._state = OnlyPluginLifecycleState.INITIALIZED

    def connect(self) -> object:
        if self._state is not OnlyPluginLifecycleState.INITIALIZED:
            raise RuntimeError("BINANCE_BROKER_RESOURCE_CONNECT_STATE_INVALID")
        self._state = OnlyPluginLifecycleState.CONNECTING
        try:
            self.gateway.connect()
            result = self.gateway.authenticate()
            self.stream.connect(f"onlyalpha-{self.plugin_resource_id}"[:36])
        except Exception:
            self._state = OnlyPluginLifecycleState.FAILED
            raise
        self._state = OnlyPluginLifecycleState.CONNECTED
        return result

    def start(self) -> None:
        if self._state is not OnlyPluginLifecycleState.CONNECTED:
            raise RuntimeError("BINANCE_BROKER_RESOURCE_START_STATE_INVALID")
        self._state = OnlyPluginLifecycleState.RUNNING

    def stop(self) -> None:
        if self._state not in {OnlyPluginLifecycleState.CONNECTED, OnlyPluginLifecycleState.RUNNING}:
            return
        self._state = OnlyPluginLifecycleState.STOPPING
        self.stream.disconnect()
        self.gateway.disconnect()
        self._state = OnlyPluginLifecycleState.STOPPED

    def close(self) -> None:
        self.stop()
        if self._state is OnlyPluginLifecycleState.CREATED:
            self._state = OnlyPluginLifecycleState.STOPPED

    def health(self) -> OnlyPluginHealth:
        if self._state is OnlyPluginLifecycleState.FAILED:
            return OnlyPluginHealth(OnlyPluginHealthStatus.UNHEALTHY, "Binance Broker resource failed")
        if self._state is OnlyPluginLifecycleState.STOPPED:
            return OnlyPluginHealth(OnlyPluginHealthStatus.STOPPED)
        if self.gateway.connection_snapshot().state.value == "READY":
            return OnlyPluginHealth(OnlyPluginHealthStatus.HEALTHY)
        return OnlyPluginHealth(OnlyPluginHealthStatus.DEGRADED, "Broker reconciliation/stream trust incomplete")


class OnlyBinanceSpotBrokerFactory:
    def __init__(
        self,
        *,
        private_transport: OnlyBinancePrivateTransport | None = None,
        user_stream_transport: Callable[[], OnlyBinanceUserStreamTransport] = OnlyBinanceThreadedUserStreamTransport,
    ) -> None:
        self._private_transport = private_transport
        self._user_stream_transport = user_stream_transport

    @property
    def descriptor(self) -> OnlyPluginDescriptor:
        return BROKER_DESCRIPTOR

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyBinanceSpotBrokerPluginConfig:
        allowed = {
            "environment",
            "api_key_env",
            "api_secret_env",
            "rest_base_url",
            "websocket_api_base_url",
            "currencies",
            "recv_window_ms",
            "timeout_seconds",
            "max_response_bytes",
        }
        unknown = set(extensions) - allowed
        if unknown:
            raise ValueError(f"unknown Binance Spot Broker extensions: {', '.join(sorted(unknown))}")
        environment = OnlyBinanceEnvironment(str(extensions.get("environment", "SPOT_TESTNET")).upper())
        raw_currencies = extensions.get("currencies")
        if not isinstance(raw_currencies, Mapping) or not raw_currencies:
            raise ValueError("BINANCE_SPOT_BROKER_CURRENCIES_REQUIRED")
        default_key_env = (
            "ONLYALPHA_BINANCE_TESTNET_API_KEY"
            if environment is OnlyBinanceEnvironment.SPOT_TESTNET
            else "ONLYALPHA_BINANCE_API_KEY"
        )
        default_secret_env = (
            "ONLYALPHA_BINANCE_TESTNET_API_SECRET"
            if environment is OnlyBinanceEnvironment.SPOT_TESTNET
            else "ONLYALPHA_BINANCE_API_SECRET"
        )
        return OnlyBinanceSpotBrokerPluginConfig(
            environment,
            str(extensions.get("api_key_env", default_key_env)),
            str(extensions.get("api_secret_env", default_secret_env)),
            str(extensions.get("rest_base_url", environment.rest_base_url)),
            str(extensions.get("websocket_api_base_url", environment.websocket_api_base_url)),
            tuple(sorted((str(code), int(precision)) for code, precision in raw_currencies.items())),
            _integer_extension(extensions, "recv_window_ms", 5_000),
            _float_extension(extensions, "timeout_seconds", 10.0),
            _integer_extension(extensions, "max_response_bytes", 8 * 1024 * 1024),
        )

    def validate_request(self, request: OnlyBrokerCreateRequest) -> Sequence[OnlyPluginValidationIssue]:
        issues: list[OnlyPluginValidationIssue] = []
        capabilities = self.descriptor.capabilities
        if not isinstance(capabilities, OnlyBrokerPluginCapabilities):
            issues.append(OnlyPluginValidationIssue("PLUGIN_DESCRIPTOR_INVALID", "invalid Broker capabilities"))
        else:
            issues.extend(
                OnlyPluginValidationIssue(
                    "PLUGIN_CAPABILITY_NOT_SUPPORTED",
                    f"Binance Spot Broker does not support {name}",
                    name,
                )
                for name in capabilities.missing(request.requested_capabilities)
            )
        if not isinstance(request.plugin_config, OnlyBinanceSpotBrokerPluginConfig):
            issues.append(OnlyPluginValidationIssue("PLUGIN_CONFIG_INVALID", "invalid Binance Spot Broker config"))
        if request.command_evidence_store is None:
            issues.append(
                OnlyPluginValidationIssue(
                    "BROKER_COMMAND_DURABILITY_REQUIRED",
                    "Binance Spot Broker requires the Runtime-owned durable command evidence port",
                    "command_evidence_store",
                )
            )
        return tuple(issues)

    def create(self, request: OnlyBrokerCreateRequest) -> OnlyBrokerComponent:
        issues = self.validate_request(request)
        if issues:
            raise ValueError("; ".join(f"{item.code}: {item.message}" for item in issues))
        config = request.plugin_config
        assert isinstance(config, OnlyBinanceSpotBrokerPluginConfig)
        evidence = request.command_evidence_store
        assert evidence is not None
        api_key = os.environ.get(config.api_key_env)
        api_secret = os.environ.get(config.api_secret_env)
        if not api_key or not api_secret:
            raise ValueError("BINANCE_SPOT_CREDENTIALS_REQUIRED")
        credentials = OnlyBinanceCredentials(api_key, api_secret)
        if self._private_transport is None:
            http = OnlyBinancePrivateHttpClient(
                config.rest_base_url,
                credentials,
                lambda: request.clock.timestamp_ns() // 1_000_000,
                recv_window_ms=config.recv_window_ms,
                timeout_seconds=config.timeout_seconds,
                max_response_bytes=config.max_response_bytes,
            )
        else:
            http = OnlyBinancePrivateHttpClient(
                config.rest_base_url,
                credentials,
                lambda: request.clock.timestamp_ns() // 1_000_000,
                recv_window_ms=config.recv_window_ms,
                timeout_seconds=config.timeout_seconds,
                max_response_bytes=config.max_response_bytes,
                transport=self._private_transport,
            )
        rest = OnlyBinanceSpotPrivateRestClient(http)
        readiness = OnlyBrokerReadinessAuthority()

        def now() -> OnlyTimestamp:
            return OnlyTimestamp.from_unix_nanos(request.clock.timestamp_ns())

        currencies = {
            code: OnlyCurrency(code, precision, OnlyCurrencyType.CRYPTO) for code, precision in config.currencies
        }
        gateway = OnlyBinanceSpotBrokerGateway(
            gateway_id=request.gateway_id,
            account_id=request.account_id,
            rest=rest,
            readiness=readiness,
            evidence=evidence,
            currencies=currencies,
            now=now,
        )
        normalizer = OnlyBinanceSpotUserStreamNormalizer(
            runtime_id=request.runtime_id,
            gateway_id=request.gateway_id,
            account_id=request.account_id,
            identities=gateway.resolve_order_identity,
            currencies=currencies,
            received_at=now,
        )
        stream = OnlyBinanceSpotUserStream(
            websocket_base_url=config.websocket_api_base_url,
            transport=self._user_stream_transport(),
            normalizer=normalizer,
            inbound=request.broker_inbound_queue,
            credentials=credentials,
            timestamp_ms=lambda: request.clock.timestamp_ns() // 1_000_000,
            recv_window_ms=config.recv_window_ms,
            on_subscription_acknowledged=gateway.stream_lost,
        )
        discovery = OnlyBinanceSpotVenueDiscovery(
            runtime_id=request.runtime_id,
            gateway_id=request.gateway_id,
            account_id=request.account_id,
            rest=rest,
            gateway=gateway,
            now=now,
            stable_venue_history=config.environment is OnlyBinanceEnvironment.LIVE,
        )
        reconciliation = OnlyBrokerReconciliationCoordinator(
            discovery,
            request.broker_inbound_queue,
            readiness,
            evidence,
            now,
        )
        resource = OnlyBinanceSpotBrokerResource(gateway, stream, reconciliation)
        return OnlyBrokerComponent(gateway, resource)


__all__ = [name for name in globals() if name.startswith("Only")]
