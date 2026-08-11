"""Runtime composition boundary for fee binding, scope resolution and basis authority."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from decimal import Decimal

from onlyalpha.domain.enums import OnlyLiquiditySide
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyTradeId
from onlyalpha.domain.instrument import OnlyCryptoSpot, OnlyFuture, OnlyInstrument
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyMoney, OnlyPrice
from onlyalpha.fee.assessment import OnlyTradeFeeAssessmentRequest
from onlyalpha.fee.basis import OnlyFeeBasisProviderRegistry
from onlyalpha.fee.broker_contract import OnlyBrokerFeeContract
from onlyalpha.fee.engine import OnlyFeeEngine
from onlyalpha.fee.estimate import OnlyOrderFeeEstimate, OnlyOrderFeeEstimateRequest, OnlyOrderFundingPlan
from onlyalpha.fee.market_pack import OnlyMarketFeePack
from onlyalpha.fee.models import (
    OnlyFeeAssessment,
    OnlyFeeBasisValues,
    OnlyFeeResolutionPolicy,
    OnlyFeeScheduleAuthority,
    OnlyFeeScheduleFamilyIdentity,
    OnlyFeeScheduleIdentity,
    OnlyFeeSubject,
    OnlyLocalFeeFinality,
    OnlyOrderFeeApplicabilityScopeIdentity,
    OnlyOrderFeePolicyBinding,
    only_fee_fingerprint,
)
from onlyalpha.fee.policy import OnlyResolvedFeePolicySet
from onlyalpha.fee.resolution import OnlyFeePolicyResolution
from onlyalpha.fee.schedules import (
    OnlyBrokerFeeApplicabilityContext,
    OnlyBrokerFeeSchedule,
    OnlyBrokerFeeScheduleRegistry,
    OnlyMarketFeeApplicabilityContext,
    OnlyMarketFeeSchedule,
    OnlyMarketFeeScheduleRegistry,
)
from onlyalpha.market.runtime_rules import OnlyTradeInstructionPort


class OnlyFeeResolver:
    """Binds immutable authorities and prepares proven pure-engine requests."""

    def __init__(
        self,
        engine: OnlyFeeEngine,
        market_fee_pack: OnlyMarketFeePack,
        broker_fee_contract: OnlyBrokerFeeContract,
        broker_id: str,
        market_rules: OnlyTradeInstructionPort,
        instruments: Mapping[OnlyInstrumentId, OnlyInstrument],
        basis_providers: OnlyFeeBasisProviderRegistry,
        trading_day: Callable[[OnlyTimestamp], OnlyTradingDay],
    ) -> None:
        self._engine = engine
        self._market_pack = market_fee_pack
        self._broker_contract = broker_fee_contract
        self._broker_id = broker_id
        self._market_rules = market_rules
        self._instruments = instruments
        self._basis_providers = basis_providers
        self._trading_day = trading_day
        self._market = OnlyMarketFeeScheduleRegistry()
        self._broker = OnlyBrokerFeeScheduleRegistry()
        for schedule in market_fee_pack.schedules:
            self._market.register(schedule)
        for broker_schedule in broker_fee_contract.schedules:
            self._broker.register(broker_schedule)

    @property
    def market_fee_pack(self) -> OnlyMarketFeePack:
        return self._market_pack

    @property
    def broker_fee_contract(self) -> OnlyBrokerFeeContract:
        return self._broker_contract

    def bind_order(self, order: OnlyOrderSnapshot, timestamp: OnlyTimestamp) -> OnlyOrderFeePolicyBinding:
        day = self._trading_day(timestamp)
        self._market_rules.compiled_rules(str(order.instrument_id), day)
        product = self._market_rules.market_product_identity
        product_id = str(product.product_id)
        product_version = str(product.product_version)
        self._market_pack.validate_compatibility(product_id)
        self._broker_contract.validate_compatibility(broker_id=self._broker_id, account_id=order.account_id)
        instrument = self._instruments[order.instrument_id]
        market = next((item.market for item in self._market_pack.schedules), product_id)
        scope = self._scope(order, instrument, product_id, market, str(order.instrument_id.venue))
        market_context, broker_context = self._contexts(scope, day)
        fixed: list[OnlyFeeScheduleIdentity] = []
        families: list[OnlyFeeScheduleFamilyIdentity] = []
        for schedules in (
            self._applicable_market_families(market_context),
            self._applicable_broker_families(broker_context),
        ):
            for family_schedules in schedules:
                effective = tuple(item for item in family_schedules if item.applies_on(day.value))
                if not effective:
                    raise ValueError("FEE_SCHEDULE_NOT_FOUND")
                if len(effective) > 1:
                    raise ValueError("FEE_SCHEDULE_AMBIGUOUS")
                schedule = effective[0]
                resolution_policy = schedule.rules[0].resolution_policy
                if resolution_policy is OnlyFeeResolutionPolicy.ORDER_FIXED:
                    fixed.append(schedule.identity)
                else:
                    families.append(schedule.family_identity)
        if not fixed and not families:
            raise ValueError("FEE_SCHEDULE_NOT_FOUND")
        ordered_fixed = tuple(sorted(fixed, key=lambda item: (item.authority.value, item.schedule_id, item.version)))
        ordered_families = tuple(sorted(families, key=lambda item: (item.authority.value, item.schedule_id)))
        return OnlyOrderFeePolicyBinding.create(
            runtime_id=order.runtime_id,
            account_id=order.account_id,
            cluster_id=order.cluster_id,
            order_id=order.order_id,
            instrument_id=order.instrument_id,
            market_product_id=product_id,
            market_product_version=product_version,
            market_fee_pack=self._market_pack.identity,
            broker_fee_contract=self._broker_contract.identity,
            applicability_scope=scope,
            order_fixed_schedules=ordered_fixed,
            fill_effective_families=ordered_families,
            charge_currency=instrument.settlement_currency,
            bound_at=timestamp,
        )

    def policies(
        self, order: OnlyOrderSnapshot, binding: OnlyOrderFeePolicyBinding, trading_day: OnlyTradingDay
    ) -> OnlyFeePolicyResolution:
        self._validate_binding(order, binding)
        market_context, broker_context = self._contexts(binding.applicability_scope, trading_day)
        schedules: list[OnlyMarketFeeSchedule | OnlyBrokerFeeSchedule] = []
        for identity in binding.order_fixed_schedules:
            if identity.authority is OnlyFeeScheduleAuthority.MARKET:
                market_schedule = self._market.resolve_version(identity)
                if not market_schedule.matches_scope(market_context):
                    raise ValueError("ORDER_FEE_SCOPE_AUTHORITY_CHANGED")
                schedules.append(market_schedule)
            else:
                broker_schedule = self._broker.resolve_version(identity)
                if not broker_schedule.matches_scope(broker_context):
                    raise ValueError("ORDER_FEE_SCOPE_AUTHORITY_CHANGED")
                schedules.append(broker_schedule)
        for family in binding.fill_effective_families:
            if family.authority is OnlyFeeScheduleAuthority.MARKET:
                schedules.append(self._market.resolve_family(family, market_context))
            else:
                schedules.append(self._broker.resolve_family(family, broker_context))
        applicable_schedules = tuple(
            schedule
            for schedule in schedules
            if any(
                (rule.side is None or rule.side is order.side) and (rule.offset is None or rule.offset is order.offset)
                for rule in schedule.rules
            )
        )
        policies = tuple(
            policy
            for schedule in applicable_schedules
            for policy in schedule.resolved_policies()
            if policy.rule.side is None or policy.rule.side is order.side
            if policy.rule.offset is None or policy.rule.offset is order.offset
        )
        if not policies:
            raise ValueError("FEE_POLICY_SET_HAS_NO_MATCHING_RULE")
        if any(item.currency != binding.charge_currency for item in policies):
            raise ValueError("FEE_CURRENCY_CONVERSION_UNSUPPORTED")
        return OnlyFeePolicyResolution.create(
            binding_fingerprint=binding.fingerprint,
            market_fee_pack=binding.market_fee_pack,
            broker_fee_contract=binding.broker_fee_contract,
            scope_fingerprint=binding.applicability_scope.fingerprint,
            resolved_schedules=tuple(schedule.identity for schedule in applicable_schedules),
            policies=OnlyResolvedFeePolicySet.create(policies),
            trading_day=trading_day,
        )

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
        self._market_rules.compiled_rules(str(order.instrument_id), day)
        finality = OnlyLocalFeeFinality.MODEL_CONFIRMED
        fill_basis = self._basis(order, price, quantity)
        cumulative_basis = replace(
            self._basis(order, price, cumulative_quantity),
            notional=cumulative_notional,
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
        return self._basis_providers.require(instrument).resolve(
            instrument=instrument,
            price=price,
            quantity=quantity,
        )

    @staticmethod
    def _subject(order: OnlyOrderSnapshot) -> OnlyFeeSubject:
        return OnlyFeeSubject(order.runtime_id, order.account_id, order.cluster_id, order.order_id, order.instrument_id)

    def _scope(
        self,
        order: OnlyOrderSnapshot,
        instrument: OnlyInstrument,
        product_id: str,
        market: str,
        venue: str,
    ) -> OnlyOrderFeeApplicabilityScopeIdentity:
        instrument_class = _instrument_class(instrument)
        return OnlyOrderFeeApplicabilityScopeIdentity.create(
            market_product_id=product_id,
            market=market,
            venue=venue,
            instrument_class=instrument_class,
            broker_id=self._broker_id,
            account_id=order.account_id,
            instrument_id=order.instrument_id,
            charge_currency=instrument.settlement_currency,
        )

    @staticmethod
    def _contexts(
        scope: OnlyOrderFeeApplicabilityScopeIdentity, day: OnlyTradingDay
    ) -> tuple[OnlyMarketFeeApplicabilityContext, OnlyBrokerFeeApplicabilityContext]:
        return (
            OnlyMarketFeeApplicabilityContext(
                day,
                scope.market_product_id,
                scope.market,
                scope.venue,
                scope.instrument_class,
                scope.instrument_id,
            ),
            OnlyBrokerFeeApplicabilityContext(day, scope.broker_id, scope.account_id, scope.instrument_id),
        )

    def _applicable_market_families(
        self, context: OnlyMarketFeeApplicabilityContext
    ) -> tuple[tuple[OnlyMarketFeeSchedule, ...], ...]:
        applicable = tuple(item for item in self._market_pack.schedules if item.matches_scope(context))
        grouped: dict[str, list[OnlyMarketFeeSchedule]] = {}
        for item in applicable:
            grouped.setdefault(item.schedule_id, []).append(item)
        return tuple(tuple(grouped[key]) for key in sorted(grouped))

    def _applicable_broker_families(
        self, context: OnlyBrokerFeeApplicabilityContext
    ) -> tuple[tuple[OnlyBrokerFeeSchedule, ...], ...]:
        applicable = tuple(item for item in self._broker_contract.schedules if item.matches_scope(context))
        grouped: dict[str, list[OnlyBrokerFeeSchedule]] = {}
        for item in applicable:
            grouped.setdefault(item.schedule_id, []).append(item)
        return tuple(tuple(grouped[key]) for key in sorted(grouped))

    def _validate_binding(self, order: OnlyOrderSnapshot, binding: OnlyOrderFeePolicyBinding) -> None:
        if (
            binding.runtime_id != order.runtime_id
            or binding.account_id != order.account_id
            or binding.cluster_id != order.cluster_id
            or binding.order_id != order.order_id
            or binding.instrument_id != order.instrument_id
        ):
            raise ValueError("ORDER_FEE_BINDING_CONFLICT")
        if binding.market_fee_pack != self._market_pack.identity:
            raise ValueError("ORDER_FEE_POLICY_AUTHORITY_CONFLICT")
        if binding.broker_fee_contract != self._broker_contract.identity:
            raise ValueError("ORDER_FEE_POLICY_AUTHORITY_CONFLICT")
        scope = binding.applicability_scope
        if scope.fingerprint != only_fee_fingerprint(scope.authority_payload()):
            raise ValueError("ORDER_FEE_SCOPE_AUTHORITY_CHANGED")
        if binding.fingerprint != only_fee_fingerprint(binding.authority_payload()):
            raise ValueError("ORDER_FEE_BINDING_CONFLICT")


def _instrument_class(instrument: OnlyInstrument) -> str:
    if isinstance(instrument, OnlyFuture):
        return "FUTURES"
    if isinstance(instrument, OnlyCryptoSpot):
        return "CRYPTO_SPOT"
    return "CASH"


__all__ = ["OnlyFeeResolver"]
