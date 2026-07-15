"""Audited broker/local Position comparison without silent overwrite."""

from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.value import OnlyQuantity
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.authority import OnlyPositionAuthorityPolicy
from onlyalpha.position.enums import (
    OnlyReconciliationAction,
    OnlyReconciliationSeverity,
)
from onlyalpha.position.keys import OnlyPositionKey
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.position.models import (
    OnlyBrokerPositionSnapshot,
    OnlyPositionConflict,
    OnlyPositionDifference,
    OnlyPositionReconciliationResult,
    OnlyPositionSnapshot,
)
from onlyalpha.position.reservations import OnlyPositionReservationManager

_SEVERITY_ORDER = {
    OnlyReconciliationSeverity.INFO: 0,
    OnlyReconciliationSeverity.WARNING: 1,
    OnlyReconciliationSeverity.BLOCK_INSTRUMENT: 2,
    OnlyReconciliationSeverity.BLOCK_ACCOUNT: 3,
    OnlyReconciliationSeverity.FAIL_RUNTIME: 4,
}


class OnlyPositionReconciliationService:
    def __init__(
        self,
        runtime_id: OnlyRuntimeId,
        positions: OnlyPositionManager,
        allocations: OnlyPositionAllocationManager,
        authority_policy: OnlyPositionAuthorityPolicy,
        reservations: OnlyPositionReservationManager | None = None,
    ) -> None:
        self.runtime_id = runtime_id
        self._positions = positions
        self._allocations = allocations
        self._policy = authority_policy
        self._reservations = reservations

    def reconcile(self, broker: OnlyBrokerPositionSnapshot) -> OnlyPositionReconciliationResult:
        key = OnlyPositionKey(
            self.runtime_id,
            broker.account_id,
            broker.instrument_id,
            broker.position_side,
        )
        local = self._positions.get_snapshot(key)
        differences: list[OnlyPositionDifference] = []
        if local is None:
            if broker.total_quantity.value != 0:
                differences.append(self._difference("total_quantity", "0", broker.total_quantity.value, True))
        else:
            self._compare_quantity(differences, "total_quantity", local.total_quantity, broker.total_quantity, True)
            self._compare_quantity(
                differences, "available_quantity", local.available_quantity, broker.available_quantity, False
            )
            self._compare_quantity(differences, "frozen_quantity", local.frozen_quantity, broker.frozen_quantity, False)
            self._compare_quantity(
                differences, "settled_quantity", local.settled_quantity, broker.settled_quantity, True
            )
            self._compare_quantity(
                differences, "unsettled_quantity", local.unsettled_quantity, broker.unsettled_quantity, True
            )
            if local.position_side != broker.position_side:
                differences.append(
                    self._difference("position_side", local.position_side.value, broker.position_side.value, True)
                )
            if local.average_open_price != broker.broker_average_price:
                differences.append(
                    OnlyPositionDifference(
                        "average_price",
                        "None" if local.average_open_price is None else str(local.average_open_price.value),
                        "None" if broker.broker_average_price is None else str(broker.broker_average_price.value),
                        self._policy.authority_for("broker_average_price"),
                        OnlyReconciliationSeverity.INFO,
                    )
                )
        severity = max(
            (item.severity for item in differences),
            key=lambda item: _SEVERITY_ORDER[item],
            default=OnlyReconciliationSeverity.INFO,
        )
        blocking = _SEVERITY_ORDER[severity] >= _SEVERITY_ORDER[OnlyReconciliationSeverity.BLOCK_INSTRUMENT]
        conflicts = (
            ()
            if not differences
            else (
                OnlyPositionConflict(
                    broker.account_id,
                    broker.instrument_id,
                    severity,
                    "broker/local Position differs; no local state was overwritten",
                    blocking,
                ),
            )
        )
        actions = self._actions(differences, severity)
        effective = self._effective_available(local, broker)
        if local is not None:
            self._positions.set_broker_available(key, broker.available_quantity)
            if blocking:
                self._positions.set_reconciling(key, broker.available_quantity)
                local = self._positions.require_snapshot(key)
                effective = OnlyQuantity(Decimal(0), effective.precision)
            else:
                self._positions.clear_reconciling(key)
                local = self._positions.require_snapshot(key)
            self._allocations.reconcile_unallocated(
                broker.account_id,
                broker.instrument_id,
                broker.position_side,
                local.total_quantity,
                local.settled_quantity,
                local.unsettled_quantity,
                broker.snapshot_time,
            )
        return OnlyPositionReconciliationResult(
            local,
            broker,
            tuple(differences),
            conflicts,
            severity,
            actions,
            effective,
            not differences,
        )

    def _effective_available(
        self,
        local: OnlyPositionSnapshot | None,
        broker: OnlyBrokerPositionSnapshot,
    ) -> OnlyQuantity:
        if local is None:
            return OnlyQuantity(Decimal(0), broker.total_quantity.precision)
        local_only = Decimal(0)
        if self._reservations is not None:
            local_only = self._reservations.active_quantity(
                broker.instrument_id,
                account_id=broker.account_id,
                local_only=True,
            ).value
        locally_calculated_tradable = max(
            local.tradable_quantity.value - local.order_frozen_quantity.value - local.restricted_quantity.value,
            Decimal(0),
        )
        effective = max(
            min(broker.available_quantity.value, locally_calculated_tradable) - local_only,
            Decimal(0),
        )
        if local.status.value == "RECONCILING":
            effective = Decimal(0)
        return OnlyQuantity(effective, local.total_quantity.precision)

    def _compare_quantity(
        self,
        output: list[OnlyPositionDifference],
        field_name: str,
        local: OnlyQuantity,
        broker: OnlyQuantity,
        blocking: bool,
    ) -> None:
        if local.value != broker.value:
            output.append(self._difference(field_name, local.value, broker.value, blocking))

    def _difference(
        self,
        field_name: str,
        local: object,
        broker: object,
        blocking: bool,
    ) -> OnlyPositionDifference:
        return OnlyPositionDifference(
            field_name,
            str(local),
            str(broker),
            self._policy.authority_for(field_name),
            OnlyReconciliationSeverity.BLOCK_INSTRUMENT if blocking else OnlyReconciliationSeverity.WARNING,
        )

    @staticmethod
    def _actions(
        differences: list[OnlyPositionDifference],
        severity: OnlyReconciliationSeverity,
    ) -> tuple[OnlyReconciliationAction, ...]:
        if not differences:
            return (OnlyReconciliationAction.NONE,)
        actions = [OnlyReconciliationAction.RECORD_DIFFERENCE]
        if _SEVERITY_ORDER[severity] >= _SEVERITY_ORDER[OnlyReconciliationSeverity.BLOCK_INSTRUMENT]:
            actions.extend(
                (
                    OnlyReconciliationAction.QUERY_ORDERS_AND_TRADES,
                    OnlyReconciliationAction.BLOCK_INSTRUMENT,
                )
            )
        return tuple(actions)
