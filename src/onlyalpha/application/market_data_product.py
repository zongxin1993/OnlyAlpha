"""Provider-neutral Market Data Product Query/Command boundary.

The boundary resolves one exact Integration Revision, composes the existing durable
market-data authority over it and projects canonical Coverage/Revision facts. It
defines no market-data semantics of its own: Binance-specific meaning stays in the
plugin, and historical reads are served from the database.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, time
from logging import Logger
from pathlib import Path
from time import perf_counter_ns
from types import MappingProxyType
from typing import Literal, Protocol, cast

from onlyalpha.application.integration_configuration import OnlyIntegration, OnlyIntegrationLifecycleState
from onlyalpha.application.integration_runtime import (
    OnlyIntegrationRuntimeError,
    OnlyIntegrationRuntimeResolver,
)
from onlyalpha.cache.historical import OnlyHistoricalCacheService, OnlyParquetHistoricalCacheStore
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.config.models import (
    OnlyDataSourceCoverageConfig,
    OnlyDataSourceRuntimeConfig,
    OnlyJsonMapping,
    OnlyRuntimeConfigurationMode,
)
from onlyalpha.core.clock import OnlyClock, only_system_utc_now
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataRange,
    OnlyMarketDataInboundUpdate,
)
from onlyalpha.domain.calendar import OnlyTradingCalendar
from onlyalpha.domain.enums import OnlyAdjustmentType, OnlyPriceType
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBar, OnlyBarSemantic, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.market_data.aggregation.base import OnlyBarAggregationError
from onlyalpha.market_data.aggregation.time_bar import OnlyTimeBarAggregator
from onlyalpha.market_data.durable.backfill import (
    OnlyMarketDataBackfillCoordinator,
    only_plan_contiguous_bar_gaps,
)
from onlyalpha.market_data.durable.ingress import OnlyMarketDataIngress
from onlyalpha.market_data.durable.models import (
    OnlyAcquisitionOutcome,
    OnlyBarCoverageGap,
    OnlyCanonicalMarketFactRecord,
    OnlyCoverageManifest,
    OnlyCoverageStatus,
    OnlyMarketDataAcquisitionAttempt,
    OnlyMarketDataAcquisitionIntent,
    OnlyMarketDataProvenance,
    OnlyMarketDataRangeFamily,
    OnlyMarketDataRevision,
    OnlyMarketDataScope,
    OnlyMarketDataSeal,
)
from onlyalpha.market_data.durable.ports import OnlyMarketDataCatalog, OnlyMarketFactStore
from onlyalpha.market_data.durable.range_query import (
    OnlyBarWindowAnchorKind,
    OnlyMarketDataRevisionEvidence,
    OnlyVerifiedMarketDataRangeQuery,
    only_history_projection_fingerprint,
    only_plan_acquisition_ranges,
    only_plan_utc_24x7_bar_window,
)
from onlyalpha.market_data.durable.recorder import OnlyDurableMarketDataRecorder
from onlyalpha.market_data.durable.recovery import OnlyMarketDataRecoveryCoordinator
from onlyalpha.market_data.durable.revision import (
    OnlyHistoricalMarketDataQueryService,
    OnlyMarketDataConflictError,
    OnlyMarketDataSealError,
    OnlyRevisionCommitService,
    only_build_coverage,
)
from onlyalpha.market_data.durable.wal import OnlyMarketDataWal
from onlyalpha.market_data.resolution import (
    OnlyBarConstructionAlgorithmRegistry,
    OnlyBarConstructionIdentity,
    OnlyBarResolutionMode,
    OnlyBarResolutionPlan,
    only_plan_bar_resolution,
)
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities
from onlyalpha.plugin.data_source import (
    OnlyDataSource,
    OnlyDataSourceBarCapabilities,
    OnlyDataSourceCreateRequest,
    OnlyDataSourceInstrumentCatalog,
    OnlyDataSourceInstrumentCatalogRequestV1,
    OnlyDataSourceTimeBarCalendar,
)
from onlyalpha.plugin.integration import OnlyIntegrationTypeDescriptorV1
from onlyalpha.runtime.data_source_integration import (
    only_admit_data_source_runtime_configuration,
    only_resolve_data_source_runtime_configuration,
)

SCHEMA_VERSION = 1
DEFAULT_ACQUISITION_SECONDS = 86_400
MAX_ACQUISITION_SECONDS = 7 * 86_400
MINUTE_NS = 60_000_000_000
BASE_BAR_SEMANTIC = OnlyBarSemantic.fixed_duration(1)
MAX_FIXED_DURATION_WINDOW_MINUTES = 240
DEFAULT_TARGET_BAR_COUNT = 1_440
MAX_TARGET_BAR_COUNT = 2_000
_WAL_CAPACITY_BYTES = 256 * 1024 * 1024

# A configured Integration that cannot be resolved for this Product is simply not
# eligible; anything else is a real availability or corruption failure.
_INELIGIBLE_SOURCE_CODES = frozenset(
    {
        "MARKET_DATA_INSTRUMENT_CATALOG_UNAVAILABLE",
        "MARKET_DATA_SOURCE_SELECTION_MISMATCH",
        "MARKET_DATA_SOURCE_SELECTION_UNRESOLVED",
    }
)


class OnlyMarketDataProductError(RuntimeError):
    def __init__(self, code: str, detail: str | None = None, *, phase: Literal["QUERY", "COMMAND"] = "QUERY") -> None:
        self.code = code
        self.detail = detail or code
        self.phase = phase
        super().__init__(f"{code}: {self.detail}")


def only_product_bar_semantic(semantic: OnlyBarSemantic) -> OnlyBarSemantic:
    if (
        not isinstance(semantic, OnlyBarSemantic)
        or not semantic.is_fixed_duration
        or semantic.window_minutes < 1
        or semantic.price_type is not OnlyPriceType.LAST
        or semantic.adjustment_policy is not OnlyAdjustmentType.RAW
    ):
        raise OnlyMarketDataProductError("MARKET_DATA_BAR_SEMANTIC_UNSUPPORTED")
    return semantic


class OnlyIntegrationListing(Protocol):
    """Formal Product read of configured Integrations, filtered by exact criteria."""

    def list_integrations(
        self, *, type_id: str | None = None, lifecycle_state: OnlyIntegrationLifecycleState | None = None
    ) -> tuple[OnlyIntegration, ...]: ...


@dataclass(frozen=True, slots=True)
class OnlyMarketDataSourceReferenceV1:
    """Client reference to one exact published Integration Revision.

    The browser selects a configured source; the canonical Market Source identity is
    resolved server-side from the exact Revision plus the plugin market identity. The
    client owns no canonical source authority.
    """

    integration_id: str
    integration_revision_fingerprint: str
    expected_type_id: str | None = None

    def __post_init__(self) -> None:
        if not self.integration_id.strip() or not self.integration_revision_fingerprint.strip():
            raise OnlyMarketDataProductError("MARKET_DATA_SOURCE_REFERENCE_INVALID")
        if self.expected_type_id is not None and not self.expected_type_id.strip():
            raise OnlyMarketDataProductError("MARKET_DATA_SOURCE_REFERENCE_INVALID")
        fingerprint = self.integration_revision_fingerprint
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise OnlyMarketDataProductError("MARKET_DATA_SOURCE_REFERENCE_INVALID")

    def binding_reference(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "integration_id": self.integration_id,
                "revision_fingerprint": self.integration_revision_fingerprint,
            }
        )


@dataclass(frozen=True, slots=True)
class OnlyMarketDataSourceSelectionV1:
    """Server-derived canonical Market Source identity for one exact Revision."""

    integration_id: str
    integration_revision_fingerprint: str
    type_id: str
    source_id: str
    environment: str


@dataclass(frozen=True, slots=True)
class OnlyMarketDataTimeBarCapabilityV1:
    provider_base_semantic: OnlyBarSemantic = field(default_factory=lambda: OnlyBarSemantic.fixed_duration(1))
    derived_algorithm: str | None = "TIME_BAR@1"
    minimum_window_minutes: int = 1
    maximum_window_minutes: int = MAX_FIXED_DURATION_WINDOW_MINUTES


@dataclass(frozen=True, slots=True)
class OnlyMarketDataSourceProjectionV1:
    """A configured Integration that is eligible for this Market Data Product."""

    integration_id: str
    integration_revision_fingerprint: str
    display_name: str
    type_id: str
    source_id: str
    environment: str
    time_bar_capability: OnlyMarketDataTimeBarCapabilityV1


@dataclass(frozen=True, slots=True)
class OnlyMarketDataInstrumentProjectionV1:
    instrument_id: str
    display_symbol: str
    venue: str
    market: str
    asset_class: str
    instrument_type: str
    status: str
    market_data_capabilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OnlyMarketDataInstrumentListProjectionV1:
    source_selection: OnlyMarketDataSourceSelectionV1
    instruments: tuple[OnlyMarketDataInstrumentProjectionV1, ...]


@dataclass(frozen=True, slots=True)
class OnlyMarketDataBarV1:
    bar_start_ns: int
    bar_end_ns: int
    open: str
    high: str
    low: str
    close: str
    volume: str
    closed: bool


@dataclass(frozen=True, slots=True)
class OnlyMarketDataCoverageGapV1:
    start_ns: int
    end_ns: int


@dataclass(frozen=True, slots=True)
class OnlyMarketDataCoverageProjectionV1:
    status: str
    manifest_id: str | None
    manifest_fingerprint: str | None
    expected_bar_count: int
    actual_bar_count: int
    issues: tuple[str, ...]
    gaps: tuple[OnlyMarketDataCoverageGapV1, ...]
    planned_acquisition_ranges: tuple[OnlyMarketDataCoverageGapV1, ...]

    @property
    def complete(self) -> bool:
        return self.status == OnlyCoverageStatus.COMPLETE.value


@dataclass(frozen=True, slots=True)
class OnlyMarketDataBarWindowProjectionV1:
    schema_version: int
    source_selection: OnlyMarketDataSourceSelectionV1
    instrument_id: str
    display_symbol: str
    venue: str
    market: str
    bar_semantic: OnlyBarSemantic
    closed_only: bool
    anchor_kind: str
    requested_before_ns: int | None
    requested_bar_count: int
    resolved_start_ns: int
    resolved_end_ns: int
    coverage: OnlyMarketDataCoverageProjectionV1
    bars: tuple[OnlyMarketDataBarV1, ...]
    revision_evidence: tuple[OnlyMarketDataRevisionEvidence, ...]
    history_projection_fingerprint: str | None
    derived_projection_fingerprint: str | None
    aggregation_semantics_version: str | None = None
    calendar_fingerprint: str | None = None
    resolution_mode: str | None = None
    resolution_plan_fingerprint: str | None = None
    resume_after_sequence: str | None = None
    resume_plan_fingerprint: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyMarketDataAcquisitionProjectionV1:
    schema_version: int
    acquisition_id: str
    status: str
    source_id: str
    integration_binding_fingerprint: str | None
    instrument_id: str
    bar_semantic: OnlyBarSemantic
    start_ns: int
    end_ns: int
    provenance: str
    coverage: OnlyMarketDataCoverageProjectionV1
    revision_id: str | None
    revision_fingerprint: str | None
    seal_id: str | None
    failure_detail: str | None


@dataclass(frozen=True, slots=True)
class OnlyResolvedMarketDataRuntime:
    selection: OnlyMarketDataSourceSelectionV1
    binding_fingerprint: str
    venue: str
    market: str
    environment: str
    source_id: OnlyMarketDataSourceId
    data_version: OnlyDataVersion
    factory: object
    plugin_config: object
    catalog: OnlyDataSourceInstrumentCatalog


@dataclass(frozen=True, slots=True)
class _OnlyExactSealedHistory:
    revision: OnlyMarketDataRevision
    manifest: OnlyCoverageManifest
    seal: OnlyMarketDataSeal
    facts: tuple[OnlyCanonicalMarketFactRecord, ...]


class _OnlyAcquisitionSession:
    """One bounded product acquisition over the durable market-data authority."""

    def __init__(
        self,
        source: OnlyDataSource,
        recorder: OnlyDurableMarketDataRecorder,
        recovery: OnlyMarketDataRecoveryCoordinator,
        coordinator: OnlyMarketDataBackfillCoordinator,
        logger: Logger,
    ) -> None:
        self.source = source
        self._recorder = recorder
        self._recovery = recovery
        self._logger = logger
        self.coordinator = coordinator
        self._closed = False

    def close(self) -> None:
        """Seal the WAL tail, drain it once and stop the DataSource deterministically."""

        if self._closed:
            return
        self._closed = True
        self._recorder.close()
        self._recovery.recover_all()
        try:
            self.source.stop()
        except Exception as exc:  # pragma: no cover - stop must not mask the acquisition outcome
            self._logger.warning("market-data acquisition stop failed: %s", exc)


class OnlyMarketDataProductService:
    """Composes exact Integration runtime, DataSource and durable market-data authority."""

    def __init__(
        self,
        *,
        resolver: OnlyIntegrationRuntimeResolver,
        integrations: OnlyIntegrationListing,
        data_sources: OnlyDataSourceFactoryRegistry,
        catalog: OnlyMarketDataCatalog,
        fact_store: OnlyMarketFactStore,
        wal_root: Path,
        clock: OnlyClock,
        logger: Logger,
        batch_size: int = 1024,
        now: Callable[[], datetime] = only_system_utc_now,
    ) -> None:
        self._resolver = resolver
        self._integrations = integrations
        self._data_sources = data_sources
        self._catalog = catalog
        self._facts = fact_store
        self._wal_root = wal_root
        self._clock = clock
        self._logger = logger
        self._batch_size = batch_size
        self._now = now
        self._ranges = OnlyVerifiedMarketDataRangeQuery(catalog, fact_store)

    # --- Product Query -----------------------------------------------------------------

    def list_sources(self) -> tuple[OnlyMarketDataSourceProjectionV1, ...]:
        """Configured Integrations that this Market Data Product can actually serve.

        Eligibility is a Product judgement, not a Web filter: the candidate must be an
        ACTIVE Integration with a published Revision that resolves through the exact
        DataSource runtime binding with the capabilities this Product requires, and it
        must provide the Market Source identity and Instrument Catalog the Product reads.
        """

        try:
            candidates = self._integrations.list_integrations(
                type_id=None, lifecycle_state=OnlyIntegrationLifecycleState.ACTIVE
            )
        except Exception as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_SOURCE_CATALOG_UNAVAILABLE", "Integration catalog is unavailable"
            ) from exc
        eligible: list[OnlyMarketDataSourceProjectionV1] = []
        for candidate in candidates:
            fingerprint = candidate.current_revision_fingerprint
            if fingerprint is None:
                continue
            reference = OnlyMarketDataSourceReferenceV1(candidate.integration_id.value, fingerprint, candidate.type_id)
            try:
                resolved = self.resolve_runtime(reference)
            except OnlyMarketDataProductError as exc:
                if exc.code in _INELIGIBLE_SOURCE_CODES:
                    continue
                raise
            eligible.append(
                OnlyMarketDataSourceProjectionV1(
                    reference.integration_id,
                    reference.integration_revision_fingerprint,
                    candidate.display_name,
                    resolved.selection.type_id,
                    resolved.selection.source_id,
                    resolved.environment,
                    OnlyMarketDataTimeBarCapabilityV1(
                        derived_algorithm=(
                            "TIME_BAR@1" if isinstance(resolved.factory, OnlyDataSourceTimeBarCalendar) else None
                        )
                    ),
                )
            )
        return tuple(eligible)

    def list_instruments(
        self,
        reference: OnlyMarketDataSourceReferenceV1,
        *,
        instrument_ids: tuple[str, ...] = (),
        query: str = "",
        limit: int = 25,
    ) -> OnlyMarketDataInstrumentListProjectionV1:
        resolved = self.resolve_runtime(reference)
        request = OnlyDataSourceInstrumentCatalogRequestV1(
            resolved.plugin_config,
            instrument_ids=tuple(sorted(set(instrument_ids))),
            query=query,
            limit=limit,
        )
        try:
            projected = resolved.catalog.list_instruments(request)
        except Exception as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_REFERENCE_UNAVAILABLE", "provider reference lookup failed"
            ) from exc
        found = {str(item.instrument.instrument_id) for item in projected}
        if request.instrument_ids and found != set(request.instrument_ids):
            raise OnlyMarketDataProductError(
                "MARKET_DATA_INSTRUMENT_NOT_FOUND", "requested instrument is not published by this source"
            )
        return OnlyMarketDataInstrumentListProjectionV1(
            resolved.selection,
            tuple(
                OnlyMarketDataInstrumentProjectionV1(
                    str(item.instrument.instrument_id),
                    item.display_symbol,
                    item.venue,
                    item.market,
                    item.instrument.asset_class.value,
                    item.instrument.instrument_type.value,
                    item.instrument.status.value,
                    item.market_data_capabilities,
                )
                for item in projected
            ),
        )

    def query_bars(
        self,
        reference: OnlyMarketDataSourceReferenceV1,
        *,
        instrument_id: str,
        anchor_kind: OnlyBarWindowAnchorKind,
        target_bar_count: int,
        before_ns: int | None = None,
        bar_semantic: OnlyBarSemantic = BASE_BAR_SEMANTIC,
    ) -> OnlyMarketDataBarWindowProjectionV1:
        """DB-first verified range read; a Query never acquires or mutates state."""

        query_started = perf_counter_ns()
        resolved = self.resolve_runtime(reference)
        semantic = only_product_bar_semantic(bar_semantic)
        if target_bar_count < 1 or target_bar_count > MAX_TARGET_BAR_COUNT:
            raise OnlyMarketDataProductError("MARKET_DATA_WINDOW_REQUEST_INVALID")
        plan = self._plan(resolved, instrument_id, semantic)
        acquisition_plan = (
            plan
            if plan.mode is OnlyBarResolutionMode.PROVIDER_NATIVE
            else self._plan(resolved, instrument_id, BASE_BAR_SEMANTIC)
        )
        try:
            window = only_plan_utc_24x7_bar_window(
                semantic,
                anchor_kind=anchor_kind,
                before_ns=before_ns,
                target_bar_count=target_bar_count,
                latest_closed_ns=self._closed_minute_ns(),
            )
        except (TypeError, ValueError) as exc:
            raise OnlyMarketDataProductError("MARKET_DATA_WINDOW_REQUEST_INVALID", str(exc)) from exc
        scope = self._scope(resolved, instrument_id, window.resolved_start_ns, window.resolved_end_ns, acquisition_plan)
        family = OnlyMarketDataRangeFamily.from_scope(scope)
        try:
            verified = self._ranges.read(family, window.target_intervals)
            bars: tuple[OnlyMarketDataBarV1, ...] = ()
            calendar_fingerprint: str | None = None
            resume_after_sequence: str | None = None
            history_fingerprint: str | None = None
            derived_fingerprint: str | None = None
            if verified.coverage_status is OnlyCoverageStatus.COMPLETE:
                if not verified.facts:
                    raise OnlyMarketDataProductError("MARKET_DATA_RANGE_CURSOR_UNPROVABLE")
                try:
                    latest = max(verified.facts, key=lambda item: (item.ts_event_ns, item.canonical_fact_id))
                    sequence = latest.canonical_payload.get("source_sequence")
                    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
                        raise ValueError("provider sequence is absent")
                    resume_after_sequence = str(sequence)
                except Exception as exc:
                    raise OnlyMarketDataProductError("MARKET_DATA_RANGE_CURSOR_UNPROVABLE") from exc
                history_fingerprint = only_history_projection_fingerprint(
                    {
                        "source_selection": resolved.selection,
                        "range_family": family,
                        "anchor_kind": anchor_kind.value,
                        "requested_before_ns": before_ns,
                        "requested_bar_count": target_bar_count,
                        "resolved_start_ns": window.resolved_start_ns,
                        "resolved_end_ns": window.resolved_end_ns,
                        "bar_semantic": semantic,
                        "resolution_plan_fingerprint": plan.fingerprint,
                        "revision_evidence": verified.evidence,
                    }
                )
                if plan.mode is OnlyBarResolutionMode.PROVIDER_NATIVE:
                    bars = self._crop_bars(self._bars(verified.facts), window.target_intervals)
                else:
                    bars, calendar_fingerprint = self._derived_bars(resolved, verified.facts, semantic)
                    bars = self._crop_bars(bars, window.target_intervals)
                    if calendar_fingerprint != plan.alignment_id:
                        raise OnlyMarketDataProductError("MARKET_DATA_BAR_ALIGNMENT_CHANGED")
                    derived_fingerprint = only_history_projection_fingerprint(
                        {
                            "history_projection_fingerprint": history_fingerprint,
                            "target_semantic": semantic,
                            "resolution_plan_fingerprint": plan.fingerprint,
                            "resolved_start_ns": window.resolved_start_ns,
                            "resolved_end_ns": window.resolved_end_ns,
                        }
                    )
                if len(bars) != target_bar_count:
                    raise OnlyMarketDataProductError("MARKET_DATA_REVISION_EVIDENCE_INVALID")
            planned = only_plan_acquisition_ranges(
                verified.gaps,
                window.target_intervals,
                maximum_duration_ns=MAX_ACQUISITION_SECONDS * 1_000_000_000,
                provider_grid_step_ns=(
                    acquisition_plan.provider_semantic.stride_minutes * MINUTE_NS
                    if plan.mode is OnlyBarResolutionMode.DERIVED and acquisition_plan.provider_semantic is not None
                    else None
                ),
            )
            coverage = OnlyMarketDataCoverageProjectionV1(
                verified.coverage_status.value,
                None,
                None,
                target_bar_count,
                verified.complete_interval_count,
                verified.issues,
                tuple(OnlyMarketDataCoverageGapV1(item.start_ns, item.end_ns) for item in verified.gaps),
                tuple(OnlyMarketDataCoverageGapV1(item.start_ns, item.end_ns) for item in planned),
            )
        except OnlyMarketDataConflictError as exc:
            raise OnlyMarketDataProductError("MARKET_DATA_RANGE_COMPOSITION_CONFLICT", str(exc)) from exc
        except OnlyMarketDataSealError as exc:
            code = str(exc)
            if code not in {
                "MARKET_DATA_REVISION_EVIDENCE_INVALID",
                "MARKET_DATA_CATALOG_UNAVAILABLE",
            }:
                code = "MARKET_DATA_REVISION_EVIDENCE_INVALID"
            raise OnlyMarketDataProductError(code, str(exc)) from exc
        except OnlyMarketDataProductError:
            raise
        except Exception as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_FACT_STORE_UNAVAILABLE", "canonical market-data store is unavailable"
            ) from exc
        projection = OnlyMarketDataBarWindowProjectionV1(
            SCHEMA_VERSION,
            resolved.selection,
            instrument_id,
            _display_symbol(instrument_id, resolved.venue),
            resolved.venue,
            resolved.market,
            semantic,
            True,
            anchor_kind.value,
            before_ns,
            target_bar_count,
            window.resolved_start_ns,
            window.resolved_end_ns,
            coverage,
            bars,
            verified.evidence,
            history_fingerprint,
            derived_fingerprint,
            plan.aggregation_semantics_version,
            plan.calendar_fingerprint if plan.mode is OnlyBarResolutionMode.PROVIDER_NATIVE else calendar_fingerprint,
            plan.mode.value,
            plan.fingerprint,
            resume_after_sequence if coverage.complete else None,
            plan.fingerprint if coverage.complete else None,
        )
        self._logger.info("market_data_final_query final_query_ms=%d", (perf_counter_ns() - query_started) // 1_000_000)
        return projection

    # --- Product Command ---------------------------------------------------------------

    def acquire_bars(
        self,
        reference: OnlyMarketDataSourceReferenceV1,
        *,
        instrument_id: str,
        start_ns: int,
        end_ns: int,
        bar_semantic: OnlyBarSemantic = BASE_BAR_SEMANTIC,
    ) -> OnlyMarketDataAcquisitionProjectionV1:
        try:
            return self._acquire_bars(
                reference,
                instrument_id=instrument_id,
                start_ns=start_ns,
                end_ns=end_ns,
                bar_semantic=bar_semantic,
            )
        except OnlyMarketDataProductError as exc:
            raise OnlyMarketDataProductError(exc.code, exc.detail, phase="COMMAND") from exc

    def _acquire_bars(
        self,
        reference: OnlyMarketDataSourceReferenceV1,
        *,
        instrument_id: str,
        start_ns: int,
        end_ns: int,
        bar_semantic: OnlyBarSemantic = BASE_BAR_SEMANTIC,
    ) -> OnlyMarketDataAcquisitionProjectionV1:
        """Validate, admit the execution intent durably, then execute.

        No provider session, WAL or reference call happens before the exact intent is
        durable: a FAILED Product response must never describe a state the database
        cannot reproduce after restart.
        """

        resolved = self.resolve_runtime(reference)
        semantic = only_product_bar_semantic(bar_semantic)
        plan = self._plan(resolved, instrument_id, semantic)
        acquisition_plan = (
            plan
            if plan.mode is OnlyBarResolutionMode.PROVIDER_NATIVE
            else self._plan(resolved, instrument_id, BASE_BAR_SEMANTIC)
        )
        if plan.mode is OnlyBarResolutionMode.DERIVED:
            provider_semantic = acquisition_plan.provider_semantic
            if provider_semantic is None:
                raise OnlyMarketDataProductError("MARKET_DATA_DERIVED_RANGE_UNALIGNED")
            step_ns = provider_semantic.stride_minutes * MINUTE_NS
            if start_ns % step_ns or end_ns % step_ns:
                raise OnlyMarketDataProductError("MARKET_DATA_DERIVED_RANGE_UNALIGNED")
        scope = self._scope(
            resolved,
            instrument_id,
            start_ns,
            end_ns,
            acquisition_plan,
        )
        self._assert_acquisition_window(start_ns, end_ns)
        intent = OnlyMarketDataAcquisitionIntent.build(
            str(resolved.source_id),
            scope,
            provenance=OnlyMarketDataProvenance.REST_BACKFILL,
            admitted_at=self._now(),
            integration_binding_fingerprint=resolved.binding_fingerprint,
        )
        admitted = self._admit(intent)
        sealed = self._sealed_for_scope(scope)
        if sealed is not None:
            return self._projection(
                resolved,
                admitted,
                status="COMPLETE",
                sealed=sealed,
                failure_detail=None,
            )
        try:
            lease = self._catalog.try_acquire_acquisition_execution(admitted.acquisition_id)
        except Exception as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_CATALOG_UNAVAILABLE", "acquisition execution ownership is unavailable"
            ) from exc
        if not lease.acquired:
            return self._projection(resolved, admitted, status="RUNNING", sealed=None, failure_detail=None)
        try:
            sealed = self._sealed_for_scope(scope)
            if sealed is not None:
                return self._projection(
                    resolved,
                    admitted,
                    status="COMPLETE",
                    sealed=sealed,
                    failure_detail=None,
                )
            attempt = self._start_attempt(admitted.acquisition_id, started_at=self._now())
            sealed, failure = self._execute_acquisition(resolved, admitted)
            if failure is None and sealed is not None:
                # Coverage + Revision + Seal are canonical success even if optional
                # operational attempt evidence cannot be completed.
                try:
                    self._record_attempt(
                        attempt,
                        OnlyAcquisitionOutcome.COMPLETE,
                        detail="MARKET_DATA_ACQUISITION_COMPLETE",
                        revision_id=sealed.revision.revision_id,
                    )
                except Exception as exc:
                    self._logger.warning("market-data acquisition attempt evidence failed: %s", exc)
                return self._projection(resolved, admitted, status="COMPLETE", sealed=sealed, failure_detail=None)
            detail = failure or "MARKET_DATA_ACQUISITION_INCOMPLETE"
            self._record_terminal_failure(attempt, detail=detail)
            return self._projection(resolved, admitted, status="FAILED", sealed=None, failure_detail=detail)
        finally:
            lease.close()

    def acquisition_status(
        self, reference: OnlyMarketDataSourceReferenceV1, acquisition_id: str
    ) -> OnlyMarketDataAcquisitionProjectionV1:
        resolved = self.resolve_runtime(reference)
        try:
            intent = self._catalog.load_acquisition_intent(acquisition_id)
            attempt = None if intent is None else self._catalog.latest_acquisition_attempt(acquisition_id)
        except Exception as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_CATALOG_UNAVAILABLE", "acquisition catalog is unavailable"
            ) from exc
        if intent is None:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_ACQUISITION_NOT_FOUND", "acquisition is not admitted by this deployment"
            )
        if intent.integration_binding_fingerprint != resolved.binding_fingerprint:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_ACQUISITION_PROVENANCE_CONFLICT",
                "acquisition was admitted under a different Integration runtime binding",
            )
        sealed = self._sealed_for_scope(intent.requested_scope)
        if sealed is not None:
            return self._projection(resolved, intent, status="COMPLETE", sealed=sealed, failure_detail=None)
        try:
            active = self._catalog.acquisition_execution_active(acquisition_id)
        except Exception as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_CATALOG_UNAVAILABLE", "acquisition execution ownership is unavailable"
            ) from exc
        if active:
            return self._projection(resolved, intent, status="RUNNING", sealed=None, failure_detail=None)
        if attempt is not None and attempt.outcome is OnlyAcquisitionOutcome.FAILED:
            return self._projection(resolved, intent, status="FAILED", sealed=None, failure_detail=attempt.detail)
        return self._projection(resolved, intent, status="PENDING", sealed=None, failure_detail=None)

    # --- Internals ---------------------------------------------------------------------

    def resolve_runtime(self, reference: OnlyMarketDataSourceReferenceV1) -> OnlyResolvedMarketDataRuntime:
        if not isinstance(reference, OnlyMarketDataSourceReferenceV1):
            raise OnlyMarketDataProductError("MARKET_DATA_SOURCE_REFERENCE_INVALID")
        runtime_config = OnlyDataSourceRuntimeConfig(
            source_id=OnlyMarketDataSourceId("unresolved"),
            plugin_id="",
            enabled=True,
            data_version=OnlyDataVersion("unresolved"),
            coverage=OnlyDataSourceCoverageConfig(universe_ids=("unresolved",)),
            batch_size=self._batch_size,
            configuration_mode=OnlyRuntimeConfigurationMode.INTEGRATION_REVISION,
            integration_binding=cast(OnlyJsonMapping, reference.binding_reference()),
        )
        capabilities = OnlyDataSourceCapabilities(historical_bars=True)
        try:
            admitted = only_admit_data_source_runtime_configuration(runtime_config, self._resolver, capabilities)
            factory, plugin_config = only_resolve_data_source_runtime_configuration(
                admitted, self._data_sources, self._resolver, capabilities
            )
        except OnlyIntegrationRuntimeError as exc:
            # An unavailable Integration authority is not "this source is ineligible":
            # it must never be projected as an empty source list or a missing scope.
            if exc.code == "INTEGRATION_RUNTIME_PERSISTENCE_UNAVAILABLE":
                raise OnlyMarketDataProductError(
                    "MARKET_DATA_SOURCE_CATALOG_UNAVAILABLE", "Integration authority is unavailable"
                ) from exc
            raise OnlyMarketDataProductError(
                "MARKET_DATA_SOURCE_SELECTION_UNRESOLVED", "exact Integration runtime binding cannot be resolved"
            ) from exc
        except Exception as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_SOURCE_SELECTION_UNRESOLVED", "exact Integration runtime binding cannot be resolved"
            ) from exc
        binding = admitted.integration_binding
        if binding is None:  # pragma: no cover - admission always binds an exact revision
            raise OnlyMarketDataProductError("MARKET_DATA_SOURCE_SELECTION_UNRESOLVED")
        if reference.expected_type_id is not None and str(binding["type_id"]) != reference.expected_type_id:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_SOURCE_SELECTION_MISMATCH",
                "declared type does not match the exact Integration Revision",
            )
        if not isinstance(factory, OnlyDataSourceInstrumentCatalog):
            raise OnlyMarketDataProductError(
                "MARKET_DATA_INSTRUMENT_CATALOG_UNAVAILABLE",
                "data source implementation cannot project reference instruments",
            )
        descriptor = cast(OnlyIntegrationTypeDescriptorV1, getattr(factory, "integration_type", None))
        if not isinstance(descriptor, OnlyIntegrationTypeDescriptorV1):
            raise OnlyMarketDataProductError(
                "MARKET_DATA_SOURCE_SELECTION_UNRESOLVED",
                "data source implementation does not declare an Integration type",
            )
        identity = factory.market_identity(plugin_config)
        return OnlyResolvedMarketDataRuntime(
            OnlyMarketDataSourceSelectionV1(
                reference.integration_id,
                reference.integration_revision_fingerprint,
                str(descriptor.type_id),
                identity.source_id,
                identity.environment,
            ),
            str(binding["binding_fingerprint"]),
            identity.venue,
            identity.market,
            identity.environment,
            OnlyMarketDataSourceId(identity.source_id),
            OnlyDataVersion(f"{descriptor.type_id}@{descriptor.public_api_version}"),
            factory,
            plugin_config,
            factory,
        )

    def _scope(
        self,
        resolved: OnlyResolvedMarketDataRuntime,
        instrument_id: str,
        start_ns: int,
        end_ns: int,
        plan: OnlyBarResolutionPlan,
    ) -> OnlyMarketDataScope:
        if start_ns >= end_ns:
            raise OnlyMarketDataProductError("MARKET_DATA_RANGE_INVALID", "requested range must be increasing")
        if plan.mode is not OnlyBarResolutionMode.PROVIDER_NATIVE or plan.provider_semantic is None:
            raise OnlyMarketDataProductError("MARKET_DATA_ACQUISITION_PLAN_INVALID")
        semantic = plan.provider_semantic
        grid = semantic.stride_minutes * MINUTE_NS
        if (start_ns - plan.grid_origin_ns) % grid or (end_ns - plan.grid_origin_ns) % grid:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_RANGE_INVALID", "requested range must align to the selected bar grid"
            )
        try:
            instrument = OnlyInstrumentId.parse(instrument_id)
        except Exception as exc:
            raise OnlyMarketDataProductError("MARKET_DATA_INSTRUMENT_INVALID") from exc
        if str(instrument.venue) != resolved.venue:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_INSTRUMENT_SOURCE_MISMATCH", "instrument does not belong to this source venue"
            )
        return OnlyMarketDataScope(
            str(resolved.source_id),
            resolved.market,
            str(instrument),
            "BAR",
            start_ns,
            end_ns,
            str(resolved.data_version),
            only_canonical_fingerprint(_bar_type(instrument, semantic).to_dict()),
            bar_construction=OnlyBarConstructionIdentity.build(plan, data_version=str(resolved.data_version)),
        )

    def _plan(
        self,
        resolved: OnlyResolvedMarketDataRuntime,
        instrument_id: str,
        semantic: OnlyBarSemantic,
    ) -> OnlyBarResolutionPlan:
        if not isinstance(resolved.factory, OnlyDataSourceBarCapabilities) or not isinstance(
            resolved.factory, OnlyDataSourceTimeBarCalendar
        ):
            raise OnlyMarketDataProductError("MARKET_DATA_BAR_CAPABILITY_UNAVAILABLE")
        calendar = resolved.factory.time_bar_calendar(resolved.plugin_config)
        if (
            calendar.timezone.zone_info.key != "UTC"
            or len(calendar.sessions) != 1
            or calendar.sessions[0].opens_at != time(0)
            or calendar.sessions[0].closes_at != time(0)
            or calendar.holidays
            or calendar.weekend_days
            or calendar.special_schedules
        ):
            raise OnlyMarketDataProductError("MARKET_DATA_BAR_GRID_UNSUPPORTED")
        alignment_id = only_canonical_fingerprint(calendar.to_dict())
        try:
            plan = only_plan_bar_resolution(
                semantic,
                resolved.factory.bar_capabilities(resolved.plugin_config, OnlyInstrumentId.parse(instrument_id)),
                calendar_fingerprint=alignment_id,
                source_id=str(resolved.source_id),
                instrument_id=instrument_id,
                integration_revision_fingerprint=resolved.selection.integration_revision_fingerprint,
            )
            OnlyBarConstructionAlgorithmRegistry().require(plan.resolved_recipe)
            if plan.mode is OnlyBarResolutionMode.DERIVED and plan.grid_origin_ns != 0:
                raise ValueError("BAR_RESOLUTION_BASE_ALIGNMENT_UNSUPPORTED")
            return plan
        except (ValueError, TypeError) as exc:
            raise OnlyMarketDataProductError("MARKET_DATA_BAR_RESOLUTION_UNAVAILABLE", str(exc)) from exc

    def _assert_acquisition_window(self, start_ns: int, end_ns: int) -> None:
        if (end_ns - start_ns) // 1_000_000_000 > MAX_ACQUISITION_SECONDS:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_ACQUISITION_RANGE_TOO_LARGE",
                f"bounded acquisition window is at most {MAX_ACQUISITION_SECONDS} seconds",
            )
        if end_ns > self._closed_minute_ns():
            raise OnlyMarketDataProductError(
                "MARKET_DATA_ACQUISITION_RANGE_NOT_CLOSED",
                "acquisition accepts only already closed canonical 1m bars",
            )

    def _closed_minute_ns(self) -> int:
        return (self._clock.timestamp_ns() // MINUTE_NS) * MINUTE_NS

    def _execute_acquisition(
        self, resolved: OnlyResolvedMarketDataRuntime, intent: OnlyMarketDataAcquisitionIntent
    ) -> tuple[_OnlyExactSealedHistory | None, str | None]:
        session: _OnlyAcquisitionSession | None = None
        try:
            session = self._open_session(resolved, intent.requested_scope)
            manifest = session.coordinator.inspect(intent)
            if manifest.coverage_status is OnlyCoverageStatus.COMPLETE:
                segments = self._catalog.list_durable_segments(intent.requested_scope)
                proofs = self._catalog.load_physical_proofs(tuple(item.segment_id for item in segments))
                facts = self._facts.read_segment_facts(segments, intent.requested_scope, proofs)
                OnlyRevisionCommitService(self._facts, self._catalog, now=self._now).commit_durable_facts(
                    segments, intent.requested_scope, facts, reason="BACKFILL"
                )
            for planned in only_plan_contiguous_bar_gaps(
                tuple(item for item in manifest.gaps if isinstance(item, OnlyBarCoverageGap))
            ):
                session.coordinator.backfill_bar_gap(
                    intent,
                    _bar_request(intent.requested_scope, planned, resolved.data_version, self._batch_size),
                    planned,
                )
            session.close()
            sealed = self._sealed_for_scope(intent.requested_scope)
            if sealed is None:
                return None, self._coverage(intent.requested_scope).status
            return sealed, None
        except OnlyMarketDataProductError:
            raise
        except Exception as exc:
            self._logger.warning("market-data acquisition failed: %s", exc)
            return None, f"{type(exc).__name__}:{exc}"
        finally:
            if session is not None:
                session.close()

    def _open_session(
        self, resolved: OnlyResolvedMarketDataRuntime, scope: OnlyMarketDataScope
    ) -> _OnlyAcquisitionSession:
        source_root = self._wal_root / str(resolved.source_id)
        source_root.mkdir(parents=True, exist_ok=True)
        wal = OnlyMarketDataWal(source_root / "wal", capacity_bytes=_WAL_CAPACITY_BYTES, now=self._now)
        descriptor = resolved.factory.descriptor  # type: ignore[attr-defined]
        ingress = OnlyMarketDataIngress(
            wal,
            normalizer_id=str(descriptor.plugin_id),
            normalizer_version=str(descriptor.plugin_version),
            ingest_clock_ns=self._clock.timestamp_ns,
            integration_binding_fingerprint=resolved.binding_fingerprint,
            bar_construction=scope.bar_construction,
        )
        recovery = OnlyMarketDataRecoveryCoordinator(
            wal,
            self._facts,
            self._catalog,
            OnlyRevisionCommitService(self._facts, self._catalog, now=self._now),
        )
        recovery.recover_all()
        # One provider response remains one durable segment. The bounded backfill
        # drains all sealed pages together after provider loading completes.
        recorder = OnlyDurableMarketDataRecorder(
            ingress,
            max_records_per_segment=1,
        )
        instrument_id = OnlyInstrumentId.parse(scope.instrument_id)
        instruments = resolved.catalog.list_instruments(
            OnlyDataSourceInstrumentCatalogRequestV1(resolved.plugin_config, instrument_ids=(str(instrument_id),))
        )
        if len(instruments) != 1:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_INSTRUMENT_NOT_FOUND", "requested instrument is not published by this source"
            )
        instrument = instruments[0].instrument
        request = OnlyDataSourceCreateRequest(
            resolved.source_id,
            resolved.plugin_config,
            "PRODUCT",
            OnlyDataSourceCapabilities(historical_bars=True),
            self._clock,
            OnlyEventBus(),
            {instrument.instrument_id: instrument},
            {instrument.instrument_id: _bar_type(instrument.instrument_id, _scope_bar_semantic(scope))},
            {},
            (),
            OnlyDataSourceCoverageConfig(instrument_ids=(instrument.instrument_id,)),
            OnlyRuntimeId(f"market-data:{resolved.source_id}"),
            resolved.data_version,
            self._batch_size,
            source_root,
            self._logger,
            historical_cache_service=OnlyHistoricalCacheService(
                OnlyParquetHistoricalCacheStore(source_root / "historical-cache")
            ),
            runtime_state_root=source_root,
            provider_evidence_sink=recorder,
            durable_recording_required=True,
        )
        source: OnlyDataSource = resolved.factory.create(request)  # type: ignore[attr-defined]
        coordinator = OnlyMarketDataBackfillCoordinator(
            source,
            self._catalog,
            self._facts,
            recovery,
            OnlyRevisionCommitService(self._facts, self._catalog, now=self._now),
        )
        session = _OnlyAcquisitionSession(source, recorder, recovery, coordinator, self._logger)
        source.initialize()
        source.connect()
        source.authenticate()
        return session

    def _sealed_for_scope(self, scope: OnlyMarketDataScope) -> _OnlyExactSealedHistory | None:
        """Explicit not-found is the only condition that may mean "no data yet".

        An unavailable, corrupt or schema-incompatible catalog must never be projected
        as an empty result: that would turn a database outage into a silent claim that
        no canonical history exists, and would let a Query or Command proceed on it.
        """

        try:
            revision = self._catalog.latest_sealed_revision(scope)
        except KeyError as exc:
            if exc.args and exc.args[0] == "SEALED_REVISION_NOT_FOUND":
                return None
            raise OnlyMarketDataProductError(
                "MARKET_DATA_CATALOG_CORRUPT", "sealed revision lookup returned an invalid result"
            ) from exc
        except Exception as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_CATALOG_UNAVAILABLE", "canonical market-data catalog is unavailable"
            ) from exc
        query = OnlyHistoricalMarketDataQueryService(self._catalog, self._facts)
        try:
            stored, seal = query.resolve_with_seal(revision.revision_id)
            manifest = self._catalog.load_coverage_manifest(stored.manifest_id)
        except (KeyError, TypeError, ValueError) as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_CATALOG_CORRUPT", "latest sealed revision evidence is not readable"
            ) from exc
        except OnlyMarketDataSealError as exc:
            raise OnlyMarketDataProductError("MARKET_DATA_REVISION_EVIDENCE_INVALID", str(exc)) from exc
        except Exception as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_CATALOG_UNAVAILABLE", "canonical market-data catalog is unavailable"
            ) from exc
        if stored != revision or stored.scope != scope:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_CATALOG_CORRUPT", "sealed revision does not match its own scope identity"
            )
        try:
            facts = query.read_exact(stored.revision_id, scope)
        except (OnlyMarketDataSealError, OnlyMarketDataConflictError, KeyError, TypeError, ValueError) as exc:
            raise OnlyMarketDataProductError("MARKET_DATA_REVISION_EVIDENCE_INVALID", str(exc)) from exc
        except Exception as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_FACT_STORE_UNAVAILABLE", "canonical market-data store is unavailable"
            ) from exc
        return _OnlyExactSealedHistory(stored, manifest, seal, facts)

    def _coverage(
        self, scope: OnlyMarketDataScope, sealed: _OnlyExactSealedHistory | None = None
    ) -> OnlyMarketDataCoverageProjectionV1:
        if sealed is not None:
            manifest = sealed.manifest
            facts = sealed.facts
            complete = True
        else:
            complete = False
            try:
                segments = self._catalog.list_durable_segments(scope)
            except Exception as exc:
                raise OnlyMarketDataProductError(
                    "MARKET_DATA_CATALOG_UNAVAILABLE", "canonical market-data catalog is unavailable"
                ) from exc
            proofs = self._catalog.load_physical_proofs(tuple(item.segment_id for item in segments)) if segments else ()
            facts = self._facts.read_segment_facts(tuple(segments), scope, proofs) if segments else ()
            manifest = only_build_coverage(scope, tuple(segments), facts)
        bar_gaps = tuple(item for item in manifest.gaps if isinstance(item, OnlyBarCoverageGap))
        step_ns = (
            MINUTE_NS
            if scope.bar_construction is None
            else scope.bar_construction.plan.target_semantic.stride_minutes * MINUTE_NS
        )
        expected = max(0, (scope.end_ns - scope.start_ns) // step_ns)
        unknown = len({fact.canonical_fact_id for fact in facts})
        unsealed = manifest.coverage_status is OnlyCoverageStatus.COMPLETE and not complete
        return OnlyMarketDataCoverageProjectionV1(
            OnlyCoverageStatus.INCOMPLETE.value if unsealed else manifest.coverage_status.value,
            manifest.manifest_id,
            manifest.fingerprint,
            expected,
            unknown,
            (*manifest.issues, "SEALED_REVISION_NOT_FOUND") if unsealed else manifest.issues,
            tuple(OnlyMarketDataCoverageGapV1(item.start_ns, item.end_ns) for item in bar_gaps),
            ()
            if complete
            else tuple(
                OnlyMarketDataCoverageGapV1(item.start_ns, item.end_ns)
                for item in only_plan_contiguous_bar_gaps(bar_gaps)
            ),
        )

    def _bars(self, facts: tuple[OnlyCanonicalMarketFactRecord, ...]) -> tuple[OnlyMarketDataBarV1, ...]:
        bars: list[OnlyMarketDataBarV1] = []
        for fact in facts:
            update = OnlyMarketDataInboundUpdate.from_dict(fact.canonical_payload)
            if not isinstance(update.payload, OnlyBarUpdate):
                continue
            bar = update.payload.bar
            bars.append(
                OnlyMarketDataBarV1(
                    OnlyTimestamp.from_datetime(bar.bar_start).unix_nanos,
                    OnlyTimestamp.from_datetime(bar.bar_end).unix_nanos,
                    str(bar.open.value),
                    str(bar.high.value),
                    str(bar.low.value),
                    str(bar.close.value),
                    str(bar.volume.value),
                    bar.is_closed,
                )
            )
        return tuple(sorted(bars, key=lambda item: item.bar_start_ns))

    @staticmethod
    def _crop_bars(
        bars: tuple[OnlyMarketDataBarV1, ...], intervals: tuple[OnlyBarCoverageGap, ...]
    ) -> tuple[OnlyMarketDataBarV1, ...]:
        expected = {(item.start_ns, item.end_ns) for item in intervals}
        return tuple(item for item in bars if (item.bar_start_ns, item.bar_end_ns) in expected)

    def _derived_bars(
        self,
        resolved: OnlyResolvedMarketDataRuntime,
        facts: tuple[OnlyCanonicalMarketFactRecord, ...],
        semantic: OnlyBarSemantic,
    ) -> tuple[tuple[OnlyMarketDataBarV1, ...], str]:
        if not isinstance(resolved.factory, OnlyDataSourceTimeBarCalendar):
            raise OnlyMarketDataProductError("MARKET_DATA_TIME_BAR_CALENDAR_UNAVAILABLE")
        calendar: OnlyTradingCalendar = resolved.factory.time_bar_calendar(resolved.plugin_config)
        calendar_fingerprint = only_canonical_fingerprint(calendar.to_dict())
        source_bars = tuple(
            update.bar
            for fact in facts
            if isinstance(
                update := OnlyMarketDataInboundUpdate.from_dict(fact.canonical_payload).payload, OnlyBarUpdate
            )
        )
        if not source_bars:
            return (), calendar_fingerprint
        source_type = source_bars[0].bar_type
        target_type = OnlyBarType(source_type.instrument_id, semantic)
        aggregator = OnlyTimeBarAggregator(source_type, target_type, calendar, self._clock)
        derived: list[OnlyBar] = []
        started = False
        try:
            for bar in source_bars:
                if not started:
                    window_start, _, _ = aggregator.window_for(bar)
                    if bar.bar_start != window_start:
                        continue
                    started = True
                result = aggregator.process(bar)
                if result is not None:
                    derived.append(result)
        except OnlyBarAggregationError as exc:
            raise OnlyMarketDataProductError("MARKET_DATA_DERIVED_SOURCE_INVALID", str(exc)) from exc
        return tuple(
            OnlyMarketDataBarV1(
                OnlyTimestamp.from_datetime(bar.bar_start).unix_nanos,
                OnlyTimestamp.from_datetime(bar.bar_end).unix_nanos,
                str(bar.open.value),
                str(bar.high.value),
                str(bar.low.value),
                str(bar.close.value),
                str(bar.volume.value),
                True,
            )
            for bar in derived
        ), calendar_fingerprint

    def _record_attempt(
        self,
        attempt: OnlyMarketDataAcquisitionAttempt,
        outcome: OnlyAcquisitionOutcome,
        *,
        detail: str,
        revision_id: str | None = None,
    ) -> None:
        self._catalog.record_acquisition_attempt(
            attempt.finish(
                outcome,
                detail=detail,
                completed_at=self._now(),
                revision_id=revision_id,
            )
        )

    def _admit(self, intent: OnlyMarketDataAcquisitionIntent) -> OnlyMarketDataAcquisitionIntent:
        try:
            return self._catalog.admit_acquisition_intent(intent)
        except Exception as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_CATALOG_UNAVAILABLE", "acquisition intent could not be admitted durably"
            ) from exc

    def _start_attempt(self, acquisition_id: str, *, started_at: datetime) -> OnlyMarketDataAcquisitionAttempt:
        try:
            return self._catalog.start_acquisition_attempt(acquisition_id, started_at=started_at)
        except Exception as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_CATALOG_UNAVAILABLE", "acquisition attempt occurrence could not be admitted"
            ) from exc

    def _record_terminal_failure(self, attempt: OnlyMarketDataAcquisitionAttempt, *, detail: str) -> None:
        """Without canonical Coverage/Revision/Seal, FAILED must itself be durable.

        If the failure observation cannot be persisted the Product may not report a
        durable FAILED; it reports explicit uncertainty instead of swallowing the error.
        """

        try:
            self._record_attempt(
                attempt,
                OnlyAcquisitionOutcome.FAILED,
                detail=detail,
            )
        except Exception as exc:
            self._logger.warning("market-data acquisition failure evidence failed: %s", exc)
            raise OnlyMarketDataProductError(
                "MARKET_DATA_ACQUISITION_EVIDENCE_UNAVAILABLE",
                "terminal acquisition failure could not be persisted",
            ) from exc

    def _projection(
        self,
        resolved: OnlyResolvedMarketDataRuntime,
        intent: OnlyMarketDataAcquisitionIntent,
        *,
        status: str,
        sealed: _OnlyExactSealedHistory | None,
        failure_detail: str | None,
    ) -> OnlyMarketDataAcquisitionProjectionV1:
        return OnlyMarketDataAcquisitionProjectionV1(
            SCHEMA_VERSION,
            intent.acquisition_id,
            status,
            intent.source_id,
            intent.integration_binding_fingerprint,
            intent.requested_scope.instrument_id,
            _scope_bar_semantic(intent.requested_scope),
            intent.requested_scope.start_ns,
            intent.requested_scope.end_ns,
            intent.provenance.value,
            self._coverage(intent.requested_scope, sealed),
            None if sealed is None else sealed.revision.revision_id,
            None if sealed is None else sealed.revision.fingerprint,
            None if sealed is None else sealed.seal.seal_id,
            failure_detail,
        )


def _bar_type(instrument_id: OnlyInstrumentId, semantic: OnlyBarSemantic = BASE_BAR_SEMANTIC) -> OnlyBarType:
    return OnlyBarType(instrument_id, semantic)


def _scope_bar_semantic(scope: OnlyMarketDataScope) -> OnlyBarSemantic:
    if scope.bar_construction is None:
        raise OnlyMarketDataProductError("MARKET_DATA_BAR_CONSTRUCTION_UNPROVABLE")
    return scope.bar_construction.plan.target_semantic


def _bar_request(
    scope: OnlyMarketDataScope, planned: OnlyBarCoverageGap, data_version: OnlyDataVersion, batch_size: int
) -> OnlyHistoricalBarRequest:
    instrument = OnlyInstrumentId.parse(scope.instrument_id)
    return OnlyHistoricalBarRequest(
        f"market-data-acquisition:{planned.start_ns}:{planned.end_ns}",
        frozenset({instrument}),
        frozenset({_bar_type(instrument, _scope_bar_semantic(scope))}),
        OnlyHistoricalDataRange(
            OnlyTimestamp.from_unix_nanos(planned.start_ns).to_datetime(),
            OnlyTimestamp.from_unix_nanos(planned.end_ns).to_datetime(),
        ),
        data_version,
        batch_size=batch_size,
    )


def _display_symbol(instrument_id: str, venue: str) -> str:
    symbol, _, suffix = instrument_id.rpartition(".")
    return symbol if symbol and suffix == venue else instrument_id


__all__ = [
    "DEFAULT_ACQUISITION_SECONDS",
    "DEFAULT_TARGET_BAR_COUNT",
    "MAX_ACQUISITION_SECONDS",
    "SCHEMA_VERSION",
    "BASE_BAR_SEMANTIC",
    "MAX_FIXED_DURATION_WINDOW_MINUTES",
    "MAX_TARGET_BAR_COUNT",
    "OnlyMarketDataAcquisitionProjectionV1",
    "OnlyMarketDataBarV1",
    "OnlyMarketDataBarWindowProjectionV1",
    "OnlyMarketDataCoverageGapV1",
    "OnlyMarketDataCoverageProjectionV1",
    "OnlyMarketDataInstrumentProjectionV1",
    "OnlyMarketDataInstrumentListProjectionV1",
    "OnlyMarketDataProductError",
    "OnlyMarketDataProductService",
    "OnlyMarketDataSourceProjectionV1",
    "OnlyMarketDataSourceReferenceV1",
    "OnlyMarketDataSourceSelectionV1",
    "OnlyMarketDataTimeBarCapabilityV1",
    "OnlyIntegrationListing",
]
