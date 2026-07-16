"""Restricted Factor contexts: no order, account, position, ledger, or risk mutation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import TypeVar

from onlyalpha.core.clock import OnlyClockView
from onlyalpha.domain.market import OnlyBar
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.factor.score import OnlyFactorScore
from onlyalpha.factor.snapshot import OnlyFactorSnapshot
from onlyalpha.indicator.identifiers import OnlyIndicatorId
from onlyalpha.indicator.registry import OnlyIndicatorRegistry
from onlyalpha.indicator.score import OnlyIndicatorScore
from onlyalpha.indicator.snapshot import OnlyIndicatorSnapshot
from onlyalpha.runtime.context import OnlyInstrumentView, OnlyMarketDataView, OnlyRuntimeLogger

OnlyIndicatorSnapshotT = TypeVar("OnlyIndicatorSnapshotT", bound=OnlyIndicatorSnapshot)


class OnlyFactorIndicatorContext:
    __slots__ = ("_factor_id", "_registry")

    def __init__(self, factor_id: OnlyFactorId, registry: OnlyIndicatorRegistry) -> None:
        self._factor_id = factor_id
        self._registry = registry

    def create_for_bars(self, **kwargs: object) -> OnlyIndicatorId:
        return self._registry.create_for_bars(self._factor_id, **kwargs)  # type: ignore[arg-type]

    def score(self, indicator_id: OnlyIndicatorId) -> OnlyIndicatorScore | None:
        return self._registry.score(self._factor_id, indicator_id)

    def require_snapshot(
        self,
        indicator_id: OnlyIndicatorId,
        snapshot_type: type[OnlyIndicatorSnapshotT],
    ) -> OnlyIndicatorSnapshotT:
        return self._registry.require_snapshot(self._factor_id, indicator_id, snapshot_type)


class OnlyDependentFactorView:
    __slots__ = ("_scores", "_snapshots")

    def __init__(
        self,
        snapshots: Mapping[OnlyFactorId, OnlyFactorSnapshot],
        scores: Mapping[OnlyFactorId, OnlyFactorScore],
    ) -> None:
        self._snapshots = snapshots
        self._scores = scores

    def require(self, factor_id: OnlyFactorId, snapshot_type: type[OnlyFactorSnapshot]) -> OnlyFactorSnapshot:
        value = self._snapshots[factor_id]
        if not isinstance(value, snapshot_type):
            raise TypeError(f"factor {factor_id} snapshot is not {snapshot_type.__name__}")
        return value

    def score(self, factor_id: OnlyFactorId) -> OnlyFactorScore:
        return self._scores[factor_id]


@dataclass(frozen=True, slots=True)
class OnlyFactorContext:
    clock: OnlyClockView
    market_data: OnlyMarketDataView
    indicators: OnlyFactorIndicatorContext
    dependent_factors: OnlyDependentFactorView
    instruments: OnlyInstrumentView
    logger: OnlyRuntimeLogger


@dataclass(frozen=True, slots=True)
class OnlyFactorBarContext:
    bar: OnlyBar
    context: OnlyFactorContext


@dataclass(frozen=True, slots=True)
class OnlyCrossSectionUniverseSnapshot:
    """Immutable point-in-time universe with explicit missing-member quality."""

    ts_event: datetime | None
    bars: Mapping[str, OnlyBar]
    expected_instrument_ids: tuple[str, ...]
    missing_instrument_ids: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.missing_instrument_ids


@dataclass(frozen=True, slots=True)
class OnlyCrossSectionFactorContext:
    bars: Mapping[str, OnlyBar]
    context: OnlyFactorContext
    expected_instrument_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ordered = dict(sorted(self.bars.items()))
        bar_ends = {bar.bar_end for bar in ordered.values()}
        if len(bar_ends) > 1:
            raise ValueError("cross-section bars must share one point-in-time bar_end")
        expected = tuple(sorted(self.expected_instrument_ids or tuple(ordered)))
        object.__setattr__(self, "bars", MappingProxyType(ordered))
        object.__setattr__(self, "expected_instrument_ids", expected)

    @property
    def universe(self) -> OnlyCrossSectionUniverseSnapshot:
        missing = tuple(item for item in self.expected_instrument_ids if item not in self.bars)
        ts_event = next(iter(self.bars.values())).bar_end if self.bars else None
        return OnlyCrossSectionUniverseSnapshot(ts_event, self.bars, self.expected_instrument_ids, missing)
