"""Canonical market-neutral execution semantics.

Legacy order offsets remain an ingress compatibility spelling.  Every new
execution path must normalize them into :class:`OnlyExecutionIntent` before
making economic decisions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide


class OnlyPositionSide(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class OnlyPositionMode(StrEnum):
    NETTING = "NETTING"
    HEDGING = "HEDGING"


class OnlyPositionEffect(StrEnum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    AUTO = "AUTO"

    # Compatibility-only serialized spellings.  Canonical execution intents
    # normalize these into CLOSE + CloseScope or ExposureConstraint.
    CLOSE_TODAY = "CLOSE_TODAY"
    CLOSE_YESTERDAY = "CLOSE_YESTERDAY"
    REDUCE_ONLY = "REDUCE_ONLY"


class OnlyCloseScope(StrEnum):
    ANY = "ANY"
    TODAY = "TODAY"
    YESTERDAY = "YESTERDAY"


class OnlyExposureConstraint(StrEnum):
    NONE = "NONE"
    REDUCE_ONLY = "REDUCE_ONLY"


class OnlyTargetExposure(StrEnum):
    LONG = "LONG"
    FLAT = "FLAT"
    SHORT = "SHORT"


class OnlyReferencePriceKind(StrEnum):
    TRADE = "TRADE"
    MARK = "MARK"
    INDEX = "INDEX"
    SETTLEMENT = "SETTLEMENT"


@dataclass(frozen=True, slots=True)
class OnlyExecutionIntent(OnlyDomainModel):
    """One authoritative, orthogonal execution-facing economic intent."""

    schema_version = 2

    side: OnlyOrderSide
    position_side: OnlyPositionSide
    position_effect: OnlyPositionEffect
    close_scope: OnlyCloseScope = OnlyCloseScope.ANY
    exposure_constraint: OnlyExposureConstraint = OnlyExposureConstraint.NONE
    position_mode: OnlyPositionMode = OnlyPositionMode.NETTING

    def __post_init__(self) -> None:
        if self.position_side is OnlyPositionSide.FLAT:
            raise ValueError("EXECUTION_INTENT_POSITION_SIDE_REQUIRED")
        if self.position_effect not in {OnlyPositionEffect.OPEN, OnlyPositionEffect.CLOSE}:
            raise ValueError("EXECUTION_INTENT_EFFECT_NOT_NORMALIZED")
        expected = _expected_side(self.position_side, self.position_effect)
        if self.side is not expected:
            raise ValueError("EXECUTION_INTENT_SIDE_EFFECT_CONFLICT")
        if self.position_effect is OnlyPositionEffect.OPEN:
            if self.close_scope is not OnlyCloseScope.ANY:
                raise ValueError("EXECUTION_INTENT_OPEN_CLOSE_SCOPE_CONFLICT")
            if self.exposure_constraint is OnlyExposureConstraint.REDUCE_ONLY:
                raise ValueError("EXECUTION_INTENT_REDUCE_ONLY_OPEN_CONFLICT")

    @classmethod
    def from_offset(
        cls,
        *,
        side: OnlyOrderSide,
        offset: OnlyOffset,
        position_side: OnlyPositionSide | None = None,
    ) -> OnlyExecutionIntent:
        """Normalize the canonical Offset surface without granting it authority."""

        if offset is OnlyOffset.NONE:
            # Historical Spot semantics: BUY opens long and SELL closes long.
            effect = OnlyPositionEffect.OPEN if side is OnlyOrderSide.BUY else OnlyPositionEffect.CLOSE
            resolved_side = position_side or OnlyPositionSide.LONG
            return cls(side, resolved_side, effect)
        if offset is OnlyOffset.OPEN:
            resolved_side = position_side or (
                OnlyPositionSide.LONG if side is OnlyOrderSide.BUY else OnlyPositionSide.SHORT
            )
            return cls(side, resolved_side, OnlyPositionEffect.OPEN)
        resolved_side = position_side or (
            OnlyPositionSide.LONG if side is OnlyOrderSide.SELL else OnlyPositionSide.SHORT
        )
        close_scope = {
            OnlyOffset.CLOSE: OnlyCloseScope.ANY,
            OnlyOffset.CLOSE_TODAY: OnlyCloseScope.TODAY,
            OnlyOffset.CLOSE_YESTERDAY: OnlyCloseScope.YESTERDAY,
        }[offset]
        return cls(side, resolved_side, OnlyPositionEffect.CLOSE, close_scope)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyExecutionIntent:
        compatible = dict(payload)
        if compatible.get("schema_version") == 1:
            compatible["position_mode"] = OnlyPositionMode.NETTING.value
            compatible["schema_version"] = cls.schema_version
        return super(OnlyExecutionIntent, cls).from_dict(compatible)

    @property
    def reduces_exposure(self) -> bool:
        return self.position_effect is OnlyPositionEffect.CLOSE


def _expected_side(position_side: OnlyPositionSide, effect: OnlyPositionEffect) -> OnlyOrderSide:
    if position_side is OnlyPositionSide.LONG:
        return OnlyOrderSide.BUY if effect is OnlyPositionEffect.OPEN else OnlyOrderSide.SELL
    return OnlyOrderSide.SELL if effect is OnlyPositionEffect.OPEN else OnlyOrderSide.BUY


__all__ = [
    "OnlyCloseScope",
    "OnlyExecutionIntent",
    "OnlyExposureConstraint",
    "OnlyPositionEffect",
    "OnlyPositionMode",
    "OnlyPositionSide",
    "OnlyReferencePriceKind",
    "OnlyTargetExposure",
]
