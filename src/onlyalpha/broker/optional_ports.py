"""Typed resolution for explicitly declared optional Broker Ports."""

from onlyalpha.broker.capabilities import OnlyBrokerCapabilities
from onlyalpha.broker.enums import OnlyBrokerCapability
from onlyalpha.broker.ports import OnlyBrokerFeeEvidencePort, OnlyBrokerGateway


class OnlyBrokerCapabilityContractError(RuntimeError):
    """A Broker declared a capability without implementing its Port contract."""

    def __init__(self, capability: OnlyBrokerCapability) -> None:
        super().__init__(f"BROKER_CAPABILITY_CONTRACT_INVALID: {capability.value}")
        self.capability = capability


def only_require_broker_fee_evidence_port(
    gateway: OnlyBrokerGateway,
) -> OnlyBrokerFeeEvidencePort:
    """Resolve fee evidence only when declaration and structural Port both exist."""

    capability = OnlyBrokerCapability.QUERY_FEE_EVIDENCE
    capabilities: OnlyBrokerCapabilities = gateway.capabilities
    capabilities.require(capability)
    if not isinstance(gateway, OnlyBrokerFeeEvidencePort):
        raise OnlyBrokerCapabilityContractError(capability)
    return gateway


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
