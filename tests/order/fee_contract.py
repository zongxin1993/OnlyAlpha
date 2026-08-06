"""Explicit zero-fee Order contract used by isolated Order/Risk tests."""

from decimal import Decimal

from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee.estimate import OnlyOrderFeeEstimate, OnlyOrderFundingPlan
from onlyalpha.fee.models import (
    OnlyFeeAssessment,
    OnlyFeeSubject,
    OnlyLocalFeeFinality,
    OnlyOrderFeePolicyBinding,
)


def only_test_zero_fee_contract(
    order: OnlyOrderSnapshot,
    timestamp: OnlyTimestamp,
) -> tuple[OnlyOrderFeePolicyBinding, OnlyOrderFeeEstimate, OnlyOrderFundingPlan]:
    currency = OnlyCurrency("CNY", 2)
    digest = "0" * 64
    binding = OnlyOrderFeePolicyBinding(
        order.runtime_id,
        order.account_id,
        order.cluster_id,
        order.order_id,
        order.instrument_id,
        "TEST_ZERO_FEE",
        "1",
        (),
        (),
        currency,
        timestamp,
        digest,
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
        OnlyLocalFeeFinality.MODEL_CONFIRMED,
        binding,
    )
    estimate = OnlyOrderFeeEstimate(assessment, assessment, zero, zero, digest)
    principal_amount = Decimal(0) if order.price is None else order.price.value * order.quantity.value
    principal = OnlyMoney(principal_amount.quantize(Decimal("0.01")), currency)
    funding = OnlyOrderFundingPlan(order.order_id, principal, zero, principal, digest, digest)
    return binding, estimate, funding


__all__ = ["only_test_zero_fee_contract"]
