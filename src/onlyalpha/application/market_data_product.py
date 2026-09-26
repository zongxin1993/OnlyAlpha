"""Provider-neutral Market Data Product Query/Command boundary.

The boundary resolves one exact Integration Revision, composes the existing durable
market-data authority over it and projects canonical Coverage/Revision facts. It
defines no market-data semantics of its own: Binance-specific meaning stays in the
plugin, and historical reads are served from the database.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from logging import Logger
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, cast

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
from onlyalpha.domain.enums import OnlyAggregationSource, OnlyBarAggregation, OnlyPriceType
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.market_data.durable.backfill import (
    OnlyMarketDataBackfillCoordinator,
    only_plan_contiguous_bar_gaps,
)
from onlyalpha.market_data.durable.ingress import OnlyMarketDataIngress
from onlyalpha.market_data.durable.models import (
    OnlyAcquisitionOutcome,
    OnlyBarCoverageGap,
    OnlyCanonicalMarketFactRecord,
    OnlyCoverageStatus,
    OnlyMarketDataAcquisitionAttempt,
    OnlyMarketDataAcquisitionIntent,
    OnlyMarketDataProvenance,
    OnlyMarketDataRevision,
    OnlyMarketDataScope,
    OnlyMarketDataSeal,
)
from onlyalpha.market_data.durable.ports import OnlyMarketDataCatalog, OnlyMarketFactStore
from onlyalpha.market_data.durable.recorder import OnlyDurableMarketDataRecorder
from onlyalpha.market_data.durable.recovery import OnlyMarketDataRecoveryCoordinator
from onlyalpha.market_data.durable.revision import (
    OnlyHistoricalMarketDataQueryService,
    OnlyRevisionCommitService,
    only_build_coverage,
)
from onlyalpha.market_data.durable.wal import OnlyMarketDataWal
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities
from onlyalpha.plugin.data_source import (
    OnlyDataSource,
    OnlyDataSourceCreateRequest,
    OnlyDataSourceInstrumentCatalog,
    OnlyDataSourceInstrumentCatalogRequestV1,
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
SUPPORTED_BAR_SPECIFICATION = "1m"
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
    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail or code
        super().__init__(f"{code}: {self.detail}")


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
class OnlyMarketDataSourceProjectionV1:
    """A configured Integration that is eligible for this Market Data Product."""

    integration_id: str
    integration_revision_fingerprint: str
    display_name: str
    type_id: str
    source_id: str
    environment: str


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
class OnlyMarketDataBarsProjectionV1:
    schema_version: int
    source_selection: OnlyMarketDataSourceSelectionV1
    instrument_id: str
    display_symbol: str
    venue: str
    market: str
    bar_specification: str
    aggregation_source: str
    adjustment: str
    closed_only: bool
    start_ns: int
    end_ns: int
    coverage: OnlyMarketDataCoverageProjectionV1
    revision_id: str | None
    revision_fingerprint: str | None
    seal_id: str | None
    bars: tuple[OnlyMarketDataBarV1, ...]


@dataclass(frozen=True, slots=True)
class OnlyMarketDataAcquisitionProjectionV1:
    schema_version: int
    acquisition_id: str
    status: str
    source_id: str
    integration_binding_fingerprint: str | None
    instrument_id: str
    bar_specification: str
    start_ns: int
    end_ns: int
    provenance: str
    coverage: OnlyMarketDataCoverageProjectionV1
    revision_id: str | None
    revision_fingerprint: str | None
    seal_id: str | None
    failure_detail: str | None


@dataclass(frozen=True, slots=True)
class _OnlyResolvedSelection:
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
        self._queries = OnlyHistoricalMarketDataQueryService(catalog, fact_store)
        self._lock = threading.Lock()
        self._running: dict[str, int] = {}

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
                resolved = self._resolve(reference)
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
        resolved = self._resolve(reference)
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
        start_ns: int,
        end_ns: int,
        bar_specification: str = SUPPORTED_BAR_SPECIFICATION,
    ) -> OnlyMarketDataBarsProjectionV1:
        """DB-first exact read; a Query never acquires, retries or mutates state."""

        resolved = self._resolve(reference)
        scope = self._scope(resolved, instrument_id, start_ns, end_ns, bar_specification)
        try:
            sealed = self._sealed_for_scope(scope)
            bars: tuple[OnlyMarketDataBarV1, ...] = ()
            revision_id: str | None = None
            revision_fingerprint: str | None = None
            seal_id: str | None = None
            if sealed is not None:
                revision, seal = sealed
                bars = self._bars(self._queries.read_exact(revision.revision_id, scope))
                revision_id = revision.revision_id
                revision_fingerprint = revision.fingerprint
                seal_id = seal.seal_id
            coverage = self._coverage(scope, sealed is not None)
        except OnlyMarketDataProductError:
            raise
        except Exception as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_FACT_STORE_UNAVAILABLE", "canonical market-data store is unavailable"
            ) from exc
        return OnlyMarketDataBarsProjectionV1(
            SCHEMA_VERSION,
            resolved.selection,
            instrument_id,
            _display_symbol(instrument_id, resolved.venue),
            resolved.venue,
            resolved.market,
            bar_specification,
            OnlyAggregationSource.EXTERNAL.value,
            "RAW",
            True,
            start_ns,
            end_ns,
            coverage,
            revision_id,
            revision_fingerprint,
            seal_id,
            bars,
        )

    # --- Product Command ---------------------------------------------------------------

    def acquire_bars(
        self,
        reference: OnlyMarketDataSourceReferenceV1,
        *,
        instrument_id: str,
        start_ns: int,
        end_ns: int,
        bar_specification: str = SUPPORTED_BAR_SPECIFICATION,
    ) -> OnlyMarketDataAcquisitionProjectionV1:
        """Validate, admit the execution intent durably, then execute.

        No provider session, WAL or reference call happens before the exact intent is
        durable: a FAILED Product response must never describe a state the database
        cannot reproduce after restart.
        """

        resolved = self._resolve(reference)
        scope = self._scope(resolved, instrument_id, start_ns, end_ns, bar_specification)
        self._assert_acquisition_window(start_ns, end_ns)
        intent = OnlyMarketDataAcquisitionIntent.build(
            str(resolved.source_id),
            scope,
            provenance=OnlyMarketDataProvenance.REST_BACKFILL,
            admitted_at=self._now(),
            integration_binding_fingerprint=resolved.binding_fingerprint,
        )
        with self._lock:
            admitted = self._admit(intent)
            sealed = self._sealed_for_scope(scope)
            if sealed is not None:
                return self._projection(
                    resolved,
                    admitted,
                    status="COMPLETE",
                    revision=sealed[0],
                    seal=sealed[1],
                    failure_detail=None,
                )
            started_at = self._now()
            attempt = self._start_attempt(admitted.acquisition_id, started_at=started_at)
            self._running[admitted.acquisition_id] = self._running.get(admitted.acquisition_id, 0) + 1
        try:
            revision, seal, failure = self._execute_acquisition(resolved, admitted)
        finally:
            with self._lock:
                remaining = self._running[admitted.acquisition_id] - 1
                if remaining:
                    self._running[admitted.acquisition_id] = remaining
                else:
                    del self._running[admitted.acquisition_id]
        if failure is None and revision is not None and seal is not None:
            # Canonical success authority is Coverage + Revision + Seal; the COMPLETE
            # attempt is operational evidence and cannot demote an already sealed revision.
            try:
                self._record_attempt(
                    attempt,
                    OnlyAcquisitionOutcome.COMPLETE,
                    detail="MARKET_DATA_ACQUISITION_COMPLETE",
                    revision_id=revision.revision_id,
                )
            except Exception as exc:
                self._logger.warning("market-data acquisition attempt evidence failed: %s", exc)
            return self._projection(
                resolved, admitted, status="COMPLETE", revision=revision, seal=seal, failure_detail=None
            )
        detail = failure or "MARKET_DATA_ACQUISITION_INCOMPLETE"
        self._record_terminal_failure(attempt, detail=detail)
        return self._projection(resolved, admitted, status="FAILED", revision=None, seal=None, failure_detail=detail)

    def acquisition_status(
        self, reference: OnlyMarketDataSourceReferenceV1, acquisition_id: str
    ) -> OnlyMarketDataAcquisitionProjectionV1:
        resolved = self._resolve(reference)
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
            return self._projection(
                resolved, intent, status="COMPLETE", revision=sealed[0], seal=sealed[1], failure_detail=None
            )
        if acquisition_id in self._running:
            return self._projection(resolved, intent, status="RUNNING", revision=None, seal=None, failure_detail=None)
        if attempt is not None and attempt.outcome is OnlyAcquisitionOutcome.FAILED:
            return self._projection(
                resolved, intent, status="FAILED", revision=None, seal=None, failure_detail=attempt.detail
            )
        return self._projection(resolved, intent, status="PENDING", revision=None, seal=None, failure_detail=None)

    # --- Internals ---------------------------------------------------------------------

    def _resolve(self, reference: OnlyMarketDataSourceReferenceV1) -> _OnlyResolvedSelection:
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
        return _OnlyResolvedSelection(
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
        resolved: _OnlyResolvedSelection,
        instrument_id: str,
        start_ns: int,
        end_ns: int,
        bar_specification: str,
    ) -> OnlyMarketDataScope:
        if bar_specification != SUPPORTED_BAR_SPECIFICATION:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_BAR_SPECIFICATION_UNSUPPORTED",
                f"supported bar specification: {SUPPORTED_BAR_SPECIFICATION}",
            )
        if start_ns >= end_ns:
            raise OnlyMarketDataProductError("MARKET_DATA_RANGE_INVALID", "requested range must be increasing")
        if start_ns % MINUTE_NS or end_ns % MINUTE_NS:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_RANGE_INVALID", "requested range must be aligned to the canonical 1m grid"
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
            only_canonical_fingerprint(_bar_type(instrument).to_dict()),
        )

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
        self, resolved: _OnlyResolvedSelection, intent: OnlyMarketDataAcquisitionIntent
    ) -> tuple[OnlyMarketDataRevision | None, OnlyMarketDataSeal | None, str | None]:
        session: _OnlyAcquisitionSession | None = None
        try:
            session = self._open_session(resolved, intent.requested_scope)
            manifest = session.coordinator.inspect(intent)
            if manifest.coverage_status is OnlyCoverageStatus.COMPLETE:
                segments = self._catalog.list_durable_segments(intent.requested_scope)
                facts = self._facts.read_segment_facts(segments, intent.requested_scope)
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
                return None, None, self._coverage(intent.requested_scope, False).status
            return sealed[0], sealed[1], None
        except Exception as exc:
            self._logger.warning("market-data acquisition failed: %s", exc)
            return None, None, f"{type(exc).__name__}:{exc}"
        finally:
            if session is not None:
                session.close()

    def _open_session(self, resolved: _OnlyResolvedSelection, scope: OnlyMarketDataScope) -> _OnlyAcquisitionSession:
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
        )
        recovery = OnlyMarketDataRecoveryCoordinator(
            wal,
            self._facts,
            self._catalog,
            OnlyRevisionCommitService(self._facts, self._catalog, now=self._now),
        )
        recovery.recover_all()
        # One provider response is one durable segment, drained synchronously: the
        # acquisition must observe canonical Coverage before it can report COMPLETE.
        recorder = OnlyDurableMarketDataRecorder(
            ingress,
            max_records_per_segment=1,
            on_sealed=lambda _segment: _drain(recovery),
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
            {instrument.instrument_id: _bar_type(instrument.instrument_id)},
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

    def _sealed_for_scope(self, scope: OnlyMarketDataScope) -> tuple[OnlyMarketDataRevision, OnlyMarketDataSeal] | None:
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
        try:
            stored, seal = self._catalog.load_sealed_revision(revision.revision_id)
        except KeyError as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_CATALOG_CORRUPT", "latest sealed revision is not readable"
            ) from exc
        except Exception as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_CATALOG_UNAVAILABLE", "canonical market-data catalog is unavailable"
            ) from exc
        if (
            stored.revision_id != revision.revision_id
            or stored.scope != scope
            or stored.fingerprint != revision.fingerprint
            or seal.revision_fingerprint != stored.fingerprint
        ):
            raise OnlyMarketDataProductError(
                "MARKET_DATA_CATALOG_CORRUPT", "sealed revision does not match its own scope identity"
            )
        return stored, seal

    def _coverage(self, scope: OnlyMarketDataScope, complete: bool) -> OnlyMarketDataCoverageProjectionV1:
        try:
            segments = self._catalog.list_durable_segments(scope)
        except Exception as exc:
            raise OnlyMarketDataProductError(
                "MARKET_DATA_CATALOG_UNAVAILABLE", "canonical market-data catalog is unavailable"
            ) from exc
        facts = self._facts.read_segment_facts(tuple(segments), scope) if segments else ()
        manifest = only_build_coverage(scope, tuple(segments), facts)
        bar_gaps = tuple(item for item in manifest.gaps if isinstance(item, OnlyBarCoverageGap))
        expected = max(0, (scope.end_ns - scope.start_ns) // MINUTE_NS)
        unknown = len({fact.canonical_fact_id for fact in facts})
        return OnlyMarketDataCoverageProjectionV1(
            manifest.coverage_status.value,
            manifest.manifest_id,
            manifest.fingerprint,
            expected,
            unknown,
            manifest.issues,
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
        resolved: _OnlyResolvedSelection,
        intent: OnlyMarketDataAcquisitionIntent,
        *,
        status: str,
        revision: OnlyMarketDataRevision | None,
        seal: OnlyMarketDataSeal | None,
        failure_detail: str | None,
    ) -> OnlyMarketDataAcquisitionProjectionV1:
        return OnlyMarketDataAcquisitionProjectionV1(
            SCHEMA_VERSION,
            intent.acquisition_id,
            status,
            intent.source_id,
            intent.integration_binding_fingerprint,
            intent.requested_scope.instrument_id,
            SUPPORTED_BAR_SPECIFICATION,
            intent.requested_scope.start_ns,
            intent.requested_scope.end_ns,
            intent.provenance.value,
            self._coverage(intent.requested_scope, revision is not None),
            None if revision is None else revision.revision_id,
            None if revision is None else revision.fingerprint,
            None if seal is None else seal.seal_id,
            failure_detail,
        )


def _bar_type(instrument_id: OnlyInstrumentId) -> OnlyBarType:
    return OnlyBarType(
        instrument_id,
        OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )


def _drain(recovery: OnlyMarketDataRecoveryCoordinator) -> None:
    """Sealed WAL segments become canonical evidence before the acquisition proceeds."""

    recovery.recover_all()


def _bar_request(
    scope: OnlyMarketDataScope, planned: OnlyBarCoverageGap, data_version: OnlyDataVersion, batch_size: int
) -> OnlyHistoricalBarRequest:
    instrument = OnlyInstrumentId.parse(scope.instrument_id)
    return OnlyHistoricalBarRequest(
        f"market-data-acquisition:{planned.start_ns}:{planned.end_ns}",
        frozenset({instrument}),
        frozenset({_bar_type(instrument)}),
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
    "MAX_ACQUISITION_SECONDS",
    "SCHEMA_VERSION",
    "SUPPORTED_BAR_SPECIFICATION",
    "OnlyMarketDataAcquisitionProjectionV1",
    "OnlyMarketDataBarV1",
    "OnlyMarketDataBarsProjectionV1",
    "OnlyMarketDataCoverageGapV1",
    "OnlyMarketDataCoverageProjectionV1",
    "OnlyMarketDataInstrumentProjectionV1",
    "OnlyMarketDataInstrumentListProjectionV1",
    "OnlyMarketDataProductError",
    "OnlyMarketDataProductService",
    "OnlyMarketDataSourceProjectionV1",
    "OnlyMarketDataSourceReferenceV1",
    "OnlyMarketDataSourceSelectionV1",
    "OnlyIntegrationListing",
]
