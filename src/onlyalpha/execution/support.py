"""Pure projection of captured execution authority into support semantics."""

from __future__ import annotations

from onlyalpha.account.models import OnlyAccountSnapshot
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind

from .capability import OnlyExecutionReservationShape, OnlyExecutionSupportContext
from .scope import OnlyExecutionPositionScope


def only_execution_reservation_shape(
    *,
    account_cash_authority: object | None,
    strategy_cash_authority: object | None,
    position_authority: object | None,
    margin_authority: object | None,
    risk_authority: object | None,
) -> OnlyExecutionReservationShape:
    """Project presence from already captured immutable Reservation authorities."""

    return OnlyExecutionReservationShape(
        account_cash=account_cash_authority is not None,
        strategy_cash=strategy_cash_authority is not None,
        position=position_authority is not None,
        margin=margin_authority is not None,
        risk=risk_authority is not None,
    )


def only_execution_support_context(
    *,
    operation_kind: OnlyRuntimeOperationKind,
    account: OnlyAccountSnapshot,
    order: OnlyOrderSnapshot,
    position_scope: OnlyExecutionPositionScope,
    has_margin: bool,
    account_ledger_parity: bool,
    reservations: OnlyExecutionReservationShape,
) -> OnlyExecutionSupportContext:
    """Project one market-neutral context from immutable captured authority."""

    return OnlyExecutionSupportContext(
        operation_kind=operation_kind,
        account_type=account.account_type,
        order_type=order.order_type,
        order_side=order.side,
        offset=order.offset,
        position_side=position_scope.position_side,
        position_effect=position_scope.position_effect,
        position_mode=position_scope.position_mode,
        close_scope=position_scope.close_scope,
        exposure_constraint=position_scope.exposure_constraint,
        has_margin=has_margin,
        account_ledger_parity=account_ledger_parity,
        reservations=reservations,
    )


__all__ = ["only_execution_reservation_shape", "only_execution_support_context"]
