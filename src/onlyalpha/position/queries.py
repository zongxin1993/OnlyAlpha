"""Read-only account and Cluster Position queries."""

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.position.allocation_manager import OnlyPositionAllocationManager
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide
from onlyalpha.position.keys import OnlyPositionAllocationKey, OnlyPositionKey
from onlyalpha.position.manager import OnlyPositionManager
from onlyalpha.position.models import OnlyPositionAllocationSnapshot, OnlyPositionSnapshot


class OnlyPositionQueryService:
    def __init__(self, positions: OnlyPositionManager, allocations: OnlyPositionAllocationManager) -> None:
        self._positions = positions
        self._allocations = allocations

    @property
    def runtime_id(self) -> OnlyRuntimeId:
        return self._positions.runtime_id

    def account(
        self,
        account_id: OnlyAccountId,
        instrument_id: OnlyInstrumentId,
        side: OnlyPositionSide = OnlyPositionSide.LONG,
        mode: OnlyPositionMode = OnlyPositionMode.NETTING,
    ) -> OnlyPositionSnapshot | None:
        return self._positions.get_snapshot(
            OnlyPositionKey(self._positions.runtime_id, account_id, instrument_id, side, mode)
        )

    def cluster(
        self,
        account_id: OnlyAccountId,
        cluster_id: OnlyClusterId,
        instrument_id: OnlyInstrumentId,
        side: OnlyPositionSide = OnlyPositionSide.LONG,
    ) -> OnlyPositionAllocationSnapshot | None:
        return self._allocations.get_snapshot(
            OnlyPositionAllocationKey(
                self._positions.runtime_id,
                account_id,
                cluster_id,
                instrument_id,
                side,
            )
        )


OnlyPositionQueryView = OnlyPositionQueryService
OnlyPositionAllocationQueryView = OnlyPositionQueryService
