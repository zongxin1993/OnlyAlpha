"""Deterministic order-level partial-fill plan authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyOrderId, OnlyVenueOrderId
from onlyalpha.domain.value import OnlyQuantity


class OnlyVirtualFillScheduleMode(StrEnum):
    WHOLE = "WHOLE"
    MAX_PER_BAR = "MAX_PER_BAR"
    SCHEDULE = "SCHEDULE"


class OnlyVirtualFillDispatchMode(StrEnum):
    ONE_PER_BAR = "ONE_PER_BAR"
    ALL_DUE = "ALL_DUE"


class OnlyVirtualFillPlanStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class OnlyVirtualFillScheduleStepSpec(OnlyDomainModel):
    bar_offset: int
    quantity: Decimal | None = None
    ratio: Decimal | None = None

    def __post_init__(self) -> None:
        if self.bar_offset < 1:
            raise ValueError("VIRTUAL_FILL_STEP_BAR_OFFSET_INVALID")
        if (self.quantity is None) == (self.ratio is None):
            raise ValueError("VIRTUAL_FILL_STEP_VALUE_INVALID")
        if self.quantity is not None and self.quantity <= 0:
            raise ValueError("VIRTUAL_FILL_STEP_QUANTITY_INVALID")
        if self.ratio is not None and not Decimal(0) < self.ratio <= Decimal(1):
            raise ValueError("VIRTUAL_FILL_STEP_RATIO_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyVirtualFillPlanStep(OnlyDomainModel):
    step_index: int
    bar_offset: int
    quantity: OnlyQuantity

    def __post_init__(self) -> None:
        if self.step_index < 1 or self.bar_offset < 1 or self.quantity.value <= 0:
            raise ValueError("VIRTUAL_FILL_PLAN_STEP_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyVirtualOrderFillPlan(OnlyDomainModel):
    order_id: OnlyOrderId
    venue_order_id: OnlyVenueOrderId
    plan_id: str
    plan_fingerprint: str
    original_quantity: OnlyQuantity
    accepted_bar_sequence: int
    mode: OnlyVirtualFillScheduleMode
    dispatch_mode: OnlyVirtualFillDispatchMode
    steps: tuple[OnlyVirtualFillPlanStep, ...]
    next_step_index: int = 0
    status: OnlyVirtualFillPlanStatus = OnlyVirtualFillPlanStatus.ACTIVE
    version: int = 1

    def __post_init__(self) -> None:
        if not self.plan_id.startswith("VPLAN-") or len(self.plan_fingerprint) != 64:
            raise ValueError("VIRTUAL_FILL_PLAN_ID_INVALID")
        if self.original_quantity.value <= 0 or self.accepted_bar_sequence < 0 or not self.steps:
            raise ValueError("VIRTUAL_FILL_PLAN_INVALID")
        if not 0 <= self.next_step_index <= len(self.steps) or self.version < 1:
            raise ValueError("VIRTUAL_FILL_PLAN_CURSOR_INVALID")
        if tuple(step.step_index for step in self.steps) != tuple(range(1, len(self.steps) + 1)):
            raise ValueError("VIRTUAL_FILL_PLAN_STEP_INDEX_INVALID")
        offsets = tuple(step.bar_offset for step in self.steps)
        if offsets != tuple(sorted(offsets)):
            raise ValueError("VIRTUAL_FILL_PLAN_BAR_OFFSET_INVALID")
        if self.dispatch_mode is OnlyVirtualFillDispatchMode.ONE_PER_BAR and len(offsets) != len(set(offsets)):
            raise ValueError("VIRTUAL_FILL_ONE_PER_BAR_DUPLICATE_OFFSET")
        total = sum((step.quantity.value for step in self.steps), Decimal(0))
        if total != self.original_quantity.value:
            raise ValueError("VIRTUAL_FILL_PLAN_QUANTITY_MISMATCH")
        if self.status is OnlyVirtualFillPlanStatus.ACTIVE and self.next_step_index >= len(self.steps):
            raise ValueError("VIRTUAL_FILL_PLAN_ACTIVE_CURSOR_INVALID")
        if self.status is OnlyVirtualFillPlanStatus.COMPLETED and self.next_step_index != len(self.steps):
            raise ValueError("VIRTUAL_FILL_PLAN_COMPLETED_CURSOR_INVALID")
        if self.status in {
            OnlyVirtualFillPlanStatus.CANCELLED,
            OnlyVirtualFillPlanStatus.EXPIRED,
        } and self.next_step_index >= len(self.steps):
            raise ValueError("VIRTUAL_FILL_PLAN_TERMINAL_CURSOR_INVALID")

    @property
    def executed_quantity(self) -> OnlyQuantity:
        value = sum((step.quantity.value for step in self.steps[: self.next_step_index]), Decimal(0))
        return OnlyQuantity(value, self.original_quantity.precision)

    @property
    def remaining_quantity(self) -> OnlyQuantity:
        value = sum((step.quantity.value for step in self.steps[self.next_step_index :]), Decimal(0))
        return OnlyQuantity(value, self.original_quantity.precision)

    @property
    def next_step(self) -> OnlyVirtualFillPlanStep | None:
        if self.status is not OnlyVirtualFillPlanStatus.ACTIVE:
            return None
        return self.steps[self.next_step_index]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _quantity_text(quantity: OnlyQuantity) -> str:
    return format(quantity.value, f".{quantity.precision}f")


def _normalize_schedule_steps(
    original_quantity: OnlyQuantity,
    specs: tuple[OnlyVirtualFillScheduleStepSpec, ...],
    dispatch_mode: OnlyVirtualFillDispatchMode,
) -> tuple[OnlyVirtualFillPlanStep, ...]:
    if not specs:
        raise ValueError("VIRTUAL_FILL_SCHEDULE_EMPTY")
    offsets = tuple(spec.bar_offset for spec in specs)
    if offsets != tuple(sorted(offsets)):
        raise ValueError("VIRTUAL_FILL_SCHEDULE_OFFSETS_NOT_SORTED")
    if dispatch_mode is OnlyVirtualFillDispatchMode.ONE_PER_BAR and len(offsets) != len(set(offsets)):
        raise ValueError("VIRTUAL_FILL_ONE_PER_BAR_DUPLICATE_OFFSET")
    all_quantity = all(spec.quantity is not None for spec in specs)
    all_ratio = all(spec.ratio is not None for spec in specs)
    if not (all_quantity or all_ratio):
        raise ValueError("VIRTUAL_FILL_SCHEDULE_MIXED_STEP_TYPES")
    if all_quantity:
        values = tuple(spec.quantity for spec in specs)
        assert all(value is not None for value in values)
        normalized_values = tuple(value for value in values if value is not None)
    else:
        ratios = tuple(spec.ratio for spec in specs)
        assert all(ratio is not None for ratio in ratios)
        ratio_values = tuple(ratio for ratio in ratios if ratio is not None)
        if sum(ratio_values, Decimal(0)) != Decimal(1):
            raise ValueError("VIRTUAL_FILL_SCHEDULE_RATIO_SUM_INVALID")
        quantum = Decimal(1).scaleb(-original_quantity.precision)
        prefix = tuple(
            (original_quantity.value * ratio).quantize(quantum, rounding=ROUND_DOWN) for ratio in ratio_values[:-1]
        )
        normalized_values = (*prefix, original_quantity.value - sum(prefix, Decimal(0)))
    if any(value <= 0 for value in normalized_values):
        raise ValueError("VIRTUAL_FILL_PLAN_STEP_QUANTITY_INVALID")
    if sum(normalized_values, Decimal(0)) != original_quantity.value:
        raise ValueError("VIRTUAL_FILL_PLAN_QUANTITY_MISMATCH")
    return tuple(
        OnlyVirtualFillPlanStep(index, spec.bar_offset, OnlyQuantity(value, original_quantity.precision))
        for index, (spec, value) in enumerate(zip(specs, normalized_values, strict=True), start=1)
    )


def only_create_virtual_order_fill_plan(
    *,
    gateway_id: str,
    account_id: OnlyAccountId,
    order_id: OnlyOrderId,
    venue_order_id: OnlyVenueOrderId,
    original_quantity: OnlyQuantity,
    accepted_bar_sequence: int,
    mode: OnlyVirtualFillScheduleMode,
    dispatch_mode: OnlyVirtualFillDispatchMode,
    schedule_steps: tuple[OnlyVirtualFillScheduleStepSpec, ...] = (),
    maximum_fill_quantity: OnlyQuantity | None = None,
) -> OnlyVirtualOrderFillPlan:
    steps: tuple[OnlyVirtualFillPlanStep, ...]
    if mode is OnlyVirtualFillScheduleMode.WHOLE:
        steps = (OnlyVirtualFillPlanStep(1, 1, original_quantity),)
    elif mode is OnlyVirtualFillScheduleMode.MAX_PER_BAR:
        if maximum_fill_quantity is None or maximum_fill_quantity.value <= 0:
            raise ValueError("VIRTUAL_FILL_MAXIMUM_REQUIRED")
        steps_list: list[OnlyVirtualFillPlanStep] = []
        remaining = original_quantity.value
        while remaining > 0:
            value = min(remaining, maximum_fill_quantity.value)
            index = len(steps_list) + 1
            steps_list.append(OnlyVirtualFillPlanStep(index, index, OnlyQuantity(value, original_quantity.precision)))
            remaining -= value
        steps = tuple(steps_list)
        dispatch_mode = OnlyVirtualFillDispatchMode.ONE_PER_BAR
    else:
        steps = _normalize_schedule_steps(original_quantity, schedule_steps, dispatch_mode)
    identity_payload = {
        "account_id": str(account_id),
        "dispatch_mode": dispatch_mode.value,
        "gateway_id": gateway_id,
        "mode": mode.value,
        "normalized_steps": [
            {
                "bar_offset": step.bar_offset,
                "quantity": _quantity_text(step.quantity),
                "step_index": step.step_index,
            }
            for step in steps
        ],
        "order_id": str(order_id),
        "original_quantity": _quantity_text(original_quantity),
        "quantity_precision": original_quantity.precision,
        "schema_version": 1,
        "venue_order_id": str(venue_order_id),
    }
    fingerprint = hashlib.sha256(_canonical_json(identity_payload).encode("utf-8")).hexdigest()
    return OnlyVirtualOrderFillPlan(
        order_id,
        venue_order_id,
        f"VPLAN-{fingerprint}",
        fingerprint,
        original_quantity,
        accepted_bar_sequence,
        mode,
        dispatch_mode,
        steps,
    )


def only_virtual_fill_plan_to_checkpoint(plan: OnlyVirtualOrderFillPlan) -> object:
    return {
        "accepted_bar_sequence": plan.accepted_bar_sequence,
        "dispatch_mode": plan.dispatch_mode.value,
        "mode": plan.mode.value,
        "next_step_index": plan.next_step_index,
        "order_id": str(plan.order_id),
        "original_quantity": str(plan.original_quantity.value),
        "original_quantity_precision": plan.original_quantity.precision,
        "plan_fingerprint": plan.plan_fingerprint,
        "plan_id": plan.plan_id,
        "status": plan.status.value,
        "steps": [
            {
                "bar_offset": step.bar_offset,
                "quantity": str(step.quantity.value),
                "quantity_precision": step.quantity.precision,
                "step_index": step.step_index,
            }
            for step in plan.steps
        ],
        "venue_order_id": str(plan.venue_order_id),
        "version": plan.version,
    }


def only_virtual_fill_plan_from_checkpoint(payload: object) -> OnlyVirtualOrderFillPlan:
    if not isinstance(payload, dict):
        raise ValueError("Virtual Fill Plan checkpoint must be an object")
    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list):
        raise ValueError("Virtual Fill Plan steps checkpoint must be a list")
    steps = tuple(
        OnlyVirtualFillPlanStep(
            int(item["step_index"]),
            int(item["bar_offset"]),
            OnlyQuantity(Decimal(str(item["quantity"])), int(item["quantity_precision"])),
        )
        for item in raw_steps
        if isinstance(item, dict)
    )
    if len(steps) != len(raw_steps):
        raise ValueError("Virtual Fill Plan step checkpoint must be an object")
    return OnlyVirtualOrderFillPlan(
        OnlyOrderId(str(payload["order_id"])),
        OnlyVenueOrderId(str(payload["venue_order_id"])),
        str(payload["plan_id"]),
        str(payload["plan_fingerprint"]),
        OnlyQuantity(
            Decimal(str(payload["original_quantity"])),
            int(payload["original_quantity_precision"]),
        ),
        int(payload["accepted_bar_sequence"]),
        OnlyVirtualFillScheduleMode(str(payload["mode"])),
        OnlyVirtualFillDispatchMode(str(payload["dispatch_mode"])),
        steps,
        int(payload["next_step_index"]),
        OnlyVirtualFillPlanStatus(str(payload["status"])),
        int(payload["version"]),
    )


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
