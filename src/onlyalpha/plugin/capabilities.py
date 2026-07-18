"""Data-source capabilities and structured validation issues."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OnlyDataSourceCapabilities:
    historical_bars: bool = False
    historical_ticks: bool = False
    live_bars: bool = False
    live_ticks: bool = False
    instruments: bool = False
    calendars: bool = False

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
    live_execution: bool = False
    simulated_execution: bool = False

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
