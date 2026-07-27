"""Pure reservation-presence rules for prepared execution transactions."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide
from onlyalpha.market.models import OnlyPositionEffect


@dataclass(frozen=True, slots=True)
class OnlyExecutionReservationPresence:
    require_account_cash: bool
    require_strategy_cash: bool
    require_position: bool
    require_margin: bool
    require_risk: bool


def only_expected_execution_reservations(
    *,
    market_profile_id: str,
    side: OnlyOrderSide,
    offset: OnlyOffset,
    position_effect: OnlyPositionEffect,
    margin_instruction_present: bool,
) -> OnlyExecutionReservationPresence:
    """Return the exact reservation set required by an execution fact."""

    if not market_profile_id.strip():
        raise ValueError("reservation presence requires a Market Profile identity")
    opening = position_effect is OnlyPositionEffect.OPEN
    closing = position_effect in {
        OnlyPositionEffect.CLOSE,
        OnlyPositionEffect.CLOSE_TODAY,
        OnlyPositionEffect.CLOSE_YESTERDAY,
        OnlyPositionEffect.REDUCE_ONLY,
    }
    if opening != (offset in {OnlyOffset.NONE, OnlyOffset.OPEN}):
        raise ValueError("execution offset and Position Effect disagree")
    if closing != (offset not in {OnlyOffset.NONE, OnlyOffset.OPEN}):
        raise ValueError("execution offset and Position Effect disagree")
    cash_open = opening and side is OnlyOrderSide.BUY and not margin_instruction_present
    return OnlyExecutionReservationPresence(
        require_account_cash=cash_open,
        require_strategy_cash=cash_open,
        require_position=closing,
        require_margin=margin_instruction_present,
        require_risk=True,
    )


__all__ = ["OnlyExecutionReservationPresence", "only_expected_execution_reservations"]
