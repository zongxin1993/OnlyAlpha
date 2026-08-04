"""Provider-neutral contracts for mandatory streaming historical warmup."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from onlyalpha.data.identifiers import OnlyDataVersion
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyAggregationSource, OnlyBarAggregation
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp


class OnlyHistoricalWarmupStatus(StrEnum):
    SUCCESS = "SUCCESS"
    INVALID_REQUEST = "INVALID_REQUEST"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    IMPORT_FAILED = "IMPORT_FAILED"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    QUERY_FAILED = "QUERY_FAILED"
    EMPTY_RESULT = "EMPTY_RESULT"
    INVALID_DATA = "INVALID_DATA"
    WORKER_ABORTED = "WORKER_ABORTED"
    TIMEOUT = "TIMEOUT"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"


class OnlyHistoricalValidationError(RuntimeError):
    """A historical result violated the frozen cross-process contract."""


@dataclass(frozen=True, slots=True)
class OnlyHistoricalWarmupRequest:
    request_id: str
    runtime_id: OnlyRuntimeId
    instrument_id: OnlyInstrumentId
    bar_type: OnlyBarType
    required_bars: int
    requested_start: OnlyTimestamp
    end_time: OnlyTimestamp
    bootstrap_observed_at: OnlyTimestamp
    data_version: OnlyDataVersion
    adjustment_type: OnlyAdjustmentType
    timeout_seconds: int
    compatibility_profile_id: str

    def __post_init__(self) -> None:
        if not self.request_id.strip():
            raise ValueError("historical warmup request_id cannot be blank")
        if self.instrument_id != self.bar_type.instrument_id:
            raise ValueError("historical warmup instrument and Bar type must match")
        if self.required_bars <= 0 or self.timeout_seconds <= 0:
            raise ValueError("historical warmup counts and timeout must be positive")
        if self.requested_start >= self.end_time:
            raise ValueError("historical warmup requested range must be increasing")
        if self.end_time > self.bootstrap_observed_at:
            raise ValueError("historical warmup end cannot exceed its bootstrap observation")
        if self.bar_type.aggregation_source is not OnlyAggregationSource.EXTERNAL:
            raise ValueError("historical warmup requires an external Bar type")
        if self.bar_type.specification.aggregation is not OnlyBarAggregation.TIME:
            raise ValueError("historical warmup supports time Bars only")
        if self.adjustment_type is not OnlyAdjustmentType.RAW:
            raise ValueError("historical warmup requires explicit RAW adjustment")
        if not str(self.data_version).strip() or not self.compatibility_profile_id.strip():
            raise ValueError("historical warmup data version and compatibility profile are required")


@dataclass(frozen=True, slots=True)
class OnlyHistoricalWarmupDiagnostic:
    code: str
    message: str
    worker_exit_code: int | None
    stderr_tail: str | None
    stdout_tail: str | None
    request_fingerprint: str
    working_directory: str | None
    provider_version: str | None
    compatibility_profile_id: str | None
    userdata_mini_path: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyHistoricalWarmupResult:
    status: OnlyHistoricalWarmupStatus
    bars: tuple[OnlyBar, ...]
    request_fingerprint: str
    content_fingerprint: str | None
    first_bar_end: OnlyTimestamp | None
    last_bar_end: OnlyTimestamp | None
    bootstrap_observed_at: OnlyTimestamp
    requested_start: OnlyTimestamp
    requested_end: OnlyTimestamp
    provider_raw_bar_count: int
    accepted_bar_count: int
    rejected_out_of_range_count: int
    provider_raw_last_bar_end: OnlyTimestamp | None
    accepted_last_bar_end: OnlyTimestamp | None
    provider: str
    provider_version: str | None
    compatibility_profile_id: str | None
    diagnostic: OnlyHistoricalWarmupDiagnostic | None
    working_directory: str | None = None

    def __post_init__(self) -> None:
        if self.status is OnlyHistoricalWarmupStatus.SUCCESS:
            if not self.bars or self.content_fingerprint is None:
                raise ValueError("successful historical warmup requires Bars and content fingerprint")
            if self.first_bar_end is None or self.last_bar_end is None or self.diagnostic is not None:
                raise ValueError("successful historical warmup has invalid boundary metadata")
            if self.accepted_bar_count != len(self.bars) or self.accepted_bar_count <= 0:
                raise ValueError("successful historical warmup accepted count must match Bars")
            if self.accepted_last_bar_end != self.last_bar_end:
                raise ValueError("successful historical warmup accepted boundary must match Bars")
        elif self.bars or self.content_fingerprint is not None or self.diagnostic is None:
            raise ValueError("failed historical warmup must contain only structured diagnostics")
        if self.requested_start >= self.requested_end or self.requested_end > self.bootstrap_observed_at:
            raise ValueError("historical warmup result has invalid frozen request boundaries")
        if min(self.provider_raw_bar_count, self.accepted_bar_count, self.rejected_out_of_range_count) < 0:
            raise ValueError("historical warmup result counts cannot be negative")
        if self.provider_raw_bar_count < self.accepted_bar_count + self.rejected_out_of_range_count:
            raise ValueError("historical warmup provider count cannot be less than classified rows")


class OnlyHistoricalWarmupPort(Protocol):
    def load_warmup(self, request: OnlyHistoricalWarmupRequest) -> OnlyHistoricalWarmupResult: ...


def only_validate_historical_warmup_result(
    request: OnlyHistoricalWarmupRequest,
    result: OnlyHistoricalWarmupResult,
) -> None:
    """Validate untrusted provider output again in the parent process."""
    if (
        result.bootstrap_observed_at != request.bootstrap_observed_at
        or result.requested_start != request.requested_start
        or result.requested_end != request.end_time
    ):
        raise OnlyHistoricalValidationError("HISTORICAL_RESULT_BOUNDARY_METADATA_MISMATCH")
    for bar in result.bars:
        if OnlyTimestamp.from_datetime(bar.bar_end) > request.end_time:
            raise OnlyHistoricalValidationError("HISTORICAL_BAR_EXCEEDS_REQUESTED_BOUNDARY")
