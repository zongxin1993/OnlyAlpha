"""Non-publishing Chart Query over owning history and the retained installed SMA SPI."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import DecimalException
from threading import Lock

import pyarrow as pa  # type: ignore[import-untyped]

from onlyalpha.application.chart_study_numeric import OnlyChartStudySmaAdmission, OnlyChartStudySmaInvocation
from onlyalpha.application.market_data_product import (
    OnlyMarketDataBarWindowProjectionV1,
    OnlyMarketDataProductError,
    OnlyMarketDataProductService,
    OnlyMarketDataSourceReferenceV1,
)
from onlyalpha.application.source_read_access import OnlySourceReadPermission, OnlySourceReadSession
from onlyalpha.calculation.definition import OnlyCalculationDefinition
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.domain.market import OnlyBarSemantic
from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendExecutionV2


class OnlyChartStudyQueryError(RuntimeError):
    """A sanitized display Query failure, never a scientific outcome."""

    def __init__(self, code: str, status: int) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class OnlyChartStudyRequestV1:
    reference: OnlyMarketDataSourceReferenceV1
    instrument_id: str
    bar_semantic: OnlyBarSemantic
    before_ns: int
    target_bar_count: int
    period: int
    expected_history_projection_fingerprint: str
    expected_descriptor_fingerprint: str
    expected_implementation_fingerprint: str
    expected_capability_projection_fingerprint: str

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
            or type(self.period) is not int
            or not 1 <= self.period <= 10000
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


@dataclass(frozen=True, slots=True)
class OnlyChartStudyProjectionV1:
    window: OnlyMarketDataBarWindowProjectionV1
    admission: OnlyChartStudySmaAdmission
    definition: OnlyCalculationDefinition
    execution: OnlyResearchCalculationBackendExecutionV2 | None


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
        invocation: OnlyChartStudySmaInvocation,
    ) -> None:
        if type(market_data) is not OnlyMarketDataProductService or type(invocation) is not OnlyChartStudySmaInvocation:
            raise OnlyChartStudyQueryError("CHART_STUDY_CAPABILITY_UNAVAILABLE", 503)
        self._market_data = market_data
        self._invocation = invocation
        self._slot = Lock()

    def capabilities(self, session: OnlySourceReadSession) -> OnlyChartStudySmaAdmission:
        session.check_active()
        if not any(OnlySourceReadPermission.CLOSED_HISTORY in grant.permissions for grant in session.authority.grants):
            raise OnlyChartStudyQueryError("CHART_STUDY_FORBIDDEN", 403)
        try:
            admission = self._invocation.admission
        except ValueError as error:
            raise OnlyChartStudyQueryError("CHART_STUDY_CAPABILITY_UNAVAILABLE", 503) from error
        session.check_active()
        return admission

    def evaluate(self, request: OnlyChartStudyRequestV1, session: OnlySourceReadSession) -> OnlyChartStudyProjectionV1:
        session.require_reference(request.reference, OnlySourceReadPermission.CLOSED_HISTORY)
        if not self._slot.acquire(blocking=False):
            raise OnlyChartStudyQueryError("CHART_STUDY_CAPACITY_UNAVAILABLE", 503)
        try:
            admission = self.capabilities(session)
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
            parameters = {"period": request.period, "price_field": "CLOSE"}
            definition = registration.definition_resolver.resolve(parameters, {})
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
                raise OnlyChartStudyQueryError(error.code, status) from error
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
                return OnlyChartStudyProjectionV1(window, admission, definition, None)
            if window.history_projection_fingerprint != request.expected_history_projection_fingerprint:
                raise OnlyChartStudyQueryError("CHART_STUDY_DATA_CHANGED", 409)
            try:
                execution = self._invocation.invoke_closed_history(
                    parameters, handoff, capability_fingerprint=admission.fingerprint
                )
            except (ValueError, DecimalException, pa.ArrowException) as error:
                code = str(error)
                status = 503 if "UNAVAILABLE" in code or "CAPACITY" in code else 409 if "CHANGED" in code else 500
                raise OnlyChartStudyQueryError(
                    code if code.startswith("CHART_STUDY_") else "CHART_STUDY_OUTPUT_INVALID", status
                ) from error
            handoff.require_window()
            self.capabilities(session)
            return OnlyChartStudyProjectionV1(window, admission, definition, execution)
        finally:
            self._slot.release()
