from dataclasses import replace
from decimal import Decimal

from onlyalpha.account.enums import OnlyAccountType
from onlyalpha.domain.enums import OnlyMarginMode, OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyOrderId
from onlyalpha.domain.trading import OnlyExecutionIntent, OnlyPositionEffect, OnlyPositionSide
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.execution import (
    OnlyExecutionCapability,
    OnlyExecutionCapabilityResolver,
    OnlyExecutionReservationShape,
    OnlyExecutionSupportContext,
    OnlyMarginReservationExecutionStage,
    OnlyMarginReservationExecutionState,
    OnlyMarginReservationExecutionStatus,
    OnlyTradeExecutionTransactionPlanner,
)
from onlyalpha.market.runtime_rules import OnlyMarginInstruction
from onlyalpha.transaction import OnlyRuntimeOperationKind, OnlyRuntimeProjectionComponent

from .factories.trade_planning_factory import only_test_generic_t0_trade_planning_context
from .support.generic_t0_trade_harness import only_test_generic_t0_long_close_context


def _margin_context():
    context = only_test_generic_t0_trade_planning_context()
    currency = context.account_before.base_currency
    reserved = OnlyMoney(Decimal("100"), currency)
    zero = OnlyMoney(Decimal(0), currency)
    trade_available = context.account_before.ledger_cash
    withdrawable = OnlyMoney(
        trade_available.amount - context.account_before.unsettled_receivable_cash.amount,
        currency,
    )
    account = replace(
        context.account_before,
        account_type=OnlyAccountType.MARGIN,
        trade_available_cash=trade_available,
        withdrawable_cash=withdrawable,
        order_reserved_cash=zero,
        reserved_margin=reserved,
        occupied_margin=zero,
        released_margin=zero,
        available_margin=OnlyMoney(withdrawable.amount - reserved.amount, currency),
    )
    instruction = OnlyMarginInstruction(
        "OCCUPY",
        str(context.update.account_id),
        str(context.order_before.instrument_id),
        currency.code,
        Decimal("100"),
        Decimal("50"),
        str(context.order_before.order_id),
        str(context.update.fill.trade_id),
        context.update.ts_event,
        OnlyMarginMode.CROSS.value,
        None,
        OnlyPositionSide.LONG.value,
    )
    margin = OnlyMarginReservationExecutionState(
        "margin-reservation",
        context.update.runtime_id,
        context.update.account_id,
        context.order_before.instrument_id,
        context.order_before.order_id,
        currency,
        reserved,
        reserved,
        zero,
        zero,
        zero,
        OnlyMarginReservationExecutionStatus.ACTIVE,
        OnlyMarginReservationExecutionStage.RESERVED,
        context.order_before.created_at,
        context.order_before.created_at,
        1,
        OnlyMarginMode.CROSS,
        None,
        OnlyPositionSide.LONG,
    )
    trade_instruction = replace(
        context.trade_instruction,
        margin_instruction=instruction,
        cash_instruction=replace(context.trade_instruction.cash_instruction, amount=Decimal(0), settle_notional=False),
    )
    support = OnlyExecutionCapabilityResolver().resolve(
        OnlyExecutionSupportContext(
            operation_kind=OnlyRuntimeOperationKind.TRADE_FILL,
            account_type=OnlyAccountType.MARGIN,
            order_type=context.order_before.order_type,
            order_side=context.order_before.side,
            offset=context.order_before.offset,
            position_side=context.position_scope.position_side,
            position_effect=context.position_scope.position_effect,
            position_mode=context.position_scope.position_mode,
            has_margin=True,
            account_ledger_parity=True,
            reservations=OnlyExecutionReservationShape(False, False, False, True, True),
        )
    )
    assert support.capability is OnlyExecutionCapability.DURABLE_TRADE
    return replace(
        context,
        trade_instruction=trade_instruction,
        support_decision=support,
        account_before=account,
        strategy_ledger_before=replace(
            context.strategy_ledger_before,
            cash_reserved=zero,
            cash_available=context.strategy_ledger_before.ledger_cash,
        ),
        account_cash_reservation_before=None,
        strategy_cash_reservation_before=None,
        margin_reservation_before=margin,
    )


def _margin_close_context(*, fill_quantity: str = "40", fill_price: str = "12.00"):
    _, context, _ = only_test_generic_t0_long_close_context(
        open_quantity="100",
        close_quantity="100",
        fill_quantity=fill_quantity,
        fill_price=fill_price,
    )
    assert context.position_before is not None
    assert context.position_reservation_before is not None
    currency = context.account_before.base_currency
    zero = OnlyMoney(Decimal(0), currency)
    occupied = OnlyMoney(Decimal("100"), currency)
    maintenance = OnlyMoney(Decimal("50"), currency)
    account = replace(
        context.account_before,
        account_type=OnlyAccountType.MARGIN,
        position_market_value=zero,
        unrealized_pnl=zero,
        equity=context.account_before.ledger_cash,
        reserved_margin=zero,
        occupied_margin=occupied,
        released_margin=zero,
        available_margin=OnlyMoney(context.account_before.ledger_cash.amount - occupied.amount, currency),
    )
    ledger = replace(
        context.strategy_ledger_before,
        position_market_value=zero,
        unrealized_pnl=zero,
        equity=context.strategy_ledger_before.ledger_cash,
    )
    margin = OnlyMarginReservationExecutionState(
        "margin-open-order",
        context.update.runtime_id,
        context.update.account_id,
        context.order_before.instrument_id,
        context.position_reservation_before.order_id,
        currency,
        occupied,
        zero,
        occupied,
        zero,
        maintenance,
        OnlyMarginReservationExecutionStatus.OCCUPIED,
        OnlyMarginReservationExecutionStage.OCCUPIED,
        context.position_before.opened_at,
        context.position_before.updated_at,
        2,
        OnlyMarginMode.CROSS,
        None,
        context.position_scope.position_side,
    )
    release = OnlyMarginInstruction(
        "RELEASE",
        str(context.update.account_id),
        str(context.order_before.instrument_id),
        currency.code,
        Decimal(0),
        Decimal(0),
        str(context.order_before.order_id),
        str(context.update.fill.trade_id),
        context.update.ts_event,
        OnlyMarginMode.CROSS.value,
        None,
        context.position_scope.position_side.value,
    )
    instruction = replace(
        context.trade_instruction,
        margin_instruction=release,
        cash_instruction=replace(context.trade_instruction.cash_instruction, amount=Decimal(0), settle_notional=False),
    )
    support = OnlyExecutionCapabilityResolver().resolve(
        OnlyExecutionSupportContext(
            operation_kind=OnlyRuntimeOperationKind.TRADE_FILL,
            account_type=OnlyAccountType.MARGIN,
            order_type=context.order_before.order_type,
            order_side=context.order_before.side,
            offset=context.order_before.offset,
            position_side=context.position_scope.position_side,
            position_effect=context.position_scope.position_effect,
            position_mode=context.position_scope.position_mode,
            has_margin=True,
            account_ledger_parity=True,
            reservations=OnlyExecutionReservationShape(False, False, True, True, True),
        )
    )
    assert support.capability is OnlyExecutionCapability.DURABLE_TRADE
    return replace(
        context,
        trade_instruction=instruction,
        support_decision=support,
        account_before=account,
        strategy_ledger_before=ledger,
        valuation_before=replace(
            context.valuation_before,
            cash=account.ledger_cash,
            position_market_value=zero,
            unrealized_pnl=zero,
            equity=account.ledger_cash,
        ),
        margin_reservation_before=margin,
    )


def _short_margin_close_context():
    context = _margin_close_context(fill_price="8.00")
    assert context.position_before is not None
    assert context.allocation_before is not None
    assert context.position_reservation_before is not None
    assert context.margin_reservation_before is not None
    assert context.position_scope.allocation_key is not None
    assert context.trade_instruction.margin_instruction is not None
    short_scope = replace(
        context.position_scope,
        position_side=OnlyPositionSide.SHORT,
        position_key=replace(context.position_scope.position_key, position_side=OnlyPositionSide.SHORT),
        allocation_key=replace(context.position_scope.allocation_key, position_side=OnlyPositionSide.SHORT),
    )
    order = replace(
        context.order_before,
        side=OnlyOrderSide.BUY,
        execution_intent=OnlyExecutionIntent(
            OnlyOrderSide.BUY,
            OnlyPositionSide.SHORT,
            OnlyPositionEffect.CLOSE,
        ),
    )
    instruction = replace(
        context.trade_instruction,
        position_instruction=replace(
            context.trade_instruction.position_instruction,
            position_side=OnlyPositionSide.SHORT.value,
        ),
        margin_instruction=replace(
            context.trade_instruction.margin_instruction,
            position_side=OnlyPositionSide.SHORT.value,
        ),
    )
    support = OnlyExecutionCapabilityResolver().resolve(
        OnlyExecutionSupportContext(
            operation_kind=OnlyRuntimeOperationKind.TRADE_FILL,
            account_type=OnlyAccountType.MARGIN,
            order_type=order.order_type,
            order_side=order.side,
            offset=order.offset,
            position_side=OnlyPositionSide.SHORT,
            position_effect=OnlyPositionEffect.CLOSE,
            position_mode=short_scope.position_mode,
            has_margin=True,
            account_ledger_parity=True,
            reservations=OnlyExecutionReservationShape(False, False, True, True, True),
        )
    )
    assert support.capability is OnlyExecutionCapability.DURABLE_TRADE
    return replace(
        context,
        order_before=order,
        position_scope=short_scope,
        position_before=replace(
            context.position_before,
            key=replace(context.position_before.key, position_side=OnlyPositionSide.SHORT),
        ),
        allocation_before=replace(
            context.allocation_before,
            key=replace(context.allocation_before.key, position_side=OnlyPositionSide.SHORT),
        ),
        position_reservation_before=replace(
            context.position_reservation_before,
            position_side=OnlyPositionSide.SHORT,
        ),
        margin_reservation_before=replace(
            context.margin_reservation_before,
            position_side=OnlyPositionSide.SHORT,
        ),
        trade_instruction=instruction,
        support_decision=support,
    )


def test_margin_open_uses_one_durable_trade_path_without_notional_cash_exchange() -> None:
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(_margin_context())
    fact = prepared.fact_draft
    components = tuple(item.identity.component for item in prepared.projections)

    assert OnlyRuntimeProjectionComponent.MARGIN_RESERVATION in components
    assert OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION not in components
    assert OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION not in components
    assert fact.settled_notional.amount == 0
    assert fact.account_cash_delta.amount == -fact.incremental_fee_charges.amount
    assert fact.reserved_margin_delta.amount == Decimal("-100")
    assert fact.occupied_margin_delta.amount == Decimal("100")
    assert fact.maintenance_margin_after.amount == Decimal("50")


def test_margin_open_planner_is_byte_deterministic() -> None:
    planner = OnlyTradeExecutionTransactionPlanner()
    assert planner.prepare(_margin_context()) == planner.prepare(_margin_context())


def test_margin_partial_close_releases_original_margin_and_realizes_pnl_without_notional_exchange() -> None:
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(_margin_close_context())
    fact = prepared.fact_draft
    margin_projection = next(
        item
        for item in prepared.projections
        if item.identity.component is OnlyRuntimeProjectionComponent.MARGIN_RESERVATION
    )

    assert fact.settled_notional.amount == 0
    assert fact.position_realized_pnl_delta.amount == Decimal("80.00")
    assert fact.occupied_margin_delta.amount == Decimal("-40")
    assert fact.released_margin_delta.amount == Decimal("40")
    assert fact.maintenance_margin_after.amount == Decimal("30")
    assert margin_projection.after.occupied_amount.amount == Decimal("60")
    assert margin_projection.after.maintenance_amount.amount == Decimal("30")
    assert (
        fact.account_cash_delta.amount == fact.position_realized_pnl_delta.amount - fact.incremental_fee_charges.amount
    )


def test_margin_full_close_releases_all_original_margin() -> None:
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(_margin_close_context(fill_quantity="100"))
    margin_projection = next(
        item
        for item in prepared.projections
        if item.identity.component is OnlyRuntimeProjectionComponent.MARGIN_RESERVATION
    )

    assert prepared.fact_draft.occupied_margin_delta.amount == Decimal("-100")
    assert prepared.fact_draft.released_margin_delta.amount == Decimal("100")
    assert margin_projection.after.state is OnlyMarginReservationExecutionStatus.RELEASED


def test_margin_close_releases_multiple_opening_order_authorities_proportionally() -> None:
    context = _margin_close_context()
    assert context.margin_reservation_before is not None
    currency = context.margin_reservation_before.currency
    zero = OnlyMoney(Decimal(0), currency)
    first = replace(
        context.margin_reservation_before,
        reservation_id="margin-open-1",
        order_id=OnlyOrderId("open-1"),
        original_reserved_amount=OnlyMoney(Decimal("40"), currency),
        occupied_amount=OnlyMoney(Decimal("40"), currency),
        maintenance_amount=OnlyMoney(Decimal("20"), currency),
        remaining_reserved_amount=zero,
    )
    second = replace(
        context.margin_reservation_before,
        reservation_id="margin-open-2",
        order_id=OnlyOrderId("open-2"),
        original_reserved_amount=OnlyMoney(Decimal("60"), currency),
        occupied_amount=OnlyMoney(Decimal("60"), currency),
        maintenance_amount=OnlyMoney(Decimal("30"), currency),
        remaining_reserved_amount=zero,
    )
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(
        replace(
            context,
            margin_reservation_before=first,
            margin_reservations_before=(first, second),
        )
    )
    margin_projections = tuple(
        item
        for item in prepared.projections
        if item.identity.component is OnlyRuntimeProjectionComponent.MARGIN_RESERVATION
    )

    assert len(margin_projections) == 2
    assert tuple(item.after.occupied_amount.amount for item in margin_projections) == (
        Decimal("24"),
        Decimal("36"),
    )
    assert prepared.fact_draft.occupied_margin_delta.amount == Decimal("-40")
    assert prepared.fact_draft.released_margin_delta.amount == Decimal("40")
    assert prepared.fact_draft.maintenance_margin_after.amount == Decimal("30")
    assert tuple(item.identity.projection_sequence for item in prepared.projections) == tuple(
        range(1, len(prepared.projections) + 1)
    )


def test_short_margin_close_uses_short_realized_pnl_sign() -> None:
    prepared = OnlyTradeExecutionTransactionPlanner().prepare(_short_margin_close_context())

    assert prepared.fact_draft.position_side is OnlyPositionSide.SHORT
    assert prepared.fact_draft.position_realized_pnl_delta.amount == Decimal("80.00")
