"""The single, immutable Position scope used by Execution processing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.market.models import OnlyPositionEffect
from onlyalpha.market.runtime_rules import OnlyTradeApplicationInstruction
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide
from onlyalpha.position.keys import OnlyPositionAllocationKey, OnlyPositionKey


class OnlyPositionScopeResolutionSource(StrEnum):
    MARKET_RULE_INSTRUCTION = "MARKET_RULE_INSTRUCTION"
    EXPLICIT_ORDER_OFFSET = "EXPLICIT_ORDER_OFFSET"
    NORMALIZED_CASH_ORDER = "NORMALIZED_CASH_ORDER"
    BROKER_POSITION_SNAPSHOT = "BROKER_POSITION_SNAPSHOT"


@dataclass(frozen=True, slots=True)
class OnlyExecutionPositionScope(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId | None
    instrument_id: OnlyInstrumentId
    position_side: OnlyPositionSide
    position_effect: OnlyPositionEffect
    position_mode: OnlyPositionMode
    position_key: OnlyPositionKey
    allocation_key: OnlyPositionAllocationKey | None
    resolution_source: OnlyPositionScopeResolutionSource

    def __post_init__(self) -> None:
        if self.position_key.position_side is not self.position_side:
            raise ValueError("Position Scope side conflicts with Position Key")
        if self.allocation_key is not None and self.allocation_key.position_side is not self.position_side:
            raise ValueError("Position Scope side conflicts with Allocation Key")


class OnlyExecutionPositionScopeResolver:
    """Resolves an Order/market instruction once; consumers must reuse the result."""

    def __init__(self, runtime_id: OnlyRuntimeId) -> None:
        self._runtime_id = runtime_id

    def resolve_order(self, order: OnlyOrderSnapshot) -> OnlyExecutionPositionScope:
        if order.offset is OnlyOffset.NONE:
            # Orders reaching this compatibility boundary are already normalized cash orders.
            effect = OnlyPositionEffect.OPEN if order.side is OnlyOrderSide.BUY else OnlyPositionEffect.CLOSE
            source = OnlyPositionScopeResolutionSource.NORMALIZED_CASH_ORDER
        else:
            effect = OnlyPositionEffect(order.offset.value)
            source = OnlyPositionScopeResolutionSource.EXPLICIT_ORDER_OFFSET
        side = self._side(order.side, effect)
        return self._build(order, side, effect, OnlyPositionMode.NETTING, source)

    def resolve_trade(
        self,
        order: OnlyOrderSnapshot,
        instruction: OnlyTradeApplicationInstruction | None,
        position_mode: OnlyPositionMode,
    ) -> OnlyExecutionPositionScope:
        fallback = self.resolve_order(order)
        if instruction is None:
            return self._build(
                order, fallback.position_side, fallback.position_effect, position_mode, fallback.resolution_source
            )
        side = OnlyPositionSide(instruction.position_instruction.position_side)
        effect = instruction.position_instruction.position_effect
        if fallback.position_side is not side or fallback.position_effect is not effect:
            raise ValueError("POSITION_SCOPE_CONFLICT: market instruction conflicts with Order scope")
        return self._build(
            order, side, effect, position_mode, OnlyPositionScopeResolutionSource.MARKET_RULE_INSTRUCTION
        )

    def resolve_broker_position(
        self, account_id: OnlyAccountId, instrument_id: OnlyInstrumentId, position_side: OnlyPositionSide
    ) -> OnlyExecutionPositionScope:
        key = OnlyPositionKey(self._runtime_id, account_id, instrument_id, position_side)
        return OnlyExecutionPositionScope(
            self._runtime_id,
            account_id,
            None,
            instrument_id,
            position_side,
            OnlyPositionEffect.AUTO,
            OnlyPositionMode.NETTING,
            key,
            None,
            OnlyPositionScopeResolutionSource.BROKER_POSITION_SNAPSHOT,
        )

    def _build(
        self,
        order: OnlyOrderSnapshot,
        side: OnlyPositionSide,
        effect: OnlyPositionEffect,
        mode: OnlyPositionMode,
        source: OnlyPositionScopeResolutionSource,
    ) -> OnlyExecutionPositionScope:
        key = OnlyPositionKey(self._runtime_id, order.account_id, order.instrument_id, side, mode)
        allocation = OnlyPositionAllocationKey(
            self._runtime_id, order.account_id, order.cluster_id, order.instrument_id, side
        )
        return OnlyExecutionPositionScope(
            self._runtime_id,
            order.account_id,
            order.cluster_id,
            order.instrument_id,
            side,
            effect,
            mode,
            key,
            allocation,
            source,
        )

    @staticmethod
    def _side(side: OnlyOrderSide, effect: OnlyPositionEffect) -> OnlyPositionSide:
        if effect is OnlyPositionEffect.OPEN:
            return OnlyPositionSide.LONG if side is OnlyOrderSide.BUY else OnlyPositionSide.SHORT
        if effect in {
            OnlyPositionEffect.CLOSE,
            OnlyPositionEffect.CLOSE_TODAY,
            OnlyPositionEffect.CLOSE_YESTERDAY,
        }:
            return OnlyPositionSide.SHORT if side is OnlyOrderSide.BUY else OnlyPositionSide.LONG
        raise ValueError("POSITION_SIDE_RESOLUTION_FAILED: position effect is ambiguous")
