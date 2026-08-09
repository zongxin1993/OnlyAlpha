"""Pure market-neutral admission authority for durable execution operations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum

from onlyalpha.account.enums import OnlyAccountType
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind

ONLY_EXECUTION_SUPPORT_POLICY_VERSION = "1"


class OnlyExecutionCapability(StrEnum):
    DURABLE_TRADE = "DURABLE_TRADE"
    DURABLE_TERMINAL = "DURABLE_TERMINAL"
    UNSUPPORTED = "UNSUPPORTED"


class OnlyExecutionSupportReason(StrEnum):
    OPERATION_KIND_UNSUPPORTED = "OPERATION_KIND_UNSUPPORTED"
    ACCOUNT_TYPE_UNSUPPORTED = "ACCOUNT_TYPE_UNSUPPORTED"
    ORDER_TYPE_UNSUPPORTED = "ORDER_TYPE_UNSUPPORTED"
    ORDER_SEMANTICS_UNSUPPORTED = "ORDER_SEMANTICS_UNSUPPORTED"
    POSITION_SIDE_UNSUPPORTED = "POSITION_SIDE_UNSUPPORTED"
    POSITION_MODE_UNSUPPORTED = "POSITION_MODE_UNSUPPORTED"
    POSITION_EFFECT_UNSUPPORTED = "POSITION_EFFECT_UNSUPPORTED"
    MARGIN_UNSUPPORTED = "MARGIN_UNSUPPORTED"
    ACCOUNT_LEDGER_PARITY_REQUIRED = "ACCOUNT_LEDGER_PARITY_REQUIRED"
    RESERVATION_SHAPE_UNSUPPORTED = "RESERVATION_SHAPE_UNSUPPORTED"
    TERMINAL_SHAPE_UNSUPPORTED = "TERMINAL_SHAPE_UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class OnlyExecutionReservationShape:
    """Presence of immutable Reservation authorities captured for one operation."""

    account_cash: bool
    strategy_cash: bool
    position: bool
    margin: bool
    risk: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class OnlyExecutionSupportContext:
    """Economic shape that can affect durable-kernel implementation support."""

    operation_kind: OnlyRuntimeOperationKind
    account_type: OnlyAccountType
    order_type: OnlyOrderType
    order_side: OnlyOrderSide
    offset: OnlyOffset
    position_side: OnlyPositionSide
    position_effect: OnlyPositionEffect
    position_mode: OnlyPositionMode
    has_margin: bool
    account_ledger_parity: bool
    reservations: OnlyExecutionReservationShape


@dataclass(frozen=True, slots=True)
class OnlyExecutionSupportDecision:
    """Versioned deterministic proof of one support admission outcome."""

    capability: OnlyExecutionCapability
    reason: OnlyExecutionSupportReason | None
    schema_version: str
    fingerprint: str

    def __post_init__(self) -> None:
        supported = self.capability is not OnlyExecutionCapability.UNSUPPORTED
        if supported != (self.reason is None):
            raise ValueError("supported execution decisions require no reason; unsupported decisions require one")
        if self.schema_version != ONLY_EXECUTION_SUPPORT_POLICY_VERSION:
            raise ValueError("execution support decision policy version is unsupported")
        if len(self.fingerprint) != 64:
            raise ValueError("execution support decision requires a SHA-256 fingerprint")


class OnlyExecutionCapabilityResolver:
    """Stateless deterministic implementation-support authority."""

    def resolve(self, context: OnlyExecutionSupportContext) -> OnlyExecutionSupportDecision:
        capability, reason = self._resolve(context)
        payload = {
            "schema_version": ONLY_EXECUTION_SUPPORT_POLICY_VERSION,
            "context": _canonical_context(context),
            "capability": capability.value,
            "reason": None if reason is None else reason.value,
        }
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return OnlyExecutionSupportDecision(
            capability,
            reason,
            ONLY_EXECUTION_SUPPORT_POLICY_VERSION,
            fingerprint,
        )

    @staticmethod
    def _resolve(
        context: OnlyExecutionSupportContext,
    ) -> tuple[OnlyExecutionCapability, OnlyExecutionSupportReason | None]:
        if context.operation_kind not in {
            OnlyRuntimeOperationKind.TRADE_FILL,
            OnlyRuntimeOperationKind.ORDER_TERMINAL,
        }:
            return _unsupported(OnlyExecutionSupportReason.OPERATION_KIND_UNSUPPORTED)
        if context.account_type is not OnlyAccountType.CASH:
            return _unsupported(OnlyExecutionSupportReason.ACCOUNT_TYPE_UNSUPPORTED)
        if context.order_type is not OnlyOrderType.LIMIT:
            return _unsupported(OnlyExecutionSupportReason.ORDER_TYPE_UNSUPPORTED)
        if context.position_side is not OnlyPositionSide.LONG:
            return _unsupported(OnlyExecutionSupportReason.POSITION_SIDE_UNSUPPORTED)
        if context.position_mode is not OnlyPositionMode.NETTING:
            return _unsupported(OnlyExecutionSupportReason.POSITION_MODE_UNSUPPORTED)
        if context.has_margin or context.reservations.margin:
            return _unsupported(OnlyExecutionSupportReason.MARGIN_UNSUPPORTED)
        if not context.account_ledger_parity:
            return _unsupported(OnlyExecutionSupportReason.ACCOUNT_LEDGER_PARITY_REQUIRED)

        buy_open = (
            context.order_side is OnlyOrderSide.BUY
            and context.offset is OnlyOffset.OPEN
            and context.position_effect is OnlyPositionEffect.OPEN
        )
        sell_close = (
            context.order_side is OnlyOrderSide.SELL
            and context.offset is OnlyOffset.CLOSE
            and context.position_effect is OnlyPositionEffect.CLOSE
        )
        if context.position_effect not in {OnlyPositionEffect.OPEN, OnlyPositionEffect.CLOSE}:
            return _unsupported(OnlyExecutionSupportReason.POSITION_EFFECT_UNSUPPORTED)
        if not buy_open and not sell_close:
            return _unsupported(OnlyExecutionSupportReason.ORDER_SEMANTICS_UNSUPPORTED)

        buy_open_reservations = OnlyExecutionReservationShape(True, True, False, False, True)
        sell_close_reservations = OnlyExecutionReservationShape(False, False, True, False, True)
        if context.operation_kind is OnlyRuntimeOperationKind.TRADE_FILL:
            expected = buy_open_reservations if buy_open else sell_close_reservations
            if context.reservations != expected:
                return _unsupported(OnlyExecutionSupportReason.RESERVATION_SHAPE_UNSUPPORTED)
            return OnlyExecutionCapability.DURABLE_TRADE, None

        if not sell_close:
            return _unsupported(OnlyExecutionSupportReason.TERMINAL_SHAPE_UNSUPPORTED)
        if context.reservations != sell_close_reservations:
            return _unsupported(OnlyExecutionSupportReason.RESERVATION_SHAPE_UNSUPPORTED)
        return OnlyExecutionCapability.DURABLE_TERMINAL, None


def _unsupported(
    reason: OnlyExecutionSupportReason,
) -> tuple[OnlyExecutionCapability, OnlyExecutionSupportReason]:
    return OnlyExecutionCapability.UNSUPPORTED, reason


def _canonical_context(context: OnlyExecutionSupportContext) -> dict[str, object]:
    payload = asdict(context)
    return {
        "operation_kind": context.operation_kind.value,
        "account_type": context.account_type.value,
        "order_type": context.order_type.value,
        "order_side": context.order_side.value,
        "offset": context.offset.value,
        "position_side": context.position_side.value,
        "position_effect": context.position_effect.value,
        "position_mode": context.position_mode.value,
        "has_margin": context.has_margin,
        "account_ledger_parity": context.account_ledger_parity,
        "reservations": payload["reservations"],
    }


__all__ = [
    "ONLY_EXECUTION_SUPPORT_POLICY_VERSION",
    "OnlyExecutionCapability",
    "OnlyExecutionCapabilityResolver",
    "OnlyExecutionReservationShape",
    "OnlyExecutionSupportContext",
    "OnlyExecutionSupportDecision",
    "OnlyExecutionSupportReason",
]
