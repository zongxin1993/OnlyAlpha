from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MarketDataStreamSourceReferenceDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    integration_id: str = Field(min_length=1)
    integration_revision_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_type_id: str = Field(min_length=1)


class MarketDataStreamSubscribeDto(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    operation: Literal["SUBSCRIBE_BAR"]
    source_reference: MarketDataStreamSourceReferenceDto
    instrument_id: str = Field(min_length=1)
    bar_specification: Literal["1m"]
    resume_after_sequence: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")


__all__ = [name for name in globals() if name.startswith("MarketData")]
