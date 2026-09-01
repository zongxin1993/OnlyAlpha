"""Pure market-neutral admission authority for durable execution operations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum

from onlyalpha.account.enums import OnlyAccountType
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderType
from onlyalpha.domain.trading import (
    OnlyCloseScope,
    OnlyExposureConstraint,
    OnlyPositionEffect,
    OnlyPositionMode,
    OnlyPositionSide,
)
from onlyalpha.transaction.enums import OnlyRuntimeOperationKind

ONLY_EXECUTION_SUPPORT_POLICY_VERSION = "3"
ONLY_READABLE_EXECUTION_SUPPORT_POLICY_VERSIONS = frozenset({"2", "3"})


def only_execution_support_policy_version_is_readable(version: str) -> bool:
    """Historical facts retain the immutable policy version that admitted them."""

    return version in ONLY_READABLE_EXECUTION_SUPPORT_POLICY_VERSIONS


class OnlyExecutionCapability(StrEnum):
    DURABLE_ORDER_ACCEPTED = "DURABLE_ORDER_ACCEPTED"
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
    close_scope: OnlyCloseScope = OnlyCloseScope.ANY
    exposure_constraint: OnlyExposureConstraint = OnlyExposureConstraint.NONE


@dataclass(frozen=True, slots=True)
class OnlyExecutionSupportDecision:
    """Versioned deterministic proof of one support admission outcome."""

    capability: OnlyExecutionCapability
    reason: OnlyExecutionSupportReason | None
    policy_version: str
    fingerprint: str

    def __post_init__(self) -> None:
        supported = self.capability is not OnlyExecutionCapability.UNSUPPORTED
        if supported != (self.reason is None):
            raise ValueError("supported execution decisions require no reason; unsupported decisions require one")
        if self.policy_version != ONLY_EXECUTION_SUPPORT_POLICY_VERSION:
            raise ValueError("execution support decision policy version is unsupported")
        if len(self.fingerprint) != 64:
            raise ValueError("execution support decision requires a SHA-256 fingerprint")


class OnlyExecutionCapabilityResolver:
    """Stateless deterministic implementation-support authority."""

    def resolve(self, context: OnlyExecutionSupportContext) -> OnlyExecutionSupportDecision:
        capability, reason = self._resolve(context)
        payload = {
            "policy_version": ONLY_EXECUTION_SUPPORT_POLICY_VERSION,
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
            OnlyRuntimeOperationKind.ORDER_ACCEPTED,
            OnlyRuntimeOperationKind.TRADE_FILL,
            OnlyRuntimeOperationKind.ORDER_TERMINAL,
        }:
            return _unsupported(OnlyExecutionSupportReason.OPERATION_KIND_UNSUPPORTED)
        if context.account_type not in {OnlyAccountType.CASH, OnlyAccountType.MARGIN}:
            return _unsupported(OnlyExecutionSupportReason.ACCOUNT_TYPE_UNSUPPORTED)
        if context.order_type is not OnlyOrderType.LIMIT:
            return _unsupported(OnlyExecutionSupportReason.ORDER_TYPE_UNSUPPORTED)
        if context.position_side not in {OnlyPositionSide.LONG, OnlyPositionSide.SHORT}:
            return _unsupported(OnlyExecutionSupportReason.POSITION_SIDE_UNSUPPORTED)
        if context.position_mode not in {OnlyPositionMode.NETTING, OnlyPositionMode.HEDGING}:
            return _unsupported(OnlyExecutionSupportReason.POSITION_MODE_UNSUPPORTED)
        if not context.account_ledger_parity:
            return _unsupported(OnlyExecutionSupportReason.ACCOUNT_LEDGER_PARITY_REQUIRED)
        if context.position_effect not in {OnlyPositionEffect.OPEN, OnlyPositionEffect.CLOSE}:
            return _unsupported(OnlyExecutionSupportReason.POSITION_EFFECT_UNSUPPORTED)
        if context.account_type is OnlyAccountType.CASH and context.has_margin:
            return _unsupported(OnlyExecutionSupportReason.MARGIN_UNSUPPORTED)
        if context.account_type is OnlyAccountType.CASH and context.position_side is OnlyPositionSide.SHORT:
            return _unsupported(OnlyExecutionSupportReason.POSITION_SIDE_UNSUPPORTED)
        if context.account_type is OnlyAccountType.CASH and context.position_mode is OnlyPositionMode.HEDGING:
            return _unsupported(OnlyExecutionSupportReason.POSITION_MODE_UNSUPPORTED)
        expected_side = (
            OnlyOrderSide.BUY
            if (context.position_side, context.position_effect)
            in {
                (OnlyPositionSide.LONG, OnlyPositionEffect.OPEN),
                (OnlyPositionSide.SHORT, OnlyPositionEffect.CLOSE),
            }
            else OnlyOrderSide.SELL
        )
        opening = context.position_effect is OnlyPositionEffect.OPEN
        offset_opening = context.offset in {OnlyOffset.NONE, OnlyOffset.OPEN}
        if context.order_side is not expected_side or opening != offset_opening:
            return _unsupported(OnlyExecutionSupportReason.ORDER_SEMANTICS_UNSUPPORTED)
        if opening and context.close_scope is not OnlyCloseScope.ANY:
            return _unsupported(OnlyExecutionSupportReason.ORDER_SEMANTICS_UNSUPPORTED)
        if opening and context.exposure_constraint is OnlyExposureConstraint.REDUCE_ONLY:
            return _unsupported(OnlyExecutionSupportReason.ORDER_SEMANTICS_UNSUPPORTED)

        if opening:
            expected = (
                OnlyExecutionReservationShape(False, False, False, True, True)
                if context.has_margin
                else OnlyExecutionReservationShape(True, True, False, False, True)
            )
        else:
            expected = OnlyExecutionReservationShape(False, False, True, context.has_margin, True)
        if context.reservations != expected:
            return _unsupported(OnlyExecutionSupportReason.RESERVATION_SHAPE_UNSUPPORTED)
        if context.operation_kind is OnlyRuntimeOperationKind.ORDER_ACCEPTED:
            return OnlyExecutionCapability.DURABLE_ORDER_ACCEPTED, None
        if context.operation_kind is OnlyRuntimeOperationKind.TRADE_FILL:
            return OnlyExecutionCapability.DURABLE_TRADE, None
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
        "close_scope": context.close_scope.value,
        "exposure_constraint": context.exposure_constraint.value,
        "has_margin": context.has_margin,
        "account_ledger_parity": context.account_ledger_parity,
        "reservations": payload["reservations"],
    }


__all__ = [
    "ONLY_EXECUTION_SUPPORT_POLICY_VERSION",
    "ONLY_READABLE_EXECUTION_SUPPORT_POLICY_VERSIONS",
    "OnlyExecutionCapability",
    "OnlyExecutionCapabilityResolver",
    "OnlyExecutionReservationShape",
    "OnlyExecutionSupportContext",
    "OnlyExecutionSupportDecision",
    "OnlyExecutionSupportReason",
    "only_execution_support_policy_version_is_readable",
]
