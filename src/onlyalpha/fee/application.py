"""The unique incremental fee command for one Fill."""

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyTradeId
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.fee.models import (
    OnlyFeeComponentIdentity,
    OnlyFeeEconomicDirection,
    OnlyFeeSubject,
    OnlyLocalFeeFinality,
)


@dataclass(frozen=True, slots=True)
class OnlyFeeApplicationComponent(OnlyDomainModel):
    identity: OnlyFeeComponentIdentity
    amount: OnlyMoney
    economic_direction: OnlyFeeEconomicDirection
    fill_raw_amount: OnlyMoney
    cumulative_raw_after: OnlyMoney
    cumulative_target_after: OnlyMoney
    cumulative_applied_before: OnlyMoney
    cumulative_applied_after: OnlyMoney

    def __post_init__(self) -> None:
        values = (
            self.amount,
            self.fill_raw_amount,
            self.cumulative_raw_after,
            self.cumulative_target_after,
            self.cumulative_applied_before,
            self.cumulative_applied_after,
        )
        if len({item.currency for item in values}) != 1 or any(item.amount < 0 for item in values):
            raise ValueError("fee application component currency/amount is invalid")
        if self.economic_direction is not self.identity.economic_direction:
            raise ValueError("fee application direction conflicts with component identity")
        if self.cumulative_applied_after.amount != self.cumulative_applied_before.amount + self.amount.amount:
            raise ValueError("fee application cumulative amount is not conserved")


@dataclass(frozen=True, slots=True)
class OnlyFeeApplicationInstruction(OnlyDomainModel):
    application_id: str
    subject: OnlyFeeSubject
    trade_id: OnlyTradeId
    components: tuple[OnlyFeeApplicationComponent, ...]
    total_charges: OnlyMoney
    total_rebates: OnlyMoney
    signed_cash_effect: Decimal
    accrual_before_fingerprint: str | None
    accrual_after_fingerprint: str
    local_finality: OnlyLocalFeeFinality
    idempotency_key: str

    def __post_init__(self) -> None:
        if not self.application_id.strip() or not self.idempotency_key.strip():
            raise ValueError("fee application identity cannot be empty")
        if self.total_charges.currency != self.total_rebates.currency:
            raise ValueError("fee application total currency mismatch")
        charges = sum(
            (
                item.amount.amount
                for item in self.components
                if item.economic_direction is OnlyFeeEconomicDirection.CHARGE
            ),
            Decimal(0),
        )
        rebates = sum(
            (
                item.amount.amount
                for item in self.components
                if item.economic_direction is OnlyFeeEconomicDirection.REBATE
            ),
            Decimal(0),
        )
        if charges != self.total_charges.amount or rebates != self.total_rebates.amount:
            raise ValueError("fee application totals disagree with components")
        if self.signed_cash_effect != rebates - charges:
            raise ValueError("fee application signed cash effect is invalid")


__all__ = ["OnlyFeeApplicationComponent", "OnlyFeeApplicationInstruction"]
