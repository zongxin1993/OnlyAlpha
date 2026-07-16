from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.factor.base import OnlyCrossSectionFactor, OnlyTimeSeriesFactor
from onlyalpha.factor.config import OnlyFactorConfig, OnlyFactorType
from onlyalpha.factor.context import OnlyCrossSectionFactorContext, OnlyFactorBarContext, OnlyFactorContext
from onlyalpha.factor.dependency import OnlyFactorDependencyGraph
from onlyalpha.factor.identifiers import OnlyFactorId
from onlyalpha.factor.score import OnlyFactorScore, OnlyFactorScoreDimension
from onlyalpha.factor.snapshot import OnlyFactorSnapshot


@dataclass(frozen=True, slots=True)
class OnlyTestFactorSnapshot(OnlyFactorSnapshot):
    factor_id: OnlyFactorId
    ready: bool
    ts_event: OnlyTimestamp | None = None

    def to_dict(self) -> Mapping[str, object]:
        return {"factor_id": str(self.factor_id), "ready": self.ready}


class OnlyTestTimeSeriesFactor(OnlyTimeSeriesFactor):
    def on_initialize(self) -> None:
        pass

    def on_bar(self, context: OnlyFactorBarContext) -> None:
        del context

    def snapshot(self) -> OnlyTestFactorSnapshot:
        return OnlyTestFactorSnapshot(self.factor_id, True)

    def score(self) -> OnlyFactorScore:
        return OnlyFactorScore(self.factor_id, Decimal(0), OnlyFactorScoreDimension.ALPHA, Decimal(1), True, None)


class OnlyTestCrossSectionFactor(OnlyCrossSectionFactor):
    def on_initialize(self) -> None:
        pass

    def on_cross_section(self, context: OnlyCrossSectionFactorContext) -> None:
        del context

    def snapshot(self) -> OnlyTestFactorSnapshot:
        return OnlyTestFactorSnapshot(self.factor_id, True)

    def score(self) -> OnlyFactorScore:
        return OnlyFactorScore(self.factor_id, Decimal(0), OnlyFactorScoreDimension.ALPHA, Decimal(1), True, None)


def _time(factor_id: str, dependencies: tuple[OnlyFactorId, ...] = ()) -> OnlyTestTimeSeriesFactor:
    return OnlyTestTimeSeriesFactor(
        OnlyFactorConfig(OnlyFactorId(factor_id), OnlyFactorType.TIME_SERIES, dependencies=dependencies)
    )


def test_factor_dependency_plan_is_stable_and_rejects_missing_cycle_and_invalid_phase() -> None:
    first = _time("a")
    second = _time("b", (first.factor_id,))
    assert OnlyFactorDependencyGraph().build((second, first)).ordered_factor_ids == (
        first.factor_id,
        second.factor_id,
    )
    with pytest.raises(ValueError, match="unknown"):
        OnlyFactorDependencyGraph().build((_time("missing", (OnlyFactorId("nope"),)),))
    with pytest.raises(ValueError, match="cycle"):
        OnlyFactorDependencyGraph().build(
            (_time("left", (OnlyFactorId("right"),)), _time("right", (OnlyFactorId("left"),)))
        )
    cross = OnlyTestCrossSectionFactor(OnlyFactorConfig(OnlyFactorId("cross"), OnlyFactorType.CROSS_SECTION))
    with pytest.raises(ValueError, match="cannot depend"):
        OnlyFactorDependencyGraph().build((_time("time", (cross.factor_id,)), cross))


def test_factor_context_has_no_trading_mutation_capabilities() -> None:
    fields = set(OnlyFactorContext.__dataclass_fields__)
    assert fields == {"clock", "market_data", "indicators", "dependent_factors", "instruments", "logger"}
    assert fields.isdisjoint({"orders", "positions", "ledger", "accounts", "risk", "broker"})


def test_cross_section_context_sorts_point_in_time_universe() -> None:
    @dataclass(frozen=True)
    class OnlyBarStub:
        bar_end: datetime
        close: Decimal

    context = object.__new__(OnlyFactorContext)
    point = datetime(2026, 1, 5, 1, 31, tzinfo=UTC)
    cross = OnlyCrossSectionFactorContext(
        {
            "z": OnlyBarStub(point, Decimal("9")),
            "a": OnlyBarStub(point, Decimal("11")),
        },  # type: ignore[arg-type]
        context,
        ("z", "missing", "a"),
    )
    assert tuple(cross.bars) == ("a", "z")
    assert cross.universe.expected_instrument_ids == ("a", "missing", "z")
    assert cross.universe.missing_instrument_ids == ("missing",)
    assert cross.universe.complete is False
    ranks = {
        instrument_id: rank
        for rank, (instrument_id, _bar) in enumerate(
            sorted(cross.bars.items(), key=lambda item: (-item[1].close, item[0])),
            start=1,
        )
    }
    assert ranks == {"a": 1, "z": 2}

    later = datetime(2026, 1, 5, 1, 32, tzinfo=UTC)
    with pytest.raises(ValueError, match="point-in-time"):
        OnlyCrossSectionFactorContext(
            {
                "a": OnlyBarStub(point, Decimal("11")),
                "z": OnlyBarStub(later, Decimal("9")),
            },  # type: ignore[arg-type]
            context,
        )
