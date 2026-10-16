"""Non-publishing Chart Query over owning history, stream previews and registered calculation SPI."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import DecimalException
from threading import Lock
from types import MappingProxyType

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.application.chart_study_numeric import (
    OnlyChartStudyAdmission,
    OnlyChartStudyInvocation,
    _require_chart_parameters,
)
from onlyalpha.application.market_data_product import (
    OnlyMarketDataBarWindowProjectionV1,
    OnlyMarketDataProductError,
    OnlyMarketDataProductService,
    OnlyMarketDataSourceReferenceV1,
)
from onlyalpha.application.market_data_stream import OnlyMarketDataStreamProductService
from onlyalpha.application.source_read_access import (
    OnlySourceReadAccessError,
    OnlySourceReadPermission,
    OnlySourceReadSession,
)
from onlyalpha.calculation.definition import OnlyCalculationDefinition
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.market import OnlyBarSemantic
from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendExecutionV2


class OnlyChartStudyQueryError(RuntimeError):
    """A sanitized display Query failure, never a scientific outcome."""

    def __init__(self, code: str, status: int, *, retry_after_seconds: int | None = None) -> None:
        self.code = code
        self.status = status
        self.retry_after_seconds = retry_after_seconds
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class OnlyChartStudyRequestV2:
    reference: OnlyMarketDataSourceReferenceV1
    instrument_id: str
    bar_semantic: OnlyBarSemantic
    before_ns: int
    target_bar_count: int
    type_id: str
    semantic_version: str
    parameters: Mapping[str, object]
    output_members: tuple[str, ...]
    expected_history_projection_fingerprint: str
    expected_descriptor_fingerprint: str
    expected_implementation_fingerprint: str
    expected_capability_projection_fingerprint: str
    include_unclosed_preview: bool = False
    preview_stream_id: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.bar_semantic) is not OnlyBarSemantic
            or not self.bar_semantic.is_aligned
            or type(self.before_ns) is not int
            or not 0 < self.before_ns <= 9_223_372_036_854_775_807
            or type(self.target_bar_count) is not int
            or not 1 <= self.target_bar_count <= 2000
            or self.before_ns % (self.bar_semantic.stride_minutes * 60_000_000_000) != 0
            or self.before_ns < self.target_bar_count * self.bar_semantic.stride_minutes * 60_000_000_000
            or type(self.type_id) is not str
            or not 1 <= len(self.type_id) <= 256
            or type(self.semantic_version) is not str
            or not 1 <= len(self.semantic_version) <= 256
            or not isinstance(self.parameters, Mapping)
            or len(self.parameters) > 16
            or any(type(value) is int and not 1 <= value <= 10000 for value in self.parameters.values())
            or type(self.output_members) is not tuple
            or not 1 <= len(self.output_members) <= 8
            or len(set(self.output_members)) != len(self.output_members)
            or any(type(name) is not str or not 1 <= len(name) <= 128 for name in self.output_members)
            or type(self.include_unclosed_preview) is not bool
            or self.include_unclosed_preview
            and (
                type(self.preview_stream_id) is not str or re.fullmatch(r"[0-9a-f]{32}", self.preview_stream_id) is None
            )
            or not self.include_unclosed_preview
            and self.preview_stream_id is not None
            or type(self.instrument_id) is not str
            or not 1 <= len(self.instrument_id) <= 256
            or type(self.reference) is not OnlyMarketDataSourceReferenceV1
            or self.reference.expected_type_id is None
            or any(
                type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
                for value in (
                    self.expected_history_projection_fingerprint,
                    self.expected_descriptor_fingerprint,
                    self.expected_implementation_fingerprint,
                    self.expected_capability_projection_fingerprint,
                )
            )
        ):
            raise OnlyChartStudyQueryError("CHART_STUDY_REQUEST_INVALID", 400)
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True, slots=True)
class OnlyChartStudyPreviewProjection:
    stream_id: str
    revision_fingerprint: str
    bar_start_ns: int
    bar_end_ns: int
    execution: OnlyResearchCalculationBackendExecutionV2


@dataclass(frozen=True, slots=True)
class OnlyChartStudyProjectionV2:
    window: OnlyMarketDataBarWindowProjectionV1
    admission: OnlyChartStudyAdmission
    definition: OnlyCalculationDefinition
    execution: OnlyResearchCalculationBackendExecutionV2 | None
    output_members: tuple[str, ...]
    preview: OnlyChartStudyPreviewProjection | None = None


class OnlyChartStudyProductQueryService:
    """Disposable bounded orchestration; admits no writer, executor, queue or cache.

    The outer slot covers owning IO as well as numeric work. The synchronous owner
    retains it until the actual call ends, irrespective of HTTP cancellation.
    Exact instrument membership and native semantic support are proved by the
    owning Source catalog and resolution planner for every request.
    """

    def __init__(
        self,
        market_data: OnlyMarketDataProductService,
        invocation: OnlyChartStudyInvocation,
        market_data_stream: OnlyMarketDataStreamProductService | None = None,
    ) -> None:
        if type(market_data) is not OnlyMarketDataProductService or type(invocation) is not OnlyChartStudyInvocation:
            raise OnlyChartStudyQueryError("CHART_STUDY_CAPABILITY_UNAVAILABLE", 503)
        if market_data_stream is not None and type(market_data_stream) is not OnlyMarketDataStreamProductService:
            raise TypeError("Chart preview requires the owning Market Data stream service")
        self._market_data_stream = market_data_stream
        self._market_data = market_data
        self._invocation = invocation
        self._slot = Lock()

    def capabilities(self, session: OnlySourceReadSession) -> tuple[OnlyChartStudyAdmission, ...]:
        session.check_active()
        if not any(OnlySourceReadPermission.CLOSED_HISTORY in grant.permissions for grant in session.authority.grants):
            raise OnlyChartStudyQueryError("CHART_STUDY_FORBIDDEN", 403)
        try:
            admission = self._invocation.admissions
        except ValueError as error:
            raise OnlyChartStudyQueryError("CHART_STUDY_CAPABILITY_UNAVAILABLE", 503) from error
        session.check_active()
        return admission

    def evaluate(self, request: OnlyChartStudyRequestV2, session: OnlySourceReadSession) -> OnlyChartStudyProjectionV2:
        session.require_reference(request.reference, OnlySourceReadPermission.CLOSED_HISTORY)
        if not self._slot.acquire(blocking=False):
            raise OnlyChartStudyQueryError("CHART_STUDY_CAPACITY_UNAVAILABLE", 503)
        try:
            admissions = self.capabilities(session)
            matches = [
                a
                for a in admissions
                if (a.registration.type_definition.type_id, a.registration.type_definition.semantic_version)
                == (request.type_id, request.semantic_version)
            ]
            if len(matches) != 1:
                raise OnlyChartStudyQueryError("CHART_STUDY_UNSUPPORTED", 400)
            admission = matches[0]
            if not set(request.output_members).issubset({s.output_name for s in admission.support.series}):
                raise OnlyChartStudyQueryError("CHART_STUDY_REQUEST_INVALID", 400)
            registration = admission.registration
            manifest = registration.implementation_manifest
            assert manifest is not None and registration.definition_resolver is not None
            # Completeness precedes equality: missing installation is not a change.
            if (
                request.expected_capability_projection_fingerprint != admission.fingerprint
                or request.expected_descriptor_fingerprint
                != only_canonical_fingerprint(registration.type_definition.descriptor())
                or request.expected_implementation_fingerprint != manifest.implementation_fingerprint
            ):
                raise OnlyChartStudyQueryError("CHART_STUDY_REGISTRATION_CHANGED", 409)
            parameters = request.parameters
            try:
                _require_chart_parameters(registration.type_definition, parameters)
                definition = registration.definition_resolver.resolve(parameters, {})
            except (ValueError, TypeError) as error:
                raise OnlyChartStudyQueryError("CHART_STUDY_REQUEST_INVALID", 400) from error
            try:
                window, handoff = self._market_data.read_chart_study_history(
                    request.reference,
                    instrument_id=request.instrument_id,
                    target_bar_count=request.target_bar_count,
                    before_ns=request.before_ns,
                    bar_semantic=request.bar_semantic,
                    read_session=session,
                )
            except OnlyMarketDataProductError as error:
                status = (
                    404
                    if error.code.endswith("NOT_FOUND")
                    else 500
                    if error.code.endswith("CORRUPT") or error.code == "MARKET_DATA_REVISION_EVIDENCE_INVALID"
                    else 409
                    if error.code.endswith("CONFLICT")
                    else 400
                    if error.code.endswith(("INVALID", "UNSUPPORTED"))
                    else 503
                )
                raise OnlyChartStudyQueryError(
                    error.code, status, retry_after_seconds=error.retry_after_seconds
                ) from error
            session.require_selection(window.source_selection, OnlySourceReadPermission.CLOSED_HISTORY)
            if (
                window.instrument_id != request.instrument_id
                or window.bar_semantic != request.bar_semantic
                or window.anchor_kind != "BEFORE_TIME"
                or window.requested_before_ns != request.before_ns
                or window.resolved_end_ns != request.before_ns
                or window.requested_bar_count != request.target_bar_count
                or window.resolved_start_ns
                != request.before_ns - request.target_bar_count * request.bar_semantic.stride_minutes * 60_000_000_000
                or window.resolution_mode != "PROVIDER_NATIVE"
                or window.resolution_plan_fingerprint is None
                or window.calendar_fingerprint is None
                or not window.closed_only
                or window.derived_projection_fingerprint is not None
            ):
                raise OnlyChartStudyQueryError("CHART_STUDY_SOURCE_UNAVAILABLE", 503)
            if handoff is None:
                if window.coverage.status != "INCOMPLETE" or window.bars or window.history_projection_fingerprint:
                    raise OnlyChartStudyQueryError("CHART_STUDY_SOURCE_UNAVAILABLE", 503)
                self.capabilities(session)
                return OnlyChartStudyProjectionV2(window, admission, definition, None, request.output_members)
            if window.history_projection_fingerprint != request.expected_history_projection_fingerprint:
                raise OnlyChartStudyQueryError("CHART_STUDY_DATA_CHANGED", 409)
            preview_input = None
            if request.include_unclosed_preview:
                session.require_reference(request.reference, OnlySourceReadPermission.REALTIME_PREVIEW)
                if self._market_data_stream is not None and request.preview_stream_id is not None:
                    try:
                        candidate = self._market_data_stream.read_chart_study_preview(
                            request.preview_stream_id,
                            reference=request.reference,
                            instrument_id=request.instrument_id,
                            bar_semantic=request.bar_semantic,
                            read_session=session,
                        )
                        if candidate is not None and candidate.require_preview().bar_start_ns == window.resolved_end_ns:
                            preview_input = candidate
                    except ValueError as error:
                        if str(error) != "CHART_STUDY_PREVIEW_UNAVAILABLE":
                            raise
            try:
                execution, live_execution = self._invocation.invoke_owned_inputs(
                    parameters,
                    handoff,
                    type_id=request.type_id,
                    semantic_version=request.semantic_version,
                    capability_fingerprint=admission.fingerprint,
                    preview=preview_input,
                )
            except OnlySourceReadAccessError:
                raise
            except (ValueError, DecimalException, pa.ArrowException) as error:
                code = str(error)
                status = 503 if "UNAVAILABLE" in code or "CAPACITY" in code else 409 if "CHANGED" in code else 500
                raise OnlyChartStudyQueryError(
                    code if code.startswith("CHART_STUDY_") else "CHART_STUDY_OUTPUT_INVALID", status
                ) from error
            handoff.require_window()
            self.capabilities(session)
            live_projection = None
            if preview_input is not None and live_execution is not None:
                try:
                    live = preview_input.require_preview()
                    live_projection = OnlyChartStudyPreviewProjection(
                        preview_input.stream_id,
                        preview_input.revision_fingerprint,
                        live.bar_start_ns,
                        live.bar_end_ns,
                        live_execution,
                    )
                except ValueError as error:
                    if str(error) != "CHART_STUDY_PREVIEW_UNAVAILABLE":
                        raise
            return OnlyChartStudyProjectionV2(
                window, admission, definition, execution, request.output_members, live_projection
            )
        finally:
            self._slot.release()
