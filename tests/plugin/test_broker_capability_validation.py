import logging
from decimal import Decimal

import pytest
from onlyalpha_test_plugin.broker import OnlyExternalTestBrokerFactory

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.inbound import OnlyBoundedBrokerInboundQueue
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.plugin import OnlyBrokerPluginCapabilities, OnlyCheckpointCapability
from onlyalpha.plugin.broker import OnlyBrokerCreateRequest


def test_broker_capability_reports_missing_requirement() -> None:
    actual = OnlyBrokerPluginCapabilities(simulated_execution=True)
    required = OnlyBrokerPluginCapabilities(simulated_execution=True, cancel_order=True)
    assert actual.missing(required) == ("cancel_order",)


def test_broker_checkpointable_capability_requires_schema_version() -> None:
    with pytest.raises(ValueError, match="positive schema version"):
        OnlyBrokerPluginCapabilities(
            supports_runtime_checkpoint=OnlyCheckpointCapability.CHECKPOINTABLE,
        )
    capability = OnlyBrokerPluginCapabilities(
        simulated_execution=True,
        supports_runtime_checkpoint=OnlyCheckpointCapability.CHECKPOINTABLE,
        checkpoint_schema_version=1,
    )
    assert capability.checkpoint_schema_version == 1


def test_broker_factory_validates_requested_capabilities_before_create() -> None:
    factory = OnlyExternalTestBrokerFactory()
    currency = OnlyCurrency("CNY", 2)
    request = OnlyBrokerCreateRequest(
        OnlyBrokerGatewayId("limited"),
        factory.parse_config({}),
        "LIVE",
        OnlyBrokerPluginCapabilities(live_execution=True),
        OnlyBacktestClock(OnlyTimestamp(0).to_datetime()),
        OnlyEventBus(),
        OnlyBoundedBrokerInboundQueue(),
        OnlyRuntimeId("runtime"),
        OnlyAccountId("account"),
        OnlyMoney(Decimal("100.00"), currency),
        logging.getLogger(__name__),
    )
    issues = factory.validate_request(request)
    assert issues[0].code == "PLUGIN_CAPABILITY_NOT_SUPPORTED"
    assert issues[0].field == "live_execution"
