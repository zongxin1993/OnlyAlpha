"""Immutable, Runtime-mode-neutral Trading Kernel configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId, OnlyEngineId, OnlyRuntimeId
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.event.bus import OnlyEventQueuePolicy


@dataclass(frozen=True, slots=True)
class OnlyTradingKernelConfig:
    """Identity and capacity configuration consumed by shared trading semantics."""

    engine_id: OnlyEngineId
    runtime_id: OnlyRuntimeId
    default_account_id: OnlyAccountId
    strategy_base_currency: OnlyCurrency
    strategy_capitals: Mapping[OnlyClusterId, OnlyMoney] = field(default_factory=dict)
    event_capacity: int = 1024
    history_limit: int = 1024
    event_queue_policy: OnlyEventQueuePolicy = OnlyEventQueuePolicy.REJECT

    def __post_init__(self) -> None:
        if self.event_capacity <= 0 or self.history_limit <= 0:
            raise ValueError("Trading Kernel capacities must be positive")
        capitals = MappingProxyType(dict(self.strategy_capitals))
        if any(value.amount < 0 for value in capitals.values()):
            raise ValueError("Strategy capital cannot be negative")
        if any(value.currency != self.strategy_base_currency for value in capitals.values()):
            raise ValueError("Strategy capital currency must equal Trading Kernel base currency")
        object.__setattr__(self, "strategy_capitals", capitals)
