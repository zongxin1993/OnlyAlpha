"""Shared long-lived Runtime kernel for Paper and future Live composition roots."""

from __future__ import annotations

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
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.order.execution.service import OnlyExecutionService
from onlyalpha.plugin.lifecycle import OnlyPluginResource
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.persistence.store import OnlyRuntimePersistenceStorePort
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig, OnlyRuntimeError, OnlyRuntimeState

from .live_bar import OnlyLiveBarFinalizer
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
    ) -> None:
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
        self._historical_warmup_results: list[OnlyHistoricalWarmupResult] = []
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
        )
        self._services.market_data_source_registry.register(data_source)  # type: ignore[arg-type]

    @property
    def processing_results(self) -> tuple[OnlyMarketDataProcessingResult, ...]:
        return tuple(self._processing_results)

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
        self._bootstrap()
        subscribe = getattr(self._streaming_source, "subscribe", None)
        if not callable(subscribe):
            raise OnlyRuntimeError("streaming DataSource does not provide subscribe()")
        result = subscribe(self._streaming_subscription)
        if result.subscription_id is None:
            raise OnlyRuntimeError(f"live subscription failed: {result.reason}")
        self._streaming_subscription_id = result.subscription_id
        self._streaming_worker.start()

    def wait(self, timeout: float | None = None) -> None:
        if self.state is not OnlyRuntimeState.RUNNING:
            raise OnlyRuntimeError("Streaming Runtime can only wait while RUNNING")
        self._stop_requested.wait(timeout)
        if self._streaming_worker.failure is not None:
            raise OnlyRuntimeError(
                f"streaming market-data worker failed: {self._streaming_worker.failure}"
            ) from self._streaming_worker.failure

    def stop(self) -> None:
        if self.state in {OnlyRuntimeState.STOPPED, OnlyRuntimeState.CLOSED}:
            return
        self._stop_requested.set()
        subscription_id = self._streaming_subscription_id
        if subscription_id is not None:
            unsubscribe = getattr(self._streaming_source, "unsubscribe", None)
            if callable(unsubscribe):
                unsubscribe(
                    OnlyMarketDataUnsubscriptionRequest(
                        f"stop-{self.runtime_id}",
                        subscription_id,
                    )
                )
            self._streaming_subscription_id = None
        self._streaming_worker.stop()
        super().stop()

    def _bootstrap(self) -> None:
        load_warmup = getattr(self._streaming_source, "load_warmup", None)
        if not callable(load_warmup):
            raise OnlyRuntimeError("streaming DataSource does not provide the Historical Warmup Port")
        now = self._services.clock.now_utc()
        closed_cutoff = now.replace(second=0, microsecond=0)
        bars: list[OnlyBar] = []
        alignment = lcm(*self._warmup_alignment_steps) if self._warmup_alignment_steps else 1
        for bar_type in sorted(self._streaming_subscription.bar_types, key=str):
            request = OnlyHistoricalWarmupRequest(
                f"bootstrap-{self.runtime_id}-{bar_type.instrument_id}-{bar_type.specification.step}",
                OnlyRuntimeId(self.runtime_id),
                bar_type.instrument_id,
                bar_type,
                self._bootstrap_bars + alignment,
                OnlyTimestamp.from_datetime(closed_cutoff),
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
            bars.extend(self._align_warmup_bars(result.bars))
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
