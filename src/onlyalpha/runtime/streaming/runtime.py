"""Shared long-lived Runtime kernel for streaming Trading composition roots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from math import lcm
from typing import cast

from onlyalpha.broker.inbound import OnlyBrokerInboundQueue
from onlyalpha.broker.ports import OnlyBrokerGateway
from onlyalpha.config.persistence import OnlyRuntimePersistenceConfig
from onlyalpha.core.clock import OnlyLiveClock, OnlyTimerEvent, OnlyTimerHandle, OnlyTimerId
from onlyalpha.data.enums import OnlyMarketDataProcessingStatus, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyDataVersion, OnlyMarketDataUpdateId
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyMarketDataInboundUpdate,
    OnlyMarketDataProcessingResult,
    OnlyMarketDataSubscriptionRequest,
    OnlyMarketDataUnsubscriptionRequest,
)
from onlyalpha.data.ports import OnlyHistoricalDataSource, OnlyMarketDataGateway
from onlyalpha.data.queue import OnlyMarketDataInboundQueue
from onlyalpha.data.warmup import (
    OnlyHistoricalValidationError,
    OnlyHistoricalWarmupRequest,
    OnlyHistoricalWarmupResult,
    OnlyHistoricalWarmupStatus,
    only_validate_historical_warmup_result,
)
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyRuntimeMode
from onlyalpha.domain.execution import OnlyOrderRequest, OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.market.session_clock import (
    OnlyMarketSessionResolver,
    OnlyMarketSessionSnapshot,
    OnlyMarketSessionState,
)
from onlyalpha.market_data.completed_boundary import OnlyCompletedBarBoundaryResolver
from onlyalpha.market_data.pipeline import OnlyMarketDataUpdateResult
from onlyalpha.market_data.watermark import OnlyHistoricalWatermark
from onlyalpha.observation import (
    OnlyCompositeObservationSink,
    OnlyLatestObservationStore,
    OnlyMarketObservationSnapshot,
    OnlyObservationPublisher,
    OnlyObservationSink,
    OnlyObservationSource,
)
from onlyalpha.order.execution.service import OnlyExecutionService
from onlyalpha.order.results import OnlyOrderSubmitResult
from onlyalpha.plugin.broker import OnlyDeterministicBrokerDriver
from onlyalpha.plugin.lifecycle import OnlyPluginResource
from onlyalpha.runtime.checkpoint.participant import OnlyJsonRuntimeCheckpointParticipant
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStorePort
from onlyalpha.runtime.persistence.timer_journal import OnlyRuntimeTimerOccurrence
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig, OnlyRuntimeError, OnlyRuntimeState
from onlyalpha.runtime.trading_facade import OnlyTradingRuntimeFacade

from .continuity import OnlyStreamingContinuityTracker
from .driver import OnlyStreamingMarketDataDriver
from .health import OnlyStreamingRuntimeHealth, only_streaming_data_state
from .live_bar import OnlyLiveBarFinalizer
from .phase import OnlyStreamingDataState, OnlyStreamingPhase
from .phase_controller import OnlyStreamingPhaseController, OnlyStreamingPhaseSnapshot
from .recovery import (
    OnlyStreamingRecoveryPlan,
    OnlyStreamingRecoveryReason,
)
from .recovery_loader import OnlyStreamingRecoveryLoader
from .semantic_lane import OnlyStreamingSemanticLane
from .timer_registry import OnlyRuntimeTimerRegistry


class OnlyStreamingRuntime(OnlyTradingRuntimeFacade):
    """Trading Kernel composed with one long-lived market-data driver."""

    _supported_modes = frozenset({OnlyRuntimeMode.PAPER, OnlyRuntimeMode.LIVE})

    def __init__(
        self,
        config: OnlyRuntimeAssemblyConfig,
        calendar: OnlyTradingCalendar,
        *,
        clock: OnlyLiveClock,
        event_bus: OnlyEventBus,
        data_source: OnlyHistoricalDataSource | OnlyMarketDataGateway | OnlyPluginResource,
        inbound_queue: OnlyMarketDataInboundQueue,
        persistence_store: OnlyRuntimePersistenceStorePort,
        persistence_config: OnlyRuntimePersistenceConfig | None = None,
        config_fingerprint: str = "",
        subscription: OnlyMarketDataSubscriptionRequest,
        data_version: OnlyDataVersion,
        execution_service: OnlyExecutionService | None = None,
        broker_gateway: OnlyBrokerGateway | None = None,
        broker_inbound_queue: OnlyBrokerInboundQueue | None = None,
        deterministic_broker_driver: OnlyDeterministicBrokerDriver | None = None,
        broker_resource: OnlyPluginResource | None = None,
        bootstrap_bars: int = 0,
        historical_compatibility_profile: str = "miniqmt-history-v2",
        historical_protocol_version: int = 2,
        historical_time_semantics_version: int = 2,
        historical_timeout_seconds: int = 30,
        warmup_alignment_steps: tuple[int, ...] = (),
        stale_after_seconds: int = 10,
        observation_sinks: tuple[OnlyObservationSink, ...] = (),
        observation_queue_capacity: int = 1024,
    ) -> None:
        self._phase_controller = OnlyStreamingPhaseController()
        super().__init__(
            config,
            calendar,
            clock.now_utc(),
            owned_clock=clock,
            owned_event_bus=event_bus,
            account_created_at=OnlyTimestamp.from_datetime(clock.now_utc() - timedelta(days=1)),
            broker_gateway=broker_gateway,
            execution_service=execution_service,
            deterministic_broker_driver=deterministic_broker_driver,
            broker_inbound_queue=broker_inbound_queue,
            market_data_inbound_queue=inbound_queue,
            runtime_persistence_store=persistence_store,
            persistence_config=persistence_config,
            config_fingerprint=config_fingerprint,
            plugin_resources=(
                ((broker_resource,) if broker_resource is not None else ()) + (cast(OnlyPluginResource, data_source),)
            ),
        )
        self._bootstrap_bars = bootstrap_bars
        self._streaming_data_version = data_version
        self._historical_compatibility_profile = historical_compatibility_profile
        self._historical_protocol_version = historical_protocol_version
        self._historical_time_semantics_version = historical_time_semantics_version
        self._historical_timeout_seconds = historical_timeout_seconds
        self._warmup_alignment_steps = tuple(sorted(set(warmup_alignment_steps)))
        self._stale_after_seconds = stale_after_seconds
        self._historical_warmup_results: list[OnlyHistoricalWarmupResult] = []
        self._historical_watermarks: dict[tuple[str, OnlyBarType], OnlyHistoricalWatermark] = {}
        self._continuity = OnlyStreamingContinuityTracker()
        self._overlap_count = 0
        self._duplicate_count = 0
        self._sequence_gap_count = 0
        self._stale_count = 0
        self._received_update_count = 0
        self._closed_external_bar_count = 0
        self._derived_internal_bar_count = 0
        self._historical_observation_count = 0
        self._bootstrap_observed_at: OnlyTimestamp | None = None
        self._historical_requested_end: OnlyTimestamp | None = None
        self._historical_provider_bar_count = 0
        self._historical_replay_attempted_count = 0
        self._historical_rejected_bar_count = 0
        self._historical_duplicate_count = 0
        self._historical_provider_last_bar_end: OnlyTimestamp | None = None
        self._historical_last_attempted_bar_end: OnlyTimestamp | None = None
        self._historical_last_processed_bar_end: OnlyTimestamp | None = None
        self._historical_first_rejection_reason: str | None = None
        self._acceptance_execution_stage = "ENGINE_START"
        self._historical_processed_bar_count = 0
        self._live_observation_count = 0
        self._out_of_order_count = 0
        self._bootstrap_suppressed_intent_count = 0
        self._catch_up_suppressed_intent_count = 0
        self._degraded_suppressed_intent_count = 0
        self._recovery_suppressed_intent_count = 0
        self._last_received_at: OnlyTimestamp | None = None
        self._latest_bars: dict[tuple[str, OnlyBarType], OnlyBar] = {}
        self._latest_sources: dict[tuple[str, OnlyBarType], OnlyObservationSource] = {}
        self._recovery_generation = 0
        self._recovery_plan: OnlyStreamingRecoveryPlan | None = None
        self._recovery_failure: str | None = None
        self._idle_check_ns = 0
        self._observation_store = OnlyLatestObservationStore()
        self._observation_publisher = OnlyObservationPublisher(
            OnlyCompositeObservationSink(observation_sinks), observation_queue_capacity
        )
        self._streaming_stop_attempted = False
        self._processing_results: list[OnlyMarketDataProcessingResult] = []
        self._live_finalizer = OnlyLiveBarFinalizer()
        self._semantic_lane = OnlyStreamingSemanticLane(self._services.market_data_processor)
        self._timer_registry = OnlyRuntimeTimerRegistry(
            OnlyRuntimeId(self.runtime_id),
            clock,
            persistence_store,
            self._execute_timer_occurrence,
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "streaming.continuity",
                self._continuity.checkpoint_schema_version,
                self._continuity.capture_checkpoint,
                self._continuity.restore_checkpoint,
            )
        )
        self._checkpoint_registry.register(
            OnlyJsonRuntimeCheckpointParticipant(
                "streaming.timer-authority",
                self._timer_registry.checkpoint_schema_version,
                self._timer_registry.capture_checkpoint,
                self._timer_registry.restore_checkpoint,
            )
        )
        source_id = data_source.source_id  # type: ignore[union-attr]
        self._recovery_loader = OnlyStreamingRecoveryLoader(
            source=cast(OnlyHistoricalDataSource, data_source),
            calendar=self._selected_calendar,
            data_version=data_version,
            runtime_id=OnlyRuntimeId(self.runtime_id),
            source_id=source_id,
        )
        self._driver = OnlyStreamingMarketDataDriver(
            source=data_source,
            subscription=subscription,
            inbound_queue=inbound_queue,
            processing_lane=self._semantic_lane,
            finalizer=self._live_finalizer,
            clock=clock,
            shutdown_timeout_seconds=float(historical_timeout_seconds) + 5.0,
            commit_result=self._record_processing_result,
            on_processed=self._handle_worker_result,
            on_idle=self._handle_worker_idle,
            accept_update=self._accept_streaming_update,
            accept_finalized=self._accept_finalized_bar,
        )
        self._services.market_data_source_registry.register(data_source)  # type: ignore[arg-type]

    @property
    def processing_results(self) -> tuple[OnlyMarketDataProcessingResult, ...]:
        return tuple(self._processing_results)

    @property
    def streaming_phase(self) -> OnlyStreamingPhase:
        return self._phase_controller.snapshot().phase

    @property
    def streaming_phase_snapshot(self) -> OnlyStreamingPhaseSnapshot:
        return self._phase_controller.snapshot()

    def wait_for_streaming_phase(
        self,
        target: OnlyStreamingPhase,
        *,
        after_revision: int | None = None,
        timeout: float | None = None,
    ) -> OnlyStreamingPhaseSnapshot | None:
        return self._phase_controller.wait_for(target, after_revision=after_revision, timeout=timeout)

    def _transition_streaming_phase(self, target: OnlyStreamingPhase) -> bool:
        return self._phase_controller.transition(set(OnlyStreamingPhase), target)

    @property
    def historical_watermarks(self) -> tuple[OnlyHistoricalWatermark, ...]:
        return tuple(self._historical_watermarks[key] for key in sorted(self._historical_watermarks, key=str))

    @property
    def latest_observation_store(self) -> OnlyLatestObservationStore:
        return self._observation_store

    @property
    def worker_alive(self) -> bool:
        return self._driver.alive

    @property
    def worker_failure(self) -> BaseException | None:
        return self._driver.failure

    @property
    def observation_publisher_alive(self) -> bool:
        return self._observation_publisher.alive

    @property
    def order_snapshots(self) -> tuple[OnlyOrderSnapshot, ...]:
        return self._services.order_manager.snapshot_all()

    @property
    def historical_warmup_results(self) -> tuple[OnlyHistoricalWarmupResult, ...]:
        return tuple(self._historical_warmup_results)

    @property
    def last_historical_bar_end(self) -> OnlyTimestamp | None:
        return self._historical_last_processed_bar_end

    @property
    def inspection_timestamp(self) -> OnlyTimestamp:
        return OnlyTimestamp.from_datetime(self._services.clock.now_utc())

    @property
    def inspection_run_id(self) -> str:
        return f"{self.runtime_type.lower()}-{self.runtime_id}"

    @property
    def streaming_subscription(self) -> OnlyMarketDataSubscriptionRequest:
        return self._driver.subscription

    @property
    def _streaming_subscription(self) -> OnlyMarketDataSubscriptionRequest:
        """Legacy internal spelling delegated to the Streaming Driver."""

        return self._driver.subscription

    @property
    def subscription_active(self) -> bool:
        return self._driver.subscription_id is not None

    @property
    def received_update_count(self) -> int:
        return self._received_update_count

    @property
    def closed_external_bar_count(self) -> int:
        return self._closed_external_bar_count

    @property
    def derived_internal_bar_count(self) -> int:
        return self._derived_internal_bar_count

    @property
    def historical_observation_count(self) -> int:
        return self._historical_observation_count

    @property
    def historical_protocol_version(self) -> int:
        return self._historical_protocol_version

    @property
    def historical_time_semantics_version(self) -> int:
        return self._historical_time_semantics_version

    @property
    def historical_processed_bar_count(self) -> int:
        return self._historical_processed_bar_count

    @property
    def bootstrap_observed_at(self) -> OnlyTimestamp | None:
        return self._bootstrap_observed_at

    @property
    def historical_requested_end(self) -> OnlyTimestamp | None:
        return self._historical_requested_end

    @property
    def historical_provider_bar_count(self) -> int:
        return self._historical_provider_bar_count

    @property
    def historical_replay_attempted_count(self) -> int:
        return self._historical_replay_attempted_count

    @property
    def historical_rejected_bar_count(self) -> int:
        return self._historical_rejected_bar_count

    @property
    def historical_duplicate_count(self) -> int:
        return self._historical_duplicate_count

    @property
    def historical_provider_last_bar_end(self) -> OnlyTimestamp | None:
        return self._historical_provider_last_bar_end

    @property
    def historical_last_attempted_bar_end(self) -> OnlyTimestamp | None:
        return self._historical_last_attempted_bar_end

    @property
    def historical_last_processed_bar_end(self) -> OnlyTimestamp | None:
        return self._historical_last_processed_bar_end

    @property
    def historical_first_rejection_reason(self) -> str | None:
        return self._historical_first_rejection_reason

    @property
    def acceptance_execution_stage(self) -> str:
        return self._acceptance_execution_stage

    @property
    def live_observation_count(self) -> int:
        return self._live_observation_count

    @property
    def out_of_order_count(self) -> int:
        return self._out_of_order_count

    @property
    def bootstrap_suppressed_intent_count(self) -> int:
        return self._bootstrap_suppressed_intent_count

    @property
    def catch_up_suppressed_intent_count(self) -> int:
        return self._catch_up_suppressed_intent_count

    @property
    def recovery_suppressed_intent_count(self) -> int:
        return self._recovery_suppressed_intent_count

    @property
    def recovery_generation(self) -> int:
        return self._recovery_generation

    @property
    def recovery_plan(self) -> OnlyStreamingRecoveryPlan | None:
        return self._recovery_plan

    @property
    def recovery_failure(self) -> str | None:
        return self._recovery_failure

    @property
    def pending_live_bar_count(self) -> int:
        return self._live_finalizer.pending_count

    def _recover_runtime(self) -> None:
        # Streaming checkpoint/restart is deliberately unsupported.
        self._services.event_router.complete_fresh_bootstrap()

    def _after_clusters_started(self) -> None:
        authenticate = getattr(self._driver.source, "authenticate", None)
        if callable(authenticate):
            authenticate()
        subscribe = getattr(self._driver.source, "subscribe", None)
        if not callable(subscribe):
            raise OnlyRuntimeError("streaming DataSource does not provide subscribe()")
        self._observation_publisher.start()
        try:
            self._transition_streaming_phase(OnlyStreamingPhase.SUBSCRIBING)
            result = subscribe(self._streaming_subscription)
            if result.subscription_id is None:
                raise OnlyRuntimeError(f"live subscription failed: {result.reason}")
            self._driver.subscription_id = result.subscription_id
            self._transition_streaming_phase(OnlyStreamingPhase.BOOTSTRAP)
            self._bootstrap()
            self._transition_streaming_phase(OnlyStreamingPhase.CATCH_UP)
            self._drain_catch_up()
            self._transition_streaming_phase(OnlyStreamingPhase.LIVE)
            self._driver.start_worker()
        except Exception:
            self._transition_streaming_phase(OnlyStreamingPhase.FAILED)
            self._unsubscribe()
            self._observation_publisher.stop()
            raise

    def start(self) -> None:
        try:
            super().start()
        except Exception:
            self._transition_streaming_phase(OnlyStreamingPhase.FAILED)
            raise
        self._acceptance_execution_stage = "HISTORICAL_OBSERVATION"
        for key, bar in sorted(self._latest_bars.items(), key=lambda item: str(item[0])):
            self._publish_observations(bar, self._latest_sources[key])
        self._acceptance_execution_stage = "LIVE_COLLECTION"

    def wait(self, timeout: float | None = None) -> None:
        if self.state is not OnlyRuntimeState.RUNNING:
            raise OnlyRuntimeError("Streaming Runtime can only wait while RUNNING")
        self._driver.wait(timeout)
        if self._driver.failure is not None:
            raise OnlyRuntimeError(
                f"streaming market-data worker failed: {self._driver.failure}"
            ) from self._driver.failure

    def run(self) -> object:
        raise OnlyRuntimeError("Streaming Runtime is long-lived; use start(), wait(), and stop()")

    def stop(self) -> None:
        if self.state in {OnlyRuntimeState.STOPPED, OnlyRuntimeState.CLOSED}:
            return
        if self._streaming_stop_attempted:
            return
        self._streaming_stop_attempted = True
        self._semantic_lane.revoke(self._phase_controller.begin_stop)
        self._driver.request_stop()
        failure: BaseException | None = None
        for operation in (
            self._unsubscribe,
            self._driver.worker.stop,
            self._observation_publisher.stop,
            super().stop,
        ):
            try:
                operation()
            except BaseException as exc:
                failure = failure or exc
        self._transition_streaming_phase(
            OnlyStreamingPhase.FAILED if failure is not None else OnlyStreamingPhase.STOPPED
        )
        if failure is not None:
            self._stop_failure = failure
            self._state = OnlyRuntimeState.FAILED
            raise failure

    def _unsubscribe(self) -> None:
        subscription_id = self._driver.subscription_id
        if subscription_id is None:
            return
        unsubscribe = getattr(self._driver.source, "unsubscribe", None)
        try:
            if callable(unsubscribe):
                unsubscribe(OnlyMarketDataUnsubscriptionRequest(f"stop-{self.runtime_id}", subscription_id))
        finally:
            self._driver.subscription_id = None

    def _bootstrap(self) -> None:
        load_warmup = getattr(self._driver.source, "load_warmup", None)
        if not callable(load_warmup):
            raise OnlyRuntimeError("streaming DataSource does not provide the Historical Warmup Port")
        observed_at = OnlyTimestamp.from_datetime(self._services.clock.now_utc())
        self._bootstrap_observed_at = observed_at
        bars: list[OnlyBar] = []
        alignment = lcm(*self._warmup_alignment_steps) if self._warmup_alignment_steps else 1
        for bar_type in sorted(self._driver.subscription.bar_types, key=str):
            closed_cutoff = OnlyCompletedBarBoundaryResolver().latest_completed_bar_end(
                calendar=self._selected_calendar,
                bar_type=bar_type,
                observed_at=observed_at,
            )
            self._historical_requested_end = (
                closed_cutoff
                if self._historical_requested_end is None
                else min(self._historical_requested_end, closed_cutoff)
            )
            request = OnlyHistoricalWarmupRequest(
                f"bootstrap-{self.runtime_id}-{bar_type.instrument_id}-{bar_type.specification.step}",
                OnlyRuntimeId(self.runtime_id),
                bar_type.instrument_id,
                bar_type,
                self._bootstrap_bars + alignment,
                OnlyTimestamp.from_datetime(closed_cutoff.to_datetime() - timedelta(days=10)),
                closed_cutoff,
                observed_at,
                self._streaming_data_version,
                OnlyAdjustmentType.RAW,
                self._historical_timeout_seconds,
                self._historical_compatibility_profile,
            )
            self._acceptance_execution_stage = "HISTORICAL_WORKER"
            result = load_warmup(request)
            self._historical_warmup_results.append(result)
            if result.status is not OnlyHistoricalWarmupStatus.SUCCESS:
                diagnostic = result.diagnostic
                detail = result.status.value
                if diagnostic is not None:
                    detail = f"{detail}: {diagnostic.code}: {diagnostic.message}"
                    if diagnostic.worker_exit_code is not None:
                        detail += f" (worker_exit_code={diagnostic.worker_exit_code})"
                    if diagnostic.working_directory is not None:
                        detail += f" (diagnostics={diagnostic.working_directory})"
                raise OnlyRuntimeError(f"historical warmup failed closed: {detail}")
            self._acceptance_execution_stage = "HISTORICAL_PARENT_VALIDATION"
            only_validate_historical_warmup_result(request, result)
            self._historical_provider_bar_count += result.provider_raw_bar_count
            provider_last = result.provider_raw_last_bar_end
            if provider_last is not None:
                self._historical_provider_last_bar_end = (
                    provider_last
                    if self._historical_provider_last_bar_end is None
                    else max(self._historical_provider_last_bar_end, provider_last)
                )
            aligned = self._align_warmup_bars(result.bars)
            bars.extend(aligned)
            if not aligned:
                raise OnlyRuntimeError("historical warmup returned no aligned Bars")
        ordered = sorted(bars, key=lambda bar: (bar.bar_end, str(bar.bar_type)))
        source_id = self._driver.source.source_id  # type: ignore[union-attr]
        records = tuple(
            OnlyMarketDataInboundUpdate(
                OnlyMarketDataUpdateId(f"warmup-{self.runtime_id}-{sequence}"),
                OnlyRuntimeId(self.runtime_id),
                source_id,
                OnlyDataSequence(sequence),
                self._streaming_data_version,
                bar.instrument_id,
                OnlyMarketDataType.BAR,
                OnlyBarUpdate(bar),
                OnlyTimestamp.from_datetime(bar.ts_event),
                OnlyTimestamp.from_datetime(bar.ts_init),
                metadata=(("warmup", "historical"),),
            )
            for sequence, bar in enumerate(ordered, start=1)
        )
        self._acceptance_execution_stage = "HISTORICAL_REPLAY"
        processed_records: list[OnlyMarketDataInboundUpdate] = []
        processed_by_type: dict[OnlyBarType, list[OnlyBar]] = {}
        replay_sequence = 0
        for update in records:
            if not isinstance(update.payload, OnlyBarUpdate):
                raise AssertionError("historical warmup records must contain Bars")
            bar = update.payload.bar
            self._historical_replay_attempted_count += 1
            self._historical_last_attempted_bar_end = OnlyTimestamp.from_datetime(bar.bar_end)
            if not self._historical_bar_is_in_calendar_session(bar):
                self._record_historical_rejection("HISTORICAL_BAR_OUTSIDE_CALENDAR_SESSION")
                continue
            replay_sequence += 1
            update = replace(
                update,
                source_sequence=OnlyDataSequence(replay_sequence),
                metadata=update.metadata + (("provider_sequence", str(int(update.source_sequence))),),
            )
            outcome = self._semantic_lane.process(update, self._record_processing_result)
            if not outcome.started or outcome.result is None:
                raise OnlyRuntimeError("historical warmup lost processing permission")
            result = outcome.result
            if result.status is OnlyMarketDataProcessingStatus.DUPLICATE:
                self._historical_duplicate_count += 1
                if self._historical_first_rejection_reason is None:
                    self._historical_first_rejection_reason = "HISTORICAL_BAR_DUPLICATE"
                continue
            if not isinstance(result.pipeline_result, OnlyMarketDataUpdateResult):
                reason = (
                    result.status.value
                    if result.failure is None
                    else f"{result.status.value}: {result.failure.error_type}: {result.failure.message}"
                )
                self._record_historical_rejection(reason)
                if result.status is OnlyMarketDataProcessingStatus.FAILED:
                    raise OnlyRuntimeError(f"historical warmup failed: {result}")
                continue
            processed_records.append(update)
            processed_by_type.setdefault(bar.bar_type, []).append(result.pipeline_result.base_bar)
            self._historical_last_processed_bar_end = OnlyTimestamp.from_datetime(
                result.pipeline_result.base_bar.bar_end
            )
        if not processed_records:
            raise OnlyHistoricalValidationError("NO_HISTORICAL_BAR_PROCESSED")
        self._acceptance_execution_stage = "HISTORICAL_WATERMARK"
        for bar_type, processed in sorted(processed_by_type.items(), key=lambda item: str(item[0])):
            latest = processed[-1]
            fingerprint = hashlib.sha256(
                json.dumps([item.to_dict() for item in processed], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            watermark = OnlyHistoricalWatermark(
                source_id,
                bar_type.instrument_id,
                bar_type,
                OnlyTimestamp.from_datetime(latest.bar_start),
                OnlyTimestamp.from_datetime(latest.bar_end),
                self._streaming_data_version,
                fingerprint,
            )
            if watermark.last_bar_end != OnlyTimestamp.from_datetime(latest.bar_end):
                raise AssertionError("historical Watermark must equal the last processed Bar")
            self._historical_watermarks[(str(bar_type.instrument_id), bar_type)] = watermark
        self._live_finalizer.seed_closed_sequences(tuple(processed_records))
        set_floor = getattr(self._driver.source, "set_live_sequence_floor", None)
        if callable(set_floor):
            set_floor(max(int(item.source_sequence) for item in processed_records))

    def _historical_bar_is_in_calendar_session(self, bar: OnlyBar) -> bool:
        intervals = self._selected_calendar.session_intervals_for_trading_day(OnlyTradingDay(bar.trading_day))
        return any(start <= bar.bar_start < end and start < bar.bar_end <= end for start, end in intervals)

    def _record_historical_rejection(self, reason: str) -> None:
        self._historical_rejected_bar_count += 1
        if self._historical_first_rejection_reason is None:
            self._historical_first_rejection_reason = reason

    def _align_warmup_bars(self, bars: tuple[OnlyBar, ...]) -> tuple[OnlyBar, ...]:
        if not self._warmup_alignment_steps:
            return bars[-self._bootstrap_bars :]
        maximum_start = len(bars) - self._bootstrap_bars
        for index, value in enumerate(bars):
            if index > maximum_start:
                break
            bar = value
            intervals = self._selected_calendar.session_intervals_for_trading_day(OnlyTradingDay(bar.trading_day))
            session = next(
                ((start, end) for start, end in intervals if start <= bar.bar_start < end),
                None,
            )
            if session is None:
                continue
            elapsed_minutes = int((bar.bar_start - session[0]).total_seconds() // 60)
            if all(elapsed_minutes % step == 0 for step in self._warmup_alignment_steps):
                return bars[index:]
        raise OnlyRuntimeError("historical warmup cannot establish an aligned aggregation boundary")

    def _record_processing_result(
        self,
        update: OnlyMarketDataInboundUpdate,
        result: OnlyMarketDataProcessingResult,
    ) -> None:
        self._processing_results.append(result)
        if result.status is OnlyMarketDataProcessingStatus.DUPLICATE:
            self._duplicate_count += 1
        if result.status is OnlyMarketDataProcessingStatus.GAP_DETECTED:
            self._sequence_gap_count += 1
        pipeline = result.pipeline_result
        if isinstance(pipeline, OnlyMarketDataUpdateResult):
            self._closed_external_bar_count += 1
            if self.streaming_phase is OnlyStreamingPhase.BOOTSTRAP:
                self._historical_processed_bar_count += 1
            self._derived_internal_bar_count += len(pipeline.derived_bars)
            bar = pipeline.base_bar
            key = (str(bar.instrument_id), bar.bar_type)
            self._latest_bars[key] = bar
            self._continuity.advance(update)
            source = (
                OnlyObservationSource.HISTORICAL_BOOTSTRAP
                if self.streaming_phase is OnlyStreamingPhase.BOOTSTRAP
                else OnlyObservationSource.CATCH_UP
                if self.streaming_phase is OnlyStreamingPhase.CATCH_UP
                else OnlyObservationSource.LIVE
            )
            self._latest_sources[key] = source
            if self.streaming_phase is not OnlyStreamingPhase.BOOTSTRAP:
                self._publish_observations(bar, source)

    def _drain_catch_up(self) -> None:
        buffered: list[OnlyMarketDataInboundUpdate] = []
        while (update := self._services.market_data_inbound.get()) is not None:
            buffered.append(update)
        buffered.sort(
            key=lambda item: (
                item.payload.bar.bar_start if isinstance(item.payload, OnlyBarUpdate) else item.ts_event.to_datetime(),
                int(item.source_sequence),
                str(item.update_id),
            )
        )
        for update in buffered:
            if not self._accept_streaming_update(update):
                continue
            for finalized in self._live_finalizer.accept(update):
                if self._accept_finalized_bar(finalized):
                    outcome = self._semantic_lane.process(finalized, self._record_processing_result)
                    if not outcome.started:
                        return

    def _accept_streaming_update(self, update: OnlyMarketDataInboundUpdate) -> bool:
        self._received_update_count += 1
        self._last_received_at = OnlyTimestamp.from_datetime(self._services.clock.now_utc())
        if not isinstance(update.payload, OnlyBarUpdate):
            return True
        bar = update.payload.bar
        watermark = self._historical_watermarks.get((str(bar.instrument_id), bar.bar_type))
        if (
            watermark is not None
            and OnlyTimestamp.from_datetime(bar.bar_end).unix_nanos <= watermark.last_bar_end.unix_nanos
        ):
            self._overlap_count += 1
            return False
        return True

    def _accept_finalized_bar(self, update: OnlyMarketDataInboundUpdate) -> bool:
        if not isinstance(update.payload, OnlyBarUpdate):
            return True
        if self._continuity.contains(update):
            self._duplicate_count += 1
            return False
        return True

    def _handle_worker_result(
        self,
        update: OnlyMarketDataInboundUpdate,
        result: OnlyMarketDataProcessingResult,
    ) -> None:
        if result.status is not OnlyMarketDataProcessingStatus.GAP_DETECTED:
            return
        self._recover_gap(update)

    def _execute_timer_occurrence(
        self,
        occurrence: OnlyRuntimeTimerOccurrence,
        event: OnlyTimerEvent,
        callback: Callable[[OnlyTimerEvent], None],
    ) -> None:
        del occurrence
        outcome = self._semantic_lane.execute(lambda: callback(event))
        if not outcome.started:
            raise OnlyRuntimeError("STREAMING_TIMER_SEMANTIC_PERMISSION_REVOKED")

    def _schedule_at(self, cluster_id: OnlyClusterId, timer_id: str, when_ns: int) -> OnlyTimerHandle:
        self._require_timer_permission(cluster_id)
        identifier = OnlyTimerId(self._timer_name(cluster_id, timer_id))
        handle = self._timer_registry.schedule_at(
            identifier,
            cluster_id,
            when_ns,
            lambda event: super(OnlyStreamingRuntime, self)._timer_callback(cluster_id, event),
        )
        return self._remember_timer(cluster_id, timer_id, handle)

    def _schedule_after(self, cluster_id: OnlyClusterId, timer_id: str, delay_ns: int) -> OnlyTimerHandle:
        self._require_timer_permission(cluster_id)
        identifier = OnlyTimerId(self._timer_name(cluster_id, timer_id))
        handle = self._timer_registry.schedule_after(
            identifier,
            cluster_id,
            delay_ns,
            lambda event: super(OnlyStreamingRuntime, self)._timer_callback(cluster_id, event),
        )
        return self._remember_timer(cluster_id, timer_id, handle)

    def _schedule_every(
        self,
        cluster_id: OnlyClusterId,
        timer_id: str,
        interval_ns: int,
        start_ns: int | None,
    ) -> OnlyTimerHandle:
        self._require_timer_permission(cluster_id)
        identifier = OnlyTimerId(self._timer_name(cluster_id, timer_id))
        handle = self._timer_registry.schedule_every(
            identifier,
            cluster_id,
            interval_ns,
            lambda event: super(OnlyStreamingRuntime, self)._timer_callback(cluster_id, event),
            start_ns=start_ns,
        )
        return self._remember_timer(cluster_id, timer_id, handle)

    def _recover_gap(self, trigger: OnlyMarketDataInboundUpdate) -> None:
        if not isinstance(trigger.payload, OnlyBarUpdate):
            self._fail_streaming_recovery("unexpected non-Bar continuity gap")
            return
        bar = trigger.payload.bar
        key = (str(bar.instrument_id), bar.bar_type)
        confirmed = self._latest_bars.get(key)
        if confirmed is None:
            self._fail_streaming_recovery("continuity gap has no confirmed Bar frontier")
            return
        if not self._transition_streaming_phase(OnlyStreamingPhase.DEGRADED):
            return
        self._recovery_generation += 1
        plan = OnlyStreamingRecoveryPlan(
            self._recovery_generation,
            OnlyStreamingRecoveryReason.GAP,
            bar.instrument_id,
            bar.bar_type,
            OnlyTimestamp.from_datetime(confirmed.bar_end),
            OnlyTimestamp.from_datetime(bar.bar_start),
            trigger,
        )
        self._recover_market_continuity(plan)

    def _recover_market_continuity(self, plan: OnlyStreamingRecoveryPlan) -> None:
        self._recovery_plan = plan
        self._live_finalizer.reset_pending()
        try:
            if self._semantic_lane.revoked:
                return
            if not self._transition_streaming_phase(OnlyStreamingPhase.RECOVERING):
                return
            accepted_sequence = self._continuity.accepted_sequence(
                self._driver.source.source_id,  # type: ignore[union-attr]
                OnlyMarketDataType.BAR,
            )
            batch = self._recovery_loader.load(plan, accepted_sequence)
            if self._semantic_lane.revoked or self.streaming_phase is OnlyStreamingPhase.STOPPING:
                return
            for update in batch.updates:
                outcome = self._semantic_lane.process(update, self._record_processing_result)
                if not outcome.started:
                    return
                if outcome.result is None:
                    raise AssertionError("started processing must return a result")
                result = outcome.result
                if result.status is not OnlyMarketDataProcessingStatus.APPLIED:
                    raise OnlyRuntimeError(f"recovery Bar was not applied: {result.status.value}")
            if not self._transition_streaming_phase(OnlyStreamingPhase.CATCH_UP):
                return
            buffered = (() if plan.trigger_update is None else (plan.trigger_update,)) + self._drain_buffered_updates()
            self._process_buffered_updates(buffered)
            while True:
                suffix = self._drain_buffered_updates()
                if not suffix:
                    break
                self._process_buffered_updates(suffix)
            self._verify_recovery_complete(plan)
            self._recovery_plan = None
            self._transition_streaming_phase(OnlyStreamingPhase.LIVE)
        except Exception as exc:
            self._fail_streaming_recovery(str(exc))

    def _drain_buffered_updates(self) -> tuple[OnlyMarketDataInboundUpdate, ...]:
        updates: list[OnlyMarketDataInboundUpdate] = []
        while (update := self._services.market_data_inbound.get()) is not None:
            updates.append(update)
        return tuple(updates)

    def _process_buffered_updates(self, updates: tuple[OnlyMarketDataInboundUpdate, ...]) -> None:
        ordered = sorted(
            updates,
            key=lambda item: (
                item.payload.bar.bar_start if isinstance(item.payload, OnlyBarUpdate) else item.ts_event.to_datetime(),
                int(item.source_sequence),
                str(item.update_id),
            ),
        )
        seen: set[tuple[str, OnlyBarType, int]] = set()
        for update in ordered:
            if self._semantic_lane.revoked:
                return
            if not self._accept_streaming_update(update):
                continue
            for finalized in self._live_finalizer.accept(update):
                if not isinstance(finalized.payload, OnlyBarUpdate):
                    continue
                bar = finalized.payload.bar
                identity = (str(bar.instrument_id), bar.bar_type, OnlyTimestamp.from_datetime(bar.bar_start).unix_nanos)
                if identity in seen or not self._accept_finalized_bar(finalized):
                    continue
                seen.add(identity)
                next_sequence = (
                    self._continuity.accepted_sequence(finalized.source_id, finalized.data_type)
                    + 1
                )
                normalized = replace(
                    finalized,
                    source_sequence=OnlyDataSequence(next_sequence),
                    metadata=finalized.metadata + (("provider_sequence", str(int(finalized.source_sequence))),),
                )
                outcome = self._semantic_lane.process(normalized, self._record_processing_result)
                if not outcome.started:
                    return
                if outcome.result is None:
                    raise AssertionError("started processing must return a result")
                result = outcome.result
                if result.status is OnlyMarketDataProcessingStatus.GAP_DETECTED:
                    raise OnlyRuntimeError("buffered realtime suffix contains a secondary gap")
                if result.status not in {
                    OnlyMarketDataProcessingStatus.APPLIED,
                    OnlyMarketDataProcessingStatus.DUPLICATE,
                }:
                    raise OnlyRuntimeError(f"buffered realtime update was not applied: {result.status.value}")

    def _verify_recovery_complete(self, plan: OnlyStreamingRecoveryPlan) -> None:
        if self._semantic_lane.revoked or self.streaming_phase in {
            OnlyStreamingPhase.STOPPING,
            OnlyStreamingPhase.FAILED,
        }:
            raise OnlyRuntimeError("streaming recovery lost processing permission")
        if self._recovery_plan != plan or len(self._services.market_data_inbound) != 0:
            raise OnlyRuntimeError("streaming recovery did not reconcile its buffered suffix")
        if not self._source_connected() or self._driver.subscription_id is None or not self.worker_alive:
            raise OnlyRuntimeError("streaming transport is not healthy after recovery")
        observed = OnlyTimestamp.from_datetime(self._services.clock.now_utc())
        session = OnlyMarketSessionResolver(self._selected_calendar).resolve(observed)
        state = only_streaming_data_state(
            session=session,
            phase=OnlyStreamingPhase.LIVE,
            source_connected=True,
            observed_at=observed,
            next_expected_bar_end=self._next_expected_bar_end(session),
            grace_seconds=self._stale_after_seconds,
        )
        if session.state is OnlyMarketSessionState.OPEN and state is OnlyStreamingDataState.STALE:
            raise OnlyRuntimeError("open-market stream remains stale after recovery")

    def _fail_streaming_recovery(self, reason: str) -> None:
        if self.streaming_phase in {OnlyStreamingPhase.STOPPING, OnlyStreamingPhase.STOPPED}:
            return
        self._recovery_failure = reason
        if self._transition_streaming_phase(OnlyStreamingPhase.FAILED):
            self._state = OnlyRuntimeState.FAILED

    def _source_connected(self) -> bool:
        snapshot = getattr(self._driver.source, "connection_snapshot", None)
        if not callable(snapshot):
            return self._driver.subscription_id is not None
        from onlyalpha.data.enums import OnlyMarketDataConnectionState

        return snapshot().state in {
            OnlyMarketDataConnectionState.CONNECTED,
            OnlyMarketDataConnectionState.READY,
        }

    def _handle_worker_idle(self) -> None:
        now = self._services.clock.monotonic_ns()
        if now - self._idle_check_ns < 1_000_000_000:
            return
        self._idle_check_ns = now
        if self.streaming_phase is not OnlyStreamingPhase.LIVE:
            return
        health = self.health()
        if health.data_state not in {OnlyStreamingDataState.STALE, OnlyStreamingDataState.DISCONNECTED}:
            return
        self._stale_count += int(health.data_state is OnlyStreamingDataState.STALE)
        self._recover_stale_or_disconnect(health.data_state)

    def _recover_stale_or_disconnect(self, state: OnlyStreamingDataState) -> None:
        if not self._latest_bars:
            self._fail_streaming_recovery("stale recovery has no confirmed Bar frontier")
            return
        if not self._transition_streaming_phase(OnlyStreamingPhase.DEGRADED):
            return
        if state is OnlyStreamingDataState.DISCONNECTED and not self._reconnect_source():
            self._fail_streaming_recovery("streaming DataSource reconnect failed")
            return
        for _key, confirmed in sorted(self._latest_bars.items(), key=lambda item: str(item[0])):
            target = OnlyCompletedBarBoundaryResolver().latest_completed_bar_end(
                calendar=self._selected_calendar,
                bar_type=confirmed.bar_type,
                observed_at=OnlyTimestamp.from_datetime(self._services.clock.now_utc()),
            )
            self._recovery_generation += 1
            plan = OnlyStreamingRecoveryPlan(
                self._recovery_generation,
                OnlyStreamingRecoveryReason.DISCONNECTED
                if state is OnlyStreamingDataState.DISCONNECTED
                else OnlyStreamingRecoveryReason.STALE,
                confirmed.instrument_id,
                confirmed.bar_type,
                OnlyTimestamp.from_datetime(confirmed.bar_end),
                target,
            )
            self._recover_market_continuity(plan)
            if self.streaming_phase is OnlyStreamingPhase.FAILED:
                return

    def _reconnect_source(self) -> bool:
        try:
            self._unsubscribe()
            connect = getattr(self._driver.source, "connect", None)
            authenticate = getattr(self._driver.source, "authenticate", None)
            subscribe = getattr(self._driver.source, "subscribe", None)
            if not callable(connect) or not callable(authenticate) or not callable(subscribe):
                return False
            connect_result = connect()
            auth_result = authenticate()
            result = subscribe(self._streaming_subscription)
            if (
                connect_result.status.value != "ACCEPTED"
                or auth_result.status.value != "ACCEPTED"
                or result.subscription_id is None
            ):
                return False
            self._driver.subscription_id = result.subscription_id
            return self._source_connected()
        except Exception:
            return False

    def _intercept_order_submit(self, request: OnlyOrderRequest) -> OnlyOrderSubmitResult | None:
        del request
        if self.streaming_phase is OnlyStreamingPhase.BOOTSTRAP:
            self._bootstrap_suppressed_intent_count += 1
            return OnlyOrderSubmitResult(
                False, False, None, None, None, None, (), "ORDER_INTENT_SUPPRESSED_DURING_BOOTSTRAP"
            )
        if self.streaming_phase is OnlyStreamingPhase.CATCH_UP:
            self._catch_up_suppressed_intent_count += 1
            return OnlyOrderSubmitResult(
                False, False, None, None, None, None, (), "ORDER_INTENT_SUPPRESSED_DURING_CATCH_UP"
            )
        if self.streaming_phase is OnlyStreamingPhase.DEGRADED:
            self._degraded_suppressed_intent_count += 1
            return OnlyOrderSubmitResult(
                False, False, None, None, None, None, (), "ORDER_INTENT_SUPPRESSED_DURING_DEGRADED"
            )
        if self.streaming_phase is OnlyStreamingPhase.RECOVERING:
            self._recovery_suppressed_intent_count += 1
            return OnlyOrderSubmitResult(
                False, False, None, None, None, None, (), "ORDER_INTENT_SUPPRESSED_DURING_RECOVERY"
            )
        return None

    def _publish_observations(self, bar: OnlyBar, source: OnlyObservationSource) -> None:
        observed = OnlyTimestamp.from_datetime(self._services.clock.now_utc())
        session = OnlyMarketSessionResolver(self._selected_calendar).resolve(observed)
        data_state = only_streaming_data_state(
            session=session,
            phase=self.streaming_phase,
            source_connected=self._source_connected(),
            observed_at=observed,
            next_expected_bar_end=self._next_expected_bar_end(session),
            grace_seconds=self._stale_after_seconds,
        )
        watermark = self._historical_watermarks.get((str(bar.instrument_id), bar.bar_type))
        for cluster in self.clusters:
            subscription = cluster.config.subscription
            if subscription is None or bar.bar_type not in subscription.bar_types:
                continue
            pipeline = cluster.last_pipeline_result
            indicators = tuple(tuple(sorted(item.to_dict().items())) for item in cluster.indicator_snapshots)
            factors = (
                ()
                if pipeline is None
                else tuple(tuple(sorted(item.to_dict().items())) for item in pipeline.factor_snapshots)
            )
            snapshot = OnlyMarketObservationSnapshot(
                OnlyRuntimeId(self.runtime_id),
                OnlyClusterId(cluster.config.cluster_id),
                bar.instrument_id,
                bar.bar_type,
                observed,
                self.state,
                self.streaming_phase,
                session.state,
                data_state,
                source,
                OnlyTimestamp.from_datetime(bar.bar_start),
                OnlyTimestamp.from_datetime(bar.bar_end),
                bar.close.value,
                bar.volume.value,
                None if watermark is None else watermark.last_bar_end,
                session.previous_market_close,
                session.next_market_open,
                indicators,
                factors,
                (),
                max(0, (observed.unix_nanos - OnlyTimestamp.from_datetime(bar.bar_end).unix_nanos) // 1_000_000),
                data_state is OnlyStreamingDataState.STALE,
            )
            self._observation_store.put(snapshot)
            self._observation_publisher.publish(snapshot)
            if source is OnlyObservationSource.HISTORICAL_BOOTSTRAP:
                self._historical_observation_count += 1
            elif source is OnlyObservationSource.LIVE:
                self._live_observation_count += 1

    def health(self) -> OnlyStreamingRuntimeHealth:
        observed = OnlyTimestamp.from_datetime(self._services.clock.now_utc())
        session = OnlyMarketSessionResolver(self._selected_calendar).resolve(observed)
        next_expected = self._next_expected_bar_end(session)
        state = only_streaming_data_state(
            session=session,
            phase=self.streaming_phase,
            source_connected=self._source_connected(),
            observed_at=observed,
            next_expected_bar_end=next_expected,
            grace_seconds=self._stale_after_seconds,
        )
        return OnlyStreamingRuntimeHealth(
            self.state,
            self.streaming_phase,
            session.state,
            state,
            self._source_connected(),
            self.worker_alive,
            self._last_received_at,
            self._continuity.last_closed_bar_end,
            next_expected,
            session.next_market_open,
            session.next_market_close,
            len(self._services.market_data_inbound),
            self._observation_publisher.queue_size,
            self._duplicate_count,
            self._overlap_count,
            self._sequence_gap_count,
            self._stale_count + int(state is OnlyStreamingDataState.STALE),
            self._observation_publisher.drop_count,
            self._recovery_generation,
            None if self._recovery_plan is None else self._recovery_plan.reason.value,
            None if self._recovery_plan is None else self._recovery_plan.confirmed_bar_end,
            None if self._recovery_plan is None else self._recovery_plan.recovery_target,
        )

    def _next_expected_bar_end(self, session: OnlyMarketSessionSnapshot) -> OnlyTimestamp | None:
        if session.state is not OnlyMarketSessionState.OPEN:
            return None
        observed = session.observed_at.to_datetime()
        if session.current_trading_day is None:
            return None
        active = next(
            (
                interval
                for interval in self._selected_calendar.session_intervals_for_trading_day(session.current_trading_day)
                if interval[0] <= observed < interval[1]
            ),
            None,
        )
        if active is None:
            return None
        steps = tuple(item.specification.step for item in self._driver.subscription.bar_types)
        duration = timedelta(minutes=min(steps))
        last = self._continuity.last_closed_bar_end
        candidate = (
            active[0] + duration if last is None or last.to_datetime() < active[0] else last.to_datetime() + duration
        )
        return OnlyTimestamp.from_datetime(candidate) if candidate <= active[1] else None
