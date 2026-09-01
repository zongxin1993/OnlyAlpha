"""Production provider-neutral WAL ownership boundary."""

from __future__ import annotations

import threading
from collections.abc import Callable

from onlyalpha.data.evidence import OnlyDurableRecordReceipt, OnlyRawProviderObservation
from onlyalpha.data.models import OnlyMarketDataInboundUpdate

from .ingress import OnlyMarketDataIngress
from .models import OnlyIngestSegment, OnlyMarketDataHealth


class OnlyDurableMarketDataRecorder:
    """Accept one provider observation only after its WAL frame is fsynced."""

    def __init__(
        self,
        ingress: OnlyMarketDataIngress,
        *,
        max_records_per_segment: int = 1024,
        on_sealed: Callable[[OnlyIngestSegment], None] | None = None,
        on_start: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
        health_view: Callable[[], OnlyMarketDataHealth] | None = None,
    ) -> None:
        if max_records_per_segment <= 0:
            raise ValueError("MARKET_DATA_SEGMENT_MAX_RECORDS_INVALID")
        self._ingress = ingress
        self._lock = threading.Lock()
        self._max_records = max_records_per_segment
        self._on_sealed = on_sealed or (lambda _segment: None)
        self._on_start = on_start or (lambda: None)
        self._on_close = on_close or (lambda: None)
        self._health_view = health_view
        self._records = 0
        self._scope: tuple[object, ...] | None = None

    def __call__(
        self,
        observation: OnlyRawProviderObservation,
        canonical_update: OnlyMarketDataInboundUpdate | tuple[OnlyMarketDataInboundUpdate, ...] | None,
    ) -> OnlyDurableRecordReceipt:
        with self._lock:
            scope = self._observation_scope(observation, canonical_update)
            if self._ingress.segment_open and scope != self._scope:
                self._seal()
            if not self._ingress.segment_open:
                self._ingress.begin_segment()
                self._scope = scope
            receipt = self._ingress.record(observation, canonical_update)
            self._records += 1
            if self._records >= self._max_records:
                self._seal()
            return receipt

    def start(self) -> None:
        self._on_start()

    def close(self) -> None:
        """Seal a non-empty tail deterministically during clean shutdown."""

        with self._lock:
            if self._ingress.segment_open and self._records:
                self._seal()
        self._on_close()

    def _seal(self) -> None:
        segment = self._ingress.seal()
        self._records = 0
        self._scope = None
        self._on_sealed(segment)

    @staticmethod
    def _observation_scope(
        observation: OnlyRawProviderObservation,
        canonical_update: OnlyMarketDataInboundUpdate | tuple[OnlyMarketDataInboundUpdate, ...] | None,
    ) -> tuple[object, ...]:
        updates = (
            ()
            if canonical_update is None
            else canonical_update
            if isinstance(canonical_update, tuple)
            else (canonical_update,)
        )
        canonical_scope = tuple(
            (str(item.source_id), str(item.instrument_id), item.data_type.value, str(item.data_version), item.bar_type)
            for item in updates
        )
        return (
            observation.capture_session_id,
            str(observation.source_id),
            observation.provider,
            observation.venue,
            observation.market,
            observation.stream,
            observation.provenance,
            observation.provider_schema,
            observation.payload_codec,
            canonical_scope,
        )

    def health(self) -> OnlyMarketDataHealth:
        return self._ingress.health() if self._health_view is None else self._health_view()


__all__ = ["OnlyDurableMarketDataRecorder"]
