"""Checkpointable business result prefix for Backtest market-data processing."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime

from onlyalpha.data.enums import OnlyMarketDataProcessingStatus, OnlyMarketDataQualityFlag
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId, OnlyMarketDataUpdateId
from onlyalpha.data.models import OnlyMarketDataInboundUpdate, OnlyMarketDataProcessingResult
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.market_data.dispatcher import OnlyBarDispatchResult
from onlyalpha.result.diagnostics import (
    OnlyBacktestFailure,
    OnlyResultDiagnosticSeverity,
    OnlyResultFailureStage,
)


@dataclass(frozen=True, slots=True)
class OnlyBacktestBarCompletion:
    update_id: OnlyMarketDataUpdateId
    source_id: OnlyMarketDataSourceId
    data_version: OnlyDataVersion
    source_sequence: int
    processing_sequence: int
    status: OnlyMarketDataProcessingStatus
    ts_event: OnlyTimestamp
    result_progress_sequence: int


@dataclass(frozen=True, slots=True)
class OnlyBacktestResultProgressSnapshot:
    attempted_count: int
    applied_count: int
    duplicate_count: int
    gap_detected_count: int
    rejected_count: int
    failed_count: int
    processed_bar_count: int
    quality_flags: tuple[str, ...]
    business_failures: tuple[OnlyBacktestFailure, ...]
    last_market_processing_sequence: int


class OnlyBacktestResultProgress:
    def __init__(self) -> None:
        self._attempted_count = 0
        self._applied_count = 0
        self._duplicate_count = 0
        self._gap_detected_count = 0
        self._rejected_count = 0
        self._failed_count = 0
        self._processed_bar_count = 0
        self._quality_flags: set[str] = set()
        self._business_failures: list[OnlyBacktestFailure] = []
        self._last_market_processing_sequence = 0

    def observe_market_data_result(
        self,
        result: OnlyMarketDataProcessingResult,
        update: OnlyMarketDataInboundUpdate,
    ) -> OnlyBacktestBarCompletion:
        expected = self._last_market_processing_sequence + 1
        if result.processing_sequence != expected:
            raise ValueError(
                f"BACKTEST_RESULT_PROGRESS_SEQUENCE_MISMATCH: expected={expected} actual={result.processing_sequence}"
            )
        self._attempted_count += 1
        self._last_market_processing_sequence = result.processing_sequence
        self._quality_flags.update(
            item.value for item in result.quality.flags if item is not OnlyMarketDataQualityFlag.VALID
        )
        if result.status is OnlyMarketDataProcessingStatus.APPLIED:
            self._applied_count += 1
            self._processed_bar_count += 1
        elif result.status is OnlyMarketDataProcessingStatus.GAP_DETECTED:
            self._applied_count += 1
            self._gap_detected_count += 1
            self._processed_bar_count += 1
        elif result.status is OnlyMarketDataProcessingStatus.DUPLICATE:
            self._duplicate_count += 1
        elif result.status is OnlyMarketDataProcessingStatus.REJECTED:
            self._rejected_count += 1
        elif result.status is OnlyMarketDataProcessingStatus.FAILED:
            self._failed_count += 1
        self._observe_failure(result, update)
        return OnlyBacktestBarCompletion(
            update.update_id,
            update.source_id,
            update.data_version,
            int(update.source_sequence),
            result.processing_sequence,
            result.status,
            update.ts_event,
            self._attempted_count,
        )

    def capture_checkpoint(self) -> object:
        snapshot = self.snapshot()
        return {
            "applied_count": snapshot.applied_count,
            "attempted_count": snapshot.attempted_count,
            "business_failures": [self._failure_payload(item) for item in snapshot.business_failures],
            "duplicate_count": snapshot.duplicate_count,
            "failed_count": snapshot.failed_count,
            "gap_detected_count": snapshot.gap_detected_count,
            "last_market_processing_sequence": snapshot.last_market_processing_sequence,
            "processed_bar_count": snapshot.processed_bar_count,
            "quality_flags": list(snapshot.quality_flags),
            "rejected_count": snapshot.rejected_count,
        }

    def restore_checkpoint(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Backtest Result Progress checkpoint must be an object")
        self._attempted_count = int(payload["attempted_count"])
        self._applied_count = int(payload["applied_count"])
        self._duplicate_count = int(payload["duplicate_count"])
        self._gap_detected_count = int(payload["gap_detected_count"])
        self._rejected_count = int(payload["rejected_count"])
        self._failed_count = int(payload["failed_count"])
        self._processed_bar_count = int(payload["processed_bar_count"])
        quality_flags = payload["quality_flags"]
        if not isinstance(quality_flags, list):
            raise ValueError("Backtest Result Progress quality flags must be an array")
        self._quality_flags = {str(item) for item in quality_flags}
        failures = payload["business_failures"]
        if not isinstance(failures, list):
            raise ValueError("Backtest Result Progress failures must be an array")
        self._business_failures = [self._failure_from_payload(item) for item in failures]
        self._last_market_processing_sequence = int(payload["last_market_processing_sequence"])

    def snapshot(self) -> OnlyBacktestResultProgressSnapshot:
        return OnlyBacktestResultProgressSnapshot(
            self._attempted_count,
            self._applied_count,
            self._duplicate_count,
            self._gap_detected_count,
            self._rejected_count,
            self._failed_count,
            self._processed_bar_count,
            tuple(sorted(self._quality_flags)),
            tuple(self._business_failures),
            self._last_market_processing_sequence,
        )

    def _observe_failure(
        self,
        result: OnlyMarketDataProcessingResult,
        update: OnlyMarketDataInboundUpdate,
    ) -> None:
        failures: list[tuple[OnlyResultFailureStage, str, str, str | None]] = []
        if result.failure is not None:
            failures.append(
                (
                    OnlyResultFailureStage.MARKET_DATA_PIPELINE,
                    result.failure.error_type,
                    result.failure.message,
                    None,
                )
            )
        elif result.status is OnlyMarketDataProcessingStatus.REJECTED:
            failures.append(
                (
                    OnlyResultFailureStage.MARKET_DATA_PIPELINE,
                    "OnlyMarketDataValidationError",
                    "; ".join(result.validation.reasons) or "market data rejected",
                    None,
                )
            )
        for dispatch in result.dispatches:
            if not isinstance(dispatch, OnlyBarDispatchResult):
                continue
            if dispatch.error_message is None:
                continue
            exception_type, separator, message = dispatch.error_message.partition(": ")
            if not separator:
                exception_type, message = "OnlyStrategyCallbackError", dispatch.error_message
            failures.append((OnlyResultFailureStage.STRATEGY, exception_type, message, str(dispatch.cluster_id)))
        for stage, exception_type, message, cluster_id in failures:
            sequence = len(self._business_failures) + 1
            stable = (
                f"{update.runtime_id}:{result.processing_sequence}:{update.update_id}:{cluster_id}:"
                f"{exception_type}:{message}"
            )
            self._business_failures.append(
                OnlyBacktestFailure(
                    failure_id=hashlib.sha256(stable.encode("utf-8")).hexdigest(),
                    sequence=sequence,
                    severity=OnlyResultDiagnosticSeverity.ERROR,
                    stage=stage,
                    exception_type=exception_type,
                    message=message,
                    ts_event=update.ts_event.to_datetime(),
                    trading_day=update.ts_event.to_datetime().date(),
                    runtime_id=str(update.runtime_id),
                    cluster_id=cluster_id,
                    source_id=str(update.source_id),
                    instrument_id=str(update.instrument_id),
                    bar_type=None if update.bar_type is None else update.bar_type.to_json(),
                )
            )

    @staticmethod
    def _failure_payload(failure: OnlyBacktestFailure) -> dict[str, object]:
        return {
            "bar_type": failure.bar_type,
            "cluster_id": failure.cluster_id,
            "exception_type": failure.exception_type,
            "failure_id": failure.failure_id,
            "instrument_id": failure.instrument_id,
            "message": failure.message,
            "runtime_id": failure.runtime_id,
            "sequence": failure.sequence,
            "severity": failure.severity.value,
            "source_id": failure.source_id,
            "stage": failure.stage.value,
            "trading_day": None if failure.trading_day is None else failure.trading_day.isoformat(),
            "ts_event": None if failure.ts_event is None else failure.ts_event.isoformat(),
        }

    @staticmethod
    def _failure_from_payload(payload: object) -> OnlyBacktestFailure:
        if not isinstance(payload, dict):
            raise ValueError("Backtest Result Progress failure must be an object")
        ts_event = payload["ts_event"]
        trading_day = payload["trading_day"]
        return OnlyBacktestFailure(
            failure_id=str(payload["failure_id"]),
            sequence=int(payload["sequence"]),
            severity=OnlyResultDiagnosticSeverity(str(payload["severity"])),
            stage=OnlyResultFailureStage(str(payload["stage"])),
            exception_type=str(payload["exception_type"]),
            message=str(payload["message"]),
            ts_event=None if ts_event is None else datetime.fromisoformat(str(ts_event)),
            trading_day=None if trading_day is None else date.fromisoformat(str(trading_day)),
            runtime_id=None if payload["runtime_id"] is None else str(payload["runtime_id"]),
            cluster_id=None if payload["cluster_id"] is None else str(payload["cluster_id"]),
            source_id=None if payload["source_id"] is None else str(payload["source_id"]),
            instrument_id=None if payload["instrument_id"] is None else str(payload["instrument_id"]),
            bar_type=None if payload["bar_type"] is None else str(payload["bar_type"]),
        )
