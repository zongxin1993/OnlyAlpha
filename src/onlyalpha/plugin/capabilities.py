"""Data-source capabilities and structured validation issues."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class OnlyCheckpointCapability(StrEnum):
    STATELESS = "STATELESS"
    CHECKPOINTABLE = "CHECKPOINTABLE"


@dataclass(frozen=True, slots=True)
class OnlyDataSourceCapabilities:
    historical_bars: bool = False
    historical_ticks: bool = False
    historical_reference_prices: bool = False
    historical_funding_rates: bool = False
    historical_settlements: bool = False
    live_bars: bool = False
    live_ticks: bool = False
    live_reconnect: bool = False
    instruments: bool = False
    calendars: bool = False
    supports_runtime_checkpoint: OnlyCheckpointCapability | None = None
    checkpoint_schema_version: int | None = None

    def __post_init__(self) -> None:
        _validate_checkpoint_capability(self.supports_runtime_checkpoint, self.checkpoint_schema_version)

    def missing(self, required: OnlyDataSourceCapabilities) -> tuple[str, ...]:
        return tuple(
            field
            for field in self.__dataclass_fields__
            if bool(getattr(required, field)) and not bool(getattr(self, field))
        )


@dataclass(frozen=True, slots=True)
class OnlyBrokerPluginCapabilities:
    submit_order: bool = False
    cancel_order: bool = False
    replace_order: bool = False
    query_orders: bool = False
    query_trades: bool = False
    query_account: bool = False
    query_positions: bool = False
    query_fee_evidence: bool = False
    live_execution: bool = False
    simulated_execution: bool = False
    supports_runtime_checkpoint: OnlyCheckpointCapability | None = None
    checkpoint_schema_version: int | None = None

    def __post_init__(self) -> None:
        _validate_checkpoint_capability(self.supports_runtime_checkpoint, self.checkpoint_schema_version)

    def missing(self, required: OnlyBrokerPluginCapabilities) -> tuple[str, ...]:
        return tuple(
            field
            for field in self.__dataclass_fields__
            if bool(getattr(required, field)) and not bool(getattr(self, field))
        )


@dataclass(frozen=True, slots=True)
class OnlyPluginValidationIssue:
    code: str
    message: str
    field: str | None = None


def _validate_checkpoint_capability(
    capability: OnlyCheckpointCapability | None,
    schema_version: int | None,
) -> None:
    if capability is None:
        if schema_version is not None:
            raise ValueError("checkpoint schema version requires an explicit capability")
        return
    if capability is OnlyCheckpointCapability.CHECKPOINTABLE:
        if schema_version is None or schema_version < 1:
            raise ValueError("checkpointable capability requires a positive schema version")
    elif schema_version is not None:
        raise ValueError("stateless capability does not accept a checkpoint schema version")
