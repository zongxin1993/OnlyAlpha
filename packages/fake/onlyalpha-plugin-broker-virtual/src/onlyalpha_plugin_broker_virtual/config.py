"""Typed Virtual Broker configuration."""

from dataclasses import dataclass

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyQuantity
from onlyalpha_plugin_broker_virtual.fill_plan import (
    OnlyVirtualFillDispatchMode,
    OnlyVirtualFillScheduleMode,
    OnlyVirtualFillScheduleStepSpec,
)
from onlyalpha_plugin_broker_virtual.latency import OnlyLatencyModel
from onlyalpha_plugin_broker_virtual.slippage import OnlySlippageModel


@dataclass(frozen=True, slots=True)
class OnlyVirtualBrokerConfig(OnlyDomainModel):
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    base_currency: OnlyCurrency
    initial_cash: OnlyMoney
    maximum_fill_quantity: OnlyQuantity | None = None
    fill_schedule_mode: OnlyVirtualFillScheduleMode | None = None
    fill_dispatch_mode: OnlyVirtualFillDispatchMode = OnlyVirtualFillDispatchMode.ONE_PER_BAR
    fill_schedule_steps: tuple[OnlyVirtualFillScheduleStepSpec, ...] = ()
    queue_capacity: int = 1024
    long_only: bool = True
    slippage_model: OnlySlippageModel | None = None
    latency_model: OnlyLatencyModel | None = None

    def __post_init__(self) -> None:
        if self.initial_cash.currency != self.base_currency or self.initial_cash.amount < 0:
            raise ValueError("Virtual Broker initial cash requires its non-negative base currency")
        if self.queue_capacity < 1:
            raise ValueError("Virtual Broker queue capacity must be positive")
        if self.maximum_fill_quantity is not None and self.maximum_fill_quantity.value <= 0:
            raise ValueError("maximum fill quantity must be positive")
        mode = self.effective_fill_schedule_mode
        if self.fill_schedule_mode is OnlyVirtualFillScheduleMode.WHOLE and self.maximum_fill_quantity is not None:
            raise ValueError("VIRTUAL_FILL_POLICY_CONFLICT")
        if mode is OnlyVirtualFillScheduleMode.SCHEDULE and self.maximum_fill_quantity is not None:
            raise ValueError("VIRTUAL_FILL_POLICY_CONFLICT")
        if mode is OnlyVirtualFillScheduleMode.SCHEDULE and not self.fill_schedule_steps:
            raise ValueError("VIRTUAL_FILL_SCHEDULE_EMPTY")
        if mode is not OnlyVirtualFillScheduleMode.SCHEDULE and self.fill_schedule_steps:
            raise ValueError("VIRTUAL_FILL_POLICY_CONFLICT")
        if mode is OnlyVirtualFillScheduleMode.MAX_PER_BAR and self.maximum_fill_quantity is None:
            raise ValueError("VIRTUAL_FILL_MAXIMUM_REQUIRED")

    @property
    def effective_fill_schedule_mode(self) -> OnlyVirtualFillScheduleMode:
        if self.fill_schedule_mode is not None:
            return self.fill_schedule_mode
        return (
            OnlyVirtualFillScheduleMode.MAX_PER_BAR
            if self.maximum_fill_quantity is not None
            else OnlyVirtualFillScheduleMode.WHOLE
        )
