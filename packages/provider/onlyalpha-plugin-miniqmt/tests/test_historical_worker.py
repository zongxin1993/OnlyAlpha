from __future__ import annotations

import os
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from onlyalpha_plugin_miniqmt.historical_worker.cache import (
    OnlyMiniQmtIsolatedWarmupCacheProvider,
    OnlyMiniQmtWarmupFetchError,
)
from onlyalpha_plugin_miniqmt.historical_worker.client import OnlyMiniQmtHistoricalIsolatedClient
from onlyalpha_plugin_miniqmt.historical_worker.compatibility import resolve_profile
from onlyalpha_plugin_miniqmt.historical_worker.models import OnlyMiniQmtWorkerRequest
from onlyalpha_plugin_miniqmt.historical_worker.protocol import tail
from onlyalpha_plugin_miniqmt.historical_worker.query import query_history
from onlyalpha_plugin_miniqmt.historical_worker.validation import validate_records

from onlyalpha.cache.historical import OnlyHistoricalCacheService, OnlyParquetHistoricalCacheStore
from onlyalpha.cache.historical.models import OnlyHistoricalDataRequest
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.identifiers import OnlyDataVersion
from onlyalpha.data.warmup import OnlyHistoricalWarmupRequest, OnlyHistoricalWarmupStatus
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyPriceType,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp

pytestmark = [pytest.mark.contract, pytest.mark.miniqmt]

_HELPER = Path(__file__).parent / "helpers" / "historical_worker.py"


def _request(*, timeout: int = 5) -> OnlyHistoricalWarmupRequest:
    instrument_id = OnlyInstrumentId.parse("600000.XSHG")
    bar_type = OnlyBarType(
        instrument_id,
        OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )
    return OnlyHistoricalWarmupRequest(
        "warmup-test",
        OnlyRuntimeId("paper-test"),
        instrument_id,
        bar_type,
        2,
        OnlyTimestamp.from_datetime(datetime(2026, 8, 3, 2, tzinfo=UTC)),
        OnlyDataVersion("test-v1"),
        OnlyAdjustmentType.RAW,
        timeout,
        "miniqmt-history-v2",
    )


def _client(tmp_path: Path, behavior: str) -> OnlyMiniQmtHistoricalIsolatedClient:
    userdata = tmp_path / "userdata_mini"
    userdata.mkdir(parents=True)
    instrument_id = _request().instrument_id
    create_request = SimpleNamespace(
        instruments={instrument_id: SimpleNamespace(price_precision=2, quantity_precision=0)}
    )

    def command(request_path: Path) -> tuple[str, ...]:
        if behavior == "sleep":
            return (
                sys.executable,
                "-c",
                "import os,pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)",
                str(request_path.parent / "worker.pid"),
            )
        return (
            sys.executable,
            str(_HELPER),
            "--request",
            str(request_path),
            "--behavior",
            behavior,
        )

    return OnlyMiniQmtHistoricalIsolatedClient(
        create_request,
        userdata,
        tmp_path / "state" / "warmup",
        command,
    )


def _worker_with_fake_xtquant(tmp_path: Path, *, query_error: bool) -> OnlyMiniQmtHistoricalIsolatedClient:
    fake_root = tmp_path / "fake-sdk"
    package = fake_root / "xtquant"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text('__version__ = "fake-sdk-1"\n', encoding="utf-8")
    end_millis = _request().end_time.to_unix_millis()
    query_body = (
        "raise RuntimeError('fake query failure')"
        if query_error
        else f"return {{symbols[0]: ["
        f"{{'time': {end_millis - 60_000}, 'open': '10.00', 'high': '10.10', 'low': '9.90', "
        "'close': '10.05', 'volume': '100'}, "
        f"{{'time': {end_millis}, 'open': '10.05', 'high': '10.20', 'low': '10.00', "
        "'close': '10.10', 'volume': '200'}]}"
    )
    (package / "xtdata.py").write_text(
        "def download_history_data(*args, **kwargs):\n    return None\n\n"
        "def get_market_data_ex(fields, symbols, period, **kwargs):\n    " + query_body + "\n",
        encoding="utf-8",
    )
    userdata = tmp_path / "userdata_mini"
    userdata.mkdir()
    instrument_id = _request().instrument_id
    create_request = SimpleNamespace(
        instruments={instrument_id: SimpleNamespace(price_precision=2, quantity_precision=0)}
    )
    code = (
        "import runpy,sys; sys.path.insert(0,sys.argv[1]); "
        "sys.argv=['worker','--request',sys.argv[2]]; "
        "runpy.run_module('onlyalpha_plugin_miniqmt.historical_worker.worker',run_name='__main__')"
    )
    return OnlyMiniQmtHistoricalIsolatedClient(
        create_request,
        userdata,
        tmp_path / "state" / "warmup",
        lambda request_path: (sys.executable, "-c", code, str(fake_root), str(request_path)),
    )


def test_isolated_success_verifies_atomic_protocol_and_converts_bars(tmp_path: Path) -> None:
    result = _client(tmp_path, "success").load_warmup(_request())

    assert result.status is OnlyHistoricalWarmupStatus.SUCCESS
    assert len(result.bars) == 2
    assert result.content_fingerprint
    assert result.last_bar_end == _request().end_time
    workdirs = tuple((tmp_path / "state" / "warmup").iterdir())
    assert len(workdirs) == 1
    assert (workdirs[0] / "request.json").is_file()
    assert (workdirs[0] / "result.json").is_file()
    assert (workdirs[0] / "bars.jsonl").is_file()


def test_native_abort_is_contained_and_reported_as_worker_aborted(tmp_path: Path) -> None:
    userdata = tmp_path / "userdata_mini"
    userdata.mkdir()
    instrument_id = _request().instrument_id
    create_request = SimpleNamespace(
        instruments={instrument_id: SimpleNamespace(price_precision=2, quantity_precision=0)}
    )
    client = OnlyMiniQmtHistoricalIsolatedClient(
        create_request,
        userdata,
        tmp_path / "state" / "warmup",
        lambda _: (
            sys.executable,
            "-c",
            "import os,sys; print('before-abort'); print('native-assert', file=sys.stderr); "
            "sys.stdout.flush(); sys.stderr.flush(); os.abort()",
        ),
    )

    result = client.load_warmup(_request(timeout=15))

    assert result.status is OnlyHistoricalWarmupStatus.WORKER_ABORTED
    assert result.diagnostic is not None
    assert result.diagnostic.worker_exit_code not in (None, 0)
    assert "before-abort" in (result.diagnostic.stdout_tail or "")
    assert "native-assert" in (result.diagnostic.stderr_tail or "")
    assert not Path(result.diagnostic.working_directory or "missing", "result.json").exists()


def test_native_bson_abort_is_classified_with_query_identity(tmp_path: Path) -> None:
    userdata = tmp_path / "userdata_mini"
    userdata.mkdir()
    instrument_id = _request().instrument_id
    create_request = SimpleNamespace(
        instruments={instrument_id: SimpleNamespace(price_precision=2, quantity_precision=0)}
    )
    client = OnlyMiniQmtHistoricalIsolatedClient(
        create_request,
        userdata,
        tmp_path / "state" / "warmup",
        lambda _: (
            sys.executable,
            "-c",
            "import os,sys; "
            "sys.stderr.buffer.write('Assertion failed: u < 1000000, bsonobj.cpp'.encode('utf-16-le')); "
            "sys.stderr.flush(); os.abort()",
        ),
    )

    result = client.load_warmup(_request(timeout=15))

    assert result.status is OnlyHistoricalWarmupStatus.WORKER_ABORTED
    assert result.diagnostic is not None
    assert result.diagnostic.code == "MINIQMT_HISTORICAL_NATIVE_BSON_ABORT"
    assert "600000.SH 1m" in result.diagnostic.message


def test_actual_worker_contract_normalizes_a_fake_xtquant_shape(tmp_path: Path) -> None:
    result = _worker_with_fake_xtquant(tmp_path, query_error=False).load_warmup(_request())

    assert result.status is OnlyHistoricalWarmupStatus.SUCCESS
    assert result.provider_version == "fake-sdk-1"
    assert [str(bar.close.value) for bar in result.bars] == ["10.05", "10.10"]


def test_actual_worker_contract_maps_python_query_exception(tmp_path: Path) -> None:
    result = _worker_with_fake_xtquant(tmp_path, query_error=True).load_warmup(_request())

    assert result.status is OnlyHistoricalWarmupStatus.QUERY_FAILED
    assert result.diagnostic is not None
    assert result.diagnostic.code == "MINIQMT_HISTORICAL_QUERY_FAILED"
    assert result.diagnostic.worker_exit_code == 14


def test_timeout_terminates_worker_and_returns_structured_result(tmp_path: Path) -> None:
    result = _client(tmp_path, "sleep").load_warmup(_request(timeout=1))

    assert result.status is OnlyHistoricalWarmupStatus.TIMEOUT
    assert result.diagnostic is not None
    pid_path = Path(result.diagnostic.working_directory or "missing") / "worker.pid"
    assert pid_path.is_file()
    pid = int(pid_path.read_text(encoding="ascii"))
    with pytest.raises(OSError):
        os.kill(pid, 0)


def test_half_written_output_is_never_accepted(tmp_path: Path) -> None:
    result = _client(tmp_path, "half").load_warmup(_request())

    assert result.status is OnlyHistoricalWarmupStatus.PROTOCOL_ERROR
    assert result.diagnostic is not None


def test_request_fingerprint_and_profile_are_stable(tmp_path: Path) -> None:
    client = _client(tmp_path, "success")
    first = client._transport_request(_request())  # noqa: SLF001 - transport contract assertion
    second = client._transport_request(_request())  # noqa: SLF001 - transport contract assertion

    assert first.request_fingerprint == second.request_fingerprint
    assert resolve_profile("miniqmt-history-v2").profile_id == "miniqmt-history-v2"
    assert resolve_profile("miniqmt-history-v2").query_mode.value == "END_TIME_WITH_COUNT"

    with pytest.raises(ValueError, match="unknown MiniQMT historical compatibility profile"):
        resolve_profile("miniqmt-history-v1")


def test_query_converts_utc_cutoff_to_xtquant_shanghai_wall_clock(tmp_path: Path) -> None:
    transport = _client(tmp_path, "success")._transport_request(_request())  # noqa: SLF001

    class CapturingXtData:
        def __init__(self) -> None:
            self.download: tuple[object, ...] | None = None
            self.query: tuple[tuple[object, ...], dict[str, object]] | None = None

        def download_history_data(self, *args: object) -> None:
            self.download = args

        def get_market_data_ex(self, *args: object, **kwargs: object) -> dict[str, object]:
            self.query = (args, kwargs)
            return {transport.xt_symbol: []}

    xtdata = CapturingXtData()

    query_history(xtdata, transport)

    assert xtdata.download == (transport.xt_symbol, "1m", "20260724100000", "20260803100000")
    assert xtdata.query is not None
    assert xtdata.query[1]["end_time"] == "20260803100000"


def test_parent_rejects_duplicate_or_out_of_order_transport_records(tmp_path: Path) -> None:
    request = _client(tmp_path, "success")._transport_request(_request())  # noqa: SLF001
    record = {
        "instrument_id": request.instrument_id,
        "bar_type": request.period,
        "bar_start_ns": request.end_time_ns - 60_000_000_000,
        "bar_end_ns": request.end_time_ns,
        "ts_event_ns": request.end_time_ns,
        "open": "10.00",
        "high": "10.10",
        "low": "9.90",
        "close": "10.05",
        "volume": "100",
    }

    with pytest.raises(ValueError, match="strictly increasing"):
        validate_records((record, dict(record)), request, require_count=True)


def test_transport_request_rejects_unknown_protocol_or_missing_userdata(tmp_path: Path) -> None:
    payload = OnlyMiniQmtWorkerRequest(
        "id",
        str(tmp_path / "missing"),
        "600000.XSHG",
        "600000.SH",
        "1m",
        1,
        "2026-08-03T02:00:00Z",
        1,
        ("time",),
        "none",
        False,
        2,
        0,
        "miniqmt-history-v2",
        "END_TIME_WITH_COUNT",
        True,
        1,
        10,
    )
    with pytest.raises(ValueError, match="not a directory"):
        payload.validate()


def test_log_tail_decodes_native_windows_utf16_and_remains_bounded(tmp_path: Path) -> None:
    log = tmp_path / "native-stderr.log"
    log.write_bytes(("prefix\n" + "Assertion failed: u < 1000000\n").encode("utf-16-le"))

    value = tail(log, maximum_chars=32)

    assert value is not None
    assert "Assertion failed" in value
    assert "\x00" not in value
    assert len(value) <= 32


def test_validated_cache_reuses_matching_profile_but_never_stale_coverage(tmp_path: Path) -> None:
    warmup = _request()
    end = warmup.end_time.to_datetime()
    cache_request = OnlyHistoricalDataRequest(
        warmup.instrument_id,
        warmup.bar_type,
        OnlyTimeRange(end - timedelta(days=10), end + timedelta(microseconds=1)),
        warmup.adjustment_type,
    )
    service = OnlyHistoricalCacheService(OnlyParquetHistoricalCacheStore(tmp_path / "cache"))
    first_provider = OnlyMiniQmtIsolatedWarmupCacheProvider(_client(tmp_path / "first", "success"), warmup, "miniqmt")

    first = service.load(cache_request, first_provider)
    abort_provider = OnlyMiniQmtIsolatedWarmupCacheProvider(_client(tmp_path / "second", "half"), warmup, "miniqmt")
    second = service.load(cache_request, abort_provider)

    assert first.records == second.records
    assert first.manifest.key.data_version == "test-v1"
    assert first.manifest.key.compatibility_profile_id == "miniqmt-history-v2"
    assert first.manifest.time_semantics_version == 2
    stale_end = end + timedelta(minutes=1)
    stale_request = replace(cache_request, time_range=OnlyTimeRange(end - timedelta(days=10), stale_end))
    stale_warmup = replace(warmup, end_time=OnlyTimestamp.from_datetime(stale_end))
    stale_provider = OnlyMiniQmtIsolatedWarmupCacheProvider(
        _client(tmp_path / "third", "half"), stale_warmup, "miniqmt"
    )
    with pytest.raises(OnlyMiniQmtWarmupFetchError):
        service.load(stale_request, stale_provider)
