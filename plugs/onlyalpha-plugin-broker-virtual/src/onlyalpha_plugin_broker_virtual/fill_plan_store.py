"""In-memory immutable Virtual Broker Fill Plan store."""

from dataclasses import replace

from onlyalpha.domain.identifiers import OnlyOrderId
from onlyalpha_plugin_broker_virtual.fill_plan import (
    OnlyVirtualFillPlanStatus,
    OnlyVirtualOrderFillPlan,
    only_virtual_fill_plan_from_checkpoint,
    only_virtual_fill_plan_to_checkpoint,
)


class OnlyVirtualFillPlanStore:
    def __init__(self) -> None:
        self._plans: dict[OnlyOrderId, OnlyVirtualOrderFillPlan] = {}

    def save(self, plan: OnlyVirtualOrderFillPlan) -> None:
        if plan.order_id in self._plans:
            raise ValueError("VIRTUAL_FILL_PLAN_DUPLICATE_ORDER")
        self._plans[plan.order_id] = plan

    def get(self, order_id: OnlyOrderId) -> OnlyVirtualOrderFillPlan | None:
        return self._plans.get(order_id)

    def require(self, order_id: OnlyOrderId) -> OnlyVirtualOrderFillPlan:
        try:
            return self._plans[order_id]
        except KeyError as exc:
            raise ValueError("VIRTUAL_FILL_PLAN_MISSING") from exc

    def advance(self, order_id: OnlyOrderId) -> OnlyVirtualOrderFillPlan:
        current = self.require(order_id)
        if current.status is not OnlyVirtualFillPlanStatus.ACTIVE:
            raise ValueError("VIRTUAL_FILL_PLAN_TERMINAL_ADVANCE")
        next_index = current.next_step_index + 1
        status = (
            OnlyVirtualFillPlanStatus.COMPLETED
            if next_index == len(current.steps)
            else OnlyVirtualFillPlanStatus.ACTIVE
        )
        updated = replace(current, next_step_index=next_index, status=status, version=current.version + 1)
        self._plans[order_id] = updated
        return updated

    def cancel(self, order_id: OnlyOrderId) -> OnlyVirtualOrderFillPlan:
        current = self.require(order_id)
        if current.status is not OnlyVirtualFillPlanStatus.ACTIVE:
            raise ValueError("VIRTUAL_FILL_PLAN_TERMINAL_CANCEL")
        updated = replace(current, status=OnlyVirtualFillPlanStatus.CANCELLED, version=current.version + 1)
        self._plans[order_id] = updated
        return updated

    def expire(self, order_id: OnlyOrderId) -> OnlyVirtualOrderFillPlan:
        current = self.require(order_id)
        if current.status is not OnlyVirtualFillPlanStatus.ACTIVE:
            raise ValueError("VIRTUAL_FILL_PLAN_TERMINAL_EXPIRE")
        updated = replace(current, status=OnlyVirtualFillPlanStatus.EXPIRED, version=current.version + 1)
        self._plans[order_id] = updated
        return updated

    def list(self) -> tuple[OnlyVirtualOrderFillPlan, ...]:
        return tuple(self._plans[key] for key in sorted(self._plans, key=str))

    def capture_checkpoint(self) -> object:
        return [only_virtual_fill_plan_to_checkpoint(plan) for plan in self.list()]

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, list):
            raise ValueError("Virtual Fill Plan Store checkpoint must be a list")
        restored: dict[OnlyOrderId, OnlyVirtualOrderFillPlan] = {}
        for raw in payload:
            plan = only_virtual_fill_plan_from_checkpoint(raw)
            if plan.order_id in restored:
                raise ValueError("VIRTUAL_FILL_PLAN_DUPLICATE_ORDER")
            restored[plan.order_id] = plan
        self._plans = restored


__all__ = ["OnlyVirtualFillPlanStore"]
