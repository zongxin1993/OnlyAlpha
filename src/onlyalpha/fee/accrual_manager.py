"""Runtime-owned projection target state for per-Order fee accrual."""

from __future__ import annotations

from onlyalpha.domain.identifiers import OnlyOrderId

from .accrual import OnlyOrderFeeAccrualState


class OnlyOrderFeeAccrualManager:
    def __init__(self) -> None:
        self._states: dict[OnlyOrderId, OnlyOrderFeeAccrualState] = {}

    def get(self, order_id: OnlyOrderId) -> OnlyOrderFeeAccrualState | None:
        return self._states.get(order_id)

    def restore(self, state: OnlyOrderFeeAccrualState) -> None:
        current = self._states.get(state.order_id)
        if current is not None and state.version < current.version:
            raise ValueError("Order fee accrual version cannot regress")
        self._states[state.order_id] = state

    def capture_checkpoint(self) -> object:
        return [state.to_json() for state in sorted(self._states.values(), key=lambda item: str(item.order_id))]

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, list):
            raise ValueError("Order fee accrual checkpoint must be an array")
        states = tuple(OnlyOrderFeeAccrualState.from_json(str(item)) for item in payload)
        if len({item.order_id for item in states}) != len(states):
            raise ValueError("Order fee accrual checkpoint contains duplicate Orders")
        self._states = {item.order_id: item for item in states}


__all__ = ["OnlyOrderFeeAccrualManager"]
