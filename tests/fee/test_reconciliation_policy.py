from decimal import Decimal

import pytest

from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee.reconciliation_policy import (
    OnlyFeeReconciliationAction,
    OnlyFeeReconciliationPolicy,
    OnlyFeeReconciliationPolicyRegistry,
)


def _policy(threshold: str = "0.10") -> OnlyFeeReconciliationPolicy:
    currency = OnlyCurrency("CNY", 2)
    return OnlyFeeReconciliationPolicy.create(
        policy_id="policy",
        policy_version="1",
        currency=currency,
        materiality_threshold=OnlyMoney(Decimal(threshold), currency),
        unknown_difference_action=OnlyFeeReconciliationAction.BLOCK,
        incomplete_evidence_action=OnlyFeeReconciliationAction.BLOCK,
        component_mismatch_action=OnlyFeeReconciliationAction.ADJUST,
    )


def test_policy_registry_is_versioned_and_fail_closed() -> None:
    registry = OnlyFeeReconciliationPolicyRegistry()
    policy = _policy()
    registry.register(policy)
    assert registry.require("policy", "1") is policy
    with pytest.raises(ValueError, match="DUPLICATE_VERSION"):
        registry.register(policy)
    conflicting = _policy("0.20")
    other = OnlyFeeReconciliationPolicyRegistry()
    other.register(policy)
    with pytest.raises(ValueError, match="FINGERPRINT_CONFLICT"):
        other.register(conflicting)
    with pytest.raises(ValueError, match="NOT_INSTALLED"):
        registry.require("missing", "1")
    with pytest.raises(ValueError):
        _policy("-0.01")
