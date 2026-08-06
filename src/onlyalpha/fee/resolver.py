"""Runtime composition boundary for explicit fee packs and order bindings."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from onlyalpha.domain.enums import OnlyLiquiditySide, OnlyRuntimeMode
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyTradeId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyPrice
from onlyalpha.fee.assessment import OnlyTradeFeeAssessmentRequest
from onlyalpha.fee.engine import OnlyFeeEngine
from onlyalpha.fee.estimate import OnlyOrderFeeEstimate, OnlyOrderFeeEstimateRequest, OnlyOrderFundingPlan
from onlyalpha.fee.models import (
    OnlyFeeAssessment,
    OnlyFeeBasisValues,
    OnlyFeeResolutionPolicy,
    OnlyFeeSubject,
    OnlyLocalFeeFinality,
    OnlyOrderFeePolicyBinding,
    only_fee_fingerprint,
)
from onlyalpha.fee.packs import OnlyFeePolicyPack
from onlyalpha.fee.policy import OnlyResolvedFeePolicySet
from onlyalpha.fee.schedules import (
    OnlyBrokerFeeSchedule,
    OnlyBrokerFeeScheduleRegistry,
    OnlyMarketFeeSchedule,
    OnlyMarketFeeScheduleRegistry,
)
from onlyalpha.market.runtime_rules import OnlyTradeInstructionPort


class OnlyFeeResolver:
    """Binds schedule versions and prepares strongly typed pure-engine requests."""

    def __init__(
        self,
        engine: OnlyFeeEngine,
        policy_pack: OnlyFeePolicyPack,
        market_rules: OnlyTradeInstructionPort,
        instruments: Mapping[OnlyInstrumentId, OnlyInstrument],
        trading_day: Callable[[OnlyTimestamp], OnlyTradingDay],
    ) -> None:
        self._engine = engine
        self._pack = policy_pack
        self._market_rules = market_rules
        self._instruments = instruments
        self._trading_day = trading_day
        self._market = OnlyMarketFeeScheduleRegistry()
        self._broker = OnlyBrokerFeeScheduleRegistry()
        for schedule in policy_pack.market_schedules:
            self._market.register(schedule)
        for broker_schedule in policy_pack.broker_schedules:
            self._broker.register(broker_schedule)

    @property
    def policy_pack(self) -> OnlyFeePolicyPack:
        return self._pack

    def bind_order(self, order: OnlyOrderSnapshot, timestamp: OnlyTimestamp) -> OnlyOrderFeePolicyBinding:
        day = self._trading_day(timestamp)
        compiled = self._market_rules.compiled_rules(str(order.instrument_id), day)
        if compiled.identity.profile_id not in self._pack.compatible_market_profiles:
            raise ValueError("FEE_POLICY_PACK_MARKET_PROFILE_INCOMPATIBLE")
        instrument = self._instruments[order.instrument_id]
        schedules = tuple(self._pack.market_schedules) + tuple(self._pack.broker_schedules)
        effective = tuple(schedule for schedule in schedules if schedule.applies_on(day.value))
        if not effective:
            raise ValueError("FEE_PACK_NOT_INSTALLED")
        fixed = tuple(
            sorted(
                (
                    schedule.identity
                    for schedule in effective
                    if any(rule.resolution_policy is OnlyFeeResolutionPolicy.ORDER_FIXED for rule in schedule.rules)
                ),
                key=lambda item: (item.schedule_id, item.version),
            )
        )
        fill_ids = tuple(
            sorted(
                schedule.schedule_id
                for schedule in schedules
                if any(rule.resolution_policy is OnlyFeeResolutionPolicy.FILL_EFFECTIVE for rule in schedule.rules)
            )
        )
        payload = (
            str(order.runtime_id),
            str(order.account_id),
            str(order.cluster_id),
            str(order.order_id),
            str(order.instrument_id),
            compiled.identity.profile_id,
            compiled.identity.profile_version,
            tuple(item.to_dict() for item in fixed),
            fill_ids,
            instrument.settlement_currency.to_dict(),
            timestamp.to_dict(),
            self._pack.fingerprint,
        )
        return OnlyOrderFeePolicyBinding(
            order.runtime_id,
            order.account_id,
            order.cluster_id,
            order.order_id,
            order.instrument_id,
            compiled.identity.profile_id,
            compiled.identity.profile_version,
            fixed,
            fill_ids,
            instrument.settlement_currency,
            timestamp,
            only_fee_fingerprint(payload),
        )

    def policies(
        self, order: OnlyOrderSnapshot, binding: OnlyOrderFeePolicyBinding, trading_day: OnlyTradingDay
    ) -> OnlyResolvedFeePolicySet:
        if binding.order_id != order.order_id or binding.instrument_id != order.instrument_id:
            raise ValueError("ORDER_FEE_BINDING_CONFLICT")
        schedules: list[OnlyMarketFeeSchedule | OnlyBrokerFeeSchedule] = []
        for identity in binding.order_fixed_schedules:
            schedules.append(self._resolve_exact(identity.schedule_id, identity.version, identity.fingerprint))
        for schedule_id in binding.fill_effective_schedule_ids:
            schedules.append(self._resolve_effective(schedule_id, trading_day.value))
        policies = tuple(
            policy
            for schedule in schedules
            for policy in schedule.resolved_policies()
            if policy.rule.side is None or policy.rule.side is order.side
            if policy.rule.offset is None or policy.rule.offset is order.offset
        )
        if not policies:
            raise ValueError("FEE_POLICY_SET_HAS_NO_MATCHING_RULE")
        if any(item.currency != binding.charge_currency for item in policies):
            raise ValueError("FEE_CURRENCY_CONVERSION_UNSUPPORTED")
        return OnlyResolvedFeePolicySet.create(policies)

    def estimate_order(
        self,
        order: OnlyOrderSnapshot,
        binding: OnlyOrderFeePolicyBinding,
        price: OnlyPrice,
        timestamp: OnlyTimestamp,
        *,
        expected_fill_count: int = 1,
        maximum_fill_count: int | None = 1,
    ) -> OnlyOrderFeeEstimate:
        basis = self._basis(order, price, order.quantity.value)
        day = self._trading_day(timestamp)
        request = OnlyOrderFeeEstimateRequest(
            self._subject(order),
            order.side,
            order.offset,
            basis,
            basis,
            expected_fill_count,
            maximum_fill_count,
            day,
            binding,
            self.policies(order, binding, day),
        )
        return self._engine.estimate_order(request)

    def funding_plan(
        self,
        order: OnlyOrderSnapshot,
        binding: OnlyOrderFeePolicyBinding,
        estimate: OnlyOrderFeeEstimate,
        price: OnlyPrice,
    ) -> OnlyOrderFundingPlan:
        principal = self._basis(order, price, order.quantity.value).notional
        return OnlyOrderFundingPlan(
            order.order_id,
            principal,
            estimate.reservation_charge,
            principal + estimate.reservation_charge,
            binding.fingerprint,
            estimate.assumptions_fingerprint,
        )

    def assess_trade(
        self,
        order: OnlyOrderSnapshot,
        binding: OnlyOrderFeePolicyBinding,
        *,
        trade_id: OnlyTradeId,
        price: OnlyPrice,
        quantity: Decimal,
        timestamp: OnlyTimestamp,
        liquidity_role: OnlyLiquiditySide,
        cumulative_quantity: Decimal,
        cumulative_notional: OnlyMoney,
    ) -> OnlyFeeAssessment:
        day = self._trading_day(timestamp)
        compiled = self._market_rules.compiled_rules(str(order.instrument_id), day)
        finality = (
            OnlyLocalFeeFinality.MODEL_PROVISIONAL
            if compiled.identity.runtime_mode is OnlyRuntimeMode.LIVE
            else OnlyLocalFeeFinality.MODEL_CONFIRMED
        )
        fill_basis = self._basis(order, price, quantity)
        cumulative_basis = OnlyFeeBasisValues(
            cumulative_notional,
            cumulative_quantity,
            cumulative_quantity,
        )
        return self._engine.assess_trade(
            OnlyTradeFeeAssessmentRequest(
                self._subject(order),
                trade_id,
                fill_basis,
                cumulative_basis,
                day,
                liquidity_role,
                finality,
                binding,
                self.policies(order, binding, day),
            )
        )

    def _basis(self, order: OnlyOrderSnapshot, price: OnlyPrice, quantity: Decimal) -> OnlyFeeBasisValues:
        instrument = self._instruments[order.instrument_id]
        currency = instrument.settlement_currency
        quantum = Decimal(1).scaleb(-currency.precision)
        notional = OnlyMoney(
            (price.value * quantity * instrument.contract_multiplier.value).quantize(quantum, ROUND_HALF_EVEN), currency
        )
        return OnlyFeeBasisValues(notional, quantity, quantity)

    @staticmethod
    def _subject(order: OnlyOrderSnapshot) -> OnlyFeeSubject:
        return OnlyFeeSubject(order.runtime_id, order.account_id, order.cluster_id, order.order_id, order.instrument_id)

    def _resolve_exact(
        self, schedule_id: str, version: str, fingerprint: str
    ) -> OnlyMarketFeeSchedule | OnlyBrokerFeeSchedule:
        try:
            return self._market.resolve_version(schedule_id, version, fingerprint)
        except ValueError as market_error:
            try:
                return self._broker.resolve_version(schedule_id, version, fingerprint)
            except ValueError:
                raise market_error from None

    def _resolve_effective(self, schedule_id: str, trading_day: date) -> OnlyMarketFeeSchedule | OnlyBrokerFeeSchedule:
        try:
            return self._market.resolve(schedule_id, trading_day)
        except ValueError as market_error:
            try:
                return self._broker.resolve(schedule_id, trading_day)
            except ValueError:
                raise market_error from None


__all__ = ["OnlyFeeResolver"]
