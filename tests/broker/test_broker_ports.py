from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from onlyalpha.broker import (
    OnlyBrokerCapabilities,
    OnlyBrokerCapability,
    OnlyBrokerCapabilityContractError,
    OnlyBrokerFeeEvidencePort,
    OnlyBrokerGateway,
    OnlyBrokerGatewayId,
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerUpdateId,
    OnlyUnsupportedBrokerCapabilityError,
    only_require_broker_fee_evidence_port,
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


class _DeclaredFeeEvidenceGateway:
    capabilities = OnlyBrokerCapabilities(frozenset({OnlyBrokerCapability.QUERY_FEE_EVIDENCE}))

    def query_fee_evidence(self, account_id: OnlyAccountId) -> tuple[()]:
        del account_id
        return ()


class _InvalidDeclaredFeeEvidenceGateway:
    capabilities = OnlyBrokerCapabilities(frozenset({OnlyBrokerCapability.QUERY_FEE_EVIDENCE}))


class _UndeclaredFeeEvidenceGateway:
    capabilities = OnlyBrokerCapabilities(frozenset())

    def query_fee_evidence(self, account_id: OnlyAccountId) -> tuple[()]:
        del account_id
        return ()


def test_fee_evidence_optional_port_requires_capability_and_contract() -> None:
    gateway = cast(OnlyBrokerGateway, _DeclaredFeeEvidenceGateway())

    port = only_require_broker_fee_evidence_port(gateway)

    assert isinstance(port, OnlyBrokerFeeEvidencePort)
    assert port.query_fee_evidence(OnlyAccountId("account")) == ()


def test_declared_fee_evidence_capability_without_port_fails_closed() -> None:
    gateway = cast(OnlyBrokerGateway, _InvalidDeclaredFeeEvidenceGateway())

    with pytest.raises(OnlyBrokerCapabilityContractError, match="BROKER_CAPABILITY_CONTRACT_INVALID"):
        only_require_broker_fee_evidence_port(gateway)


def test_fee_evidence_method_without_capability_is_unsupported() -> None:
    gateway = cast(OnlyBrokerGateway, _UndeclaredFeeEvidenceGateway())

    with pytest.raises(OnlyUnsupportedBrokerCapabilityError):
        only_require_broker_fee_evidence_port(gateway)
