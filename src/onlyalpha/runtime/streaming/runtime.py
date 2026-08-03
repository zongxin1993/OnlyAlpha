"""Shared long-lived Runtime kernel for Paper and future Live composition roots."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from math import lcm
from threading import Event

from onlyalpha.core.clock import OnlyLiveClock
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
    OnlyHistoricalWarmupRequest,
    OnlyHistoricalWarmupResult,
    OnlyHistoricalWarmupStatus,
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
from onlyalpha.plugin.lifecycle import OnlyPluginResource
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStorePort
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig, OnlyRuntimeError, OnlyRuntimeState

from .health import OnlyStreamingRuntimeHealth, only_streaming_data_state
from .live_bar import OnlyLiveBarFinalizer
from .phase import OnlyStreamingDataState, OnlyStreamingPhase
from .worker import OnlyStreamingMarketDataWorker


class OnlyStreamingRuntime(OnlyBacktestRuntime):
    """One single-consumer market-data loop; execution is injected by capability."""

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
        execution_service: OnlyExecutionService,
        persistence_store: OnlyRuntimePersistenceStorePort,
        subscription: OnlyMarketDataSubscriptionRequest,
        data_version: OnlyDataVersion,
        bootstrap_bars: int = 0,
        historical_compatibility_profile: str = "miniqmt-history-v1",
        historical_timeout_seconds: int = 30,
        warmup_alignment_steps: tuple[int, ...] = (),
        stale_after_seconds: int = 10,
        observation_sinks: tuple[OnlyObservationSink, ...] = (),
        observation_queue_capacity: int = 1024,
    ) -> None:
        self._streaming_phase = OnlyStreamingPhase.CREATED
        super().__init__(
            config,
            calendar,
            clock.now_utc(),
            owned_clock=clock,
            owned_event_bus=event_bus,
            account_created_at=OnlyTimestamp.from_datetime(clock.now_utc() - timedelta(days=1)),
            execution_service=execution_service,
            market_data_inbound_queue=inbound_queue,
            runtime_persistence_store=persistence_store,
            plugin_resources=(data_source,),  # type: ignore[arg-type]
        )
        self._streaming_source = data_source
        self._streaming_execution = execution_service
        self._streaming_subscription = subscription
        self._streaming_subscription_id: str | None = None
        self._bootstrap_bars = bootstrap_bars
        self._streaming_data_version = data_version
        self._historical_compatibility_profile = historical_compatibility_profile
        self._historical_timeout_seconds = historical_timeout_seconds
        self._warmup_alignment_steps = tuple(sorted(set(warmup_alignment_steps)))
        self._stale_after_seconds = stale_after_seconds
        self._historical_warmup_results: list[OnlyHistoricalWarmupResult] = []
        self._historical_watermarks: dict[tuple[str, OnlyBarType], OnlyHistoricalWatermark] = {}
        self._processed_bar_identities: set[tuple[str, OnlyBarType, int]] = set()
        self._overlap_count = 0
        self._duplicate_count = 0
        self._sequence_gap_count = 0
        self._stale_count = 0
        self._last_received_at: OnlyTimestamp | None = None
        self._last_closed_bar_end: OnlyTimestamp | None = None
        self._latest_bars: dict[tuple[str, OnlyBarType], OnlyBar] = {}
        self._latest_sources: dict[tuple[str, OnlyBarType], OnlyObservationSource] = {}
        self._observation_store = OnlyLatestObservationStore()
        self._observation_publisher = OnlyObservationPublisher(
            OnlyCompositeObservationSink(observation_sinks), observation_queue_capacity
        )
        self._stop_requested = Event()
        self._processing_results: list[OnlyMarketDataProcessingResult] = []
        self._live_finalizer = OnlyLiveBarFinalizer()
        self._streaming_worker = OnlyStreamingMarketDataWorker(
            inbound_queue,
            self._services.market_data_processor,
            self._live_finalizer,
            clock,
            maximum_future_wait_seconds=10.0,
            on_result=self._record_processing_result,
            accept_update=self._accept_streaming_update,
            accept_finalized=self._accept_finalized_bar,
        )
        self._services.market_data_source_registry.register(data_source)  # type: ignore[arg-type]

    @property
    def processing_results(self) -> tuple[OnlyMarketDataProcessingResult, ...]:
        return tuple(self._processing_results)

    @property
    def streaming_phase(self) -> OnlyStreamingPhase:
        return self._streaming_phase

    @property
    def historical_watermarks(self) -> tuple[OnlyHistoricalWatermark, ...]:
        return tuple(self._historical_watermarks[key] for key in sorted(self._historical_watermarks, key=str))

    @property
    def latest_observation_store(self) -> OnlyLatestObservationStore:
        return self._observation_store

    @property
    def worker_alive(self) -> bool:
        return self._streaming_worker.alive

    @property
    def worker_failure(self) -> BaseException | None:
        return self._streaming_worker.failure

    @property
    def order_snapshots(self) -> tuple[OnlyOrderSnapshot, ...]:
        return self._services.order_manager.snapshot_all()

    @property
    def historical_warmup_results(self) -> tuple[OnlyHistoricalWarmupResult, ...]:
        return tuple(self._historical_warmup_results)

    @property
    def last_historical_bar_end(self) -> OnlyTimestamp | None:
        values = tuple(
            result.last_bar_end for result in self._historical_warmup_results if result.last_bar_end is not None
        )
        return max(values, default=None)

    def _recover_runtime(self) -> None:
        # Streaming checkpoint/restart is deliberately outside PR5.1.
        self._services.event_router.complete_fresh_bootstrap()

    def _after_clusters_started(self) -> None:
        authenticate = getattr(self._streaming_source, "authenticate", None)
        if callable(authenticate):
            authenticate()
        subscribe = getattr(self._streaming_source, "subscribe", None)
        if not callable(subscribe):
            raise OnlyRuntimeError("streaming DataSource does not provide subscribe()")
        self._observation_publisher.start()
        try:
            self._streaming_phase = OnlyStreamingPhase.SUBSCRIBING
            result = subscribe(self._streaming_subscription)
            if result.subscription_id is None:
                raise OnlyRuntimeError(f"live subscription failed: {result.reason}")
            self._streaming_subscription_id = result.subscription_id
            self._streaming_phase = OnlyStreamingPhase.BOOTSTRAP
            self._bootstrap()
            self._streaming_phase = OnlyStreamingPhase.CATCH_UP
            self._drain_catch_up()
            self._streaming_phase = OnlyStreamingPhase.LIVE
            self._streaming_worker.start()
        except Exception:
            self._streaming_phase = OnlyStreamingPhase.FAILED
            self._unsubscribe()
            self._observation_publisher.stop()
            raise

    def start(self) -> None:
        try:
            super().start()
        except Exception:
            self._streaming_phase = OnlyStreamingPhase.FAILED
            raise
        for key, bar in sorted(self._latest_bars.items(), key=lambda item: str(item[0])):
            self._publish_observations(bar, self._latest_sources[key])

    def wait(self, timeout: float | None = None) -> None:
        if self.state is not OnlyRuntimeState.RUNNING:
            raise OnlyRuntimeError("Streaming Runtime can only wait while RUNNING")
        self._stop_requested.wait(timeout)
        if self._streaming_worker.failure is not None:
            raise OnlyRuntimeError(
                f"streaming market-data worker failed: {self._streaming_worker.failure}"
            ) from self._streaming_worker.failure

    def run(self) -> object:
        raise OnlyRuntimeError("Streaming Runtime is long-lived; use start(), wait(), and stop()")

    def stop(self) -> None:
        if self.state in {OnlyRuntimeState.STOPPED, OnlyRuntimeState.CLOSED}:
            return
        self._stop_requested.set()
        self._streaming_phase = OnlyStreamingPhase.STOPPING
        self._unsubscribe()
        self._streaming_worker.stop()
        self._observation_publisher.stop()
        super().stop()
        self._streaming_phase = OnlyStreamingPhase.STOPPED

    def _unsubscribe(self) -> None:
        subscription_id = self._streaming_subscription_id
        if subscription_id is None:
            return
        unsubscribe = getattr(self._streaming_source, "unsubscribe", None)
        if callable(unsubscribe):
            unsubscribe(OnlyMarketDataUnsubscriptionRequest(f"stop-{self.runtime_id}", subscription_id))
        self._streaming_subscription_id = None

    def _bootstrap(self) -> None:
        load_warmup = getattr(self._streaming_source, "load_warmup", None)
        if not callable(load_warmup):
            raise OnlyRuntimeError("streaming DataSource does not provide the Historical Warmup Port")
        observed_at = OnlyTimestamp.from_datetime(self._services.clock.now_utc())
        bars: list[OnlyBar] = []
        alignment = lcm(*self._warmup_alignment_steps) if self._warmup_alignment_steps else 1
        for bar_type in sorted(self._streaming_subscription.bar_types, key=str):
            closed_cutoff = OnlyCompletedBarBoundaryResolver().latest_completed_bar_end(
                calendar=self._selected_calendar,
                bar_type=bar_type,
                observed_at=observed_at,
            )
            request = OnlyHistoricalWarmupRequest(
                f"bootstrap-{self.runtime_id}-{bar_type.instrument_id}-{bar_type.specification.step}",
                OnlyRuntimeId(self.runtime_id),
                bar_type.instrument_id,
                bar_type,
                self._bootstrap_bars + alignment,
                closed_cutoff,
                self._streaming_data_version,
                OnlyAdjustmentType.RAW,
                self._historical_timeout_seconds,
                self._historical_compatibility_profile,
            )
            result = load_warmup(request)
            self._historical_warmup_results.append(result)
            if result.status is not OnlyHistoricalWarmupStatus.SUCCESS:
                diagnostic = result.diagnostic
                detail = result.status.value if diagnostic is None else f"{result.status.value}: {diagnostic.code}"
                raise OnlyRuntimeError(f"historical warmup failed closed: {detail}")
            aligned = self._align_warmup_bars(result.bars)
            bars.extend(aligned)
            if not aligned:
                raise OnlyRuntimeError("historical warmup returned no aligned Bars")
            latest = aligned[-1]
            fingerprint = hashlib.sha256(
                json.dumps([item.to_dict() for item in aligned], sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            self._historical_watermarks[(str(bar_type.instrument_id), bar_type)] = OnlyHistoricalWatermark(
                self._streaming_source.source_id,  # type: ignore[union-attr]
                bar_type.instrument_id,
                bar_type,
                OnlyTimestamp.from_datetime(latest.bar_start),
                OnlyTimestamp.from_datetime(latest.bar_end),
                self._streaming_data_version,
                fingerprint,
            )
        ordered = sorted(bars, key=lambda bar: (bar.bar_end, str(bar.bar_type)))
        source_id = self._streaming_source.source_id  # type: ignore[union-attr]
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
        for update in records:
            result = self._services.market_data_processor.process(update)
            self._record_processing_result(result)
            if result.status in {
                OnlyMarketDataProcessingStatus.REJECTED,
                OnlyMarketDataProcessingStatus.FAILED,
                OnlyMarketDataProcessingStatus.STALE,
            }:
                raise OnlyRuntimeError(f"historical warmup failed: {result}")
            if not isinstance(update.payload, OnlyBarUpdate):
                raise AssertionError("historical warmup records must contain Bars")
            bar = update.payload.bar
            self._processed_bar_identities.add(
                (str(bar.instrument_id), bar.bar_type, OnlyTimestamp.from_datetime(bar.bar_start).unix_nanos)
            )
        self._live_finalizer.seed_closed_sequences(records)
        set_floor = getattr(self._streaming_source, "set_live_sequence_floor", None)
        if callable(set_floor) and records:
            set_floor(max(int(item.source_sequence) for item in records))

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

    def _record_processing_result(self, result: OnlyMarketDataProcessingResult) -> None:
        self._processing_results.append(result)
        if result.status is OnlyMarketDataProcessingStatus.DUPLICATE:
            self._duplicate_count += 1
        if result.status is OnlyMarketDataProcessingStatus.GAP_DETECTED:
            self._sequence_gap_count += 1
        pipeline = result.pipeline_result
        if isinstance(pipeline, OnlyMarketDataUpdateResult):
            bar = pipeline.base_bar
            key = (str(bar.instrument_id), bar.bar_type)
            self._latest_bars[key] = bar
            self._last_closed_bar_end = OnlyTimestamp.from_datetime(bar.bar_end)
            source = (
                OnlyObservationSource.HISTORICAL_BOOTSTRAP
                if self._streaming_phase is OnlyStreamingPhase.BOOTSTRAP
                else OnlyObservationSource.CATCH_UP
                if self._streaming_phase is OnlyStreamingPhase.CATCH_UP
                else OnlyObservationSource.LIVE
            )
            self._latest_sources[key] = source
            if self._streaming_phase is not OnlyStreamingPhase.BOOTSTRAP:
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
                    self._record_processing_result(self._services.market_data_processor.process(finalized))

    def _accept_streaming_update(self, update: OnlyMarketDataInboundUpdate) -> bool:
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
        bar = update.payload.bar
        identity = (str(bar.instrument_id), bar.bar_type, OnlyTimestamp.from_datetime(bar.bar_start).unix_nanos)
        if identity in self._processed_bar_identities:
            self._duplicate_count += 1
            return False
        self._processed_bar_identities.add(identity)
        return True

    def _intercept_order_submit(self, request: OnlyOrderRequest) -> OnlyOrderSubmitResult | None:
        del request
        if self._streaming_phase is OnlyStreamingPhase.BOOTSTRAP:
            return OnlyOrderSubmitResult(
                False, False, None, None, None, None, (), "ORDER_INTENT_SUPPRESSED_DURING_BOOTSTRAP"
            )
        if self._streaming_phase is OnlyStreamingPhase.CATCH_UP:
            return OnlyOrderSubmitResult(
                False, False, None, None, None, None, (), "ORDER_INTENT_SUPPRESSED_DURING_CATCH_UP"
            )
        return None

    def _publish_observations(self, bar: OnlyBar, source: OnlyObservationSource) -> None:
        observed = OnlyTimestamp.from_datetime(self._services.clock.now_utc())
        session = OnlyMarketSessionResolver(self._selected_calendar).resolve(observed)
        data_state = only_streaming_data_state(
            session=session,
            phase=self._streaming_phase,
            source_connected=self._streaming_subscription_id is not None,
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
                self._streaming_phase,
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

    def health(self) -> OnlyStreamingRuntimeHealth:
        observed = OnlyTimestamp.from_datetime(self._services.clock.now_utc())
        session = OnlyMarketSessionResolver(self._selected_calendar).resolve(observed)
        next_expected = self._next_expected_bar_end(session)
        state = only_streaming_data_state(
            session=session,
            phase=self._streaming_phase,
            source_connected=self._streaming_subscription_id is not None,
            observed_at=observed,
            next_expected_bar_end=next_expected,
            grace_seconds=self._stale_after_seconds,
        )
        return OnlyStreamingRuntimeHealth(
            self.state,
            self._streaming_phase,
            session.state,
            state,
            self._streaming_subscription_id is not None,
            self.worker_alive,
            self._last_received_at,
            self._last_closed_bar_end,
            next_expected,
            session.next_market_open,
            len(self._services.market_data_inbound),
            self._observation_publisher.queue_size,
            self._duplicate_count,
            self._overlap_count,
            self._sequence_gap_count,
            self._stale_count + int(state is OnlyStreamingDataState.STALE),
            self._observation_publisher.drop_count,
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
        steps = tuple(item.specification.step for item in self._streaming_subscription.bar_types)
        duration = timedelta(minutes=min(steps))
        last = self._last_closed_bar_end
        candidate = (
            active[0] + duration if last is None or last.to_datetime() < active[0] else last.to_datetime() + duration
        )
        return OnlyTimestamp.from_datetime(candidate) if candidate <= active[1] else None
