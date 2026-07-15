from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from onlyalpha.account import (
    OnlyAccountCashChange,
    OnlyAccountCashChangeId,
    OnlyAccountCashChangeType,
    OnlyAccountConfig,
    OnlyAccountFee,
    OnlyAccountFeeId,
    OnlyAccountManager,
    OnlyAccountReservation,
    OnlyAccountReservationId,
    OnlyAccountReservationState,
    OnlyAccountStatus,
    OnlyAccountTradeCashFlow,
    OnlyAccountType,
    OnlyAccountValuation,
)
from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlyTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney

CNY = OnlyCurrency("CNY", 2)
RUNTIME = OnlyRuntimeId("runtime-account")
ACCOUNT = OnlyAccountId("account-main")
T0 = OnlyTimestamp.from_unix_seconds(1)
T1 = OnlyTimestamp.from_unix_seconds(2)


def money(value: str) -> OnlyMoney:
    return OnlyMoney(Decimal(value), CNY)


def manager() -> OnlyAccountManager:
    result = OnlyAccountManager(RUNTIME)
    result.create_account(
        OnlyAccountConfig(RUNTIME, ACCOUNT, "virtual", OnlyAccountType.CASH, CNY, money("100000.00")),
        T0,
    )
    return result


def test_account_snapshot_is_immutable_and_derived_from_single_writer() -> None:
    account = manager()
    snapshot = account.require_snapshot(ACCOUNT)

    assert snapshot.cash.available_cash == money("100000.00")
    assert snapshot.equity == money("100000.00")
    with pytest.raises(FrozenInstanceError):
        snapshot.version = 9  # type: ignore[misc]


def test_reservation_lifecycle_is_idempotent_and_never_double_freezes() -> None:
    account = manager()
    reservation = OnlyAccountReservation(
        OnlyAccountReservationId("reservation-1"),
        RUNTIME,
        ACCOUNT,
        OnlyOrderId("order-1"),
        money("1000.00"),
        money("0.00"),
        money("1000.00"),
        OnlyAccountReservationState.ACTIVE,
        T0,
        T0,
    )

    first = account.reserve_cash(reservation)
    duplicate = account.reserve_cash(reservation)
    partial = account.consume_cash_reservation(reservation.reservation_id, money("400.00"), T1)
    released = account.release_cash(reservation.reservation_id, T1)

    assert first.changed is True
    assert duplicate.changed is False
    assert partial.after.cash.frozen_cash == money("600.00")
    assert released.after.cash.frozen_cash == money("0.00")
    assert released.after.reservations[0].state is OnlyAccountReservationState.RELEASED


def test_trade_and_valuation_update_cash_equity_and_pnl_once() -> None:
    account = manager()
    flow = OnlyAccountTradeCashFlow(
        RUNTIME,
        ACCOUNT,
        OnlyOrderId("order-1"),
        OnlyTradeId("trade-1"),
        OnlyOrderSide.BUY,
        money("1000.00"),
        money("5.00"),
        money("0.00"),
        T1,
        1,
    )

    applied = account.apply_trade_cash_flow(flow)
    duplicate = account.apply_trade_cash_flow(flow)
    valued = account.apply_valuation(OnlyAccountValuation(RUNTIME, ACCOUNT, money("1100.00"), money("100.00"), T1, 1))

    assert applied.after.cash.cash_balance == money("98995.00")
    assert duplicate.changed is False
    assert valued.after.equity == money("100095.00")
    assert valued.after.unrealized_pnl == money("100.00")


def test_stale_trade_blocks_new_local_account_authority_instead_of_reordering() -> None:
    account = manager()
    base = dict(
        runtime_id=RUNTIME,
        account_id=ACCOUNT,
        order_id=OnlyOrderId("order-1"),
        side=OnlyOrderSide.SELL,
        notional=money("100.00"),
        fee=money("0.00"),
        realized_pnl_delta=money("10.00"),
        timestamp=T1,
    )
    account.apply_trade_cash_flow(
        OnlyAccountTradeCashFlow(trade_id=OnlyTradeId("trade-2"), external_sequence=2, **base)
    )
    result = account.apply_trade_cash_flow(
        OnlyAccountTradeCashFlow(trade_id=OnlyTradeId("trade-1"), external_sequence=1, **base)
    )

    assert result.after.status is OnlyAccountStatus.RECONCILING
    assert "STALE_TRADE" in result.after.quality_flags


def test_account_manager_rejects_cross_runtime_input() -> None:
    account = manager()
    with pytest.raises(ValueError, match="another Runtime"):
        account.create_account(
            OnlyAccountConfig(
                OnlyRuntimeId("runtime-other"),
                OnlyAccountId("other"),
                "virtual",
                OnlyAccountType.CASH,
                CNY,
                money("1.00"),
            ),
            T0,
        )


def test_cash_change_fee_and_serialization_are_exact_and_deterministic() -> None:
    account = manager()
    account.apply_cash_change(
        OnlyAccountCashChange(
            OnlyAccountCashChangeId("deposit-1"),
            RUNTIME,
            ACCOUNT,
            money("10.00"),
            OnlyAccountCashChangeType.DEPOSIT,
            T1,
            1,
        )
    )
    fee = OnlyAccountFee(OnlyAccountFeeId("fee-1"), RUNTIME, ACCOUNT, money("1.00"), T1)
    first = account.apply_fee(fee)
    duplicate = account.apply_fee(fee)

    assert first.after.cash.cash_balance == money("100009.00")
    assert first.after.fees == money("1.00")
    assert duplicate.changed is False
    assert first.after.to_json() == first.after.to_json()
