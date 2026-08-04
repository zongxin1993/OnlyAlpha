"""Pure acceptance assertions over formal inspection read models."""

from __future__ import annotations

from dataclasses import asdict

from onlyalpha.application.runtime_inspection import OnlyEconomicBaseline, OnlyStreamingRuntimeInspectionSnapshot
from onlyalpha.observation import OnlyObservationSource
from onlyalpha.runtime.runtime import OnlyRuntimeState
from onlyalpha.runtime.streaming.phase import OnlyStreamingDataState, OnlyStreamingPhase

from .paper_plan import OnlyPaperAcceptancePlan


class OnlyPaperAcceptanceAssertions:
    def historical(
        self, snapshot: OnlyStreamingRuntimeInspectionSnapshot, plan: OnlyPaperAcceptancePlan
    ) -> tuple[bool, str, dict[str, object], dict[str, object]]:
        observations = tuple(
            item
            for item in snapshot.latest_observations
            if item.observation_source is OnlyObservationSource.HISTORICAL_BOOTSTRAP
        )
        indicator_ready = any(
            any(dict(item).get("ready") is True for item in observation.indicator_snapshots)
            for observation in observations
        )
        factor_present = any(observation.factor_snapshots for observation in observations)
        watermark_matches_processed = (
            snapshot.historical_last_processed_bar_end is not None
            and snapshot.historical_watermark_last_bar_end == snapshot.historical_last_processed_bar_end
        )
        observation_matches_watermark = bool(observations) and all(
            item.latest_bar_end == snapshot.historical_watermark_last_bar_end for item in observations
        )
        passed = all(
            (
                bool(snapshot.historical_statuses) and all(item == "SUCCESS" for item in snapshot.historical_statuses),
                bool(snapshot.historical_warmups)
                and all(
                    item.protocol_version == 2
                    and item.time_semantics_version == 2
                    and item.compatibility_profile == "miniqmt-history-v2"
                    for item in snapshot.historical_warmups
                ),
                snapshot.historical_bar_count >= plan.minimum_historical_bars,
                bool(snapshot.historical_watermarks),
                watermark_matches_processed,
                bool(observations),
                observation_matches_watermark,
                indicator_ready or not plan.require_indicator_ready,
                factor_present or not plan.require_factor_snapshot,
                snapshot.fill_count == 0,
                snapshot.position_count == 0,
                snapshot.fee_count == 0,
                snapshot.settlement_count == 0,
            )
        )
        actual: dict[str, object] = {
            "historical_statuses": snapshot.historical_statuses,
            "protocol_versions": tuple(item.protocol_version for item in snapshot.historical_warmups),
            "time_semantics_versions": tuple(item.time_semantics_version for item in snapshot.historical_warmups),
            "historical_bar_count": snapshot.historical_bar_count,
            "watermark_count": len(snapshot.historical_watermarks),
            "historical_observation_count": len(observations),
            "bootstrap_observed_at": snapshot.bootstrap_observed_at,
            "historical_requested_end": snapshot.historical_requested_end,
            "historical_provider_bar_count": snapshot.historical_provider_bar_count,
            "historical_replay_attempted_count": snapshot.historical_replay_attempted_count,
            "historical_processed_bar_count": snapshot.historical_processed_bar_count,
            "historical_rejected_bar_count": snapshot.historical_rejected_bar_count,
            "historical_first_rejection_reason": snapshot.historical_first_rejection_reason,
            "provider_last_bar_end": snapshot.historical_provider_last_bar_end,
            "processed_last_bar_end": snapshot.historical_last_processed_bar_end,
            "watermark_last_bar_end": snapshot.historical_watermark_last_bar_end,
            "watermark_matches_processed": watermark_matches_processed,
            "observation_matches_watermark": observation_matches_watermark,
            "indicator_ready": indicator_ready,
            "factor_present": factor_present,
        }
        expected: dict[str, object] = {
            "historical_status": "SUCCESS",
            "minimum_historical_bars": plan.minimum_historical_bars,
            "watermark": True,
            "historical_observation": True,
            "indicator_ready": plan.require_indicator_ready,
            "factor_snapshot": plan.require_factor_snapshot,
        }
        reason = "HISTORICAL_CONTRACT_SATISFIED" if passed else "HISTORICAL_CONTRACT_VIOLATED"
        return passed, reason, expected, actual

    def live(
        self,
        before: OnlyStreamingRuntimeInspectionSnapshot,
        after: OnlyStreamingRuntimeInspectionSnapshot,
        plan: OnlyPaperAcceptancePlan,
    ) -> tuple[bool, str, dict[str, object], dict[str, object]]:
        live_observations = after.live_observation_count - before.live_observation_count
        closed = after.closed_external_bar_count - before.closed_external_bar_count
        derived = after.derived_internal_bar_count - before.derived_internal_bar_count
        intents = after.live_order_intent_count - before.live_order_intent_count
        suppressed = after.shadow_suppressed_count - before.shadow_suppressed_count
        reservations_created = after.reservation_created_count - before.reservation_created_count
        reservations_released = after.reservation_released_count - before.reservation_released_count
        passed = all(
            (
                closed >= plan.target_live_closed_bars,
                derived >= plan.target_live_derived_bars,
                live_observations >= plan.target_live_closed_bars,
                intents >= int(plan.require_live_shadow_intent),
                suppressed >= int(plan.require_live_shadow_intent),
                reservations_created >= int(plan.require_live_shadow_intent),
                reservations_released >= reservations_created,
                after.external_order_id_count == 0,
                after.fill_count == 0,
                after.open_reservation_count == 0,
                after.cash_reservation_count == 0,
                after.position_reservation_count == 0,
                after.margin_reservation_count == 0,
                after.observation_drop_count == 0,
                after.data_state is not OnlyStreamingDataState.STALE,
            )
        )
        expected: dict[str, object] = {
            "closed_external_bars": plan.target_live_closed_bars,
            "derived_internal_bars": plan.target_live_derived_bars,
            "shadow_intents": int(plan.require_live_shadow_intent),
            "economic_mutations": 0,
        }
        actual: dict[str, object] = {
            "closed_external_bars": closed,
            "derived_internal_bars": derived,
            "live_observations": live_observations,
            "live_order_intents": intents,
            "shadow_suppressed": suppressed,
            "reservation_created": reservations_created,
            "reservation_released": reservations_released,
            "external_order_ids": after.external_order_id_count,
            "fills": after.fill_count,
            "observation_drops": after.observation_drop_count,
            "data_state": after.data_state.value,
        }
        reason = "LIVE_HANDOFF_SATISFIED" if passed else "LIVE_HANDOFF_VIOLATED"
        return passed, reason, expected, actual

    def economic_isolation(
        self, before: OnlyEconomicBaseline, after: OnlyEconomicBaseline
    ) -> tuple[bool, str, dict[str, object], dict[str, object]]:
        before_values = asdict(before)
        after_values = asdict(after)
        stable_fields = (
            "cash_balance",
            "position_count",
            "total_position_quantity",
            "fill_count",
            "fee_count",
            "settlement_count",
            "cash_reservation_count",
            "position_reservation_count",
            "margin_reservation_count",
        )
        passed = all(before_values[field] == after_values[field] for field in stable_fields)
        return (
            passed,
            "ECONOMIC_STATE_UNCHANGED" if passed else "ECONOMIC_STATE_MUTATED",
            {field: before_values[field] for field in stable_fields},
            {field: after_values[field] for field in stable_fields},
        )

    def shutdown(
        self, snapshot: OnlyStreamingRuntimeInspectionSnapshot
    ) -> tuple[bool, str, dict[str, object], dict[str, object]]:
        passed = all(
            (
                snapshot.runtime_state in {OnlyRuntimeState.STOPPED, OnlyRuntimeState.CLOSED},
                snapshot.streaming_phase is OnlyStreamingPhase.STOPPED,
                not snapshot.source_connected,
                not snapshot.worker_alive,
                not any(item.active for item in snapshot.subscriptions),
                snapshot.publisher_pending_count == 0,
            )
        )
        return (
            passed,
            "ORDERED_SHUTDOWN_SATISFIED" if passed else "ORDERED_SHUTDOWN_VIOLATED",
            {"runtime_stopped": True, "subscriptions": 0, "workers": 0, "publisher_pending": 0},
            {
                "runtime_state": snapshot.runtime_state.value,
                "streaming_phase": snapshot.streaming_phase.value,
                "active_subscriptions": sum(item.active for item in snapshot.subscriptions),
                "worker_alive": snapshot.worker_alive,
                "publisher_pending": snapshot.publisher_pending_count,
            },
        )
