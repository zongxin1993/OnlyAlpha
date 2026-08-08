"""Pure market-neutral fee target calculation service."""

from __future__ import annotations

from dataclasses import replace
from decimal import ROUND_HALF_EVEN, Decimal

from onlyalpha.domain.identifiers import OnlyTradeId
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.fee.assessment import OnlyTradeFeeAssessmentRequest
from onlyalpha.fee.estimate import OnlyOrderFeeEstimate, OnlyOrderFeeEstimateRequest
from onlyalpha.fee.formula import OnlyFeeFixedTerm
from onlyalpha.fee.models import (
    OnlyFeeAssessment,
    OnlyFeeBasisValues,
    OnlyFeeCalculationScope,
    OnlyFeeComponentIdentity,
    OnlyFeeEconomicDirection,
    OnlyFeeTargetComponent,
    OnlyLocalFeeFinality,
    OnlyOrderFeePolicyBinding,
    only_fee_fingerprint,
)
from onlyalpha.fee.policy import OnlyResolvedFeePolicy, OnlyResolvedFeePolicySet
from onlyalpha.fee.resolution import OnlyFeePolicyResolution
from onlyalpha.fee.rounding import only_apply_fee_pipeline


class OnlyFeeEngine:
    """Calculates policy targets and never reads Runtime state or external evidence."""

    def assess_trade(self, request: OnlyTradeFeeAssessmentRequest) -> OnlyFeeAssessment:
        self._validate_request_authority(
            request.binding, request.policy_resolution, request.fill_basis.notional.currency
        )
        policies = request.policy_resolution.policies
        components = tuple(
            component
            for policy in policies.policies
            if policy.rule.liquidity_role is None or policy.rule.liquidity_role is request.liquidity_role
            for component in (
                self._component(
                    policy,
                    request.fill_basis
                    if policy.rule.calculation_scope is OnlyFeeCalculationScope.FILL
                    else request.cumulative_order_basis,
                    request.local_finality,
                ),
            )
        )
        return self._assessment(
            subject=request.subject,
            trade_id=request.trade_id,
            components=components,
            policies=policies,
            resolution=request.policy_resolution,
            finality=request.local_finality,
            discriminator="trade",
            binding=request.binding,
        )

    def estimate_order(self, request: OnlyOrderFeeEstimateRequest) -> OnlyOrderFeeEstimate:
        self._validate_request_authority(
            request.binding, request.policy_resolution, request.full_order_basis.notional.currency
        )
        policies = request.policy_resolution.policies
        expected = self._estimate_assessment(request, request.expected_fill_count, maximum=False)
        maximum_count = request.maximum_fill_count
        if maximum_count is None and any(_split_sensitive(item) for item in policies.policies):
            raise ValueError("FEE_ESTIMATE_MAXIMUM_FILL_COUNT_REQUIRED")
        maximum = self._estimate_assessment(request, maximum_count or request.expected_fill_count, maximum=True)
        assumptions = only_fee_fingerprint(
            (
                request.binding.fingerprint,
                request.policy_resolution.resolution_fingerprint,
                request.expected_fill_count,
                request.maximum_fill_count,
                request.expected_basis.to_dict(),
                request.full_order_basis.to_dict(),
            )
        )
        return OnlyOrderFeeEstimate(
            expected,
            maximum,
            maximum.total_charges,
            expected.total_rebates,
            assumptions,
        )

    def _estimate_assessment(
        self, request: OnlyOrderFeeEstimateRequest, fill_count: int, *, maximum: bool
    ) -> OnlyFeeAssessment:
        components = []
        for policy in request.policy_resolution.policies.policies:
            if not policy.rule.matches(request.side, request.offset, None):
                continue
            basis = request.full_order_basis
            multiplier = 1
            if _split_sensitive(policy):
                basis = request.expected_basis
                multiplier = fill_count
            component = self._component(policy, basis, OnlyLocalFeeFinality.ESTIMATED)
            if multiplier != 1:
                component = replace(
                    component,
                    raw_amount=OnlyMoney(component.raw_amount.amount * multiplier, component.raw_amount.currency),
                    bounded_amount=OnlyMoney(
                        component.bounded_amount.amount * multiplier, component.bounded_amount.currency
                    ),
                    target_amount=OnlyMoney(
                        component.target_amount.amount * multiplier, component.target_amount.currency
                    ),
                )
            components.append(component)
        return self._assessment(
            subject=request.subject,
            trade_id=None,
            components=tuple(components),
            policies=request.policy_resolution.policies,
            resolution=request.policy_resolution,
            finality=OnlyLocalFeeFinality.ESTIMATED,
            discriminator="maximum" if maximum else "expected",
            binding=request.binding,
        )

    @staticmethod
    def _component(
        policy: OnlyResolvedFeePolicy,
        basis: OnlyFeeBasisValues,
        finality: OnlyLocalFeeFinality,
    ) -> OnlyFeeTargetComponent:
        if policy.currency != basis.notional.currency:
            raise ValueError("FEE_CURRENCY_CONVERSION_UNSUPPORTED")
        rule = policy.rule
        raw = rule.formula.evaluate(basis)
        bounded, target = only_apply_fee_pipeline(
            raw,
            minimum=rule.minimum,
            maximum=rule.maximum,
            rounding=rule.rounding,
            pipeline=rule.pipeline,
        )
        identity = OnlyFeeComponentIdentity(
            rule.fee_type,
            rule.authority,
            policy.source_id,
            policy.schedule_id,
            policy.schedule_version,
            policy.schedule_fingerprint,
            rule.rule_id,
            rule.fingerprint,
            rule.calculation_scope,
            rule.resolution_policy,
            rule.economic_direction,
        )
        quantum = Decimal(1).scaleb(-policy.currency.precision)
        return OnlyFeeTargetComponent(
            identity,
            OnlyMoney(raw.quantize(quantum, rounding=ROUND_HALF_EVEN), policy.currency),
            OnlyMoney(bounded.quantize(quantum, rounding=ROUND_HALF_EVEN), policy.currency),
            OnlyMoney(target, policy.currency),
            finality,
        )

    @staticmethod
    def _assessment(
        *,
        subject: object,
        trade_id: OnlyTradeId | None,
        components: tuple[OnlyFeeTargetComponent, ...],
        policies: OnlyResolvedFeePolicySet,
        resolution: OnlyFeePolicyResolution,
        finality: OnlyLocalFeeFinality,
        discriminator: str,
        binding: OnlyOrderFeePolicyBinding,
    ) -> OnlyFeeAssessment:
        from onlyalpha.fee.models import OnlyFeeSubject

        assert isinstance(subject, OnlyFeeSubject)
        ordered = tuple(sorted(components, key=lambda item: item.identity.sort_key))
        if ordered:
            currency = ordered[0].target_amount.currency
        else:
            raise ValueError("FEE_POLICY_SET_HAS_NO_MATCHING_RULE")
        charges = sum(
            (
                item.target_amount.amount
                for item in ordered
                if item.identity.economic_direction is OnlyFeeEconomicDirection.CHARGE
            ),
            Decimal(0),
        )
        rebates = sum(
            (
                item.target_amount.amount
                for item in ordered
                if item.identity.economic_direction is OnlyFeeEconomicDirection.REBATE
            ),
            Decimal(0),
        )
        assessment_id = only_fee_fingerprint(
            (
                discriminator,
                subject.to_dict(),
                None if trade_id is None else str(trade_id),
                tuple(item.to_dict() for item in ordered),
                policies.fingerprint,
                resolution.resolution_fingerprint,
                binding.fingerprint,
            )
        )
        return OnlyFeeAssessment(
            assessment_id,
            subject,
            trade_id,
            ordered,
            OnlyMoney(charges, currency),
            OnlyMoney(rebates, currency),
            policies.fingerprint,
            resolution.resolution_fingerprint,
            finality,
            binding,
        )

    @staticmethod
    def _validate_request_authority(
        binding: OnlyOrderFeePolicyBinding,
        resolution: OnlyFeePolicyResolution,
        currency: object,
    ) -> None:
        if (
            resolution.binding_fingerprint != binding.fingerprint
            or resolution.market_fee_pack != binding.market_fee_pack
            or resolution.broker_fee_contract != binding.broker_fee_contract
            or resolution.scope_fingerprint != binding.applicability_scope.fingerprint
        ):
            raise ValueError("ORDER_FEE_POLICY_AUTHORITY_CONFLICT")
        if not resolution.policies.policies:
            raise ValueError("FEE_SCHEDULE_NOT_FOUND")
        if any(item.currency != currency for item in resolution.policies.policies):
            raise ValueError("FEE_CURRENCY_CONVERSION_UNSUPPORTED")


def _split_sensitive(policy: OnlyResolvedFeePolicy) -> bool:
    rule = policy.rule
    return rule.calculation_scope is OnlyFeeCalculationScope.FILL and (
        rule.minimum is not None
        or rule.maximum is not None
        or any(isinstance(item, OnlyFeeFixedTerm) for item in rule.formula.terms)
    )


__all__ = ["OnlyFeeEngine"]
