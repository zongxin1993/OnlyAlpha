"""External deterministic Broker plugin using normalized inbound updates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from onlyalpha.plugin.api import (
    ONLYALPHA_PLUGIN_API_VERSION,
    OnlyBrokerCreateRequest,
    OnlyBrokerPluginCapabilities,
    OnlyPluginDescriptor,
    OnlyPluginType,
    OnlyPluginValidationIssue,
)
from onlyalpha.plugin.testing import OnlyVirtualBrokerFactory, OnlyVirtualBrokerGateway, OnlyVirtualBrokerPluginConfig

_DESCRIPTOR = OnlyPluginDescriptor(
    "test-external-broker",
    OnlyPluginType.BROKER,
    "0.1.0",
    ONLYALPHA_PLUGIN_API_VERSION,
    "OnlyAlpha External Test Broker",
    "OnlyAlpha Tests",
    OnlyBrokerPluginCapabilities(
        submit_order=True,
        cancel_order=True,
        query_orders=True,
        query_trades=True,
        query_account=True,
        query_positions=True,
        simulated_execution=True,
    ),
)


class OnlyExternalTestBrokerGateway(OnlyVirtualBrokerGateway):
    @property
    def plugin_descriptor(self) -> OnlyPluginDescriptor:
        return _DESCRIPTOR


class OnlyExternalTestBrokerFactory:
    def __init__(self) -> None:
        self._delegate = OnlyVirtualBrokerFactory()

    @property
    def descriptor(self) -> OnlyPluginDescriptor:
        return _DESCRIPTOR

    def parse_config(self, extensions: Mapping[str, object]) -> OnlyVirtualBrokerPluginConfig:
        return self._delegate.parse_config(extensions)

    def validate_request(self, request: OnlyBrokerCreateRequest) -> Sequence[OnlyPluginValidationIssue]:
        return self._delegate.validate_request(request)

    def create(self, request: OnlyBrokerCreateRequest) -> OnlyExternalTestBrokerGateway:
        gateway = self._delegate.create(request)
        return OnlyExternalTestBrokerGateway(
            gateway.config,
            request.runtime_id,
            request.clock,
            request.broker_inbound_queue.put,
        )


def factory() -> OnlyExternalTestBrokerFactory:
    return OnlyExternalTestBrokerFactory()
