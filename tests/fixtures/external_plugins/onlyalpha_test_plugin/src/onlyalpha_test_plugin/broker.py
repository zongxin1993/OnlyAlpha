"""External deterministic Broker plugin using normalized inbound updates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from onlyalpha_plugin_broker_virtual import OnlyVirtualBrokerFactory, OnlyVirtualBrokerGateway
from onlyalpha_plugin_broker_virtual.factory import OnlyVirtualBrokerPluginConfig

from onlyalpha.plugin.api import (
    ONLYALPHA_PLUGIN_API_VERSION,
    OnlyBrokerComponent,
    OnlyBrokerCreateRequest,
    OnlyBrokerPluginCapabilities,
    OnlyPluginDescriptor,
    OnlyPluginType,
    OnlyPluginValidationIssue,
)

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

    def create(self, request: OnlyBrokerCreateRequest) -> OnlyBrokerComponent:
        component = self._delegate.create(request)
        gateway = component.gateway
        if not isinstance(gateway, OnlyVirtualBrokerGateway):
            raise TypeError("test Broker delegate returned an unexpected gateway")
        external_gateway = OnlyExternalTestBrokerGateway(
            gateway.config,
            request.runtime_id,
            request.clock,
            request.broker_inbound_queue.put,
        )
        return OnlyBrokerComponent(external_gateway, external_gateway, external_gateway)


def factory() -> OnlyExternalTestBrokerFactory:
    return OnlyExternalTestBrokerFactory()
