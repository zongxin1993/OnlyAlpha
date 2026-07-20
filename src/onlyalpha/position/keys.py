"""Immutable lookup keys for account and allocation positions."""

from dataclasses import dataclass

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.position.enums import OnlyPositionMode, OnlyPositionSide


@dataclass(frozen=True, slots=True)
class OnlyPositionKey(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    instrument_id: OnlyInstrumentId
    position_side: OnlyPositionSide = OnlyPositionSide.LONG
    position_mode: OnlyPositionMode = OnlyPositionMode.NETTING

    def __post_init__(self) -> None:
        if self.position_side is OnlyPositionSide.FLAT:
            raise ValueError("Position key cannot use FLAT side")


@dataclass(frozen=True, slots=True)
class OnlyPositionAllocationKey(OnlyDomainModel):
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    position_side: OnlyPositionSide = OnlyPositionSide.LONG
