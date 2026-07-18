import logging
from dataclasses import replace
from datetime import time
from decimal import Decimal
from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.models import OnlyHistoricalBarRequest, OnlyHistoricalDataRange
from onlyalpha.data.synthetic import (
    OnlySyntheticHistoricalDataSource,
    OnlySyntheticNoiseModel,
)
from onlyalpha.data.synthetic.factory import OnlySyntheticDataSourceFactory
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEventScope
from onlyalpha.plugin import OnlyDataSourceCapabilities, OnlyPluginLifecycleState
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest

CONFIG = Path("tests/fixtures/legacy_macd/cluster.json")


def _source(config: OnlyClusterRunConfig) -> OnlySyntheticHistoricalDataSource:
    assert config.start_time is not None
    common = config.data_sources[0]
    bar_type = (
        config.cluster.factors[0]
        .subscriptions.instrument_bars[0]
        .bar_specification.to_bar_type(config.reference_data.instruments[0].instrument_id)
    )
    clock = OnlyBacktestClock(config.start_time)
    event_bus = OnlyEventBus(scope=OnlyEventScope(config.runtime.engine_id, config.runtime_id))
    factory = OnlySyntheticDataSourceFactory()
    source = factory.create(
        OnlyDataSourceCreateRequest(
            common.source_id,
            factory.parse_config(common.extensions),
            config.runtime.runtime_type,
            OnlyDataSourceCapabilities(historical_bars=True),
            clock,
            event_bus,
            config.reference_data.instrument_by_id,
            {bar_type.instrument_id: bar_type},
            config.reference_data.calendar_by_id,
            config.universes,
            common.coverage,
            config.runtime_id,
            common.data_version,
            common.batch_size,
            config.source_path.parent,
            logging.getLogger(__name__),
        )
    )
    assert isinstance(source, OnlySyntheticHistoricalDataSource)
    return source


def _load(config: OnlyClusterRunConfig, source: OnlySyntheticHistoricalDataSource | None = None):
    source = source or _source(config)
    if source.state is not OnlyPluginLifecycleState.RUNNING:
        source.initialize()
        source.connect()
        source.start()
    bar_type = (
        config.cluster.factors[0]
        .subscriptions.instrument_bars[0]
        .bar_specification.to_bar_type(config.reference_data.instruments[0].instrument_id)
    )
    assert config.start_time is not None and config.end_time is not None
    request = OnlyHistoricalBarRequest(
        "synthetic-test",
        frozenset({config.reference_data.instruments[0].instrument_id}),
        frozenset({bar_type}),
        OnlyHistoricalDataRange(config.start_time, config.end_time),
        config.data_sources[0].data_version,
        batch_size=37,
    )
    return source.load_bars(request)


def test_synthetic_source_generates_calendar_aware_valid_versioned_bars() -> None:
    config = OnlyClusterRunConfig.load(CONFIG)
    stream = _load(config)
    assert len(stream.records) == 720
    assert sum(len(batch) for batch in stream.batches()) == 720
    assert [int(item.source_sequence) for item in stream.records] == list(range(1, 721))
    assert all(item.data_version == config.data_sources[0].data_version for item in stream.records)
    for update in stream.records:
        bar = update.payload.bar  # type: ignore[union-attr]
        local = config.reference_data.calendars[0].to_local(bar.bar_start)
        assert local.weekday() < 5
        assert not (time(11, 30) <= local.time() < time(13))
        assert bar.high.value >= max(bar.open.value, bar.close.value)
        assert bar.low.value <= min(bar.open.value, bar.close.value)
        instrument = config.reference_data.instruments[0]
        assert instrument.validates_price(bar.open)
        assert instrument.validates_price(bar.high)
        assert instrument.validates_price(bar.low)
        assert instrument.validates_price(bar.close)
        assert bar.volume.value >= 0
        assert bar.volume.value % instrument.quantity_increment.value == 0


def test_synthetic_source_seed_is_reproducible_and_noise_changes_data() -> None:
    config = OnlyClusterRunConfig.load(CONFIG)
    source = _source(config)
    instrument_config = replace(
        source.config.instruments[0],
        noise_model=OnlySyntheticNoiseModel(True, 3),
    )
    noisy = OnlySyntheticHistoricalDataSource(replace(source.config, instruments=(instrument_config,)))
    same = OnlySyntheticHistoricalDataSource(replace(noisy.config, random_seed=20260715))
    different = OnlySyntheticHistoricalDataSource(replace(noisy.config, random_seed=20260716))
    first = tuple(item.to_dict() for item in _load(config, noisy).records)
    second = tuple(item.to_dict() for item in _load(config, same).records)
    third = tuple(item.to_dict() for item in _load(config, different).records)
    assert first == second
    assert first != third
    assert Decimal(str(first[0]["source_sequence"])) == Decimal(1)
