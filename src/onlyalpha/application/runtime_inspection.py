"""Immutable product read models for inspecting long-lived runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.market.session_clock import OnlyMarketSessionState
from onlyalpha.market_data.watermark import OnlyHistoricalWatermark
from onlyalpha.observation import OnlyMarketObservationSnapshot
from onlyalpha.runtime.runtime import OnlyRuntimeState
from onlyalpha.runtime.streaming.phase import OnlyStreamingDataState, OnlyStreamingPhase


@dataclass(frozen=True, slots=True)
class OnlySubscriptionInspection:
    request_id: str
    source_id: str
    instrument_ids: tuple[str, ...]
    bar_types: tuple[str, ...]
    active: bool


@dataclass(frozen=True, slots=True)
class OnlyHistoricalWarmupInspection:
    status: str
    protocol_version: int
    time_semantics_version: int
    compatibility_profile: str | None
    provider: str
    provider_version: str | None
    request_fingerprint: str
    content_fingerprint: str | None
    bar_count: int
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
    diagnostic_code: str | None
    process_exit_code: int | None


@dataclass(frozen=True, slots=True)
class OnlyStreamingRuntimeInspectionSnapshot:
    captured_at: OnlyTimestamp
    engine_id: str
    run_id: str
    runtime_id: str
    cluster_ids: tuple[str, ...]
    runtime_state: OnlyRuntimeState
    streaming_phase: OnlyStreamingPhase
    market_session_state: OnlyMarketSessionState
    data_state: OnlyStreamingDataState
    next_market_close: OnlyTimestamp
    source_connected: bool
    worker_alive: bool
    observation_publisher_alive: bool
    bootstrap_observed_at: OnlyTimestamp | None
    historical_requested_end: OnlyTimestamp | None
    historical_watermarks: tuple[OnlyHistoricalWatermark, ...]
    historical_warmups: tuple[OnlyHistoricalWarmupInspection, ...]
    historical_bar_count: int
    historical_statuses: tuple[str, ...]
    latest_observations: tuple[OnlyMarketObservationSnapshot, ...]
    subscriptions: tuple[OnlySubscriptionInspection, ...]
    received_update_count: int
    closed_external_bar_count: int
    derived_internal_bar_count: int
    historical_observation_count: int
    historical_provider_bar_count: int
    historical_replay_attempted_count: int
    historical_processed_bar_count: int
    historical_rejected_bar_count: int
    historical_duplicate_count: int
    historical_provider_last_bar_end: OnlyTimestamp | None
    historical_last_attempted_bar_end: OnlyTimestamp | None
    historical_last_processed_bar_end: OnlyTimestamp | None
    historical_watermark_last_bar_end: OnlyTimestamp | None
    historical_first_rejection_reason: str | None
    acceptance_execution_stage: str
    last_received_at: OnlyTimestamp | None
    last_closed_bar_end: OnlyTimestamp | None
    next_expected_bar_end: OnlyTimestamp | None
    pending_live_bar_count: int
    live_observation_count: int
    duplicate_count: int
    historical_overlap_count: int
    out_of_order_count: int
    gap_count: int
    stale_count: int
    observation_drop_count: int
    publisher_pending_count: int
    bootstrap_suppressed_intent_count: int
    catch_up_suppressed_intent_count: int
    live_order_intent_count: int
    risk_rejected_count: int
    external_order_id_count: int
    order_count: int
    fill_count: int
    open_reservation_count: int
    cash_reservation_count: int
    position_reservation_count: int
    margin_reservation_count: int
    reservation_created_count: int
    reservation_released_count: int
    position_count: int
    fee_count: int
    settlement_count: int


@dataclass(frozen=True, slots=True)
class OnlyEconomicBaseline:
    ledger_cash: Decimal
    position_count: int
    total_position_quantity: Decimal
    order_count: int
    fill_count: int
    fee_count: int
    settlement_count: int
    cash_reservation_count: int
    position_reservation_count: int
    margin_reservation_count: int
