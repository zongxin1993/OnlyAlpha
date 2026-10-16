"""Provider-neutral realtime Market Data Product sessions."""

from __future__ import annotations

import json
import logging
import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from decimal import Decimal
from logging import Logger
from pathlib import Path

from onlyalpha.application.market_data_product import (
    BASE_BAR_SEMANTIC,
    OnlyMarketDataProductError,
    OnlyMarketDataProductService,
    OnlyMarketDataSourceReferenceV1,
    OnlyMarketDataSourceSelectionV1,
    OnlyResolvedMarketDataRuntime,
    only_product_bar_semantic,
)
from onlyalpha.application.source_read_access import OnlySourceReadPermission, OnlySourceReadSession
from onlyalpha.cache.historical import OnlyHistoricalCacheService, OnlyParquetHistoricalCacheStore
from onlyalpha.canonical import only_canonical_fingerprint
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
    OnlyRealtimeIngressObservation,
)
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyAdjustmentType
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBar, OnlyBarSemantic, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.market_data.aggregation.base import OnlyBarAggregationError
from onlyalpha.market_data.aggregation.time_bar import OnlyTimeBarAggregator
from onlyalpha.market_data.durable.diagnostics import only_market_data_diagnostic_error
from onlyalpha.market_data.durable.drain import OnlyMarketDataDrainService
from onlyalpha.market_data.durable.ingress import OnlyMarketDataIngress
from onlyalpha.market_data.durable.models import (
    OnlyBarCoverageGap,
    OnlyCoverageStatus,
    OnlyMarketDataRangeFamily,
    OnlyRecordingState,
)
from onlyalpha.market_data.durable.ports import OnlyMarketDataCatalog, OnlyMarketFactStore
from onlyalpha.market_data.durable.recorder import OnlyDurableMarketDataRecorder
from onlyalpha.market_data.durable.recovery import OnlyMarketDataRecoveryCoordinator
from onlyalpha.market_data.durable.revision import (
    OnlyMarketDataConflictError,
    OnlyMarketDataSealError,
    OnlyRevisionCommitService,
)
from onlyalpha.market_data.durable.wal import OnlyMarketDataWal
from onlyalpha.market_data.resolution import (
    OnlyBarConstructionAlgorithmRegistry,
    OnlyBarConstructionIdentity,
    OnlyBarResolutionMode,
    OnlyBarResolutionPlan,
)
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities
from onlyalpha.plugin.data_source import (
    OnlyDataSource,
    OnlyDataSourceCreateRequest,
    OnlyDataSourceInstrumentCatalogRequestV1,
    OnlyDataSourceTimeBarCalendar,
)

_WAL_CAPACITY_BYTES = 256 * 1024 * 1024
_MINUTE_NS = 60_000_000_000
_PREVIEW_ISSUANCE = object()


@dataclass(frozen=True, slots=True)
class OnlyMarketDataStreamEventV1:
    event: str
    payload: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 2, "event": self.event, **self.payload}


@dataclass(frozen=True, slots=True, init=False)
class OnlyChartStudyPreviewInput:
    """Disposable owning-stream witness, never scientific input evidence."""

    stream_id: str
    revision_fingerprint: str
    _session: OnlyMarketDataStreamSession = field(repr=False)
    _preview: OnlyRealtimeBarPreviewV1 = field(repr=False)
    _issuance: object = field(repr=False)

    def require_current(self) -> None:
        if getattr(self, "_issuance", None) is not _PREVIEW_ISSUANCE:
            raise ValueError("CHART_STUDY_PREVIEW_UNAVAILABLE")
        session = self._session
        with session._lock:
            session._require_preview_access()
            if session._owned_preview is not self._preview:
                raise ValueError("CHART_STUDY_PREVIEW_UNAVAILABLE")

    def require_preview(self) -> OnlyRealtimeBarPreviewV1:
        self.require_current()
        return self._preview


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
        aggregator: OnlyTimeBarAggregator | None = None,
        instrument: OnlyInstrument | None = None,
        calendar: OnlyTradingCalendar | None = None,
        native_bar_type: OnlyBarType | None = None,
        source_reference: OnlyMarketDataSourceReferenceV1 | None = None,
        source_selection: OnlyMarketDataSourceSelectionV1 | None = None,
        bar_semantic: OnlyBarSemantic | None = None,
        read_session: OnlySourceReadSession | None = None,
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
        self._aggregator = aggregator
        self._instrument = instrument
        self._calendar = calendar
        self._native_bar_type = native_bar_type
        self._projection_lock = threading.Lock()
        self._source_reference = source_reference
        self._source_selection = source_selection
        self._bar_semantic = bar_semantic
        self._read_session = read_session
        self._owned_preview: OnlyRealtimeBarPreviewV1 | None = None
        self._preview_order: tuple[int, int] | None = None
        self._closed_through_ns = 0

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
                self._owned_preview = None
                self._terminal = OnlyMarketDataStreamEventV1(
                    "ERROR", {"code": "MARKET_DATA_STREAM_BACKPRESSURE", "detail": "reliable event queue full"}
                )

    def emit_preview(self, preview: OnlyRealtimeBarPreviewV1) -> None:
        if self._aggregator is not None:
            if self._instrument is None or self._calendar is None:
                raise OnlyMarketDataProductError("MARKET_DATA_TIME_BAR_CALENDAR_UNAVAILABLE")
            start = OnlyTimestamp.from_unix_nanos(preview.bar_start_ns).to_datetime()
            end = OnlyTimestamp.from_unix_nanos(preview.bar_end_ns).to_datetime()
            session = self._calendar.session_at(start)
            if session is None:
                return
            bar = OnlyBar(
                bar_type=preview.bar_type,
                open=OnlyPrice(Decimal(preview.open), self._instrument.price_precision),
                high=OnlyPrice(Decimal(preview.high), self._instrument.price_precision),
                low=OnlyPrice(Decimal(preview.low), self._instrument.price_precision),
                close=OnlyPrice(Decimal(preview.close), self._instrument.price_precision),
                volume=OnlyQuantity(Decimal(preview.volume), self._instrument.quantity_precision),
                quote_volume=None,
                turnover=None,
                trade_count=None,
                open_interest=None,
                bar_start=start,
                bar_end=end,
                ts_event=OnlyTimestamp.from_unix_nanos(preview.ts_event_ns).to_datetime(),
                ts_init=OnlyTimestamp.from_unix_nanos(max(preview.ts_receive_ns, preview.ts_event_ns)).to_datetime(),
                is_closed=False,
                revision=0,
                adjustment_type=OnlyAdjustmentType.RAW,
                trading_day=self._calendar.trading_day_at(start).value,
                session_type=session.session_type,
            )
            with self._projection_lock:
                projected = self._aggregator.preview(bar)
            if projected is None:
                return
            preview = _bar_preview(projected, preview)
        with self._lock:
            if self._closed:
                return
            self._retain_preview(preview)
            payload = _preview_payload(preview)
            payload["timing"] = self._timing_payload(
                preview.ingress_observation, preview.source_id, preview.instrument_id, preview.bar_type
            )
            self._preview = OnlyMarketDataStreamEventV1("BAR_PREVIEW", payload)

    def _retain_preview(self, preview: OnlyRealtimeBarPreviewV1) -> None:
        # Called under the same lock as delivery: consuming the event never consumes ownership.
        if (
            self._connection_state != "READY"
            or str(preview.source_id) != self.source_id
            or str(preview.instrument_id) != self.instrument_id
            or preview.bar_type.semantic != self._bar_semantic
            or preview.bar_type.instrument_id != preview.instrument_id
            or preview.closed
            or preview.bar_start_ns < self._closed_through_ns
            or preview.bar_start_ns >= preview.bar_end_ns
        ):
            return
        try:
            opening, high, low, close, volume = (
                Decimal(value) for value in (preview.open, preview.high, preview.low, preview.close, preview.volume)
            )
            if not all(value.is_finite() for value in (opening, high, low, close, volume)):
                raise ValueError("nonfinite preview")
            if not low <= opening <= high or not low <= close <= high or volume < 0:
                raise ValueError("invalid preview")
        except (ValueError, ArithmeticError):
            self._owned_preview = None
            return
        order = (preview.bar_start_ns, preview.ts_event_ns)
        if self._preview_order is not None and order < self._preview_order:
            return
        if order == self._preview_order:
            current = self._owned_preview
            if current is not None and (
                current.bar_end_ns,
                current.open,
                current.high,
                current.low,
                current.close,
                current.volume,
            ) == (preview.bar_end_ns, preview.open, preview.high, preview.low, preview.close, preview.volume):
                return
            self._owned_preview = None
            return
        self._preview_order = order
        self._owned_preview = preview

    def _require_preview_access(self) -> None:
        # Caller holds _lock. Missing proof is unavailable, never a stale fallback.
        if (
            self._closed
            or not self._active
            or self._connection_state != "READY"
            or self._terminal is not None
            or self._drain_degraded
            or self._read_session is None
            or self._source_selection is None
        ):
            raise ValueError("CHART_STUDY_PREVIEW_UNAVAILABLE")
        self._read_session.require_selection(self._source_selection, OnlySourceReadPermission.REALTIME_PREVIEW)
        health = getattr(self._drain, "health", None)
        if callable(health) and health().recording_state is not OnlyRecordingState.HEALTHY:
            self._owned_preview = None
            raise ValueError("CHART_STUDY_PREVIEW_UNAVAILABLE")

    def _invalidate_closed_preview(self, bar: OnlyBar) -> None:
        with self._lock:
            if str(bar.instrument_id) != self.instrument_id or bar.bar_type.semantic != self._bar_semantic:
                return
            self._closed_through_ns = max(self._closed_through_ns, OnlyTimestamp.from_datetime(bar.bar_end).unix_nanos)
            if self._owned_preview is not None and self._owned_preview.bar_start_ns < self._closed_through_ns:
                self._owned_preview = None

    def emit_closed(self, update: OnlyMarketDataInboundUpdate) -> None:
        if not isinstance(update.payload, OnlyBarUpdate):
            return
        matches_owner = str(update.source_id) == self.source_id and str(update.instrument_id) == self.instrument_id
        if self._aggregator is None:
            if matches_owner:
                self._invalidate_closed_preview(update.payload.bar)
            event = _closed_event(update, self.source_id)
            if event is not None:
                observation = (
                    update.ingress_observation
                    if update.runtime_id == OnlyRuntimeId(f"market-data-stream:{self.stream_id}")
                    else None
                )
                event.payload["timing"] = self._timing_payload(
                    observation, update.source_id, update.instrument_id, update.bar_type
                )
                self.emit_reliable(event)
            return
        with self._projection_lock:
            try:
                projected = self._aggregator.process(update.payload.bar)
            except OnlyBarAggregationError as exc:
                self.emit_reliable(
                    OnlyMarketDataStreamEventV1(
                        "ERROR", {"code": "MARKET_DATA_DERIVED_SOURCE_INVALID", "detail": str(exc)}
                    )
                )
                return
        self.emit_reliable(OnlyMarketDataStreamEventV1("BASE_CURSOR", {"sequence": str(int(update.source_sequence))}))
        if projected is not None:
            if matches_owner:
                self._invalidate_closed_preview(projected)
            payload = _preview_payload(_bar_preview(projected, None, update))
            payload["bar"]["closed"] = True  # type: ignore[index]
            payload["sequence"] = str(int(update.source_sequence))
            self.emit_reliable(OnlyMarketDataStreamEventV1("BAR_CLOSED", payload))

    def _timing_payload(
        self,
        observation: OnlyRealtimeIngressObservation | None,
        source_id: object,
        instrument_id: object,
        bar_type: OnlyBarType | None,
    ) -> dict[str, object] | None:
        if (
            observation is None
            or self._closed
            or self._aggregator is not None
            or observation.runtime_id != OnlyRuntimeId(f"market-data-stream:{self.stream_id}")
            or str(source_id) != self.source_id
            or str(instrument_id) != self.instrument_id
            or self._native_bar_type is None
            or bar_type != self._native_bar_type
        ):
            return None
        return {
            "stream_id": self.stream_id,
            "provider_event_ns": None if observation.provider_event_ns is None else str(observation.provider_event_ns),
            "ingress_received_ns": None
            if observation.ingress_received_ns is None
            else str(observation.ingress_received_ns),
        }

    def emit_state(self, state: str) -> None:
        with self._lock:
            self._connection_state = state
            if state != "READY":
                self._owned_preview = None
            # Reliable STATE is drained before the coalesced preview slot. Keep
            # its price projection, but never deliver old telemetry after loss.
            if state != "READY" and self._preview is not None:
                self._preview = OnlyMarketDataStreamEventV1(
                    self._preview.event, {**self._preview.payload, "timing": None}
                )
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
                snapshot = health()
                degraded = snapshot.recording_state is not OnlyRecordingState.HEALTHY
                if degraded != self._drain_degraded:
                    self._drain_degraded = degraded
                    if degraded:
                        with self._lock:
                            self._owned_preview = None
                    try:
                        diagnostic = asdict(snapshot)
                        diagnostic["last_recovery_error"] = only_market_data_diagnostic_error(
                            snapshot.last_recovery_error
                        )
                        logging.getLogger("onlyalpha.market_data.durable.stream").info(
                            "market_data_stream_health stream_id=%s state=%s health=%s",
                            self.stream_id,
                            "DEGRADED" if degraded else self._connection_state,
                            json.dumps(diagnostic, default=str, sort_keys=True),
                        )
                    except Exception:
                        # A diagnostic sink is not allowed to suppress the authoritative event.
                        pass
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
            self._owned_preview = None
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
        bar_semantic: OnlyBarSemantic,
        resume_after_sequence: int,
        resume_plan_fingerprint: str | None = None,
        read_session: OnlySourceReadSession | None = None,
    ) -> OnlyMarketDataStreamSession:
        if not self._slots.acquire(blocking=False):
            raise OnlyMarketDataProductError("MARKET_DATA_STREAM_CAPACITY_EXCEEDED")
        try:
            return self._open(
                reference,
                instrument_id=instrument_id,
                bar_semantic=bar_semantic,
                resume_after_sequence=resume_after_sequence,
                resume_plan_fingerprint=resume_plan_fingerprint,
                read_session=read_session,
            )
        except Exception:
            self._slots.release()
            raise

    def _open(
        self,
        reference: OnlyMarketDataSourceReferenceV1,
        *,
        instrument_id: str,
        bar_semantic: OnlyBarSemantic,
        resume_after_sequence: int,
        resume_plan_fingerprint: str | None,
        read_session: OnlySourceReadSession | None,
    ) -> OnlyMarketDataStreamSession:
        only_product_bar_semantic(bar_semantic)
        resolved = self._historical.resolve_read_runtime(
            reference, read_session=read_session, permission=OnlySourceReadPermission.REALTIME_PREVIEW
        )
        plan = self._historical._plan(resolved, instrument_id, bar_semantic)
        if resume_after_sequence > 0 and resume_plan_fingerprint != plan.fingerprint:
            raise OnlyMarketDataProductError("MARKET_DATA_RESUME_PLAN_MISMATCH")
        provider_semantic = bar_semantic if plan.mode is OnlyBarResolutionMode.PROVIDER_NATIVE else BASE_BAR_SEMANTIC
        provider_plan = self._historical._plan(resolved, instrument_id, provider_semantic)
        construction = OnlyBarConstructionIdentity.build(provider_plan, data_version=str(resolved.data_version))
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
        from onlyalpha.application.market_data_product import _bar_type

        aggregator = None
        calendar = None
        if plan.mode is OnlyBarResolutionMode.DERIVED:
            OnlyBarConstructionAlgorithmRegistry().require(plan.resolved_recipe)
            if not isinstance(resolved.factory, OnlyDataSourceTimeBarCalendar):
                raise OnlyMarketDataProductError("MARKET_DATA_TIME_BAR_CALENDAR_UNAVAILABLE")
            calendar = resolved.factory.time_bar_calendar(resolved.plugin_config)
            aggregator = OnlyTimeBarAggregator(
                _bar_type(instrument_key),
                OnlyBarType(instrument_key, bar_semantic),
                calendar,
                self._clock,
            )
            self._bootstrap(resolved, instrument_id, resume_after_sequence, calendar, aggregator, provider_plan)
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
                bar_construction=construction,
            ),
            max_records_per_segment=1,
            on_sealed=drain.submit,
            on_start=drain.start,
            health_view=drain.health,
        )

        def on_update(update: OnlyMarketDataInboundUpdate) -> None:
            if session_ref:
                session_ref[0].emit_closed(update)

        def on_preview(preview: OnlyRealtimeBarPreviewV1) -> None:
            if session_ref:
                session_ref[0].emit_preview(preview)

        def on_connection(snapshot: OnlyMarketDataConnectionSnapshot) -> None:
            if session_ref:
                session_ref[0].emit_state(_product_state(snapshot.state))

        request = OnlyDataSourceCreateRequest(
            resolved.source_id,
            resolved.plugin_config,
            "PRODUCT",
            OnlyDataSourceCapabilities(historical_bars=True, live_bars=True, live_reconnect=True),
            self._clock,
            OnlyEventBus(),
            {instrument_key: instrument},
            {instrument_key: _bar_type(instrument_key, provider_semantic)},
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
            aggregator=aggregator,
            instrument=instrument,
            calendar=calendar,
            native_bar_type=_bar_type(instrument_key, provider_semantic),
            source_reference=reference,
            source_selection=resolved.selection,
            bar_semantic=bar_semantic,
            read_session=read_session,
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
                    frozenset({_bar_type(instrument_key, provider_semantic)}),
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
                {
                    "stream_id": stream_id,
                    "source_id": str(resolved.source_id),
                    "instrument_id": instrument_id,
                    "resolution_mode": plan.mode.value,
                    "resolution_plan_fingerprint": plan.fingerprint,
                    "cursor_bar_stride_minutes": provider_semantic.stride_minutes,
                },
            )
        )
        with self._lock:
            self._sessions[stream_id] = session
        return session

    def read_chart_study_preview(
        self,
        stream_id: str,
        *,
        reference: OnlyMarketDataSourceReferenceV1,
        instrument_id: str,
        bar_semantic: OnlyBarSemantic,
        read_session: OnlySourceReadSession,
    ) -> OnlyChartStudyPreviewInput | None:
        read_session.require_reference(reference, OnlySourceReadPermission.REALTIME_PREVIEW)
        with self._lock:
            session = self._sessions.get(stream_id)
        if session is None:
            return None
        with session._lock:
            if (
                session._read_session != read_session
                or session._source_reference != reference
                or session.instrument_id != instrument_id
                or session._bar_semantic != bar_semantic
            ):
                raise ValueError("CHART_STUDY_PREVIEW_UNAVAILABLE")
            session._require_preview_access()
            preview = session._owned_preview
            if preview is None:
                return None
            result = object.__new__(OnlyChartStudyPreviewInput)
            object.__setattr__(result, "stream_id", stream_id)
            object.__setattr__(
                result,
                "revision_fingerprint",
                only_canonical_fingerprint(
                    {
                        "stream_id": stream_id,
                        "selection": session._source_selection,
                        "preview": _preview_payload(preview),
                        "ts_event_ns": preview.ts_event_ns,
                        "ts_receive_ns": preview.ts_receive_ns,
                    }
                ),
            )
            object.__setattr__(result, "_session", session)
            object.__setattr__(result, "_preview", preview)
            object.__setattr__(result, "_issuance", _PREVIEW_ISSUANCE)
            return result

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

    def _bootstrap(
        self,
        resolved: OnlyResolvedMarketDataRuntime,
        instrument_id: str,
        resume_after_sequence: int,
        calendar: OnlyTradingCalendar,
        aggregator: OnlyTimeBarAggregator,
        provider_plan: OnlyBarResolutionPlan,
    ) -> None:
        if resume_after_sequence < 0:
            raise OnlyMarketDataProductError("MARKET_DATA_RESUME_CURSOR_INVALID")
        bar_start = OnlyTimestamp.from_unix_nanos(resume_after_sequence * _MINUTE_NS).to_datetime()
        try:
            trading_day = calendar.trading_day_at(bar_start)
            session_start, _ = next(
                (start, end)
                for start, end in calendar.session_intervals_for_trading_day(trading_day)
                if start <= bar_start < end
            )
        except (ValueError, StopIteration) as exc:
            raise OnlyMarketDataProductError("MARKET_DATA_RESUME_CURSOR_INVALID") from exc
        duration = timedelta(minutes=aggregator.target_bar_type.semantic.window_minutes)
        window_start = session_start + ((bar_start - session_start) // duration) * duration
        start_ns = OnlyTimestamp.from_datetime(window_start).unix_nanos
        end_ns = (resume_after_sequence + 1) * _MINUTE_NS
        if start_ns == end_ns:
            return
        scope = self._historical._scope(resolved, instrument_id, start_ns, end_ns, provider_plan)
        try:
            verified = self._historical._ranges.read(
                OnlyMarketDataRangeFamily.from_scope(scope),
                (OnlyBarCoverageGap(start_ns, end_ns),),
            )
            if verified.coverage_status is not OnlyCoverageStatus.COMPLETE:
                raise OnlyMarketDataProductError("HISTORY_REFRESH_REQUIRED")
            for fact in verified.facts:
                update = OnlyMarketDataInboundUpdate.from_dict(fact.canonical_payload)
                if not isinstance(update.payload, OnlyBarUpdate):
                    raise OnlyMarketDataProductError("MARKET_DATA_DERIVED_SOURCE_INVALID")
                aggregator.process(update.payload.bar)
        except OnlyMarketDataProductError:
            raise
        except (OnlyMarketDataConflictError, OnlyMarketDataSealError) as exc:
            raise OnlyMarketDataProductError("HISTORY_REFRESH_REQUIRED") from exc
        except Exception as exc:
            raise OnlyMarketDataProductError("MARKET_DATA_DERIVED_BOOTSTRAP_UNAVAILABLE") from exc

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


def _spec_payload(semantic: OnlyBarSemantic) -> dict[str, object]:
    return semantic.to_dict()


def _bar_preview(
    bar: OnlyBar,
    preview: OnlyRealtimeBarPreviewV1 | None,
    update: OnlyMarketDataInboundUpdate | None = None,
) -> OnlyRealtimeBarPreviewV1:
    source_id = preview.source_id if preview is not None else update.source_id  # type: ignore[union-attr]
    return OnlyRealtimeBarPreviewV1(
        source_id,
        bar.instrument_id,
        bar.bar_type,
        OnlyTimestamp.from_datetime(bar.bar_start).unix_nanos,
        OnlyTimestamp.from_datetime(bar.bar_end).unix_nanos,
        str(bar.open.value),
        str(bar.high.value),
        str(bar.low.value),
        str(bar.close.value),
        str(bar.volume.value),
        OnlyTimestamp.from_datetime(bar.ts_event).unix_nanos,
        preview.ts_receive_ns if preview is not None else OnlyTimestamp.from_datetime(bar.ts_init).unix_nanos,
    )


def _preview_payload(preview: OnlyRealtimeBarPreviewV1) -> dict[str, object]:
    return {
        "source_id": str(preview.source_id),
        "instrument_id": str(preview.instrument_id),
        "bar_semantic": _spec_payload(preview.bar_type.semantic),
        "timing": None,
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
