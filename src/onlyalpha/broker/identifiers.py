"""Strong identifiers at the normalized Broker boundary."""

from dataclasses import dataclass

from onlyalpha.domain.identifiers import OnlyIdentifier


@dataclass(frozen=True, slots=True)
class OnlyBrokerGatewayId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyBrokerRequestId(OnlyIdentifier):
    pass


@dataclass(frozen=True, slots=True)
class OnlyBrokerUpdateId(OnlyIdentifier):
    pass
