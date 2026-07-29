from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.account.enums import OnlyAccountReservationState, OnlyAccountStatus, OnlyAccountType
from onlyalpha.account.identifiers import OnlyAccountReservationId
from onlyalpha.account.models import OnlyAccountCashBalance, OnlyAccountReservation, OnlyAccountSnapshot
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderStatus, OnlyOrderType, OnlyTimeInForce
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyOrderRequestId,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyVenueId,
)
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.margin.models import OnlyMarginReservation
from onlyalpha.position.enums import (
    OnlyPositionMode,
    OnlyPositionReservationStage,
    OnlyPositionReservationState,
    OnlyPositionSide,
    OnlySettlementBucket,
)
from onlyalpha.position.identifiers import OnlyPositionReservationId
from onlyalpha.position.reservations import OnlyPositionReservation
from onlyalpha.risk.enums import OnlyRiskReservationState, OnlyRiskReservationType
from onlyalpha.risk.identifiers import OnlyRiskReservationId
from onlyalpha.risk.reservations import OnlyRiskReservation
from onlyalpha.runtime.recovery.validation import OnlyOrderReservationAuthorityCheck, OnlyPostRecoveryCheckStatus
from onlyalpha.strategy_ledger.enums import OnlyStrategyCashReservationStage, OnlyStrategyCashReservationState
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyCashReservationId
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.models import OnlyStrategyCashReservation
from tests.runtime.recovery.support.authority_fixture import OnlyPostRecoveryAuthorityFixture

_CNY = OnlyCurrency("CNY")


def _authorities(currency: OnlyCurrency = _CNY):  # type: ignore[no-untyped-def]
    fixture = OnlyPostRecoveryAuthorityFixture.create()
    now = fixture.context().runtime_boundary_view.clock_time
    runtime_id = fixture.runtime_id
    account_id = OnlyAccountId("account")
    cluster_id = OnlyClusterId("cluster")
    instrument_id = OnlyInstrumentId(OnlySymbol("instrument"), OnlyVenueId("venue"))
    order_id = OnlyOrderId("order")
    quantity = OnlyQuantity(Decimal("10"), 0)
    zero_quantity = OnlyQuantity(Decimal(0), 0)
    order = OnlyOrderSnapshot(
        order_id,
        OnlyOrderRequestId("request"),
        OnlyClientOrderId("client"),
        None,
        runtime_id,
        cluster_id,
        account_id,
        instrument_id,
        OnlyOrderSide.BUY,
        OnlyOffset.OPEN,
        OnlyOrderType.LIMIT,
        OnlyTimeInForce.DAY,
        quantity,
        OnlyPrice(Decimal("1"), 2),
        None,
        None,
        OnlyOrderStatus.ACCEPTED,
        zero_quantity,
        quantity,
        None,
        now,
        now,
        now,
        now,
        None,
        None,
        None,
        None,
        None,
        None,
        1,
        1,
        None,
        None,
    )
    money = OnlyMoney(Decimal("10"), currency)
    zero = OnlyMoney(Decimal(0), currency)
    account_reservation = OnlyAccountReservation(
        OnlyAccountReservationId("account-reservation"),
        runtime_id,
        account_id,
        order_id,
        money,
        zero,
        money,
        OnlyAccountReservationState.ACTIVE,
        now,
        now,
    )
    strategy = OnlyStrategyCashReservation(
        OnlyStrategyCashReservationId("strategy-reservation"),
        OnlyStrategyLedgerKey(runtime_id, account_id, cluster_id, currency),
        order_id,
        money,
        zero,
        money,
        zero,
        money,
        OnlyStrategyCashReservationState.ACTIVE,
        OnlyStrategyCashReservationStage.LOCAL_ONLY,
        now,
        now,
    )
    risk = OnlyRiskReservation(
        OnlyRiskReservationId("risk-reservation"),
        OnlyRiskReservationType.ORDER,
        runtime_id,
        cluster_id,
        account_id,
        order_id,
        instrument_id,
        money,
        quantity,
        now,
        now,
        OnlyRiskReservationState.ACTIVE,
    )
    return fixture, order, account_reservation, strategy, risk


def _account(fixture, *, currency: OnlyCurrency = _CNY, frozen: str = "10"):  # type: ignore[no-untyped-def]
    now = fixture.context().runtime_boundary_view.clock_time
    cash = OnlyMoney(Decimal("100"), currency)
    frozen_money = OnlyMoney(Decimal(frozen), currency)
    zero = OnlyMoney(Decimal(0), currency)
    return OnlyAccountSnapshot(
        fixture.runtime_id,
        OnlyAccountId("account"),
        "gateway",
        OnlyAccountType.CASH,
        currency,
        OnlyAccountStatus.ACTIVE,
        OnlyAccountCashBalance(cash, OnlyMoney(cash.amount - frozen_money.amount, currency), frozen_money, zero),
        zero,
        zero,
        zero,
        zero,
        cash,
        (),
        now,
        now,
        now,
        1,
    )


def _failed(context) -> set[str]:  # type: ignore[no-untyped-def]
    return {
        item.code
        for item in OnlyOrderReservationAuthorityCheck().evaluate(context)
        if item.status is OnlyPostRecoveryCheckStatus.FAILED
    }


def test_normal_buy_open_order_reservations_pass() -> None:
    fixture, order, account, strategy, risk = _authorities()
    assert not _failed(
        fixture.context(
            orders=(order,),
            accounts=(_account(fixture),),
            account_reservations=(account,),
            strategy_reservations=(strategy,),
            risk_reservations=(risk,),
        )
    )


@pytest.mark.parametrize("missing", ("account", "strategy", "risk"))
def test_required_buy_reservation_missing(missing: str) -> None:
    fixture, order, account, strategy, risk = _authorities()
    values = {"account_reservations": (account,), "strategy_reservations": (strategy,), "risk_reservations": (risk,)}
    values[f"{missing}_reservations"] = ()
    assert "POST_RECOVERY_OPEN_ORDER_RESERVATION_MISSING" in _failed(fixture.context(orders=(order,), **values))


def test_unknown_and_terminal_order_reservations_are_distinct() -> None:
    fixture, order, account, _, _ = _authorities()
    unknown = replace(account, order_id=OnlyOrderId("unknown"))
    terminal = replace(order, status=OnlyOrderStatus.CANCELLED)
    unknown_failures = _failed(fixture.context(orders=(order,), account_reservations=(unknown,)))
    terminal_failures = _failed(fixture.context(orders=(terminal,), account_reservations=(account,)))
    assert "POST_RECOVERY_ORPHAN_RESERVATION" in unknown_failures
    assert "POST_RECOVERY_TERMINAL_ORDER_ACTIVE_RESERVATION" not in unknown_failures
    assert "POST_RECOVERY_TERMINAL_ORDER_ACTIVE_RESERVATION" in terminal_failures
    assert "POST_RECOVERY_ORPHAN_RESERVATION" not in terminal_failures


@pytest.mark.parametrize("kind", ("account", "strategy", "risk", "position", "margin"))
def test_each_reservation_type_checks_cross_object_scope(kind: str) -> None:
    fixture, order, account, strategy, risk = _authorities()
    now = fixture.context().runtime_boundary_view.clock_time
    wrong_runtime = OnlyRuntimeId("wrong-runtime")
    position = OnlyPositionReservation(
        OnlyPositionReservationId("position-reservation"),
        wrong_runtime,
        order.account_id,
        order.cluster_id,
        order.instrument_id,
        OnlyPositionSide.LONG,
        OnlyPositionMode.NETTING,
        order.order_id,
        order.quantity,
        order.quantity,
        OnlySettlementBucket.SETTLED,
        OnlyPositionReservationStage.LOCAL_ONLY,
        OnlyPositionReservationState.ACTIVE,
        now,
        now,
    )
    margin = OnlyMarginReservation(
        "margin-reservation",
        wrong_runtime,
        order.account_id,
        order.instrument_id,
        order.order_id,
        OnlyCurrency("CNY"),
        Decimal("10"),
        Decimal("10"),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        now,
        now,
        1,
    )
    values = {
        "account_reservations": (replace(account, runtime_id=wrong_runtime),),
        "strategy_reservations": (replace(strategy, key=replace(strategy.key, runtime_id=wrong_runtime)),),
        "risk_reservations": (replace(risk, runtime_id=wrong_runtime),),
        "position_reservations": (position,),
        "margin_reservations": (margin,),
    }
    assert "POST_RECOVERY_RESERVATION_SCOPE_MISMATCH" in _failed(
        fixture.context(orders=(order,), **{kind + "_reservations": values[kind + "_reservations"]})
    )


@pytest.mark.parametrize("kind", ("account", "strategy", "margin"))
def test_reservation_currency_must_equal_account_base_currency(kind: str) -> None:
    fixture, order, account, strategy, _ = _authorities(OnlyCurrency("USD"))
    now = fixture.context().runtime_boundary_view.clock_time
    margin = OnlyMarginReservation(
        "margin-reservation",
        fixture.runtime_id,
        order.account_id,
        order.instrument_id,
        order.order_id,
        OnlyCurrency("USD"),
        Decimal("10"),
        Decimal("10"),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        now,
        now,
        1,
    )
    values = {
        "account_reservations": (account,),
        "strategy_reservations": (strategy,),
        "margin_reservations": (margin,),
    }
    assert "POST_RECOVERY_RESERVATION_CURRENCY_MISMATCH" in _failed(
        fixture.context(
            orders=(order,),
            accounts=(_account(fixture, frozen="0"),),
            **{kind + "_reservations": values[kind + "_reservations"]},
        )
    )


def test_position_quantity_cannot_exceed_order_quantity() -> None:
    fixture, order, _, _, _ = _authorities()
    now = fixture.context().runtime_boundary_view.clock_time
    quantity = OnlyQuantity(order.quantity.value + 1, order.quantity.precision)
    position = OnlyPositionReservation(
        OnlyPositionReservationId("position-reservation"),
        fixture.runtime_id,
        order.account_id,
        order.cluster_id,
        order.instrument_id,
        OnlyPositionSide.LONG,
        OnlyPositionMode.NETTING,
        order.order_id,
        quantity,
        quantity,
        OnlySettlementBucket.SETTLED,
        OnlyPositionReservationStage.LOCAL_ONLY,
        OnlyPositionReservationState.ACTIVE,
        now,
        now,
    )
    assert "POST_RECOVERY_RESERVATION_SCOPE_MISMATCH" in _failed(
        fixture.context(orders=(order,), position_reservations=(position,))
    )
