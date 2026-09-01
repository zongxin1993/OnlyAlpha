from decimal import Decimal

import pytest

from onlyalpha.domain.identifiers import OnlyOrderId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.margin import OnlyMarginManager
from onlyalpha.margin.order_port import OnlyOrderMarginReservationAdapter
from onlyalpha.market.runtime_rules import OnlyMarginInstruction


def _instruction(
    action: str,
    instrument: str,
    order: str,
    amount: str,
    *,
    mode: str,
    isolation_key: str | None = None,
) -> OnlyMarginInstruction:
    return OnlyMarginInstruction(
        action,
        "account-1",
        instrument,
        "USD",
        Decimal(amount),
        Decimal(amount) / 2,
        order,
        f"trade-{order}",
        OnlyTimestamp(1),
        mode,
        isolation_key,
    )


def test_cross_margin_uses_one_account_collateral_scope() -> None:
    manager = OnlyMarginManager(OnlyRuntimeId("margin-modes"))
    manager.apply(_instruction("RESERVE", "FUT.A", "a", "10", mode="CROSS"))
    manager.apply(_instruction("OCCUPY", "FUT.A", "a", "10", mode="CROSS"))
    manager.apply(_instruction("RESERVE", "FUT.B", "b", "20", mode="CROSS"))
    manager.apply(_instruction("OCCUPY", "FUT.B", "b", "20", mode="CROSS"))

    assert manager.occupied("account-1", "FUT.A", "USD") == Decimal("30")
    assert manager.occupied("account-1", "FUT.B", "USD") == Decimal("30")


def test_isolated_margin_releases_only_target_bucket_and_restores() -> None:
    manager = OnlyMarginManager(OnlyRuntimeId("margin-modes"))
    manager.apply(_instruction("RESERVE", "FUT.A", "long", "10", mode="ISOLATED", isolation_key="FUT.A:LONG"))
    manager.apply(_instruction("OCCUPY", "FUT.A", "long", "10", mode="ISOLATED", isolation_key="FUT.A:LONG"))
    manager.apply(_instruction("RESERVE", "FUT.A", "short", "20", mode="ISOLATED", isolation_key="FUT.A:SHORT"))
    manager.apply(_instruction("OCCUPY", "FUT.A", "short", "20", mode="ISOLATED", isolation_key="FUT.A:SHORT"))
    manager.apply(_instruction("RELEASE", "FUT.A", "close-long", "10", mode="ISOLATED", isolation_key="FUT.A:LONG"))

    assert manager.get("long").released == Decimal("10")  # type: ignore[union-attr]
    assert manager.get("short").occupied == Decimal("20")  # type: ignore[union-attr]

    restored = OnlyMarginManager(OnlyRuntimeId("margin-modes"))
    restored.restore_checkpoint(manager.capture_checkpoint())
    assert restored.active_reservations == manager.active_reservations
    assert restored.records == manager.records


def test_margin_release_cannot_claim_more_than_authoritative_balance() -> None:
    manager = OnlyMarginManager(OnlyRuntimeId("margin-modes"))
    manager.apply(_instruction("RESERVE", "FUT.A", "a", "10", mode="CROSS"))
    manager.apply(_instruction("OCCUPY", "FUT.A", "a", "10", mode="CROSS"))
    before = manager.capture_checkpoint()
    with pytest.raises(ValueError, match="margin release exceeds"):
        manager.apply(_instruction("RELEASE", "FUT.A", "close", "20", mode="CROSS"))
    assert manager.capture_checkpoint() == before


def test_partial_occupations_restore_identical_maintenance_state() -> None:
    manager = OnlyMarginManager(OnlyRuntimeId("margin-partial"))
    manager.apply(_instruction("RESERVE", "FUT.A", "a", "10", mode="CROSS"))
    manager.apply(_instruction("OCCUPY", "FUT.A", "a", "4", mode="CROSS"))
    manager.apply(_instruction("OCCUPY", "FUT.A", "a", "6", mode="CROSS"))

    before = manager.capture_checkpoint()
    restored = OnlyMarginManager(OnlyRuntimeId("margin-partial"))
    restored.restore_checkpoint(before)

    assert restored.capture_checkpoint() == before
    assert restored.get("a").maintenance_required == Decimal("5")  # type: ignore[union-attr]


def test_release_allocates_maintenance_across_multiple_reservations() -> None:
    manager = OnlyMarginManager(OnlyRuntimeId("margin-release"))
    for order, amount in (("a", "4"), ("b", "6")):
        manager.apply(_instruction("RESERVE", "FUT.A", order, amount, mode="CROSS"))
        manager.apply(_instruction("OCCUPY", "FUT.A", order, amount, mode="CROSS"))

    manager.apply(_instruction("RELEASE", "FUT.A", "close", "7", mode="CROSS"))

    assert manager.get("a").maintenance_required == 0  # type: ignore[union-attr]
    assert manager.get("b").maintenance_required == Decimal("1.5")  # type: ignore[union-attr]
    assert manager.records[-1].maintenance_required_after == Decimal("1.5")


class _AccountMarginRecorder:
    def apply_margin_change(self, *args: object, **kwargs: object) -> None:
        del args, kwargs


def test_isolated_order_cancellation_preserves_reservation_scope() -> None:
    manager = OnlyMarginManager(OnlyRuntimeId("margin-cancel"))
    manager.apply(_instruction("RESERVE", "FUT.A", "a", "10", mode="ISOLATED", isolation_key="FUT.A:LONG"))
    adapter = OnlyOrderMarginReservationAdapter(
        manager,
        _AccountMarginRecorder(),  # type: ignore[arg-type]
        None,
        {},
        lambda timestamp: None,  # type: ignore[arg-type,return-value]
        lambda order: None,
    )

    adapter.release(OnlyOrderId("a"), OnlyTimestamp(2))

    reservation = manager.get("a")
    assert reservation is not None
    assert reservation.reserved == 0
    assert reservation.margin_mode.value == "ISOLATED"
    assert reservation.isolation_key == "FUT.A:LONG"
