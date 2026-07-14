from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.risk.enums import OnlyRiskReleaseReason, OnlyRiskReservationApplyResult
from onlyalpha.risk.identifiers import OnlyRiskProfileId
from onlyalpha.risk.profile import OnlyRiskProfile
from onlyalpha.risk.rules.runtime import OnlyMaxOrderNotionalRiskRule


def test_snapshot_updates_immediately_after_reservation(build_harness, order_request) -> None:
    profile = OnlyRiskProfile(
        OnlyRiskProfileId("snapshot"),
        (OnlyMaxOrderNotionalRiskRule(OnlyMoney(Decimal("2000.00"), OnlyCurrency("CNY", 2))),),
    )
    harness = build_harness(profile)
    before = harness.risk.get_snapshot(harness.cluster_id)
    result = harness.orders.submit(order_request, harness.cluster_id, harness.account_id)
    after = harness.risk.get_snapshot(harness.cluster_id)

    assert result.order_id is not None
    assert before.reserved_notional == OnlyMoney(Decimal("0.00"), OnlyCurrency("CNY", 2))
    assert after.version > before.version
    assert after.reserved_notional == OnlyMoney(Decimal("1000.00"), OnlyCurrency("CNY", 2))
    assert after.reserved_quantity == Decimal("100")
    with pytest.raises(FrozenInstanceError):
        after.version = 99  # type: ignore[misc]


def test_reservation_release_is_scoped_and_idempotent(build_harness, order_request) -> None:
    harness = build_harness()
    submitted = harness.orders.submit(order_request, harness.cluster_id, harness.account_id)
    assert submitted.order_id is not None
    reservation = harness.risk.reservations.get_for_order(submitted.order_id)
    assert reservation is not None
    now = harness.risk.get_snapshot(harness.cluster_id).ts_init

    released = harness.risk.release_reservation(
        reservation.reservation_id,
        harness.cluster_id,
        OnlyRiskReleaseReason.ORDER_CANCELLED,
        now,
    )
    duplicate = harness.risk.release_reservation(
        reservation.reservation_id,
        harness.cluster_id,
        OnlyRiskReleaseReason.ORDER_CANCELLED,
        now,
    )

    assert released.apply_result is OnlyRiskReservationApplyResult.APPLIED and released.changed
    assert duplicate.apply_result is OnlyRiskReservationApplyResult.DUPLICATE and not duplicate.changed
    assert harness.risk.reservations.snapshot_active() == ()
