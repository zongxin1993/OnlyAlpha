from dataclasses import replace
from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyOrderRequestId
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.risk.enums import OnlyRiskOutcome, OnlyRiskRejectionCode
from onlyalpha.risk.identifiers import OnlyRiskProfileId
from onlyalpha.risk.profile import OnlyRiskProfile
from onlyalpha.risk.rules.runtime import OnlyMaxOrderNotionalRiskRule


def _limited_profile(maximum: str) -> OnlyRiskProfile:
    return OnlyRiskProfile(
        OnlyRiskProfileId("limited"),
        (OnlyMaxOrderNotionalRiskRule(OnlyMoney(Decimal(maximum), OnlyCurrency("CNY", 2))),),
    )


def test_reject_creates_no_order_and_never_calls_execution(build_harness, order_request) -> None:
    harness = build_harness(_limited_profile("999.99"))
    result = harness.orders.submit(order_request, harness.cluster_id, harness.account_id)

    assert not result.created and not result.submitted
    assert result.order_id is None and result.snapshot is None
    assert result.risk_decision is not None
    assert result.risk_decision.outcome is OnlyRiskOutcome.REJECT
    assert result.risk_rejection is not None
    assert result.risk_rejection.code is OnlyRiskRejectionCode.MAXIMUM_ORDER_NOTIONAL_EXCEEDED
    assert harness.manager.snapshot_all() == ()
    assert harness.execution.submissions == ()
    assert harness.risk.reservations.snapshot_active() == ()


def test_accepted_order_is_reserved_before_next_submit(build_harness, order_request) -> None:
    harness = build_harness(_limited_profile("1500.00"))
    first = harness.orders.submit(order_request, harness.cluster_id, harness.account_id)
    second_request = replace(order_request, request_id=OnlyOrderRequestId("risk-request-2"))
    second = harness.orders.submit(second_request, harness.cluster_id, harness.account_id)

    assert first.created and first.submitted
    assert len(harness.risk.reservations.snapshot_active()) == 1
    assert not second.created and second.risk_rejection is not None
    assert second.risk_rejection.code is OnlyRiskRejectionCode.RISK_RESERVATION_EXCEEDED
    assert len(harness.manager.snapshot_all()) == 1
    assert len(harness.execution.submissions) == 1


def test_identical_request_is_deterministic_and_has_no_duplicate_order(build_harness, order_request) -> None:
    harness = build_harness()
    first = harness.orders.submit(order_request, harness.cluster_id, harness.account_id)
    second = harness.orders.submit(order_request, harness.cluster_id, harness.account_id)

    assert first.risk_decision == second.risk_decision
    assert first.order_id == second.order_id
    assert len(harness.manager.snapshot_all()) == 1
    assert len(harness.execution.submissions) == 1
