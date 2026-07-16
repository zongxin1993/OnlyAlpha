"""Strategy-only context and immutable Factor view."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.factor.score import OnlyFactorScore
from onlyalpha.factor.snapshot import OnlyFactorSnapshot
from onlyalpha.runtime.context import OnlyRuntimeContext

OnlyFactorSnapshotT = TypeVar("OnlyFactorSnapshotT", bound=OnlyFactorSnapshot)


class OnlyStrategyFactorView:
    __slots__ = ("_scores", "_snapshots")

    def __init__(
        self, snapshots: dict[OnlyFactorId, OnlyFactorSnapshot], scores: dict[OnlyFactorId, OnlyFactorScore]
    ) -> None:
        self._snapshots = snapshots
        self._scores = scores

    def require(self, factor_id: OnlyFactorId, snapshot_type: type[OnlyFactorSnapshotT]) -> OnlyFactorSnapshotT:
        try:
            value = self._snapshots[factor_id]
        except KeyError as exc:
            raise KeyError(f"unknown factor: {factor_id}") from exc
        if not isinstance(value, snapshot_type):
            raise TypeError(f"factor {factor_id} snapshot is not {snapshot_type.__name__}")
        return value

    def score(self, factor_id: OnlyFactorId) -> OnlyFactorScore:
        return self._scores[factor_id]


class OnlyStrategyContext:
    """Whitelisted trading capabilities; no Runtime, Manager, Broker, or Indicator access."""

    __slots__ = ("_factors", "_runtime")

    def __init__(self, runtime: OnlyRuntimeContext, factors: OnlyStrategyFactorView) -> None:
        self._runtime = runtime
        self._factors = factors

    @property
    def clock(self) -> object:
        return self._runtime.clock

    @property
    def market_data(self) -> object:
        return self._runtime.market_data

    @property
    def factors(self) -> OnlyStrategyFactorView:
        return self._factors

    @property
    def instruments(self) -> object:
        return self._runtime.instruments

    @property
    def orders(self) -> object:
        return self._runtime.orders

    @property
    def positions(self) -> object:
        return self._runtime.positions

    @property
    def ledger(self) -> object:
        return self._runtime.ledger

    @property
    def accounts(self) -> object:
        return self._runtime.accounts

    @property
    def risk(self) -> object:
        return self._runtime.risk

    @property
    def logger(self) -> object:
        return self._runtime.logger

    @property
    def timers(self) -> object:
        return self._runtime.timers


@dataclass(frozen=True, slots=True)
class OnlyStrategyBarContext:
    strategy: OnlyStrategyContext
    primary_bar: object
    snapshot: object


@dataclass(frozen=True, slots=True)
class OnlyStrategyTimerContext:
    strategy: OnlyStrategyContext
    timer: object
