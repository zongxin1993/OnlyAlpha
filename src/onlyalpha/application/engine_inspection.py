"""Engine-owned aggregation of immutable streaming runtime inspection data."""

from __future__ import annotations

from decimal import Decimal

from onlyalpha.account.enums import OnlyAccountReservationState
from onlyalpha.application.runtime_inspection import (
    OnlyEconomicBaseline,
    OnlyHistoricalWarmupInspection,
    OnlyStreamingRuntimeInspectionSnapshot,
    OnlySubscriptionInspection,
)
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.engine import OnlyEngine
from onlyalpha.position.enums import OnlyPositionReservationState
from onlyalpha.risk.enums import OnlyRiskReservationState
from onlyalpha.runtime.streaming.runtime import OnlyStreamingRuntime


class OnlyEngineInspectionService:
    """Capture read-only values without returning Runtime managers or resources."""

    def capture(self, engine: OnlyEngine) -> tuple[OnlyStreamingRuntimeInspectionSnapshot, ...]:
        snapshots: list[OnlyStreamingRuntimeInspectionSnapshot] = []
        for runtime in engine.runtimes:
            if not isinstance(runtime, OnlyStreamingRuntime):
                continue
            health = runtime.health()
            orders = runtime.order_snapshots
            risk_reservations = runtime.risk_service.reservations.snapshot_all()
            cash_reservations = runtime.account_reservation_manager.snapshots()
            position_reservations = runtime.position_reservation_manager.snapshots()
            margin_reservations = runtime.margin_manager.active_reservations
            subscription = runtime.streaming_subscription
            observations = runtime.latest_observation_store.list_runtime(OnlyRuntimeId(runtime.runtime_id))
            snapshots.append(
                OnlyStreamingRuntimeInspectionSnapshot(
                    captured_at=runtime.inspection_timestamp,
                    engine_id=engine.engine_id,
                    run_id=runtime.inspection_run_id,
                    runtime_id=runtime.runtime_id,
                    cluster_ids=tuple(sorted(str(item.config.cluster_id) for item in runtime.clusters)),
                    runtime_state=runtime.state,
                    streaming_phase=runtime.streaming_phase,
                    market_session_state=health.market_session_state,
                    data_state=health.data_state,
                    next_market_close=health.next_market_close,
                    source_connected=health.source_connected,
                    worker_alive=health.worker_alive,
                    observation_publisher_alive=runtime.observation_publisher_alive,
                    bootstrap_observed_at=runtime.bootstrap_observed_at,
                    historical_requested_end=runtime.historical_requested_end,
                    historical_watermarks=runtime.historical_watermarks,
                    historical_warmups=tuple(
                        OnlyHistoricalWarmupInspection(
                            status=item.status.value,
                            protocol_version=runtime.historical_protocol_version,
                            time_semantics_version=runtime.historical_time_semantics_version,
                            compatibility_profile=item.compatibility_profile_id,
                            provider=item.provider,
                            provider_version=item.provider_version,
                            request_fingerprint=item.request_fingerprint,
                            content_fingerprint=item.content_fingerprint,
                            bar_count=len(item.bars),
                            first_bar_end=item.first_bar_end,
                            last_bar_end=item.last_bar_end,
                            bootstrap_observed_at=item.bootstrap_observed_at,
                            requested_start=item.requested_start,
                            requested_end=item.requested_end,
                            provider_raw_bar_count=item.provider_raw_bar_count,
                            accepted_bar_count=item.accepted_bar_count,
                            rejected_out_of_range_count=item.rejected_out_of_range_count,
                            provider_raw_last_bar_end=item.provider_raw_last_bar_end,
                            accepted_last_bar_end=item.accepted_last_bar_end,
                            diagnostic_code=None if item.diagnostic is None else item.diagnostic.code,
                            process_exit_code=None if item.diagnostic is None else item.diagnostic.worker_exit_code,
                        )
                        for item in runtime.historical_warmup_results
                    ),
                    historical_bar_count=runtime.historical_processed_bar_count,
                    historical_statuses=tuple(str(item.status) for item in runtime.historical_warmup_results),
                    latest_observations=observations,
                    subscriptions=(
                        OnlySubscriptionInspection(
                            subscription.request_id,
                            str(subscription.source_id),
                            tuple(sorted(str(item) for item in subscription.instrument_ids)),
                            tuple(sorted(str(item) for item in subscription.bar_types)),
                            runtime.subscription_active,
                        ),
                    ),
                    received_update_count=runtime.received_update_count,
                    closed_external_bar_count=runtime.closed_external_bar_count,
                    derived_internal_bar_count=runtime.derived_internal_bar_count,
                    historical_observation_count=runtime.historical_observation_count,
                    historical_provider_bar_count=runtime.historical_provider_bar_count,
                    historical_replay_attempted_count=runtime.historical_replay_attempted_count,
                    historical_processed_bar_count=runtime.historical_processed_bar_count,
                    historical_rejected_bar_count=runtime.historical_rejected_bar_count,
                    historical_duplicate_count=runtime.historical_duplicate_count,
                    historical_provider_last_bar_end=runtime.historical_provider_last_bar_end,
                    historical_last_attempted_bar_end=runtime.historical_last_attempted_bar_end,
                    historical_last_processed_bar_end=runtime.historical_last_processed_bar_end,
                    historical_watermark_last_bar_end=max(
                        (item.last_bar_end for item in runtime.historical_watermarks), default=None
                    ),
                    historical_first_rejection_reason=runtime.historical_first_rejection_reason,
                    acceptance_execution_stage=runtime.acceptance_execution_stage,
                    last_received_at=health.last_received_at,
                    last_closed_bar_end=health.last_closed_bar_end,
                    next_expected_bar_end=health.next_expected_bar_end,
                    pending_live_bar_count=runtime.pending_live_bar_count,
                    live_observation_count=runtime.live_observation_count,
                    duplicate_count=health.duplicate_count,
                    historical_overlap_count=health.overlap_count,
                    out_of_order_count=runtime.out_of_order_count,
                    gap_count=health.sequence_gap_count,
                    stale_count=health.stale_count,
                    observation_drop_count=health.observation_drop_count,
                    publisher_pending_count=health.observation_queue_size,
                    bootstrap_suppressed_intent_count=runtime.bootstrap_suppressed_intent_count,
                    catch_up_suppressed_intent_count=runtime.catch_up_suppressed_intent_count,
                    live_order_intent_count=len(runtime.risk_service.audits),
                    risk_rejected_count=sum(not item.decision.is_accepted for item in runtime.risk_service.audits),
                    shadow_suppressed_count=sum(
                        item.failure is not None and item.failure.message == "EXECUTION_SUPPRESSED_BY_RUNTIME"
                        for item in orders
                    ),
                    external_order_id_count=sum(item.venue_order_id is not None for item in orders),
                    order_count=len(orders),
                    fill_count=sum(item.fill_count for item in orders),
                    open_reservation_count=sum(
                        item.state is OnlyRiskReservationState.ACTIVE for item in risk_reservations
                    ),
                    cash_reservation_count=sum(
                        item.state is OnlyAccountReservationState.ACTIVE for item in cash_reservations
                    ),
                    position_reservation_count=sum(
                        item.state
                        in {
                            OnlyPositionReservationState.ACTIVE,
                            OnlyPositionReservationState.PARTIALLY_CONSUMED,
                        }
                        for item in position_reservations
                    ),
                    margin_reservation_count=len(margin_reservations),
                    reservation_created_count=len(risk_reservations),
                    reservation_released_count=sum(
                        item.state is OnlyRiskReservationState.RELEASED for item in risk_reservations
                    ),
                    position_count=len(runtime.position_manager.snapshot_all()),
                    fee_count=len(runtime.fee_manager.records),
                    settlement_count=len(runtime.settlement_authority.records),
                )
            )
        return tuple(snapshots)

    def economic_baseline(self, engine: OnlyEngine) -> OnlyEconomicBaseline:
        runtimes = tuple(item for item in engine.runtimes if isinstance(item, OnlyStreamingRuntime))
        accounts = tuple(account for runtime in runtimes for account in runtime.account_manager.list_accounts())
        positions = tuple(position for runtime in runtimes for position in runtime.position_manager.snapshot_all())
        orders = tuple(order for runtime in runtimes for order in runtime.order_snapshots)
        return OnlyEconomicBaseline(
            ledger_cash=sum((item.cash.ledger_cash.amount for item in accounts), Decimal(0)),
            position_count=len(positions),
            total_position_quantity=sum((item.total_quantity.value for item in positions), Decimal(0)),
            order_count=len(orders),
            fill_count=sum(item.fill_count for item in orders),
            fee_count=sum(len(runtime.fee_manager.records) for runtime in runtimes),
            settlement_count=sum(len(runtime.settlement_authority.records) for runtime in runtimes),
            cash_reservation_count=sum(
                item.state is OnlyAccountReservationState.ACTIVE
                for runtime in runtimes
                for item in runtime.account_reservation_manager.snapshots()
            ),
            position_reservation_count=sum(
                item.state
                in {
                    OnlyPositionReservationState.ACTIVE,
                    OnlyPositionReservationState.PARTIALLY_CONSUMED,
                }
                for runtime in runtimes
                for item in runtime.position_reservation_manager.snapshots()
            ),
            margin_reservation_count=sum(len(runtime.margin_manager.active_reservations) for runtime in runtimes),
        )
