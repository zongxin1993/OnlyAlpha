from decimal import Decimal

import pytest

from onlyalpha.domain.errors import OnlySerializationError
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee.reconciliation_policy import (
    OnlyFeeReconciliationAction,
    OnlyFeeReconciliationPolicy,
    OnlyFeeReconciliationPolicyRegistry,
)


def _policy(
    threshold: str = "0.10",
    currency: OnlyCurrency | None = None,
) -> OnlyFeeReconciliationPolicy:
    selected_currency = currency or OnlyCurrency("CNY", 2)
    return OnlyFeeReconciliationPolicy.create(
        policy_id="policy",
        policy_version="1",
        currency=selected_currency,
        materiality_threshold=OnlyMoney(Decimal(threshold), selected_currency),
        unknown_difference_action=OnlyFeeReconciliationAction.BLOCK,
        incomplete_evidence_action=OnlyFeeReconciliationAction.BLOCK,
        component_mismatch_action=OnlyFeeReconciliationAction.ADJUST,
    )


def test_policy_registry_is_versioned_and_fail_closed() -> None:
    registry = OnlyFeeReconciliationPolicyRegistry()
    policy = _policy()
    registry.register(policy)
    assert registry.require("policy", "1", policy.currency) is policy
    with pytest.raises(ValueError, match="DUPLICATE_VERSION"):
        registry.register(policy)
    conflicting = _policy("0.20")
    other = OnlyFeeReconciliationPolicyRegistry()
    other.register(policy)
    with pytest.raises(ValueError, match="FINGERPRINT_CONFLICT"):
        other.register(conflicting)
    with pytest.raises(ValueError, match="NOT_INSTALLED"):
        registry.require("missing", "1", policy.currency)
    with pytest.raises(ValueError):
        _policy("-0.01")


def test_policy_registry_currency_is_an_exact_identity_dimension() -> None:
    cny = _policy(currency=OnlyCurrency("CNY", 2))
    usd = _policy(currency=OnlyCurrency("USD", 2))
    registry = OnlyFeeReconciliationPolicyRegistry()

    registry.register(cny)
    registry.register(usd)

    assert registry.require("policy", "1", cny.currency) is cny
    assert registry.require("policy", "1", usd.currency) is usd
    with pytest.raises(ValueError, match="NOT_INSTALLED"):
        registry.require("policy", "1", OnlyCurrency("JPY", 0))


def test_policy_identity_currency_round_trip_and_old_schema_rejection() -> None:
    identity = _policy().identity

    assert type(identity).from_json(identity.to_json()) == identity
    old_payload = identity.to_dict()
    old_payload["schema_version"] = 1
    old_payload.pop("currency")
    with pytest.raises(OnlySerializationError, match="unsupported"):
        type(identity).from_dict(old_payload)
