"""Typed Virtual Broker configuration."""

from dataclasses import dataclass

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.virtual_broker.commission import OnlyCommissionModel
from onlyalpha.broker.virtual_broker.latency import OnlyLatencyModel
from onlyalpha.broker.virtual_broker.slippage import OnlySlippageModel
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyQuantity


@dataclass(frozen=True, slots=True)
class OnlyVirtualBrokerConfig(OnlyDomainModel):
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    base_currency: OnlyCurrency
    initial_cash: OnlyMoney
    maximum_fill_quantity: OnlyQuantity | None = None
    queue_capacity: int = 1024
    long_only: bool = True
    commission_model: OnlyCommissionModel | None = None
    slippage_model: OnlySlippageModel | None = None
    latency_model: OnlyLatencyModel | None = None

    def __post_init__(self) -> None:
        if self.initial_cash.currency != self.base_currency or self.initial_cash.amount < 0:
            raise ValueError("Virtual Broker initial cash requires its non-negative base currency")
        if self.queue_capacity < 1:
            raise ValueError("Virtual Broker queue capacity must be positive")
        if self.maximum_fill_quantity is not None and self.maximum_fill_quantity.value <= 0:
            raise ValueError("maximum fill quantity must be positive")
