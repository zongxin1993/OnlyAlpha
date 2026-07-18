"""Public Broker plugin Factory SPI built on normalized Broker Ports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from logging import Logger
from typing import Protocol

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.ports import OnlyBrokerGateway
from onlyalpha.broker.updates import OnlyBrokerInboundUpdate
from onlyalpha.core.clock import OnlyClock
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.plugin.capabilities import OnlyBrokerPluginCapabilities, OnlyPluginValidationIssue
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor
from onlyalpha.plugin.lifecycle import OnlyPluginResource


class OnlyBrokerInboundQueue(Protocol):
    def put(self, update: OnlyBrokerInboundUpdate) -> None: ...

    def drain(self) -> tuple[OnlyBrokerInboundUpdate, ...]: ...


@dataclass(frozen=True, slots=True)
class OnlyBrokerCreateRequest:
    gateway_id: OnlyBrokerGatewayId
    plugin_config: object
    runtime_type: str
    requested_capabilities: OnlyBrokerPluginCapabilities
    clock: OnlyClock
    event_bus: OnlyEventBus
    broker_inbound_queue: OnlyBrokerInboundQueue
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    initial_cash: OnlyMoney
    logger: Logger


class OnlyBacktestBrokerGateway(OnlyBrokerGateway, OnlyPluginResource, Protocol):
    def on_bar(self, bar: OnlyBar) -> None: ...

    def run_due(self) -> int: ...


class OnlyBrokerGatewayFactory(Protocol):
    @property
    def descriptor(self) -> OnlyPluginDescriptor: ...

    def parse_config(self, extensions: Mapping[str, object]) -> object: ...

    def validate_request(self, request: OnlyBrokerCreateRequest) -> Sequence[OnlyPluginValidationIssue]: ...

    def create(self, request: OnlyBrokerCreateRequest) -> OnlyBrokerGateway: ...
