"""External-world driver for long-lived normalized market-data delivery."""

from __future__ import annotations

from threading import Event

from onlyalpha.core.clock import OnlyLiveClock
from onlyalpha.data.models import OnlyMarketDataSubscriptionRequest
from onlyalpha.data.ports import OnlyHistoricalDataSource, OnlyMarketDataGateway
from onlyalpha.data.processor import OnlyMarketDataProcessor
from onlyalpha.data.queue import OnlyMarketDataInboundQueue
from onlyalpha.plugin.lifecycle import OnlyPluginResource
from onlyalpha.runtime.streaming.live_bar import OnlyLiveBarFinalizer
from onlyalpha.runtime.streaming.worker import OnlyStreamingMarketDataWorker


class OnlyStreamingMarketDataDriver:
    """Own subscription/worker termination mechanics, not trading authorities."""

    def __init__(
        self,
        *,
        source: OnlyHistoricalDataSource | OnlyMarketDataGateway | OnlyPluginResource,
        subscription: OnlyMarketDataSubscriptionRequest,
        inbound_queue: OnlyMarketDataInboundQueue,
        processor: OnlyMarketDataProcessor,
        finalizer: OnlyLiveBarFinalizer,
        clock: OnlyLiveClock,
        on_result: object,
        accept_update: object,
        accept_finalized: object,
    ) -> None:
        self.source = source
        self.subscription = subscription
        self.subscription_id: str | None = None
        self.stop_requested = Event()
        self.worker = OnlyStreamingMarketDataWorker(
            inbound_queue,
            processor,
            finalizer,
            clock,
            maximum_future_wait_seconds=10.0,
            on_result=on_result,  # type: ignore[arg-type]
            accept_update=accept_update,  # type: ignore[arg-type]
            accept_finalized=accept_finalized,  # type: ignore[arg-type]
        )

    def start_worker(self) -> None:
        self.worker.start()

    def wait(self, timeout: float | None) -> None:
        self.stop_requested.wait(timeout)

    def request_stop(self) -> None:
        self.stop_requested.set()
        self.worker.request_stop()

    @property
    def alive(self) -> bool:
        return self.worker.alive

    @property
    def failure(self) -> BaseException | None:
        return self.worker.failure
