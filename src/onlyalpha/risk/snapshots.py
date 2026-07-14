"""Immutable strategy-visible Risk state snapshots."""

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.risk.enums import OnlyRiskLevel


@dataclass(frozen=True, slots=True)
class OnlyRiskSnapshot(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    account_id: OnlyAccountId
    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    version: int
    risk_level: OnlyRiskLevel
    kill_switch_active: bool
    active_order_count: int
    cluster_active_order_count: int
    reserved_notional: OnlyMoney | None
    reserved_quantity: Decimal
    remaining_order_notional: OnlyMoney | None
    recent_rejection_count: int
    warnings: tuple[str, ...] = ()
    quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("Risk Snapshot version must be positive")
        if self.active_order_count < 0 or self.cluster_active_order_count < 0:
            raise ValueError("Risk active order counts cannot be negative")
        if self.reserved_quantity < 0:
            raise ValueError("Risk reserved quantity cannot be negative")
