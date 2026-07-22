import logging
from datetime import UTC, datetime
from decimal import Decimal
from importlib import metadata

from onlyalpha_plugin_broker_virtual.factory import OnlyVirtualBrokerFactory

from onlyalpha.broker import OnlyBoundedBrokerInboundQueue, OnlyBrokerGatewayId
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.plugin import OnlyBrokerPluginCapabilities
from onlyalpha.plugin.broker import OnlyBrokerCreateRequest


def test_entry_point_loads_virtual_factory_class() -> None:
    entries = metadata.entry_points().select(group="onlyalpha.brokers", name="virtual")
    assert len(entries) == 1
    assert next(iter(entries)).load() is OnlyVirtualBrokerFactory


def test_factory_parses_extensions_and_returns_explicit_driver_component() -> None:
    factory = OnlyVirtualBrokerFactory()
    config = factory.parse_config(
        {
            "matching": {"type": "NEXT_BAR"},
            "latency": {"submit_ns": 1, "acceptance_ns": 2, "fill_ns": 3},
            "slippage": {"type": "NONE"},
            "maximum_fill_quantity": "10",
        }
    )
    currency = OnlyCurrency("CNY", 2)
    request = OnlyBrokerCreateRequest(
        OnlyBrokerGatewayId("virtual"),
        config,
        "BACKTEST",
        OnlyBrokerPluginCapabilities(simulated_execution=True),
        OnlyBacktestClock(datetime(2026, 1, 1, tzinfo=UTC)),
        OnlyEventBus(),
        OnlyBoundedBrokerInboundQueue(),
        OnlyRuntimeId("runtime"),
        OnlyAccountId("account"),
        OnlyMoney(Decimal("100000.00"), currency),
        logging.getLogger(__name__),
    )

    assert factory.validate_request(request) == ()
    component = factory.create(request)
    assert component.deterministic_driver is component.gateway
    assert component.resource is component.gateway
