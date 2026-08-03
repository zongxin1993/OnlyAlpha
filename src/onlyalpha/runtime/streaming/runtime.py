"""Shared long-lived Runtime kernel for Paper and future Live composition roots."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from threading import Event

from onlyalpha.core.clock import OnlyLiveClock
from onlyalpha.data.enums import OnlyMarketDataProcessingStatus
from onlyalpha.data.identifiers import OnlyDataVersion
from onlyalpha.data.models import (
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataRange,
    OnlyMarketDataProcessingResult,
    OnlyMarketDataSubscriptionRequest,
    OnlyMarketDataUnsubscriptionRequest,
)
from onlyalpha.data.ports import OnlyHistoricalDataSource, OnlyMarketDataGateway
from onlyalpha.data.queue import OnlyMarketDataInboundQueue
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyRuntimeMode
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.time import OnlyTimestamp
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
        if self._bootstrap_bars <= 0:
            return
        load_bars = getattr(self._streaming_source, "load_bars", None)
        if not callable(load_bars):
            raise OnlyRuntimeError("streaming DataSource does not provide historical Bar warmup")
        now = self._services.clock.now_utc()
        closed_cutoff = now.replace(second=0, microsecond=0)
        request = OnlyHistoricalBarRequest(
            f"bootstrap-{self.runtime_id}",
            self._streaming_subscription.instrument_ids,
            self._streaming_subscription.bar_types,
            OnlyHistoricalDataRange(
                closed_cutoff - timedelta(minutes=max(self._bootstrap_bars * 3, 10)),
                closed_cutoff,
            ),
            self._streaming_data_version,
            batch_size=self._bootstrap_bars,
        )
        loaded = tuple(load_bars(request))[-self._bootstrap_bars :]
        records = tuple(
            replace(update, source_sequence=type(update.source_sequence)(sequence))
            for sequence, update in enumerate(loaded, start=1)
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

    def _record_processing_result(self, result: OnlyMarketDataProcessingResult) -> None:
        self._processing_results.append(result)
