"""Runtime-owned order-level target-to-application authority."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyOrderId, OnlyRuntimeId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyQuantity
from onlyalpha.fee.application import OnlyFeeApplicationComponent, OnlyFeeApplicationInstruction
from onlyalpha.fee.models import (
    OnlyFeeAssessment,
    OnlyFeeCalculationScope,
    OnlyFeeComponentIdentity,
    OnlyFeeEconomicDirection,
    only_fee_fingerprint,
)


@dataclass(frozen=True, slots=True)
class OnlyOrderFeeComponentAccrual(OnlyDomainModel):
    identity: OnlyFeeComponentIdentity
    cumulative_raw_amount: OnlyMoney
    cumulative_target_amount: OnlyMoney
    cumulative_applied_amount: OnlyMoney

    def __post_init__(self) -> None:
        values = (self.cumulative_raw_amount, self.cumulative_target_amount, self.cumulative_applied_amount)
        if len({item.currency for item in values}) != 1 or any(item.amount < 0 for item in values):
            raise ValueError("order fee component accrual currency/amount is invalid")


@dataclass(frozen=True, slots=True)
class OnlyOrderFeeAccrualState(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    order_id: OnlyOrderId
    currency: OnlyCurrency
    cumulative_fill_quantity: OnlyQuantity
    cumulative_fill_notional: OnlyMoney
    cumulative_charges: OnlyMoney
    cumulative_rebates: OnlyMoney
    order_fixed_policy_fingerprint: str
    components: tuple[OnlyOrderFeeComponentAccrual, ...]
    fill_count: int
    last_trade_id: OnlyTradeId
    updated_at: OnlyTimestamp
    version: int

    def __post_init__(self) -> None:
        if self.fill_count < 1 or self.version < 1 or self.cumulative_fill_quantity.value <= 0:
            raise ValueError("order fee accrual fill/version authority is invalid")
        monies = (self.cumulative_fill_notional, self.cumulative_charges, self.cumulative_rebates) + tuple(
            value
            for item in self.components
            for value in (item.cumulative_raw_amount, item.cumulative_target_amount, item.cumulative_applied_amount)
        )
        if any(item.currency != self.currency or item.amount < 0 for item in monies):
            raise ValueError("order fee accrual currency/amount is invalid")
        if len({item.identity for item in self.components}) != len(self.components):
            raise ValueError("order fee accrual component identity must be unique")
        charges = sum(
            (
                item.cumulative_applied_amount.amount
                for item in self.components
                if item.identity.economic_direction is OnlyFeeEconomicDirection.CHARGE
            ),
            Decimal(0),
        )
        rebates = sum(
            (
                item.cumulative_applied_amount.amount
                for item in self.components
                if item.identity.economic_direction is OnlyFeeEconomicDirection.REBATE
            ),
            Decimal(0),
        )
        if charges != self.cumulative_charges.amount or rebates != self.cumulative_rebates.amount:
            raise ValueError("order fee accrual totals disagree with components")

    @property
    def fingerprint(self) -> str:
        return only_fee_fingerprint(self.to_dict())


class OnlyOrderFeeAccrualAuthority:
    def apply(
        self,
        before: OnlyOrderFeeAccrualState | None,
        assessment: OnlyFeeAssessment,
        *,
        cumulative_fill_quantity: OnlyQuantity,
        cumulative_fill_notional: OnlyMoney,
        updated_at: OnlyTimestamp,
        order_fixed_policy_fingerprint: str,
    ) -> tuple[OnlyOrderFeeAccrualState, OnlyFeeApplicationInstruction]:
        if assessment.trade_id is None:
            raise ValueError("trade fee assessment requires Trade identity")
        subject = assessment.subject
        if before is not None:
            if (before.runtime_id, before.account_id, before.cluster_id, before.order_id) != (
                subject.runtime_id,
                subject.account_id,
                subject.cluster_id,
                subject.order_id,
            ):
                raise ValueError("FEE_ACCRUAL_CONFLICT")
            if before.order_fixed_policy_fingerprint != order_fixed_policy_fingerprint:
                raise ValueError("ORDER_CUMULATIVE_FEE_POLICY_CHANGED")
            if before.last_trade_id == assessment.trade_id:
                raise ValueError("FEE_APPLICATION_DUPLICATE_TRADE")
        currency = assessment.total_charges.currency
        prior = {} if before is None else {item.identity: item for item in before.components}
        states: list[OnlyOrderFeeComponentAccrual] = []
        applications: list[OnlyFeeApplicationComponent] = []
        for target in assessment.components:
            existing = prior.pop(target.identity, None)
            raw_before = Decimal(0) if existing is None else existing.cumulative_raw_amount.amount
            target_before = Decimal(0) if existing is None else existing.cumulative_target_amount.amount
            applied_before = Decimal(0) if existing is None else existing.cumulative_applied_amount.amount
            if target.identity.calculation_scope is OnlyFeeCalculationScope.FILL:
                incremental = target.target_amount.amount
                raw_after = raw_before + target.raw_amount.amount
                target_after = target_before + target.target_amount.amount
            elif target.identity.calculation_scope is OnlyFeeCalculationScope.ORDER_CUMULATIVE:
                incremental = target.target_amount.amount - applied_before
                raw_after = target.raw_amount.amount
                target_after = target.target_amount.amount
            else:
                raise ValueError("FEE_SCOPE_UNSUPPORTED")
            if incremental < 0:
                raise ValueError("FEE_ACCRUAL_NEGATIVE_INCREMENT")
            applied_after = applied_before + incremental
            state = OnlyOrderFeeComponentAccrual(
                target.identity,
                OnlyMoney(raw_after, currency),
                OnlyMoney(target_after, currency),
                OnlyMoney(applied_after, currency),
            )
            states.append(state)
            applications.append(
                OnlyFeeApplicationComponent(
                    target.identity,
                    OnlyMoney(incremental, currency),
                    target.identity.economic_direction,
                    target.raw_amount,
                    state.cumulative_raw_amount,
                    state.cumulative_target_amount,
                    OnlyMoney(applied_before, currency),
                    state.cumulative_applied_amount,
                )
            )
        states.extend(prior.values())
        ordered_states = tuple(sorted(states, key=lambda item: item.identity.sort_key))
        ordered_applications = tuple(sorted(applications, key=lambda item: item.identity.sort_key))
        charges = sum(
            (
                item.amount.amount
                for item in ordered_applications
                if item.economic_direction is OnlyFeeEconomicDirection.CHARGE
            ),
            Decimal(0),
        )
        rebates = sum(
            (
                item.amount.amount
                for item in ordered_applications
                if item.economic_direction is OnlyFeeEconomicDirection.REBATE
            ),
            Decimal(0),
        )
        after = OnlyOrderFeeAccrualState(
            subject.runtime_id,
            subject.account_id,
            subject.cluster_id,
            subject.order_id,
            currency,
            cumulative_fill_quantity,
            cumulative_fill_notional,
            OnlyMoney(
                sum(
                    (
                        item.cumulative_applied_amount.amount
                        for item in ordered_states
                        if item.identity.economic_direction is OnlyFeeEconomicDirection.CHARGE
                    ),
                    Decimal(0),
                ),
                currency,
            ),
            OnlyMoney(
                sum(
                    (
                        item.cumulative_applied_amount.amount
                        for item in ordered_states
                        if item.identity.economic_direction is OnlyFeeEconomicDirection.REBATE
                    ),
                    Decimal(0),
                ),
                currency,
            ),
            order_fixed_policy_fingerprint,
            ordered_states,
            1 if before is None else before.fill_count + 1,
            assessment.trade_id,
            updated_at,
            1 if before is None else before.version + 1,
        )
        before_fingerprint = None if before is None else before.fingerprint
        application_id = only_fee_fingerprint((assessment.assessment_id, before_fingerprint, after.fingerprint))
        application = OnlyFeeApplicationInstruction(
            application_id,
            subject,
            assessment.trade_id,
            ordered_applications,
            OnlyMoney(charges, currency),
            OnlyMoney(rebates, currency),
            rebates - charges,
            before_fingerprint,
            after.fingerprint,
            assessment.binding.fingerprint,
            assessment.resolution_fingerprint,
            assessment.local_finality,
            f"fee-application:{subject.runtime_id}:{assessment.trade_id}",
        )
        return after, application


__all__ = ["OnlyOrderFeeAccrualAuthority", "OnlyOrderFeeAccrualState", "OnlyOrderFeeComponentAccrual"]
