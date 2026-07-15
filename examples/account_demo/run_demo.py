"""Minimal local Account lifecycle using only public interfaces."""

from decimal import Decimal

from onlyalpha.account import (
    OnlyAccountConfig,
    OnlyAccountManager,
    OnlyAccountReservation,
    OnlyAccountReservationId,
    OnlyAccountReservationState,
    OnlyAccountType,
)
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney


def main() -> None:
    runtime_id = OnlyRuntimeId("account-demo-runtime")
    account_id = OnlyAccountId("account-demo")
    currency = OnlyCurrency("CNY", 2)
    now = OnlyTimestamp.from_unix_seconds(1)
    manager = OnlyAccountManager(runtime_id)
    manager.create_account(
        OnlyAccountConfig(
            runtime_id,
            account_id,
            "demo-gateway",
            OnlyAccountType.CASH,
            currency,
            OnlyMoney(Decimal("100000.00"), currency),
        ),
        now,
    )
    reservation = OnlyAccountReservation(
        OnlyAccountReservationId("account-demo-reservation"),
        runtime_id,
        account_id,
        OnlyOrderId("account-demo-order"),
        OnlyMoney(Decimal("1000.00"), currency),
        OnlyMoney(Decimal("0.00"), currency),
        OnlyMoney(Decimal("1000.00"), currency),
        OnlyAccountReservationState.ACTIVE,
        now,
        now,
    )
    manager.reserve_cash(reservation)
    print(manager.require_snapshot(account_id).to_json())
    manager.release_cash(reservation.reservation_id, now)
    print(manager.require_snapshot(account_id).to_json())


if __name__ == "__main__":
    main()
