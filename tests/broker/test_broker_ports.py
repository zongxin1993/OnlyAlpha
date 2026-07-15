from dataclasses import FrozenInstanceError

import pytest

from onlyalpha.broker import (
    OnlyBrokerCapabilities,
    OnlyBrokerCapability,
    OnlyBrokerGateway,
    OnlyBrokerGatewayId,
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerUpdateId,
    OnlyUnsupportedBrokerCapabilityError,
)
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyRuntimeId, OnlyVenueOrderId
from onlyalpha.domain.time import OnlyTimestamp


def test_capabilities_are_explicit_and_immutable() -> None:
    capabilities = OnlyBrokerCapabilities(frozenset({OnlyBrokerCapability.CONNECT, OnlyBrokerCapability.SUBMIT_ORDER}))

    assert capabilities.supports(OnlyBrokerCapability.SUBMIT_ORDER)
    with pytest.raises(OnlyUnsupportedBrokerCapabilityError):
        capabilities.require(OnlyBrokerCapability.CANCEL_ORDER)
    with pytest.raises(FrozenInstanceError):
        capabilities.values = frozenset()  # type: ignore[misc]


def test_normalized_broker_update_contains_causal_identity_and_is_immutable() -> None:
    timestamp = OnlyTimestamp.from_unix_seconds(1)
    update = OnlyBrokerOrderAcceptedUpdate(
        runtime_id=OnlyRuntimeId("runtime"),
        gateway_id=OnlyBrokerGatewayId("virtual"),
        account_id=OnlyAccountId("account"),
        update_id=OnlyBrokerUpdateId("update-1"),
        source_sequence=1,
        ts_event=timestamp,
        ts_init=timestamp,
        correlation_id="order-1",
        causation_id="request-1",
        order_id=OnlyOrderId("order-1"),
        venue_order_id=OnlyVenueOrderId("venue-order-1"),
        metadata={"source": "test"},
    )

    assert update.metadata["source"] == "test"
    with pytest.raises(TypeError):
        update.metadata["source"] = "changed"  # type: ignore[index]


def test_composed_gateway_is_a_protocol_not_a_manager_owner() -> None:
    assert getattr(OnlyBrokerGateway, "_is_protocol", False)
