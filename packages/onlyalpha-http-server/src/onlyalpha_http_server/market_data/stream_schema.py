from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from .schema import MarketDataBarDto, MarketDataBarSpecificationDto


class MarketDataStreamSourceReferenceDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    integration_id: str = Field(min_length=1)
    integration_revision_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_type_id: str = Field(min_length=1)


class MarketDataStreamSubscribeDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2]
    operation: Literal["SUBSCRIBE_BAR"]
    source_reference: MarketDataStreamSourceReferenceDto
    instrument_id: str = Field(min_length=1)
    bar_specification: MarketDataBarSpecificationDto
    resume_after_sequence: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")
    resume_plan_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_resume_pair(self) -> MarketDataStreamSubscribeDto:
        if self.resume_after_sequence != "0" and self.resume_plan_fingerprint is None:
            raise ValueError("MARKET_DATA_RESUME_PLAN_MISMATCH")
        return self


class _Event(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[2]


class MarketDataSubscribedDto(_Event):
    event: Literal["SUBSCRIBED"]
    stream_id: str
    source_id: str
    instrument_id: str
    resolution_mode: Literal["EXTERNAL_NATIVE", "INTERNAL_DERIVED"]
    resolution_plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    cursor_bar_step_minutes: int = Field(ge=1, le=240)


class MarketDataStateDto(_Event):
    event: Literal["STATE"]
    state: Literal["CONNECTING", "RECOVERING", "READY", "DEGRADED", "FAILED", "CLOSED"]


class MarketDataBaseCursorDto(_Event):
    event: Literal["BASE_CURSOR"]
    sequence: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")


class _BarEvent(_Event):
    source_id: str
    instrument_id: str
    bar_specification: MarketDataBarSpecificationDto
    bar: MarketDataBarDto


class MarketDataBarPreviewDto(_BarEvent):
    event: Literal["BAR_PREVIEW"]


class MarketDataBarClosedDto(_BarEvent):
    event: Literal["BAR_CLOSED"]
    sequence: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")


class MarketDataStreamErrorDto(_Event):
    event: Literal["ERROR"]
    code: str
    detail: str | None = None


MarketDataStreamEventDto = Annotated[
    MarketDataSubscribedDto
    | MarketDataStateDto
    | MarketDataBaseCursorDto
    | MarketDataBarPreviewDto
    | MarketDataBarClosedDto
    | MarketDataStreamErrorDto,
    Field(discriminator="event"),
]
market_data_stream_event_adapter: TypeAdapter[MarketDataStreamEventDto] = TypeAdapter(MarketDataStreamEventDto)


__all__ = [name for name in globals() if name.startswith("MarketData")]
