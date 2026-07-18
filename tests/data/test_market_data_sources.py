from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest

from onlyalpha.data.enums import (
    OnlyMarketDataProcessingStatus,
    OnlyMarketDataQualityFlag,
    OnlyMarketDataType,
)
from onlyalpha.data.identifiers import (
    OnlyDataSequence,
    OnlyDataVersion,
    OnlyMarketDataSourceId,
    OnlyMarketDataUpdateId,
)
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataRange,
    OnlyHistoricalDataStream,
    OnlyHistoricalReplayConfig,
    OnlyInstrumentStatusUpdate,
    OnlyMarketDataInboundUpdate,
    OnlyMarketDataQuality,
)
from onlyalpha.data.processor import OnlyMarketDataGapDetector
from onlyalpha.data.sources import (
    OnlyCsvHistoricalDataSource,
    OnlyHistoricalDataSourceError,
    OnlyInMemoryHistoricalDataSource,
    OnlyParquetHistoricalDataSource,
)
from onlyalpha.domain.time import OnlyTimestamp

from ..integration_demo.environment import DAY_ONE, INSTRUMENT_ID, OnlyIntegrationEnvironment


def update_for(
    env: OnlyIntegrationEnvironment,
    minute: int,
    sequence: int,
    source_id: OnlyMarketDataSourceId,
    *,
    close: str = "10.00",
    update_id: str | None = None,
) -> OnlyMarketDataInboundUpdate:
    bar = env.make_bar(DAY_ONE, minute, close)
    return OnlyMarketDataInboundUpdate(
        OnlyMarketDataUpdateId(update_id or f"update-{sequence}"),
        env.runtime.config.runtime_id,  # type: ignore[arg-type]
        source_id,
        OnlyDataSequence(sequence),
        OnlyDataVersion("fixture-v1"),
        bar.instrument_id,
        OnlyMarketDataType.BAR,
        OnlyBarUpdate(bar),
        OnlyTimestamp.from_datetime(bar.ts_event),
        OnlyTimestamp.from_datetime(bar.ts_init),
        OnlyMarketDataQuality(frozenset({OnlyMarketDataQualityFlag.UNADJUSTED})),
    )


def request_for(
    env: OnlyIntegrationEnvironment, start_minute: int = 0, end_minute: int = 10
) -> OnlyHistoricalBarRequest:
    start = datetime.combine(DAY_ONE, time(1, 30), tzinfo=UTC) + timedelta(minutes=start_minute + 1)
    end = datetime.combine(DAY_ONE, time(1, 30), tzinfo=UTC) + timedelta(minutes=end_minute + 1)
    return OnlyHistoricalBarRequest(
        "request",
        frozenset({INSTRUMENT_ID}),
        frozenset({env.bar_1m}),
        OnlyHistoricalDataRange(start, end),
        OnlyDataVersion("fixture-v1"),
        batch_size=2,
    )


def test_update_round_trip_and_strong_source_metadata() -> None:
    env = OnlyIntegrationEnvironment()
    source_id = OnlyMarketDataSourceId("history")
    update = update_for(env, 0, 7, source_id)
    restored = OnlyMarketDataInboundUpdate.from_dict(update.to_dict())
    assert restored == update
    assert restored.source_sequence == OnlyDataSequence(7)
    assert restored.data_version == OnlyDataVersion("fixture-v1")
    assert OnlyMarketDataQualityFlag.UNADJUSTED in restored.quality.flags


def test_in_memory_source_filters_half_open_range_version_and_batches() -> None:
    env = OnlyIntegrationEnvironment()
    source_id = OnlyMarketDataSourceId("history")
    source = OnlyInMemoryHistoricalDataSource(source_id, tuple(update_for(env, i, i + 1, source_id) for i in range(4)))
    stream = source.load_bars(request_for(env, 1, 3))
    assert tuple(item.source_sequence.value for item in stream) == (2, 3)
    assert tuple(len(batch) for batch in stream.batches()) == (2,)


def test_replay_stable_order_duplicate_and_audit() -> None:
    env = OnlyIntegrationEnvironment()
    env.start()
    source_id = OnlyMarketDataSourceId("unordered-history")
    first = update_for(env, 0, 1, source_id)
    second = update_for(env, 1, 2, source_id)
    duplicate = update_for(env, 0, 3, source_id, update_id="duplicate-envelope")
    source = OnlyInMemoryHistoricalDataSource(source_id, (second, duplicate, first))
    result = env.runtime.replay_historical_bars(source, request_for(env))
    assert tuple(event.update.ts_event.unix_nanos for event in result.events) == tuple(
        sorted(event.update.ts_event.unix_nanos for event in result.events)
    )
    assert tuple(event.result.status for event in result.events) == (
        OnlyMarketDataProcessingStatus.APPLIED,
        OnlyMarketDataProcessingStatus.DUPLICATE,
        OnlyMarketDataProcessingStatus.APPLIED,
    )
    assert len(env.market_data_audit_store.records()) == 3


def test_gap_detector_distinguishes_session_break_from_missing_bar() -> None:
    env = OnlyIntegrationEnvironment()
    detector = OnlyMarketDataGapDetector({INSTRUMENT_ID: env.calendar})
    source_id = OnlyMarketDataSourceId("history")
    assert detector.assess(update_for(env, 0, 1, source_id), False) == ()
    unexpected = detector.assess(update_for(env, 2, 2, source_id), False)
    assert OnlyMarketDataQualityFlag.UNEXPECTED_GAP in unexpected

    lunch_detector = OnlyMarketDataGapDetector({INSTRUMENT_ID: env.calendar})
    lunch_detector.assess(update_for(env, 119, 1, source_id), False)
    expected = lunch_detector.assess(update_for(env, 210, 2, source_id), False)
    assert OnlyMarketDataQualityFlag.EXPECTED_SESSION_GAP in expected
    assert OnlyMarketDataQualityFlag.UNEXPECTED_GAP not in expected


def test_processor_rejects_lookahead_without_advancing_clock() -> None:
    env = OnlyIntegrationEnvironment()
    env.start()
    update = update_for(env, 0, 1, env.historical_data_source.source_id)
    before = env.runtime.clock.timestamp_ns()
    result = env.market_data_processor.process(update)
    assert result.status is OnlyMarketDataProcessingStatus.REJECTED
    assert result.validation.reasons == ("lookahead: update is later than Runtime Clock",)
    assert env.runtime.clock.timestamp_ns() == before


def test_realtime_gateway_uses_independent_queue_then_processor() -> None:
    env = OnlyIntegrationEnvironment()
    env.start()
    now = OnlyTimestamp.from_unix_nanos(env.runtime.clock.timestamp_ns())
    update = OnlyMarketDataInboundUpdate(
        OnlyMarketDataUpdateId("status-1"),
        env.runtime.config.runtime_id,  # type: ignore[arg-type]
        env.market_data_gateway.source_id,
        OnlyDataSequence(1),
        OnlyDataVersion("live-v1"),
        INSTRUMENT_ID,
        OnlyMarketDataType.INSTRUMENT_STATUS,
        OnlyInstrumentStatusUpdate(INSTRUMENT_ID, "OPEN"),
        now,
        now,
    )
    env.market_data_gateway.publish(update)
    assert len(env.market_data_inbound_queue) == 1
    results = env.runtime.drain_market_data_inbound()
    assert len(env.market_data_inbound_queue) == 0
    assert results[0].status is OnlyMarketDataProcessingStatus.IGNORED


@pytest.mark.parametrize("kind", ["csv", "parquet"])
def test_local_file_sources_preserve_decimal_utc_version_and_range(tmp_path: Path, kind: str) -> None:
    env = OnlyIntegrationEnvironment()
    source_id = OnlyMarketDataSourceId(f"{kind}-history")
    updates = tuple(update_for(env, i, i + 1, source_id, close=f"10.0{i}") for i in range(3))
    path = tmp_path / ("bars.csv" if kind == "csv" else "bars.parquet")
    source_type = OnlyCsvHistoricalDataSource if kind == "csv" else OnlyParquetHistoricalDataSource
    source_type.write(path, updates)
    source = source_type(source_id, path)
    loaded = tuple(source.load_bars(request_for(env, 1, 3)))
    assert tuple(item.source_sequence.value for item in loaded) == (2, 3)
    assert tuple(item.payload.bar.close.value for item in loaded if isinstance(item.payload, OnlyBarUpdate)) == (
        updates[1].payload.bar.close.value,  # type: ignore[union-attr]
        updates[2].payload.bar.close.value,  # type: ignore[union-attr]
    )


def test_parquet_schema_is_strict(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as parquet  # type: ignore[import-untyped]

    path = tmp_path / "invalid.parquet"
    parquet.write_table(pa.table({"wrong": [1]}), path)
    with pytest.raises(OnlyHistoricalDataSourceError, match="schema"):
        OnlyParquetHistoricalDataSource(OnlyMarketDataSourceId("history"), path)


def test_same_timestamp_merge_does_not_depend_on_stream_order() -> None:
    env_a = OnlyIntegrationEnvironment()
    env_b = OnlyIntegrationEnvironment()
    source_a = OnlyMarketDataSourceId("a")
    source_b = OnlyMarketDataSourceId("b")
    update_a = update_for(env_a, 0, 1, source_a, update_id="a")
    update_b = update_for(env_a, 0, 1, source_b, update_id="b")
    config_a = OnlyHistoricalReplayConfig(
        (OnlyHistoricalDataStream((update_b,), 1), OnlyHistoricalDataStream((update_a,), 1)),
        source_priority=(source_a, source_b),
    )
    config_b = OnlyHistoricalReplayConfig(
        (OnlyHistoricalDataStream((update_a,), 1), OnlyHistoricalDataStream((update_b,), 1)),
        source_priority=(source_a, source_b),
    )
    order_a = tuple(str(item.update_id) for item in env_a.historical_replay_service.prepare(config_a).updates)
    order_b = tuple(str(item.update_id) for item in env_b.historical_replay_service.prepare(config_b).updates)
    assert order_a == order_b == ("a", "b")


def test_reference_source_is_separate_and_read_only_candidate_provider() -> None:
    env = OnlyIntegrationEnvironment()
    assert env.reference_data_source.instrument(INSTRUMENT_ID) == env.instrument
    assert env.reference_data_source.calendar(env.calendar.calendar_id) == env.calendar
    assert env.runtime.broker_gateway is not env.market_data_gateway
