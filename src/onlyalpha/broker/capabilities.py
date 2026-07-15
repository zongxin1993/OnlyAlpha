"""Explicit Broker capability declaration and checking."""

from dataclasses import dataclass

from onlyalpha.broker.enums import OnlyBrokerCapability
from onlyalpha.domain.base import OnlyDomainModel


@dataclass(frozen=True, slots=True)
class OnlyBrokerCapabilities(OnlyDomainModel):
    values: frozenset[OnlyBrokerCapability]

    def supports(self, capability: OnlyBrokerCapability) -> bool:
        return capability in self.values

    def require(self, capability: OnlyBrokerCapability) -> None:
        if not self.supports(capability):
            raise OnlyUnsupportedBrokerCapabilityError(capability)


class OnlyUnsupportedBrokerCapabilityError(RuntimeError):
    def __init__(self, capability: OnlyBrokerCapability) -> None:
        super().__init__(f"unsupported Broker capability: {capability.value}")
        self.capability = capability
