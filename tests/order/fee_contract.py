"""Explicit zero-fee Order contract used by isolated Order/Risk tests."""

from decimal import Decimal

from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee.estimate import OnlyOrderFeeEstimate, OnlyOrderFundingPlan
from onlyalpha.fee.models import (
    OnlyBrokerFeeAccountScope,
    OnlyBrokerFeeAccountScopeType,
    OnlyBrokerFeeContractIdentity,
    OnlyFeeAssessment,
    OnlyFeeSubject,
    OnlyLocalFeeFinality,
    OnlyMarketFeePackIdentity,
    OnlyOrderFeeApplicabilityScopeIdentity,
    OnlyOrderFeePolicyBinding,
)


def only_test_zero_fee_contract(
    order: OnlyOrderSnapshot,
    timestamp: OnlyTimestamp,
) -> tuple[OnlyOrderFeePolicyBinding, OnlyOrderFeeEstimate, OnlyOrderFundingPlan]:
    currency = OnlyCurrency("CNY", 2)
    digest = "0" * 64
    account_scope = OnlyBrokerFeeAccountScope(OnlyBrokerFeeAccountScopeType.EXACT_ACCOUNT, order.account_id)
    market_pack = OnlyMarketFeePackIdentity("TEST_ZERO_MARKET_FEES", "1", digest)
    broker_contract = OnlyBrokerFeeContractIdentity(
        "TEST_ZERO_BROKER_FEES",
        "1",
        "TEST_BROKER",
        account_scope,
        digest,
    )
    applicability = OnlyOrderFeeApplicabilityScopeIdentity.create(
        market_product_id="TEST_ZERO_FEE",
        market="TEST",
        venue="TEST",
        instrument_class="CASH",
        broker_id="TEST_BROKER",
        account_id=order.account_id,
        instrument_id=order.instrument_id,
        charge_currency=currency,
    )
    binding = OnlyOrderFeePolicyBinding.create(
        runtime_id=order.runtime_id,
        account_id=order.account_id,
        cluster_id=order.cluster_id,
        order_id=order.order_id,
        instrument_id=order.instrument_id,
        market_product_id="TEST_ZERO_FEE",
        market_product_version="1",
        market_fee_pack=market_pack,
        broker_fee_contract=broker_contract,
        applicability_scope=applicability,
        order_fixed_schedules=(),
        fill_effective_families=(),
        charge_currency=currency,
        bound_at=timestamp,
    )
    zero = OnlyMoney(Decimal(0), currency)
    subject = OnlyFeeSubject(
        order.runtime_id,
        order.account_id,
        order.cluster_id,
        order.order_id,
        order.instrument_id,
    )
    assessment = OnlyFeeAssessment(
        "test-zero-fee",
        subject,
        None,
        (),
        zero,
        zero,
        digest,
        digest,
        OnlyLocalFeeFinality.MODEL_CONFIRMED,
        binding,
    )
    estimate = OnlyOrderFeeEstimate(assessment, assessment, zero, zero, digest)
    principal_amount = Decimal(0) if order.price is None else order.price.value * order.quantity.value
    principal = OnlyMoney(principal_amount.quantize(Decimal("0.01")), currency)
    funding = OnlyOrderFundingPlan(order.order_id, principal, zero, principal, digest, digest)
    return binding, estimate, funding


__all__ = ["only_test_zero_fee_contract"]
