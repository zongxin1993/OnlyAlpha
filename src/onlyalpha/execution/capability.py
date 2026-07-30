"""Single pure capability matrix for execution transaction routing."""

from __future__ import annotations

from enum import StrEnum

from onlyalpha.account.enums import OnlyAccountType
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide

from .enums import OnlyExecutionOperationKind


class OnlyExecutionCapability(StrEnum):
    DURABLE_TRADE = "DURABLE_TRADE"
    DURABLE_TERMINAL = "DURABLE_TERMINAL"
    LEGACY_UNMIGRATED = "LEGACY_UNMIGRATED"
    UNSUPPORTED = "UNSUPPORTED"


def only_resolve_execution_capability(
    *,
    operation_kind: OnlyExecutionOperationKind,
    market_profile_id: str,
    account_type: OnlyAccountType,
    order_type: OnlyOrderType,
    order_side: OnlyOrderSide,
    offset: OnlyOffset,
    position_side: OnlyPositionSide,
    position_effect: OnlyPositionEffect,
    position_mode: OnlyPositionMode,
    has_margin: bool,
) -> OnlyExecutionCapability:
    """Resolve one explicit support outcome without inspecting mutable Managers."""

    generic_cash = market_profile_id == "GENERIC_T0_CASH" and account_type is OnlyAccountType.CASH
    long_netting_limit = (
        order_type is OnlyOrderType.LIMIT
        and position_side is OnlyPositionSide.LONG
        and position_mode is OnlyPositionMode.NETTING
        and not has_margin
    )
    buy_open = (
        order_side is OnlyOrderSide.BUY and offset is OnlyOffset.OPEN and position_effect is OnlyPositionEffect.OPEN
    )
    sell_close = (
        order_side is OnlyOrderSide.SELL and offset is OnlyOffset.CLOSE and position_effect is OnlyPositionEffect.CLOSE
    )

    if generic_cash:
        if operation_kind is OnlyExecutionOperationKind.TRADE_FILL and long_netting_limit and (buy_open or sell_close):
            return OnlyExecutionCapability.DURABLE_TRADE
        if operation_kind is OnlyExecutionOperationKind.ORDER_TERMINAL and long_netting_limit and sell_close:
            return OnlyExecutionCapability.DURABLE_TERMINAL
        return OnlyExecutionCapability.UNSUPPORTED

    if has_margin or account_type is not OnlyAccountType.CASH:
        return OnlyExecutionCapability.LEGACY_UNMIGRATED
    if position_side is OnlyPositionSide.SHORT or position_mode is OnlyPositionMode.HEDGING:
        return OnlyExecutionCapability.LEGACY_UNMIGRATED
    return OnlyExecutionCapability.UNSUPPORTED


__all__ = ["OnlyExecutionCapability", "only_resolve_execution_capability"]
