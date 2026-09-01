"""Pure durable Margin reservation reducer for one opening Fill."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_HALF_EVEN, Decimal

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.market.runtime_rules import OnlyMarginInstruction
from onlyalpha.transaction.projection import (
    OnlyMarginReservationExecutionProjection,
    OnlyRuntimeProjectionComponent,
)
from onlyalpha.transaction.projection_builder import OnlyRuntimeProjectionBuilder

from ..execution_state import (
    OnlyMarginReservationExecutionStage,
    OnlyMarginReservationExecutionState,
    OnlyMarginReservationExecutionStatus,
)


@dataclass(frozen=True, slots=True)
class OnlyMarginReservationTradeReduction:
    instruction_id: str
    after: OnlyMarginReservationExecutionState
    projection: OnlyMarginReservationExecutionProjection
    reserved_delta: OnlyMoney
    occupied_delta: OnlyMoney
    released_delta: OnlyMoney


class OnlyMarginReservationTradeReducer:
    def reduce_open(
        self,
        before: OnlyMarginReservationExecutionState,
        instruction: OnlyMarginInstruction,
        *,
        terminal_fill: bool,
        projection_sequence: int,
    ) -> OnlyMarginReservationTradeReduction:
        instruction = _normalize_instruction(instruction, before.currency.precision)
        if instruction.action != "OCCUPY":
            raise ValueError("MARGIN_OPEN_REQUIRES_OCCUPY")
        if (
            str(before.account_id) != instruction.account_id
            or str(before.instrument_id) != instruction.instrument_id
            or str(before.order_id) != instruction.source_order_id
            or before.currency.code != instruction.currency
            or before.margin_mode.value != instruction.margin_mode
            or before.isolation_key != instruction.isolation_key
            or before.position_side.value != instruction.position_side
        ):
            raise ValueError("MARGIN_RESERVATION_SCOPE_CONFLICT")
        if instruction.amount <= 0 or instruction.maintenance_required < 0:
            raise ValueError("MARGIN_OCCUPATION_AMOUNT_INVALID")
        if instruction.amount > before.remaining_reserved_amount.amount:
            raise ValueError("MARGIN_RESERVATION_INSUFFICIENT")

        unused_release = before.remaining_reserved_amount.amount - instruction.amount if terminal_fill else Decimal(0)
        remaining = before.remaining_reserved_amount.amount - instruction.amount - unused_release
        occupied = before.occupied_amount.amount + instruction.amount
        released = before.released_amount.amount + unused_release
        maintenance = before.maintenance_amount.amount + instruction.maintenance_required
        after = replace(
            before,
            remaining_reserved_amount=OnlyMoney(remaining, before.currency),
            occupied_amount=OnlyMoney(occupied, before.currency),
            released_amount=OnlyMoney(released, before.currency),
            maintenance_amount=OnlyMoney(maintenance, before.currency),
            state=(
                OnlyMarginReservationExecutionStatus.OCCUPIED
                if remaining == 0
                else OnlyMarginReservationExecutionStatus.ACTIVE
            ),
            stage=(
                OnlyMarginReservationExecutionStage.OCCUPIED
                if remaining == 0
                else OnlyMarginReservationExecutionStage.RESERVED
            ),
            updated_at=instruction.timestamp,
            version=before.version + 1,
        )
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlyMarginReservationExecutionProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.MARGIN_RESERVATION,
                entity_key=before.reservation_id,
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyMarginReservationExecutionProjection)
        instruction_id = "MARGIN-" + only_canonical_fingerprint(instruction)
        return OnlyMarginReservationTradeReduction(
            instruction_id,
            after,
            projection,
            OnlyMoney(-instruction.amount - unused_release, before.currency),
            OnlyMoney(instruction.amount, before.currency),
            OnlyMoney(unused_release, before.currency),
        )

    def reduce_close(
        self,
        before: OnlyMarginReservationExecutionState,
        instruction: OnlyMarginInstruction,
        *,
        fill_quantity: Decimal,
        position_quantity_before: Decimal,
        projection_sequence: int,
    ) -> OnlyMarginReservationTradeReduction:
        instruction = _normalize_instruction(instruction, before.currency.precision)
        if instruction.action != "RELEASE":
            raise ValueError("MARGIN_CLOSE_REQUIRES_RELEASE")
        if (
            str(before.account_id) != instruction.account_id
            or str(before.instrument_id) != instruction.instrument_id
            or before.currency.code != instruction.currency
            or before.margin_mode.value != instruction.margin_mode
            or before.isolation_key != instruction.isolation_key
            or before.position_side.value != instruction.position_side
        ):
            raise ValueError("MARGIN_RESERVATION_SCOPE_CONFLICT")
        if not 0 < fill_quantity <= position_quantity_before or before.occupied_amount.amount <= 0:
            raise ValueError("MARGIN_RELEASE_QUANTITY_INVALID")
        ratio = fill_quantity / position_quantity_before
        quantum = Decimal(1).scaleb(-before.currency.precision)
        occupied_release = (
            before.occupied_amount.amount
            if fill_quantity == position_quantity_before
            else (before.occupied_amount.amount * ratio).quantize(quantum, rounding=ROUND_HALF_EVEN)
        )
        maintenance_release = (
            before.maintenance_amount.amount
            if fill_quantity == position_quantity_before
            else (before.maintenance_amount.amount * ratio).quantize(quantum, rounding=ROUND_HALF_EVEN)
        )
        occupied = before.occupied_amount.amount - occupied_release
        maintenance = before.maintenance_amount.amount - maintenance_release
        released = before.released_amount.amount + occupied_release
        remaining = before.remaining_reserved_amount.amount
        terminal = remaining == 0 and occupied == 0
        after = replace(
            before,
            occupied_amount=OnlyMoney(occupied, before.currency),
            released_amount=OnlyMoney(released, before.currency),
            maintenance_amount=OnlyMoney(maintenance, before.currency),
            state=(
                OnlyMarginReservationExecutionStatus.RELEASED
                if terminal
                else OnlyMarginReservationExecutionStatus.OCCUPIED
            ),
            stage=(
                OnlyMarginReservationExecutionStage.RELEASED
                if terminal
                else OnlyMarginReservationExecutionStage.OCCUPIED
            ),
            updated_at=instruction.timestamp,
            version=before.version + 1,
        )
        builder = OnlyRuntimeProjectionBuilder()
        projection = OnlyMarginReservationExecutionProjection(
            builder.identity(
                component=OnlyRuntimeProjectionComponent.MARGIN_RESERVATION,
                entity_key=before.reservation_id,
                before=before,
                after=after,
                projection_sequence=projection_sequence,
            ),
            before,
            after,
        )
        projection = builder.finalize(projection)
        assert isinstance(projection, OnlyMarginReservationExecutionProjection)
        return OnlyMarginReservationTradeReduction(
            "MARGIN-" + only_canonical_fingerprint(instruction),
            after,
            projection,
            OnlyMoney(Decimal(0), before.currency),
            OnlyMoney(-occupied_release, before.currency),
            OnlyMoney(occupied_release, before.currency),
        )


def _normalize_instruction(instruction: OnlyMarginInstruction, precision: int) -> OnlyMarginInstruction:
    quantum = Decimal(1).scaleb(-precision)
    return replace(
        instruction,
        amount=instruction.amount.quantize(quantum, rounding=ROUND_HALF_EVEN),
        maintenance_required=instruction.maintenance_required.quantize(quantum, rounding=ROUND_HALF_EVEN),
    )


__all__ = [name for name in globals() if name.startswith("Only")]
