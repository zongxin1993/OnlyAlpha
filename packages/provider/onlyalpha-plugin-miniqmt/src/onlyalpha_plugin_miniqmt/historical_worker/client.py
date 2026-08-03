"""Parent-side isolated worker client and untrusted-output verification."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from onlyalpha.data.warmup import (
    OnlyHistoricalWarmupDiagnostic,
    OnlyHistoricalWarmupRequest,
    OnlyHistoricalWarmupResult,
    OnlyHistoricalWarmupStatus,
)
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlySessionType
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest

from ..mapping.exchange import to_xt_symbol
from .compatibility import resolve_profile
from .models import OnlyMiniQmtWorkerRequest
from .protocol import (
    PROTOCOL_VERSION,
    atomic_write_json,
    bars_payload,
    bytes_fingerprint,
    fingerprint,
    read_json,
    read_jsonl,
    tail,
)
from .validation import validate_records

type OnlyWorkerCommandBuilder = Callable[[Path], Sequence[str]]

_FAILURE_STATUSES = {
    "INVALID_REQUEST": OnlyHistoricalWarmupStatus.INVALID_REQUEST,
    "IMPORT_FAILED": OnlyHistoricalWarmupStatus.IMPORT_FAILED,
    "PROVIDER_UNAVAILABLE": OnlyHistoricalWarmupStatus.PROVIDER_UNAVAILABLE,
    "DOWNLOAD_FAILED": OnlyHistoricalWarmupStatus.DOWNLOAD_FAILED,
    "QUERY_FAILED": OnlyHistoricalWarmupStatus.QUERY_FAILED,
    "EMPTY_RESULT": OnlyHistoricalWarmupStatus.EMPTY_RESULT,
    "INVALID_DATA": OnlyHistoricalWarmupStatus.INVALID_DATA,
    "PROTOCOL_ERROR": OnlyHistoricalWarmupStatus.PROTOCOL_ERROR,
}


class OnlyMiniQmtHistoricalIsolatedClient:
    def __init__(
        self,
        create_request: OnlyDataSourceCreateRequest,
        userdata_mini_path: Path,
        working_root: Path,
        command_builder: OnlyWorkerCommandBuilder | None = None,
    ) -> None:
        self._create_request = create_request
        self._userdata_mini_path = userdata_mini_path
        self._working_root = working_root
        self._command_builder = command_builder or self._default_command

    def load_warmup(self, request: OnlyHistoricalWarmupRequest) -> OnlyHistoricalWarmupResult:
        try:
            transport = self._transport_request(request)
        except Exception as exc:
            return self._failure_without_worker(request, OnlyHistoricalWarmupStatus.INVALID_REQUEST, exc)
        workdir = self._working_root / f"request-{uuid4()}"
        workdir.mkdir(parents=True, exist_ok=False)
        request_path = workdir / "request.json"
        atomic_write_json(request_path, transport.payload())
        stdout_path, stderr_path = workdir / "stdout.log", workdir / "stderr.log"
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            try:
                process = subprocess.Popen(
                    list(self._command_builder(request_path)),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    cwd=workdir,
                )
            except Exception as exc:
                return self._failure(
                    OnlyHistoricalWarmupStatus.PROVIDER_UNAVAILABLE,
                    "MINIQMT_HISTORICAL_WORKER_SPAWN_FAILED",
                    str(exc),
                    transport,
                    workdir,
                    None,
                    provider_version=self._installed_provider_version(),
                )
            try:
                exit_code = process.wait(timeout=request.timeout_seconds)
            except subprocess.TimeoutExpired:
                self._terminate(process)
                return self._failure(
                    OnlyHistoricalWarmupStatus.TIMEOUT,
                    "MINIQMT_HISTORICAL_WORKER_TIMEOUT",
                    f"historical worker exceeded {request.timeout_seconds}s",
                    transport,
                    workdir,
                    process.returncode,
                    provider_version=self._installed_provider_version(),
                )
        if exit_code != 0:
            return self._failed_worker(transport, workdir, exit_code)
        try:
            return self._success(request, transport, workdir)
        except Exception as exc:
            return self._failure(
                OnlyHistoricalWarmupStatus.PROTOCOL_ERROR,
                "MINIQMT_HISTORICAL_PROTOCOL_ERROR",
                str(exc),
                transport,
                workdir,
                exit_code,
            )

    def _transport_request(self, request: OnlyHistoricalWarmupRequest) -> OnlyMiniQmtWorkerRequest:
        profile = resolve_profile(request.compatibility_profile_id)
        instrument = self._create_request.instruments[request.instrument_id]
        minutes = request.bar_type.specification.step
        period = "1d" if minutes == 1_440 else f"{minutes // 60}h" if minutes % 60 == 0 else f"{minutes}m"
        end = request.end_time.to_datetime().astimezone(UTC).isoformat().replace("+00:00", "Z")
        return OnlyMiniQmtWorkerRequest(
            request_id=request.request_id,
            userdata_mini_path=str(self._userdata_mini_path.resolve()),
            instrument_id=str(request.instrument_id),
            xt_symbol=to_xt_symbol(request.instrument_id),
            period=period,
            required_bars=request.required_bars,
            end_time=end,
            end_time_ns=request.end_time.unix_nanos,
            fields=profile.explicit_fields,
            adjustment=profile.adjustment,
            fill_data=profile.fill_data,
            price_precision=instrument.price_precision,
            quantity_precision=instrument.quantity_precision,
            compatibility_profile_id=profile.profile_id,
            query_mode=profile.query_mode.value,
            download_before_query=profile.download_before_query,
            overlap_bars=profile.overlap_bars,
            maximum_count=profile.maximum_count,
        )

    def _success(
        self,
        request: OnlyHistoricalWarmupRequest,
        transport: OnlyMiniQmtWorkerRequest,
        workdir: Path,
    ) -> OnlyHistoricalWarmupResult:
        result_path, bars_path = workdir / "result.json", workdir / "bars.jsonl"
        if not result_path.is_file() or not bars_path.is_file():
            raise ValueError("successful worker omitted result.json or bars.jsonl")
        manifest = read_json(result_path)
        records = read_jsonl(bars_path)
        if manifest.get("protocol_version") != PROTOCOL_VERSION or manifest.get("status") != "SUCCESS":
            raise ValueError("invalid successful result manifest")
        if manifest.get("request_id") != request.request_id:
            raise ValueError("result request_id mismatch")
        if manifest.get("request_fingerprint") != transport.request_fingerprint:
            raise ValueError("result request fingerprint mismatch")
        if int(manifest.get("row_count", -1)) != len(records):
            raise ValueError("result row count mismatch")
        validate_records(records, transport, require_count=True)
        encoded = bars_payload(records)
        if manifest.get("bars_file_fingerprint") != bytes_fingerprint(encoded):
            raise ValueError("Bars file fingerprint mismatch")
        content_fingerprint = fingerprint(records)
        if manifest.get("content_fingerprint") != content_fingerprint:
            raise ValueError("content fingerprint mismatch")
        bars = tuple(self._bar(record, request) for record in records)
        first, last = bars[0], bars[-1]
        if int(manifest.get("first_bar_end_ns", -1)) != OnlyTimestamp.from_datetime(first.bar_end).unix_nanos:
            raise ValueError("first Bar boundary mismatch")
        if int(manifest.get("last_bar_end_ns", -1)) != OnlyTimestamp.from_datetime(last.bar_end).unix_nanos:
            raise ValueError("last Bar boundary mismatch")
        return OnlyHistoricalWarmupResult(
            OnlyHistoricalWarmupStatus.SUCCESS,
            bars,
            transport.request_fingerprint,
            content_fingerprint,
            OnlyTimestamp.from_datetime(first.bar_end),
            OnlyTimestamp.from_datetime(last.bar_end),
            "miniqmt",
            None if manifest.get("provider_version") is None else str(manifest["provider_version"]),
            transport.compatibility_profile_id,
            None,
        )

    def _bar(self, record: dict[str, Any], request: OnlyHistoricalWarmupRequest) -> OnlyBar:
        start = OnlyTimestamp.from_unix_nanos(int(record["bar_start_ns"])).to_datetime()
        end = OnlyTimestamp.from_unix_nanos(int(record["bar_end_ns"])).to_datetime()
        instrument = self._create_request.instruments[request.instrument_id]
        return OnlyBar(
            bar_type=request.bar_type,
            open=OnlyPrice(Decimal(str(record["open"])), instrument.price_precision),
            high=OnlyPrice(Decimal(str(record["high"])), instrument.price_precision),
            low=OnlyPrice(Decimal(str(record["low"])), instrument.price_precision),
            close=OnlyPrice(Decimal(str(record["close"])), instrument.price_precision),
            volume=OnlyQuantity(Decimal(str(record["volume"])), instrument.quantity_precision),
            quote_volume=None,
            turnover=None,
            trade_count=None,
            open_interest=None,
            bar_start=start,
            bar_end=end,
            ts_event=end,
            ts_init=end,
            is_closed=True,
            revision=0,
            adjustment_type=OnlyAdjustmentType.RAW,
            trading_day=start.astimezone(ZoneInfo("Asia/Shanghai")).date(),
            session_type=OnlySessionType.REGULAR,
        )

    def _failed_worker(
        self, transport: OnlyMiniQmtWorkerRequest, workdir: Path, exit_code: int
    ) -> OnlyHistoricalWarmupResult:
        failure_path = workdir / "failure.json"
        if failure_path.is_file():
            try:
                manifest = read_json(failure_path)
                if (
                    manifest.get("protocol_version") == PROTOCOL_VERSION
                    and manifest.get("request_fingerprint") == transport.request_fingerprint
                ):
                    status = _FAILURE_STATUSES.get(str(manifest.get("status")))
                    if status is not None:
                        return self._failure(
                            status,
                            str(manifest.get("code", "MINIQMT_HISTORICAL_WORKER_FAILED")),
                            str(manifest.get("message", "historical worker failed")),
                            transport,
                            workdir,
                            exit_code,
                            provider_version=(
                                None if manifest.get("provider_version") is None else str(manifest["provider_version"])
                            ),
                        )
            except Exception:
                pass
        stderr_tail = tail(workdir / "stderr.log")
        if stderr_tail is not None and "bsonobj.cpp" in stderr_tail and "u < 1000000" in stderr_tail:
            return self._failure(
                OnlyHistoricalWarmupStatus.WORKER_ABORTED,
                "MINIQMT_HISTORICAL_NATIVE_BSON_ABORT",
                (
                    "XtQuant aborted in its native BSON decoder while reading "
                    f"{transport.xt_symbol} {transport.period}; the provider data path for this query "
                    "is not readable by the current XtQuant service/SDK"
                ),
                transport,
                workdir,
                exit_code,
                provider_version=self._installed_provider_version(),
            )
        return self._failure(
            OnlyHistoricalWarmupStatus.WORKER_ABORTED,
            "MINIQMT_HISTORICAL_WORKER_ABORTED",
            "historical worker exited abnormally without a valid failure manifest",
            transport,
            workdir,
            exit_code,
            provider_version=self._installed_provider_version(),
        )

    def _failure(
        self,
        status: OnlyHistoricalWarmupStatus,
        code: str,
        message: str,
        transport: OnlyMiniQmtWorkerRequest,
        workdir: Path,
        exit_code: int | None,
        *,
        provider_version: str | None = None,
    ) -> OnlyHistoricalWarmupResult:
        return OnlyHistoricalWarmupResult(
            status,
            (),
            transport.request_fingerprint,
            None,
            None,
            None,
            "miniqmt",
            provider_version,
            transport.compatibility_profile_id,
            OnlyHistoricalWarmupDiagnostic(
                code,
                message,
                exit_code,
                tail(workdir / "stderr.log"),
                tail(workdir / "stdout.log"),
                transport.request_fingerprint,
                str(workdir),
                provider_version,
                transport.compatibility_profile_id,
                str(self._userdata_mini_path.resolve()),
            ),
        )

    def _failure_without_worker(
        self,
        request: OnlyHistoricalWarmupRequest,
        status: OnlyHistoricalWarmupStatus,
        exc: Exception,
    ) -> OnlyHistoricalWarmupResult:
        request_fingerprint = fingerprint(
            {"request_id": request.request_id, "compatibility_profile_id": request.compatibility_profile_id}
        )
        return OnlyHistoricalWarmupResult(
            status,
            (),
            request_fingerprint,
            None,
            None,
            None,
            "miniqmt",
            None,
            request.compatibility_profile_id,
            OnlyHistoricalWarmupDiagnostic(
                "MINIQMT_HISTORICAL_INVALID_REQUEST",
                str(exc),
                None,
                None,
                None,
                request_fingerprint,
                None,
                None,
                request.compatibility_profile_id,
                str(self._userdata_mini_path.resolve()),
            ),
        )

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

    @staticmethod
    def _default_command(request_path: Path) -> Sequence[str]:
        return (
            sys.executable,
            "-m",
            "onlyalpha_plugin_miniqmt.historical_worker.worker",
            "--request",
            str(request_path),
        )

    @staticmethod
    def _installed_provider_version() -> str | None:
        try:
            return version("xtquant")
        except PackageNotFoundError:
            return None
