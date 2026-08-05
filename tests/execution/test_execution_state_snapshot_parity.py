from dataclasses import replace
from decimal import Decimal

import pytest

from onlyalpha.account import (
    OnlyAccountConfig,
    OnlyAccountManager,
    OnlyAccountReservation,
    OnlyAccountTradeCashFlow,
    OnlyAccountType,
    OnlyAccountValuation,
)
from onlyalpha.account.enums import OnlyAccountReservationState
from onlyalpha.account.identifiers import OnlyAccountReservationId
from onlyalpha.domain.enums import OnlyDirection, OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyOrderRequestId,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyTradeId,
    OnlyVenueId,
    OnlyVenueOrderId,
    OnlyVenueTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.execution import (
    OnlyAccountExecutionState,
    only_account_cash_reservation_execution_state,
    only_account_execution_state,
    only_allocation_execution_state,
    only_execution_state_hash,
    only_margin_reservation_execution_state,
    only_order_execution_state,
    only_position_execution_state,
    only_position_reservation_execution_state,
    only_risk_reservation_execution_state,
    only_strategy_cash_reservation_execution_state,
    only_strategy_ledger_execution_state,
)
from onlyalpha.margin import OnlyMarginManager
from onlyalpha.market.runtime_rules import OnlyMarginInstruction
from onlyalpha.order.id_generator import OnlySequenceClientOrderIdGenerator, OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.position import (
    OnlyPositionAllocationManager,
    OnlyPositionManager,
    OnlyPositionReservationManager,
    OnlyPositionSide,
    OnlyPositionTrade,
    OnlySettlementBucket,
)
from onlyalpha.risk.reservations import OnlyRiskReservationManager
from onlyalpha.strategy_ledger import OnlyStrategyLedgerManager, OnlyStrategyTradeAccountingInput
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from tests.execution.factories.transaction_factory import only_test_generic_t0_cash_buy_open_transaction

RUNTIME = OnlyRuntimeId("runtime-parity")
ACCOUNT = OnlyAccountId("account-parity")
CLUSTER = OnlyClusterId("cluster-parity")
INSTRUMENT = OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG"))
CNY = OnlyCurrency("CNY", 2)
T0 = OnlyTimestamp(1_000)
T1 = OnlyTimestamp(2_000)


def money(value: str) -> OnlyMoney:
    return OnlyMoney(Decimal(value), CNY)


def quantity(value: str) -> OnlyQuantity:
    return OnlyQuantity(Decimal(value), 0)


def position_trade() -> OnlyPositionTrade:
    return OnlyPositionTrade(
        OnlyTradeId("trade-parity"),
        OnlyVenueTradeId("venue-trade-parity"),
        OnlyOrderId("order-parity"),
        CLUSTER,
        RUNTIME,
        ACCOUNT,
        INSTRUMENT,
        OnlyOrderSide.BUY,
        OnlyDirection.BUY,
        OnlyOffset.OPEN,
        OnlyPositionSide.LONG,
        OnlyPrice(Decimal("10.00"), 2),
        quantity("2"),
        money("0.00"),
        T1,
        T1,
        1,
        settlement_bucket=OnlySettlementBucket.SETTLED,
    )


def test_real_order_position_and_allocation_snapshots_convert_without_loss() -> None:
    orders = OnlyOrderManager(
        OnlyEngineId("engine"),
        RUNTIME,
        OnlySequenceOrderIdGenerator(RUNTIME),
        OnlySequenceClientOrderIdGenerator(RUNTIME),
    )
    created = orders.create_order(
        OnlyOrderRequest(
            OnlyOrderRequestId("request-parity"),
            INSTRUMENT,
            OnlyOrderSide.BUY,
            OnlyOrderType.LIMIT,
            quantity("2"),
            price=OnlyPrice(Decimal("10.00"), 2),
        ),
        CLUSTER,
        ACCOUNT,
        T0,
    )
    orders.mark_submitted(created.order_id, T1)
    accepted = orders.apply_accepted(
        created.order_id, T1, OnlyVenueOrderId("venue-order"), external_sequence=1
    ).snapshot
    order_state = only_order_execution_state(accepted)
    assert order_state.to_dict() == accepted.to_dict()

    positions = OnlyPositionManager(RUNTIME)
    allocations = OnlyPositionAllocationManager(RUNTIME)
    assert positions.list_open() == ()
    trade = position_trade()
    position_snapshot = positions.apply_trade(trade).after
    allocations.apply_trade(trade)
    allocation_snapshot = allocations.list_by_cluster(CLUSTER)[0]
    assert position_snapshot is not None
    assert only_position_execution_state(position_snapshot).to_dict() == position_snapshot.to_dict()
    assert only_allocation_execution_state(allocation_snapshot).to_dict() == allocation_snapshot.to_dict()


def test_real_account_and_ledger_snapshots_preserve_formulas_fields_and_hashes() -> None:
    accounts = OnlyAccountManager(RUNTIME)
    first = accounts.create_account(
        OnlyAccountConfig(RUNTIME, ACCOUNT, "virtual", OnlyAccountType.CASH, CNY, money("100.00")), T0
    )
    first_state = only_account_execution_state(first)
    assert first_state.ledger_cash == first.cash.ledger_cash
    assert first_state.trade_available_cash == first.cash.trade_available_cash == money("100.00")
    assert first_state.available_margin == first.available_margin == money("100.00")
    assert first_state.equity == first.equity == money("100.00")
    changed = accounts.apply_margin_change(
        ACCOUNT, reserved_delta=Decimal("10.00"), occupied_delta=Decimal("5.00"), timestamp=T1
    ).after
    changed_state = only_account_execution_state(changed)
    assert changed_state.available_margin == money("85.00")
    assert only_execution_state_hash(first_state) == only_execution_state_hash(only_account_execution_state(first))
    assert only_execution_state_hash(first_state) != only_execution_state_hash(changed_state)
    assert only_execution_state_hash(replace(changed_state, metadata={"b": "2", "a": "1"})) == (
        only_execution_state_hash(replace(changed_state, metadata={"a": "1", "b": "2"}))
    )

    ledgers = OnlyStrategyLedgerManager(RUNTIME)
    key = OnlyStrategyLedgerKey(RUNTIME, ACCOUNT, CLUSTER, CNY)
    ledgers.create_ledger(key, money("100.00"), T0)
    snapshot = ledgers.activate_ledger(key, T1)
    state = only_strategy_ledger_execution_state(snapshot)
    assert state.ledger_cash == snapshot.cash.ledger_cash
    assert state.cash_available == snapshot.cash.cash_available
    assert state.position_cost == snapshot.equity.position_cost
    assert state.position_market_value == snapshot.equity.position_market_value
    assert state.cash_entries == snapshot.cash_entries
    assert state.fee_entries == snapshot.fee_entries
    assert state.equity == snapshot.equity.equity == state.ledger_cash + state.position_market_value


@pytest.mark.parametrize(
    "changes",
    (
        {"trade_available_cash": money("99.00")},
        {"available_margin": money("99.00")},
        {"equity": money("99.00")},
        {"version": 0},
    ),
)
def test_account_execution_state_rejects_formula_and_version_errors(changes: dict[str, object]) -> None:
    accounts = OnlyAccountManager(RUNTIME)
    snapshot = accounts.create_account(
        OnlyAccountConfig(RUNTIME, ACCOUNT, "virtual", OnlyAccountType.CASH, CNY, money("100.00")), T0
    )
    state: OnlyAccountExecutionState = only_account_execution_state(snapshot)
    with pytest.raises(ValueError):
        replace(state, **changes)


def test_real_reservation_entities_convert_after_manager_transitions() -> None:
    accounts = OnlyAccountManager(RUNTIME)
    accounts.create_account(
        OnlyAccountConfig(RUNTIME, ACCOUNT, "virtual", OnlyAccountType.CASH, CNY, money("100.00")), T0
    )
    account_reservation = OnlyAccountReservation(
        OnlyAccountReservationId("account-reservation"),
        RUNTIME,
        ACCOUNT,
        OnlyOrderId("order-account"),
        money("20.00"),
        money("0.00"),
        money("20.00"),
        OnlyAccountReservationState.ACTIVE,
        T0,
        T0,
    )
    accounts.reserve_cash(account_reservation)
    account_after = accounts.consume_cash_reservation(account_reservation.reservation_id, money("20.00"), T1)
    account_entity = account_after.after.reservations[0]
    assert only_account_cash_reservation_execution_state(account_entity).consumed_amount == money("20.00")

    ledgers = OnlyStrategyLedgerManager(RUNTIME)
    key = OnlyStrategyLedgerKey(RUNTIME, ACCOUNT, CLUSTER, CNY)
    ledgers.create_ledger(key, money("100.00"), T0)
    ledgers.activate_ledger(key, T0)
    ledgers.reserve_cash(key, OnlyOrderId("order-ledger"), money("20.00"), money("0.00"), T0)
    ledgers.consume_cash_reservation(key, OnlyOrderId("order-ledger"), money("20.00"), T1)
    strategy_entity = ledgers.require_snapshot(key).reservations[0]
    assert only_strategy_cash_reservation_execution_state(strategy_entity).remaining_amount == money("0.00")

    positions = OnlyPositionManager(RUNTIME)
    allocations = OnlyPositionAllocationManager(RUNTIME)
    trade = position_trade()
    positions.apply_trade(trade)
    allocations.apply_trade(trade)
    reservations = OnlyPositionReservationManager(RUNTIME, positions, allocations)
    created = reservations.create(ACCOUNT, CLUSTER, INSTRUMENT, OnlyOrderId("order-close"), quantity("2"), T0)
    consumed = reservations.consume(created.reservation.order_id, quantity("2"), T1)
    assert only_position_reservation_execution_state(consumed.reservation).remaining_quantity == quantity("0")

    risks = OnlyRiskReservationManager(RUNTIME)
    risk = risks.create(CLUSTER, ACCOUNT, OnlyOrderId("order-risk"), INSTRUMENT, money("20.00"), quantity("2"), T0)
    consumed_risk = risks.consume_fill_for_order(
        OnlyOrderId("order-risk"),
        quantity("2"),
        money("20.00"),
        T1,
        runtime_id=RUNTIME,
        cluster_id=CLUSTER,
        complete=True,
    )
    assert risk.reservation is not None and consumed_risk.reservation is not None
    risk_state = only_risk_reservation_execution_state(consumed_risk.reservation)
    assert risk_state.remaining_quantity == quantity("0")
    assert risk_state.remaining_notional == money("0.00")

    margins = OnlyMarginManager(RUNTIME)
    margins.apply(
        OnlyMarginInstruction(
            "RESERVE",
            str(ACCOUNT),
            str(INSTRUMENT),
            CNY.code,
            Decimal("20.00"),
            Decimal("10.00"),
            "order-margin",
            "trade-margin",
            T0,
        )
    )
    margin_entity = margins.get("order-margin")
    assert margin_entity is not None
    margin_state = only_margin_reservation_execution_state(margin_entity)
    assert margin_state.original_reserved_amount == money("20.00")
    assert margin_state.remaining_reserved_amount == money("20.00")
    assert margin_state.version == margin_entity.version


def test_pr2_generic_t0_baseline_uses_real_manager_before_after_authority() -> None:
    runtime = OnlyRuntimeId("runtime")
    account_id = OnlyAccountId("account")
    cluster = OnlyClusterId("cluster")
    instrument = OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG"))
    order_id = OnlyOrderId("order")
    trade_id = OnlyTradeId("trade")
    accounts = OnlyAccountManager(runtime)
    accounts.create_account(
        OnlyAccountConfig(runtime, account_id, "gateway", OnlyAccountType.CASH, CNY, money("100.00")), T0
    )
    reservation = OnlyAccountReservation(
        OnlyAccountReservationId("account-reservation"),
        runtime,
        account_id,
        order_id,
        money("20.00"),
        money("0.00"),
        money("20.00"),
        OnlyAccountReservationState.ACTIVE,
        T0,
        T0,
    )
    account_before = accounts.reserve_cash(reservation).after
    accounts.consume_cash_reservation(reservation.reservation_id, money("20.00"), T1)
    accounts.apply_trade_cash_flow(
        OnlyAccountTradeCashFlow(
            runtime,
            account_id,
            order_id,
            trade_id,
            OnlyOrderSide.BUY,
            money("20.00"),
            money("0.00"),
            money("0.00"),
            T1,
            7,
        )
    )
    account_after = accounts.apply_valuation(
        OnlyAccountValuation(runtime, account_id, money("20.00"), money("0.00"), T1, 1)
    ).after
    account_before_state = only_account_execution_state(account_before)
    account_after_state = only_account_execution_state(account_after)

    allocations = OnlyPositionAllocationManager(runtime)
    trade = replace(
        position_trade(),
        trade_id=trade_id,
        venue_trade_id=OnlyVenueTradeId("venue-trade"),
        order_id=order_id,
        cluster_id=cluster,
        runtime_id=runtime,
        account_id=account_id,
        instrument_id=instrument,
        external_sequence=7,
    )
    ledgers = OnlyStrategyLedgerManager(runtime)
    key = OnlyStrategyLedgerKey(runtime, account_id, cluster, CNY)
    ledgers.create_ledger(key, money("100.00"), T0)
    ledgers.activate_ledger(key, T0)
    ledgers.reserve_cash(key, order_id, money("20.00"), money("0.00"), T0)
    ledger_before = ledgers.require_snapshot(key)
    allocation_before = None
    allocations.apply_trade(trade)
    allocation_after = allocations.list_by_cluster(cluster)[0]
    strategy_reservation = ledger_before.reservations[0]
    ledgers.apply_trade_accounting(
        key,
        OnlyStrategyTradeAccountingInput(
            trade,
            None,
            allocation_before,
            allocation_after,
            money("0.00"),
            money("20.00"),
            (),
            strategy_reservation,
            T1,
            7,
        ),
    )
    ledger_after = ledgers.require_snapshot(key)
    ledger_before_state = only_strategy_ledger_execution_state(ledger_before)
    ledger_after_state = only_strategy_ledger_execution_state(ledger_after)

    prepared = only_test_generic_t0_cash_buy_open_transaction()
    assert account_after_state.ledger_cash.amount - account_before_state.ledger_cash.amount == (
        prepared.fact_draft.account_cash_delta.amount
    )
    assert ledger_after_state.ledger_cash.amount - ledger_before_state.ledger_cash.amount == (
        prepared.fact_draft.ledger_cash_delta.amount
    )
    assert account_after_state.position_market_value == ledger_after_state.position_market_value == money("20.00")
    assert only_execution_state_hash(account_before_state) != only_execution_state_hash(account_after_state)
    assert only_execution_state_hash(ledger_before_state) != only_execution_state_hash(ledger_after_state)
    assert all(
        projection.identity.expected_state_hash == only_execution_state_hash(projection.before)
        and projection.identity.result_state_hash == only_execution_state_hash(projection.after)
        for projection in prepared.projections
    )
