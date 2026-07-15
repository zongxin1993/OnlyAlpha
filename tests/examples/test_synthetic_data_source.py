from dataclasses import replace
from datetime import time
from decimal import Decimal
from pathlib import Path

from onlyalpha.backtest import OnlyBacktestConfig
from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange
from onlyalpha.data.synthetic import (
    OnlySyntheticHistoricalDataSource,
    OnlySyntheticNoiseModel,
)

CONFIG = Path("examples/backtest_macd/config.yaml")


def _load(config: OnlyBacktestConfig):
    source = OnlySyntheticHistoricalDataSource(config.synthetic_source)
    request = OnlyHistoricalBarRequest(
        "synthetic-test",
        frozenset({config.instrument.instrument_id}),
        frozenset({config.primary_bar_type}),
        OnlyHistoricalDataRange(config.start_time, config.end_time),
        config.synthetic_source.data_version,
        batch_size=37,
    )
    return source.load_bars(request)


def test_synthetic_source_generates_calendar_aware_valid_versioned_bars() -> None:
    config = OnlyBacktestConfig.load(CONFIG)
    stream = _load(config)
    assert len(stream.records) == 720
    assert sum(len(batch) for batch in stream.batches()) == 720
    assert [int(item.source_sequence) for item in stream.records] == list(range(1, 721))
    assert all(item.data_version == config.synthetic_source.data_version for item in stream.records)
    for update in stream.records:
        bar = update.payload.bar  # type: ignore[union-attr]
        local = config.calendar.to_local(bar.bar_start)
        assert local.weekday() < 5
        assert not (time(11, 30) <= local.time() < time(13))
        assert bar.high.value >= max(bar.open.value, bar.close.value)
        assert bar.low.value <= min(bar.open.value, bar.close.value)
        assert config.instrument.validates_price(bar.open)
        assert config.instrument.validates_price(bar.high)
        assert config.instrument.validates_price(bar.low)
        assert config.instrument.validates_price(bar.close)
        assert bar.volume.value >= 0
        assert bar.volume.value % config.instrument.quantity_increment.value == 0


def test_synthetic_source_seed_is_reproducible_and_noise_changes_data() -> None:
    config = OnlyBacktestConfig.load(CONFIG)
    instrument_config = replace(
        config.synthetic_source.instruments[0],
        noise_model=OnlySyntheticNoiseModel(True, 3),
    )
    noisy = replace(config, synthetic_source=replace(config.synthetic_source, instruments=(instrument_config,)))
    same = replace(noisy, synthetic_source=replace(noisy.synthetic_source, random_seed=20260715))
    different = replace(noisy, synthetic_source=replace(noisy.synthetic_source, random_seed=20260716))
    first = tuple(item.to_dict() for item in _load(noisy).records)
    second = tuple(item.to_dict() for item in _load(same).records)
    third = tuple(item.to_dict() for item in _load(different).records)
    assert first == second
    assert first != third
    assert Decimal(str(first[0]["source_sequence"])) == Decimal(1)
