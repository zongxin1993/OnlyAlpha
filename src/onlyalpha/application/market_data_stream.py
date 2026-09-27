"""Provider-neutral realtime Market Data Product sessions."""

from __future__ import annotations

import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from logging import Logger
from pathlib import Path

from onlyalpha.application.market_data_product import (
    OnlyMarketDataProductError,
    OnlyMarketDataProductService,
    OnlyMarketDataSourceReferenceV1,
)
from onlyalpha.cache.historical import OnlyHistoricalCacheService, OnlyParquetHistoricalCacheStore
from onlyalpha.config.models import OnlyDataSourceCoverageConfig
from onlyalpha.core.clock import OnlyClock
from onlyalpha.data.enums import OnlyMarketDataConnectionState, OnlyMarketDataRequestStatus, OnlyMarketDataType
from onlyalpha.data.identifiers import OnlyDataVersion
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyMarketDataConnectionSnapshot,
    OnlyMarketDataInboundUpdate,
    OnlyMarketDataSubscriptionRequest,
    OnlyMarketDataUnsubscriptionRequest,
    OnlyRealtimeBarPreviewV1,
)
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.market_data.durable.drain import OnlyMarketDataDrainService
from onlyalpha.market_data.durable.ingress import OnlyMarketDataIngress
from onlyalpha.market_data.durable.models import OnlyRecordingState
from onlyalpha.market_data.durable.ports import OnlyMarketDataCatalog, OnlyMarketFactStore
from onlyalpha.market_data.durable.recorder import OnlyDurableMarketDataRecorder
from onlyalpha.market_data.durable.recovery import OnlyMarketDataRecoveryCoordinator
from onlyalpha.market_data.durable.revision import OnlyRevisionCommitService
from onlyalpha.market_data.durable.wal import OnlyMarketDataWal
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities
from onlyalpha.plugin.data_source import (
    OnlyDataSource,
    OnlyDataSourceCreateRequest,
    OnlyDataSourceInstrumentCatalogRequestV1,
)

_WAL_CAPACITY_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class OnlyMarketDataStreamEventV1:
    event: str
    payload: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "event": self.event, **self.payload}


class OnlyMarketDataStreamSession:
    def __init__(
        self,
        *,
        stream_id: str,
        source_id: str,
        instrument_id: str,
        source: OnlyDataSource,
        subscription_id: str,
        recorder: OnlyDurableMarketDataRecorder,
        drain: OnlyMarketDataDrainService,
        recovery: OnlyMarketDataRecoveryCoordinator,
        reliable_capacity: int,
        on_close: Callable[[str], None],
    ) -> None:
        self.stream_id = stream_id
        self.source_id = source_id
        self.instrument_id = instrument_id
        self._source = source
        self._subscription_id = subscription_id
        self._recorder = recorder
        self._drain = drain
        self._recovery = recovery
        self._events: queue.Queue[OnlyMarketDataStreamEventV1] = queue.Queue(reliable_capacity)
        self._preview: OnlyMarketDataStreamEventV1 | None = None
        self._terminal: OnlyMarketDataStreamEventV1 | None = None
        self._pending: list[OnlyMarketDataStreamEventV1] = []
        self._active = False
        self._connection_state = "CONNECTING"
        self._drain_degraded = False
        self._lock = threading.Lock()
        self._closed = False
        self._on_close = on_close

    def bind_subscription(self, subscription_id: str) -> None:
        self._subscription_id = subscription_id

    def activate(self, subscribed: OnlyMarketDataStreamEventV1) -> None:
        with self._lock:
            pending, self._pending, self._active = tuple(self._pending), [], True
        self.emit_reliable(subscribed)
        for event in pending:
            self.emit_reliable(event)

    def emit_reliable(self, event: OnlyMarketDataStreamEventV1) -> None:
        with self._lock:
            if not self._active:
                self._pending.append(event)
                return
            if self._terminal is not None:
                return
            try:
                self._events.put_nowait(event)
            except queue.Full:
                self._terminal = OnlyMarketDataStreamEventV1(
                    "ERROR", {"code": "MARKET_DATA_STREAM_BACKPRESSURE", "detail": "reliable event queue full"}
                )

    def emit_preview(self, preview: OnlyRealtimeBarPreviewV1) -> None:
        with self._lock:
            self._preview = OnlyMarketDataStreamEventV1("BAR_PREVIEW", _preview_payload(preview))

    def emit_state(self, state: str) -> None:
        self._connection_state = state
        self.emit_reliable(OnlyMarketDataStreamEventV1("STATE", {"state": state}))

    def next_event(self, timeout: float = 0.25) -> OnlyMarketDataStreamEventV1 | None:
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            with self._lock:
                if self._preview is not None:
                    event, self._preview = self._preview, None
                    return event
                if self._terminal is not None:
                    event, self._terminal = self._terminal, None
                    return event
            health = getattr(self._drain, "health", None)
            if callable(health):
                degraded = health().recording_state is not OnlyRecordingState.HEALTHY
                if degraded != self._drain_degraded:
                    self._drain_degraded = degraded
                    return OnlyMarketDataStreamEventV1(
                        "STATE",
                        {"state": "DEGRADED" if degraded else self._connection_state},
                    )
            return None

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        failure: Exception | None = None
        actions = (
            lambda: self._source.unsubscribe(
                OnlyMarketDataUnsubscriptionRequest(f"close-{self.stream_id}", self._subscription_id)
            ),
            self._source.stop,
            self._recorder.close,
            self._drain.stop,
            self._recovery.recover_all,
        )
        for action in actions:
            try:
                action()
            except Exception as exc:  # cleanup must continue through every owned resource
                failure = failure or exc
        self.emit_reliable(OnlyMarketDataStreamEventV1("STATE", {"state": "CLOSED"}))
        self._on_close(self.stream_id)
        if failure is not None:
            raise failure


class OnlyMarketDataStreamProductService:
    def __init__(
        self,
        *,
        historical: OnlyMarketDataProductService,
        catalog: OnlyMarketDataCatalog,
        fact_store: OnlyMarketFactStore,
        wal_root: Path,
        clock: OnlyClock,
        logger: Logger,
        max_streams: int = 8,
        reliable_capacity: int = 256,
        batch_size: int = 1024,
    ) -> None:
        self._historical = historical
        self._catalog = catalog
        self._facts = fact_store
        self._wal_root = wal_root
        self._clock = clock
        self._logger = logger
        self._slots = threading.BoundedSemaphore(max_streams)
        self._reliable_capacity = reliable_capacity
        self._batch_size = batch_size
        self._sessions: dict[str, OnlyMarketDataStreamSession] = {}
        self._lock = threading.Lock()
        self._recover_existing()

    def open(
        self,
        reference: OnlyMarketDataSourceReferenceV1,
        *,
        instrument_id: str,
        bar_specification: str,
        resume_after_sequence: int,
    ) -> OnlyMarketDataStreamSession:
        if not self._slots.acquire(blocking=False):
            raise OnlyMarketDataProductError("MARKET_DATA_STREAM_CAPACITY_EXCEEDED")
        try:
            return self._open(
                reference,
                instrument_id=instrument_id,
                bar_specification=bar_specification,
                resume_after_sequence=resume_after_sequence,
            )
        except Exception:
            self._slots.release()
            raise

    def _open(
        self,
        reference: OnlyMarketDataSourceReferenceV1,
        *,
        instrument_id: str,
        bar_specification: str,
        resume_after_sequence: int,
    ) -> OnlyMarketDataStreamSession:
        if bar_specification != "1m":
            raise OnlyMarketDataProductError("MARKET_DATA_BAR_SPECIFICATION_UNSUPPORTED")
        resolved = self._historical.resolve_runtime(reference)
        try:
            instrument_key = OnlyInstrumentId.parse(instrument_id)
        except Exception as exc:
            raise OnlyMarketDataProductError("MARKET_DATA_INSTRUMENT_INVALID") from exc
        projected = resolved.catalog.list_instruments(
            OnlyDataSourceInstrumentCatalogRequestV1(resolved.plugin_config, instrument_ids=(instrument_id,))
        )
        if len(projected) != 1:
            raise OnlyMarketDataProductError("MARKET_DATA_INSTRUMENT_NOT_FOUND")
        instrument = projected[0].instrument
        stream_id = uuid.uuid4().hex
        root = self._wal_root / str(resolved.source_id) / "realtime" / stream_id
        wal = OnlyMarketDataWal(root / "wal", capacity_bytes=_WAL_CAPACITY_BYTES)
        descriptor = resolved.factory.descriptor  # type: ignore[attr-defined]
        recovery = OnlyMarketDataRecoveryCoordinator(
            wal,
            self._facts,
            self._catalog,
            OnlyRevisionCommitService(self._facts, self._catalog),
        )
        recovery.recover_all()
        drain = OnlyMarketDataDrainService(recovery)
        session_ref: list[OnlyMarketDataStreamSession] = []
        recorder = OnlyDurableMarketDataRecorder(
            OnlyMarketDataIngress(
                wal,
                normalizer_id=str(descriptor.plugin_id),
                normalizer_version=str(descriptor.plugin_version),
                ingest_clock_ns=self._clock.timestamp_ns,
                integration_binding_fingerprint=resolved.binding_fingerprint,
            ),
            max_records_per_segment=1,
            on_sealed=drain.submit,
            on_start=drain.start,
            health_view=drain.health,
        )

        def on_update(update: OnlyMarketDataInboundUpdate) -> None:
            if session_ref:
                event = _closed_event(update, str(resolved.source_id))
                if event is not None:
                    session_ref[0].emit_reliable(event)

        def on_preview(preview: OnlyRealtimeBarPreviewV1) -> None:
            if session_ref:
                session_ref[0].emit_preview(preview)

        def on_connection(snapshot: OnlyMarketDataConnectionSnapshot) -> None:
            if session_ref:
                session_ref[0].emit_state(_product_state(snapshot.state))

        from onlyalpha.application.market_data_product import _bar_type

        request = OnlyDataSourceCreateRequest(
            resolved.source_id,
            resolved.plugin_config,
            "PRODUCT",
            OnlyDataSourceCapabilities(historical_bars=True, live_bars=True, live_reconnect=True),
            self._clock,
            OnlyEventBus(),
            {instrument_key: instrument},
            {instrument_key: _bar_type(instrument_key)},
            {},
            (),
            OnlyDataSourceCoverageConfig(instrument_ids=(instrument_key,)),
            OnlyRuntimeId(f"market-data-stream:{stream_id}"),
            OnlyDataVersion(str(resolved.data_version)),
            self._batch_size,
            root,
            self._logger,
            market_data_sink=on_update,
            market_data_preview_sink=on_preview,
            market_data_connection_sink=on_connection,
            historical_cache_service=OnlyHistoricalCacheService(
                OnlyParquetHistoricalCacheStore(root / "historical-cache")
            ),
            runtime_state_root=root,
            provider_evidence_sink=recorder,
            durable_recording_required=True,
        )
        source: OnlyDataSource = resolved.factory.create(request)  # type: ignore[attr-defined]
        session = OnlyMarketDataStreamSession(
            stream_id=stream_id,
            source_id=str(resolved.source_id),
            instrument_id=instrument_id,
            source=source,
            subscription_id="",
            recorder=recorder,
            drain=drain,
            recovery=recovery,
            reliable_capacity=self._reliable_capacity,
            on_close=self._remove,
        )
        session_ref.append(session)
        try:
            source.initialize()
            source.connect()
            source.authenticate()
            source.start()
            subscription = source.subscribe(
                OnlyMarketDataSubscriptionRequest(
                    stream_id,
                    resolved.source_id,
                    frozenset({instrument_key}),
                    frozenset({OnlyMarketDataType.BAR}),
                    frozenset({_bar_type(instrument_key)}),
                    resume_after_sequence,
                )
            )
        except Exception as exc:
            source.stop()
            drain.stop()
            recovery.recover_all()
            code = (
                "HISTORY_REFRESH_REQUIRED"
                if "HISTORY_REFRESH_REQUIRED" in str(exc)
                else "MARKET_DATA_STREAM_SUBSCRIBE_FAILED"
            )
            raise OnlyMarketDataProductError(code, str(exc)) from exc
        if subscription.status is not OnlyMarketDataRequestStatus.ACCEPTED or subscription.subscription_id is None:
            source.stop()
            drain.stop()
            recovery.recover_all()
            raise OnlyMarketDataProductError("MARKET_DATA_STREAM_SUBSCRIBE_FAILED", subscription.reason)
        session.bind_subscription(subscription.subscription_id)
        session.activate(
            OnlyMarketDataStreamEventV1(
                "SUBSCRIBED",
                {"stream_id": stream_id, "source_id": str(resolved.source_id), "instrument_id": instrument_id},
            )
        )
        with self._lock:
            self._sessions[stream_id] = session
        return session

    def close(self) -> None:
        with self._lock:
            sessions = tuple(self._sessions.values())
        for session in sessions:
            session.close()

    def _remove(self, stream_id: str) -> None:
        with self._lock:
            removed = self._sessions.pop(stream_id, None)
        if removed is not None:
            self._slots.release()

    def _recover_existing(self) -> None:
        for path in sorted(self._wal_root.glob("*/realtime/*/wal")):
            try:
                wal = OnlyMarketDataWal(path, capacity_bytes=_WAL_CAPACITY_BYTES)
                OnlyMarketDataRecoveryCoordinator(
                    wal,
                    self._facts,
                    self._catalog,
                    OnlyRevisionCommitService(self._facts, self._catalog),
                ).recover_all()
            except Exception as exc:
                self._logger.warning("realtime market-data WAL recovery deferred for %s: %s", path, exc)


def _product_state(state: OnlyMarketDataConnectionState) -> str:
    if state is OnlyMarketDataConnectionState.READY:
        return "READY"
    if state is OnlyMarketDataConnectionState.RECOVERING:
        return "RECOVERING"
    if state is OnlyMarketDataConnectionState.FAILED:
        return "FAILED"
    if state in {OnlyMarketDataConnectionState.DISCONNECTED, OnlyMarketDataConnectionState.RECONNECTING}:
        return "DEGRADED"
    return "CONNECTING"


def _preview_payload(preview: OnlyRealtimeBarPreviewV1) -> dict[str, object]:
    return {
        "source_id": str(preview.source_id),
        "instrument_id": str(preview.instrument_id),
        "bar_specification": "1m",
        "bar": {
            "bar_start_ns": str(preview.bar_start_ns),
            "bar_end_ns": str(preview.bar_end_ns),
            "open": preview.open,
            "high": preview.high,
            "low": preview.low,
            "close": preview.close,
            "volume": preview.volume,
            "closed": False,
        },
    }


def _closed_event(update: OnlyMarketDataInboundUpdate, source_id: str) -> OnlyMarketDataStreamEventV1 | None:
    if not isinstance(update.payload, OnlyBarUpdate):
        return None
    bar = update.payload.bar
    payload = _preview_payload(
        OnlyRealtimeBarPreviewV1(
            update.source_id,
            update.instrument_id,
            bar.bar_type,
            OnlyTimestamp.from_datetime(bar.bar_start).unix_nanos,
            OnlyTimestamp.from_datetime(bar.bar_end).unix_nanos,
            str(bar.open.value),
            str(bar.high.value),
            str(bar.low.value),
            str(bar.close.value),
            str(bar.volume.value),
            update.ts_event.unix_nanos,
            update.ts_init.unix_nanos,
        )
    )
    payload["source_id"] = source_id
    payload["bar"]["closed"] = True  # type: ignore[index]
    payload["sequence"] = str(int(update.source_sequence))
    return OnlyMarketDataStreamEventV1("BAR_CLOSED", payload)


__all__ = [name for name in globals() if name.startswith("Only")]
