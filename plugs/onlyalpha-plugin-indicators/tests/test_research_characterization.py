from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pyarrow as pa
import pytest
from onlyalpha_plugin_indicators.registration import (
    ATR_V2,
    TYPES,
    OnlyIndicatorBackendRequest,
    registrations,
    resolve_definition,
)

from onlyalpha.calculation import OnlyCalculationBackendKind
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.indicator.identifiers import OnlyIndicatorId

BAR_TYPE = OnlyBarType(
    OnlyInstrumentId.parse("TEST.XNAS"),
    OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
    OnlyAggregationSource.EXTERNAL,
)


def _bar(index: int, close: str, *, high: str | None = None, low: str | None = None) -> OnlyBar:
    start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC) + timedelta(minutes=index)
    value = Decimal(close)
    return OnlyBar(
        bar_type=BAR_TYPE,
        open=OnlyPrice(value, 4),
        high=OnlyPrice(Decimal(high or close), 4),
        low=OnlyPrice(Decimal(low or close), 4),
        close=OnlyPrice(value, 4),
        volume=OnlyQuantity(Decimal(100 + index), 0),
        quote_volume=None,
        turnover=None,
        trade_count=index,
        open_interest=None,
        bar_start=start,
        bar_end=start + timedelta(minutes=1),
        ts_event=start + timedelta(minutes=1),
        ts_init=start + timedelta(minutes=1),
        is_closed=True,
        revision=0,
        adjustment_type=OnlyAdjustmentType.RAW,
        trading_day=date(2026, 1, 5),
        session_type=OnlySessionType.CONTINUOUS,
    )


def _parameters(type_id: str) -> dict[str, object]:
    if type_id.endswith("macd"):
        return {"fast_period": 2, "slow_period": 3, "signal_period": 2, "warmup_bars": 3}
    return {"period": 3}


def _arrays(bars: tuple[OnlyBar, ...], definition) -> dict[str, pa.Array]:
    columns = {
        "value": [
            bar.volume.value
            if definition.input_bindings.get("value", None)
            and definition.input_bindings["value"].source == "bar.volume"
            else bar.close.value
            for bar in bars
        ],
        "high": [bar.high.value for bar in bars],
        "low": [bar.low.value for bar in bars],
        "close": [bar.close.value for bar in bars],
    }
    return {item.name: pa.array(columns[item.name], type=pa.decimal128(38, 18)) for item in definition.inputs}


def _trading_series(definition, bars: tuple[OnlyBar, ...]) -> tuple[dict[str, list[object]], list[bool]]:
    registration = next(
        item
        for item in registrations()
        if item.backend is OnlyCalculationBackendKind.TRADING
        and item.type_definition.type_id == definition.type_id
        and item.type_definition.semantic_version == definition.semantic_version
    )
    indicator = registration.provider.create(
        definition, OnlyIndicatorBackendRequest(OnlyIndicatorId("characterization"), BAR_TYPE)
    )
    result = {output.name: [] for output in definition.outputs}
    ready = []
    for bar in bars:
        indicator.update_bar(bar)
        snapshot = indicator.snapshot()
        ready.append(snapshot.ready)
        for name in result:
            value = getattr(snapshot, name)
            result[name].append(value.value if hasattr(value, "value") else value)
    return result, ready


@pytest.mark.parametrize(
    "type_definition", (*TYPES[:3], *TYPES[4:], ATR_V2), ids=lambda item: f"{item.type_id}@{item.semantic_version}"
)
def test_trading_and_research_backends_have_exact_observation_parity(type_definition) -> None:
    definition = resolve_definition(type_definition, _parameters(type_definition.type_id))
    bars = tuple(
        _bar(index, close, high=high, low=low)
        for index, (close, high, low) in enumerate(
            (
                ("1.0001", "1.1001", "0.9001"),
                ("2", "2.2", "1.7"),
                ("0", "2.5", "-0.5"),
                ("4.3333", "5", "3"),
                ("2", "3", "1"),
                ("8", "9", "7"),
            )
        )
    )
    research = next(
        item.provider
        for item in registrations()
        if item.backend is OnlyCalculationBackendKind.RESEARCH
        and item.type_definition.type_id == definition.type_id
        and item.type_definition.semantic_version == definition.semantic_version
    ).execute(definition, _arrays(bars, definition))
    trading, ready = _trading_series(definition, bars)
    assert {name: array.to_pylist() for name, array in research.items()} == trading
    assert ready == [index >= definition.warmup.minimum_observations for index in range(1, len(bars) + 1)]


def test_research_backend_rejects_missing_values() -> None:
    definition = resolve_definition(TYPES[0], {"period": 2})
    provider = next(item.provider for item in registrations() if item.backend is OnlyCalculationBackendKind.RESEARCH)
    with pytest.raises(ValueError, match="missing input"):
        provider.execute(definition, {"value": pa.array([Decimal("1"), None], type=pa.decimal128(38, 18))})


def test_atr_contract_migrates_without_changing_published_v1() -> None:
    atr_v1 = TYPES[3]
    assert atr_v1.semantic_version == "1"
    assert tuple(item.name for item in atr_v1.inputs) == ("value",)
    assert tuple(item.name for item in ATR_V2.inputs) == ("high", "low", "close")
    assert not any(
        item.backend is OnlyCalculationBackendKind.RESEARCH
        and item.type_definition.type_id == atr_v1.type_id
        and item.type_definition.semantic_version == "1"
        for item in registrations()
    )
