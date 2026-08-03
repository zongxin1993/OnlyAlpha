"""Read-only streaming health contract and session-aware data-state derivation."""

from dataclasses import dataclass

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.market.session_clock import OnlyMarketSessionSnapshot, OnlyMarketSessionState
from onlyalpha.runtime.runtime import OnlyRuntimeState

from .phase import OnlyStreamingDataState, OnlyStreamingPhase


@dataclass(frozen=True, slots=True)
class OnlyStreamingRuntimeHealth:
    runtime_state: OnlyRuntimeState
    streaming_phase: OnlyStreamingPhase
    market_session_state: OnlyMarketSessionState
    data_state: OnlyStreamingDataState
    source_connected: bool
    worker_alive: bool
    last_received_at: OnlyTimestamp | None
    last_closed_bar_end: OnlyTimestamp | None
    next_expected_bar_end: OnlyTimestamp | None
    next_market_open: OnlyTimestamp
    next_market_close: OnlyTimestamp
    inbound_queue_size: int
    observation_queue_size: int
    duplicate_count: int
    overlap_count: int
    sequence_gap_count: int
    stale_count: int
    observation_drop_count: int


def only_streaming_data_state(
    *,
    session: OnlyMarketSessionSnapshot,
    phase: OnlyStreamingPhase,
    source_connected: bool,
    observed_at: OnlyTimestamp,
    next_expected_bar_end: OnlyTimestamp | None,
    grace_seconds: int,
) -> OnlyStreamingDataState:
    if phase is OnlyStreamingPhase.FAILED:
        return OnlyStreamingDataState.FAILED
    if not source_connected:
        return OnlyStreamingDataState.DISCONNECTED
    if phase is OnlyStreamingPhase.BOOTSTRAP:
        return OnlyStreamingDataState.BOOTSTRAPPING
    if phase is OnlyStreamingPhase.CATCH_UP:
        return OnlyStreamingDataState.CATCHING_UP
    if session.state is not OnlyMarketSessionState.OPEN:
        return OnlyStreamingDataState.IDLE
    if (
        next_expected_bar_end is not None
        and observed_at.unix_nanos > next_expected_bar_end.unix_nanos + grace_seconds * 1_000_000_000
    ):
        return OnlyStreamingDataState.STALE
    return OnlyStreamingDataState.LIVE
