"""Transport schema for the Market Data Product Query/Command boundary."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from onlyalpha.application.market_data_product import (
    OnlyMarketDataAcquisitionProjectionV1,
    OnlyMarketDataBarsProjectionV1,
    OnlyMarketDataCoverageGapV1,
    OnlyMarketDataCoverageProjectionV1,
    OnlyMarketDataInstrumentListProjectionV1,
    OnlyMarketDataInstrumentProjectionV1,
    OnlyMarketDataSourceProjectionV1,
    OnlyMarketDataSourceReferenceV1,
    OnlyMarketDataSourceSelectionV1,
)

_FINGERPRINT = r"^[0-9a-f]{64}$"
# Exact nanoseconds travel as canonical decimal strings: a JSON number cannot carry
# int64 nanoseconds into a browser without silent precision loss.
_NANOSECONDS = r"^(?:0|[1-9][0-9]*)$"


class _Dto(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class MarketDataSourceSelectionDto(_Dto):
    """Server-derived canonical Market Source identity reported back to the client."""

    integration_id: str = Field(min_length=1)
    integration_revision_fingerprint: str = Field(pattern=_FINGERPRINT)
    type_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    environment: str = Field(min_length=1)

    @classmethod
    def from_model(cls, value: OnlyMarketDataSourceSelectionV1) -> MarketDataSourceSelectionDto:
        return cls(
            integration_id=value.integration_id,
            integration_revision_fingerprint=value.integration_revision_fingerprint,
            type_id=value.type_id,
            source_id=value.source_id,
            environment=value.environment,
        )


class MarketDataSourceReferenceDto(_Dto):
    """Client request reference; the client asserts no canonical source identity."""

    integration_id: str = Field(min_length=1)
    integration_revision_fingerprint: str = Field(pattern=_FINGERPRINT)
    expected_type_id: str | None = Field(default=None, min_length=1)

    def to_model(self) -> OnlyMarketDataSourceReferenceV1:
        return OnlyMarketDataSourceReferenceV1(
            self.integration_id,
            self.integration_revision_fingerprint,
            self.expected_type_id,
        )


class MarketDataSourceProjectionDto(_Dto):
    integration_id: str
    integration_revision_fingerprint: str
    display_name: str
    type_id: str
    source_id: str
    environment: str

    @classmethod
    def from_model(cls, value: OnlyMarketDataSourceProjectionV1) -> MarketDataSourceProjectionDto:
        return cls(
            integration_id=value.integration_id,
            integration_revision_fingerprint=value.integration_revision_fingerprint,
            display_name=value.display_name,
            type_id=value.type_id,
            source_id=value.source_id,
            environment=value.environment,
        )


class MarketDataSourceListDto(_Dto):
    schema_version: Literal[1]
    sources: tuple[MarketDataSourceProjectionDto, ...]


class MarketDataInstrumentDto(_Dto):
    instrument_id: str
    display_symbol: str
    venue: str
    market: str
    asset_class: str
    instrument_type: str
    status: str
    market_data_capabilities: tuple[str, ...]

    @classmethod
    def from_model(cls, value: OnlyMarketDataInstrumentProjectionV1) -> MarketDataInstrumentDto:
        return cls(
            instrument_id=value.instrument_id,
            display_symbol=value.display_symbol,
            venue=value.venue,
            market=value.market,
            asset_class=value.asset_class,
            instrument_type=value.instrument_type,
            status=value.status,
            market_data_capabilities=value.market_data_capabilities,
        )


class MarketDataInstrumentListDto(_Dto):
    schema_version: Literal[1]
    source_selection: MarketDataSourceSelectionDto
    instruments: tuple[MarketDataInstrumentDto, ...]

    @classmethod
    def from_model(cls, value: OnlyMarketDataInstrumentListProjectionV1) -> MarketDataInstrumentListDto:
        return cls(
            schema_version=1,
            source_selection=MarketDataSourceSelectionDto.from_model(value.source_selection),
            instruments=tuple(MarketDataInstrumentDto.from_model(item) for item in value.instruments),
        )


class MarketDataCoverageGapDto(_Dto):
    start_ns: str = Field(pattern=_NANOSECONDS)
    end_ns: str = Field(pattern=_NANOSECONDS)

    @classmethod
    def from_model(cls, value: OnlyMarketDataCoverageGapV1) -> MarketDataCoverageGapDto:
        return cls(start_ns=str(value.start_ns), end_ns=str(value.end_ns))


class MarketDataCoverageDto(_Dto):
    status: Literal["COMPLETE", "INCOMPLETE", "UNPROVABLE"]
    manifest_id: str | None
    manifest_fingerprint: str | None
    expected_bar_count: int
    actual_bar_count: int
    issues: tuple[str, ...]
    gaps: tuple[MarketDataCoverageGapDto, ...]
    planned_acquisition_ranges: tuple[MarketDataCoverageGapDto, ...]

    @classmethod
    def from_model(cls, value: OnlyMarketDataCoverageProjectionV1) -> MarketDataCoverageDto:
        return cls(
            status=value.status,  # type: ignore[arg-type]
            manifest_id=value.manifest_id,
            manifest_fingerprint=value.manifest_fingerprint,
            expected_bar_count=value.expected_bar_count,
            actual_bar_count=value.actual_bar_count,
            issues=value.issues,
            gaps=tuple(MarketDataCoverageGapDto.from_model(item) for item in value.gaps),
            planned_acquisition_ranges=tuple(
                MarketDataCoverageGapDto.from_model(item) for item in value.planned_acquisition_ranges
            ),
        )


class MarketDataBarDto(_Dto):
    bar_start_ns: str = Field(pattern=_NANOSECONDS)
    bar_end_ns: str = Field(pattern=_NANOSECONDS)
    open: str
    high: str
    low: str
    close: str
    volume: str
    closed: bool


class MarketDataBarsDto(_Dto):
    schema_version: Literal[1]
    source_selection: MarketDataSourceSelectionDto
    instrument_id: str
    display_symbol: str
    venue: str
    market: str
    bar_specification: str
    aggregation_source: str
    adjustment: str
    closed_only: bool
    start_ns: str = Field(pattern=_NANOSECONDS)
    end_ns: str = Field(pattern=_NANOSECONDS)
    coverage: MarketDataCoverageDto
    revision_id: str | None
    revision_fingerprint: str | None
    seal_id: str | None
    bars: tuple[MarketDataBarDto, ...]

    @classmethod
    def from_model(cls, value: OnlyMarketDataBarsProjectionV1) -> MarketDataBarsDto:
        return cls(
            schema_version=1,
            source_selection=MarketDataSourceSelectionDto.from_model(value.source_selection),
            instrument_id=value.instrument_id,
            display_symbol=value.display_symbol,
            venue=value.venue,
            market=value.market,
            bar_specification=value.bar_specification,
            aggregation_source=value.aggregation_source,
            adjustment=value.adjustment,
            closed_only=value.closed_only,
            start_ns=str(value.start_ns),
            end_ns=str(value.end_ns),
            coverage=MarketDataCoverageDto.from_model(value.coverage),
            revision_id=value.revision_id,
            revision_fingerprint=value.revision_fingerprint,
            seal_id=value.seal_id,
            bars=tuple(
                MarketDataBarDto(
                    bar_start_ns=str(item.bar_start_ns),
                    bar_end_ns=str(item.bar_end_ns),
                    open=item.open,
                    high=item.high,
                    low=item.low,
                    close=item.close,
                    volume=item.volume,
                    closed=item.closed,
                )
                for item in value.bars
            ),
        )


class MarketDataAcquisitionRequestDto(_Dto):
    source_reference: MarketDataSourceReferenceDto
    instrument_id: str = Field(min_length=1)
    start_ns: str = Field(pattern=_NANOSECONDS)
    end_ns: str = Field(pattern=_NANOSECONDS)
    bar_specification: str = "1m"
    provenance: Literal["REST_BACKFILL"] = "REST_BACKFILL"


class MarketDataAcquisitionDto(_Dto):
    schema_version: Literal[1]
    acquisition_id: str
    status: Literal["PENDING", "RUNNING", "COMPLETE", "FAILED"]
    source_id: str
    integration_binding_fingerprint: str | None
    instrument_id: str
    bar_specification: str
    start_ns: str = Field(pattern=_NANOSECONDS)
    end_ns: str = Field(pattern=_NANOSECONDS)
    provenance: str
    coverage: MarketDataCoverageDto
    revision_id: str | None
    revision_fingerprint: str | None
    seal_id: str | None
    failure_detail: str | None

    @classmethod
    def from_model(cls, value: OnlyMarketDataAcquisitionProjectionV1) -> MarketDataAcquisitionDto:
        return cls(
            schema_version=1,
            acquisition_id=value.acquisition_id,
            status=value.status,  # type: ignore[arg-type]
            source_id=value.source_id,
            integration_binding_fingerprint=value.integration_binding_fingerprint,
            instrument_id=value.instrument_id,
            bar_specification=value.bar_specification,
            start_ns=str(value.start_ns),
            end_ns=str(value.end_ns),
            provenance=value.provenance,
            coverage=MarketDataCoverageDto.from_model(value.coverage),
            revision_id=value.revision_id,
            revision_fingerprint=value.revision_fingerprint,
            seal_id=value.seal_id,
            failure_detail=value.failure_detail,
        )


class MarketDataErrorDto(_Dto):
    phase: Literal["QUERY", "COMMAND"]
    code: str
    detail: str


class MarketDataErrorEnvelopeDto(_Dto):
    error: MarketDataErrorDto


__all__ = [
    "MarketDataAcquisitionDto",
    "MarketDataAcquisitionRequestDto",
    "MarketDataBarDto",
    "MarketDataBarsDto",
    "MarketDataCoverageDto",
    "MarketDataCoverageGapDto",
    "MarketDataErrorDto",
    "MarketDataErrorEnvelopeDto",
    "MarketDataInstrumentDto",
    "MarketDataInstrumentListDto",
    "MarketDataSourceListDto",
    "MarketDataSourceProjectionDto",
    "MarketDataSourceReferenceDto",
    "MarketDataSourceSelectionDto",
]
