"""Immutable historical replay boundary used by streaming catch-up."""

from dataclasses import dataclass

from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp


@dataclass(frozen=True, slots=True)
class OnlyHistoricalWatermark:
    source_id: OnlyMarketDataSourceId
    instrument_id: OnlyInstrumentId
    bar_type: OnlyBarType
    last_bar_start: OnlyTimestamp
    last_bar_end: OnlyTimestamp
    data_version: OnlyDataVersion
    content_fingerprint: str

    def __post_init__(self) -> None:
        if not self.content_fingerprint.strip():
            raise ValueError("historical watermark requires a content fingerprint")
