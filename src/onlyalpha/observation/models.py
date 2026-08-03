"""Canonical read model for the latest computed market node."""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.identifiers import OnlyClusterId, OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.market.session_clock import OnlyMarketSessionState
from onlyalpha.runtime.runtime import OnlyRuntimeState
from onlyalpha.runtime.streaming.phase import OnlyStreamingDataState, OnlyStreamingPhase


class OnlyObservationSource(StrEnum):
    HISTORICAL_BOOTSTRAP = "HISTORICAL_BOOTSTRAP"
    CATCH_UP = "CATCH_UP"
    LIVE = "LIVE"


OnlyObservationFields = tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True)
class OnlyMarketObservationSnapshot:
    runtime_id: OnlyRuntimeId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    bar_type: OnlyBarType
    observed_at: OnlyTimestamp
    runtime_state: OnlyRuntimeState
    streaming_phase: OnlyStreamingPhase
    market_session_state: OnlyMarketSessionState
    data_state: OnlyStreamingDataState
    observation_source: OnlyObservationSource
    latest_bar_start: OnlyTimestamp
    latest_bar_end: OnlyTimestamp
    latest_close: Decimal
    latest_volume: Decimal
    historical_watermark: OnlyTimestamp | None
    previous_market_close: OnlyTimestamp | None
    next_market_open: OnlyTimestamp
    indicator_snapshots: tuple[OnlyObservationFields, ...]
    factor_snapshots: tuple[OnlyObservationFields, ...]
    latest_order_intents: tuple[OnlyObservationFields, ...]
    market_data_lag_ms: int
    stale: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "runtime_id": str(self.runtime_id),
            "cluster_id": str(self.cluster_id),
            "instrument_id": str(self.instrument_id),
            "bar_type": str(self.bar_type),
            "observed_at": self.observed_at.to_datetime().isoformat(),
            "runtime_state": self.runtime_state.value,
            "streaming_phase": self.streaming_phase.value,
            "market_session_state": self.market_session_state.value,
            "data_state": self.data_state.value,
            "observation_source": self.observation_source.value,
            "latest_bar_start": self.latest_bar_start.to_datetime().isoformat(),
            "latest_bar_end": self.latest_bar_end.to_datetime().isoformat(),
            "latest_close": str(self.latest_close),
            "latest_volume": str(self.latest_volume),
            "historical_watermark": None
            if self.historical_watermark is None
            else self.historical_watermark.to_datetime().isoformat(),
            "previous_market_close": None
            if self.previous_market_close is None
            else self.previous_market_close.to_datetime().isoformat(),
            "next_market_open": self.next_market_open.to_datetime().isoformat(),
            "indicator_snapshots": [dict(item) for item in self.indicator_snapshots],
            "factor_snapshots": [dict(item) for item in self.factor_snapshots],
            "latest_order_intents": [dict(item) for item in self.latest_order_intents],
            "market_data_lag_ms": self.market_data_lag_ms,
            "stale": self.stale,
        }
