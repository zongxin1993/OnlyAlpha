"""Market Data Product boundary: exact source selection, DB-first query, acquisition."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

import pytest

from onlyalpha.application.integration_configuration import (
    OnlyIntegration,
    OnlyIntegrationId,
    OnlyIntegrationLifecycleState,
    OnlyIntegrationRevision,
    OnlyIntegrationSecretBinding,
)
from onlyalpha.application.integration_runtime import OnlyIntegrationRuntimeResolver
from onlyalpha.application.market_data_product import (
    BASE_BAR_SPECIFICATION,
    OnlyMarketDataProductError,
    OnlyMarketDataProductService,
    OnlyMarketDataSourceReferenceV1,
)
from onlyalpha.application.market_data_stream import OnlyMarketDataStreamProductService
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.enums import (
    OnlyDataSequenceSemantics,
    OnlyMarketDataConnectionState,
    OnlyMarketDataRequestStatus,
    OnlyMarketDataType,
)
from onlyalpha.data.evidence import OnlyRawProviderObservation
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.data.identifiers import OnlyDataSequence, OnlyMarketDataGatewayId
from onlyalpha.data.identity import only_bar_update_id
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyHistoricalDataStream,
    OnlyMarketDataConnectionSnapshot,
    OnlyMarketDataInboundUpdate,
    OnlyMarketDataSubscriptionResult,
)
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyAssetClass,
    OnlyBarAggregation,
    OnlyCurrencyType,
    OnlyInstrumentType,
    OnlyMarketType,
    OnlyPriceType,
    OnlySessionType,
)
from onlyalpha.domain.identifiers import OnlyCalendarId, OnlyInstrumentId, OnlyRuntimeId, OnlyVenueId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone
from onlyalpha.domain.value import OnlyCurrency, OnlyPrice, OnlyQuantity
from onlyalpha.market_data.durable import (
    OnlyCanonicalMarketFactRecord,
    OnlyCoverageManifest,
    OnlyIngestSegment,
    OnlyInMemoryMarketDataCatalog,
    OnlyInMemoryMarketFactStore,
    OnlyMarketDataAcquisitionAttempt,
    OnlyMarketDataAcquisitionIntent,
    OnlyMarketDataRevision,
    OnlyMarketDataScope,
    OnlyMarketDataSeal,
)
from onlyalpha.market_data.resolution import OnlyBarCapability, OnlyBarIntervalKind
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities
from onlyalpha.plugin.data_source import (
    OnlyDataSourceInstrumentCatalogRequestV1,
    OnlyDataSourceInstrumentV1,
    OnlyDataSourceMarketIdentityV1,
)
from onlyalpha.plugin.descriptor import OnlyPluginDescriptor, OnlyPluginType
from onlyalpha.plugin.integration import (
    OnlyIntegrationCategory,
    OnlyIntegrationConfigurationContractV1,
    OnlyIntegrationTypeDescriptorV1,
    OnlyIntegrationTypeId,
)
from onlyalpha.plugin.version import OnlyPluginApiVersion

NOW = datetime(2026, 1, 1, tzinfo=UTC)
BASE = datetime(2026, 1, 1, tzinfo=UTC)
INTEGRATION_ID = OnlyIntegrationId("b52eb762-34cf-47d4-8cca-56ef93f0d2ac")
CREDENTIAL_ID = "ba13b6b1-af9a-450f-833d-48f5002297dc"
TYPE_ID = "test.market_data"
INSTRUMENT = OnlyInstrumentId.parse("BTCUSDT.TEST")
MINUTE_NS = 60_000_000_000


def _instrument() -> OnlyInstrument:
    quote = OnlyCurrency("USDT", 2, OnlyCurrencyType.CRYPTO)
    return OnlyInstrument(
        instrument_id=INSTRUMENT,
        raw_symbol="BTCUSDT",
        asset_class=OnlyAssetClass.CRYPTOCURRENCY,
        instrument_type=OnlyInstrumentType.CRYPTO_SPOT,
        market_type=OnlyMarketType.CASH,
        quote_currency=quote,
        settlement_currency=quote,
        base_currency=OnlyCurrency("BTC", 5, OnlyCurrencyType.CRYPTO),
        price_precision=2,
        quantity_precision=5,
        tick_size=OnlyPrice(Decimal("0.01"), 2),
        step_size=OnlyQuantity(Decimal("0.00001"), 5),
    )


def _bar_type() -> OnlyBarType:
    return OnlyBarType(
        INSTRUMENT,
        OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )


def _descriptor() -> OnlyIntegrationTypeDescriptorV1:
    return OnlyIntegrationTypeDescriptorV1(
        type_id=OnlyIntegrationTypeId(TYPE_ID),
        category=OnlyIntegrationCategory.DATA_SOURCE,
        display_name="Test market data",
        description="Deterministic local provider.",
        provider_id="test",
        implementation_id="test-data",
        implementation_version="1.0.0",
        public_api_version="1.1",
        capabilities=("HISTORICAL_BARS",),
        configuration_contract=OnlyIntegrationConfigurationContractV1(fields=()),
    )


@dataclass
class _Faults:
    """Deterministic fault injection for one Product composition."""

    provider_open: Exception | None = None
    reference_lookup: Exception | None = None
    fetch_faults: tuple[Exception | None, ...] = ()
    intent_admission: Exception | None = None
    attempt_allocation: Exception | None = None
    attempt_write: Exception | None = None
    sealed_lookup: Exception | None = None
    corrupt_seal: bool = False
    fact_read: Exception | None = None


class _FaultyCatalog(OnlyInMemoryMarketDataCatalog):
    def __init__(self, faults: _Faults) -> None:
        super().__init__()
        self._faults = faults
        self.mutations = 0

    def commit_durable_segments(self, segments: tuple[OnlyIngestSegment, ...]) -> None:
        self.mutations += 1
        super().commit_durable_segments(segments)

    def commit_coverage_manifest(self, manifest: OnlyCoverageManifest) -> None:
        self.mutations += 1
        super().commit_coverage_manifest(manifest)

    def commit_revision(
        self,
        segments: tuple[OnlyIngestSegment, ...],
        manifest: OnlyCoverageManifest,
        revision: OnlyMarketDataRevision,
        seal: OnlyMarketDataSeal,
    ) -> None:
        self.mutations += 1
        super().commit_revision(segments, manifest, revision, seal)

    def admit_acquisition_intent(self, intent: OnlyMarketDataAcquisitionIntent) -> OnlyMarketDataAcquisitionIntent:
        self.mutations += 1
        if self._faults.intent_admission is not None:
            raise self._faults.intent_admission
        return super().admit_acquisition_intent(intent)

    def start_acquisition_attempt(
        self, acquisition_id: str, *, started_at: datetime
    ) -> OnlyMarketDataAcquisitionAttempt:
        if self._faults.attempt_allocation is not None:
            raise self._faults.attempt_allocation
        return super().start_acquisition_attempt(acquisition_id, started_at=started_at)

    def record_acquisition_attempt(self, attempt: OnlyMarketDataAcquisitionAttempt) -> None:
        self.mutations += 1
        if self._faults.attempt_write is not None:
            raise self._faults.attempt_write
        super().record_acquisition_attempt(attempt)

    def latest_sealed_revision(self, scope: OnlyMarketDataScope) -> OnlyMarketDataRevision:
        if self._faults.sealed_lookup is not None:
            raise self._faults.sealed_lookup
        return super().latest_sealed_revision(scope)

    def load_sealed_revision(self, revision_id: str) -> tuple[OnlyMarketDataRevision, OnlyMarketDataSeal]:
        revision, seal = super().load_sealed_revision(revision_id)
        if self._faults.corrupt_seal:
            return revision, OnlyMarketDataSeal(seal.seal_id, seal.revision_id, "f" * 64, seal.checks, seal.sealed_at)
        return revision, seal


class _FaultyFactStore(OnlyInMemoryMarketFactStore):
    def __init__(self, faults: _Faults) -> None:
        super().__init__()
        self._faults = faults

    def read_segment_facts(
        self, segments: tuple[OnlyIngestSegment, ...], scope: OnlyMarketDataScope
    ) -> tuple[OnlyCanonicalMarketFactRecord, ...]:
        if self._faults.fact_read is not None:
            raise self._faults.fact_read
        return super().read_segment_facts(segments, scope)


class _Catalog:
    def __init__(self, descriptor: OnlyIntegrationTypeDescriptorV1) -> None:
        self.descriptor = descriptor

    def require(self, type_id: str) -> OnlyIntegrationTypeDescriptorV1:
        if self.descriptor.type_id.value != type_id:
            raise LookupError("implementation unavailable")
        return self.descriptor


class _Credentials:
    def read_secret(self, credential_id: str, credential_generation: int) -> str:
        del credential_id, credential_generation
        raise LookupError("no secrets")


class _FakeSource:
    def __init__(self, request: object, *, provider: _ProviderCalls) -> None:
        self._request = request
        self._provider = provider
        self.state = "CREATED"

    @property
    def source_id(self) -> object:
        return self._request.source_id  # type: ignore[attr-defined]

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset()

    def initialize(self) -> None:
        self.state = "INITIALIZED"

    def connect(self) -> object:
        self.state = "CONNECTED"
        return None

    def authenticate(self) -> object:
        return None

    def start(self) -> None:
        self.state = "RUNNING"

    def stop(self) -> None:
        self.state = "STOPPED"

    def load_bars(self, request: object) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        self._provider.bar_fetches += 1
        bar_type = next(iter(request.bar_types))  # type: ignore[attr-defined]
        self._provider.bar_steps.append(bar_type.specification.step)
        fault = self._provider.fetch_fault()
        if fault is not None:
            raise fault
        start_ns = OnlyTimestamp.from_datetime(request.data_range.start_time).unix_nanos  # type: ignore[attr-defined]
        end_ns = OnlyTimestamp.from_datetime(request.data_range.end_time).unix_nanos  # type: ignore[attr-defined]
        duration_ns = bar_type.specification.step * MINUTE_NS
        updates = tuple(self._update(item, bar_type) for item in range(start_ns, end_ns, duration_ns))
        self._record(start_ns, end_ns, updates)
        return OnlyHistoricalDataStream(updates, 1024)

    def load_trades(self, request: object) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        raise AssertionError("market-data acquisition must not request trades")

    def load_quotes(self, request: object) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        raise AssertionError("market-data acquisition must not request quotes")

    def _update(self, start_ns: int, bar_type: OnlyBarType) -> OnlyMarketDataInboundUpdate:
        request = self._request
        start = OnlyTimestamp.from_unix_nanos(start_ns).to_datetime()
        end = OnlyTimestamp.from_unix_nanos(start_ns + bar_type.specification.step * MINUTE_NS).to_datetime()
        bar = OnlyBar(
            bar_type=bar_type,
            open=OnlyPrice(Decimal("100.00"), 2),
            high=OnlyPrice(Decimal("102.00"), 2),
            low=OnlyPrice(Decimal("99.00"), 2),
            close=OnlyPrice(Decimal("101.00"), 2),
            volume=OnlyQuantity(Decimal("2.00000"), 5),
            quote_volume=None,
            turnover=None,
            trade_count=3,
            open_interest=None,
            bar_start=start,
            bar_end=end,
            ts_event=end,
            ts_init=end,
            is_closed=True,
            revision=0,
            adjustment_type=OnlyAdjustmentType.RAW,
            trading_day=start.date(),
            session_type=OnlySessionType.CONTINUOUS,
        )
        return OnlyMarketDataInboundUpdate(
            only_bar_update_id(request.source_id, INSTRUMENT, bar_type, start, request.data_version),  # type: ignore[attr-defined]
            OnlyRuntimeId("market-data-runtime"),
            request.source_id,  # type: ignore[attr-defined]
            OnlyDataSequence(start_ns // MINUTE_NS),
            request.data_version,  # type: ignore[attr-defined]
            INSTRUMENT,
            OnlyMarketDataType.BAR,
            OnlyBarUpdate(bar),
            OnlyTimestamp.from_datetime(end),
            OnlyTimestamp.from_datetime(end),
            sequence_semantics=OnlyDataSequenceSemantics.CONTIGUOUS,
        )

    def _record(self, start_ns: int, end_ns: int, updates: tuple[OnlyMarketDataInboundUpdate, ...]) -> None:
        request = self._request
        observation = OnlyRawProviderObservation(
            source_id=str(request.source_id),  # type: ignore[attr-defined]
            capture_session_id=f"test:{request.runtime_id}:rest",  # type: ignore[attr-defined]
            provider="TEST",
            venue="TEST",
            market="SPOT",
            stream="/klines",
            provider_event_type="klines",
            ts_receive_ns=request.clock.timestamp_ns(),  # type: ignore[attr-defined]
            payload=json.dumps({"start_ns": start_ns, "end_ns": end_ns}).encode(),
            provenance="REST_BACKFILL",
        )
        request.provider_evidence_sink(observation, updates)  # type: ignore[attr-defined]


class _ProviderCalls:
    def __init__(self, faults: _Faults | None = None) -> None:
        self.bar_fetches = 0
        self.bar_steps: list[int] = []
        self.reference_lookups = 0
        self._faults = faults or _Faults()

    def fetch_fault(self) -> Exception | None:
        """One deterministic outcome per provider fetch occurrence."""

        index = self.bar_fetches - 1
        return self._faults.fetch_faults[index] if index < len(self._faults.fetch_faults) else None


class _FakeFactory:
    def __init__(
        self,
        descriptor: OnlyIntegrationTypeDescriptorV1,
        provider: _ProviderCalls,
        faults: _Faults,
    ) -> None:
        self.integration_type = descriptor
        self._faults = faults
        self.descriptor = OnlyPluginDescriptor(
            plugin_id="test-data",
            plugin_type=OnlyPluginType.DATA_SOURCE,
            plugin_version="1.0.0",
            api_version=OnlyPluginApiVersion(major=1, minor=1),
            display_name="Test Data",
            provider="TEST",
            capabilities=OnlyDataSourceCapabilities(historical_bars=True),
        )
        self._provider = provider
        self.native_minutes = (1,)

    def parse_config(self, extensions: Mapping[str, object]) -> object:
        return dict(extensions)

    def parse_runtime_integration_config(
        self, public_configuration: Mapping[str, object], resolved_secrets: Mapping[str, str]
    ) -> object:
        del resolved_secrets
        return dict(public_configuration)

    def validate_request(self, request: object) -> Sequence[object]:
        del request
        return ()

    def create(self, request: object) -> _FakeSource:
        if self._faults.provider_open is not None:
            raise self._faults.provider_open
        return _FakeSource(request, provider=self._provider)

    def market_identity(self, plugin_config: object) -> OnlyDataSourceMarketIdentityV1:
        environment = str(plugin_config.get("environment", "LIVE")) if isinstance(plugin_config, Mapping) else "LIVE"
        return OnlyDataSourceMarketIdentityV1("TEST", "SPOT", environment, f"test.spot.{environment.lower()}")

    def time_bar_calendar(self, plugin_config: object) -> OnlyTradingCalendar:
        del plugin_config
        return OnlyTradingCalendar(
            OnlyCalendarId("TEST-24X7"),
            OnlyVenueId("TEST"),
            OnlyTimeZone("UTC"),
            (OnlyTradingSession("continuous", time(0), time(0), OnlySessionType.CONTINUOUS),),
            weekend_days=(),
        )

    def bar_capabilities(self, plugin_config: object, instrument_id: OnlyInstrumentId) -> tuple[OnlyBarCapability, ...]:
        del instrument_id
        alignment_id = only_canonical_fingerprint(self.time_bar_calendar(plugin_config).to_dict())
        return tuple(
            OnlyBarCapability(
                OnlyBarSpecification(minutes, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
                OnlyBarIntervalKind.FIXED_DURATION,
                alignment_id,
                True,
                True,
                grid_origin_ns=0,
            )
            for minutes in self.native_minutes
        )

    def list_instruments(
        self, request: OnlyDataSourceInstrumentCatalogRequestV1
    ) -> tuple[OnlyDataSourceInstrumentV1, ...]:
        if self._faults.reference_lookup is not None:
            raise self._faults.reference_lookup
        self._provider.reference_lookups += 1
        instrument = _instrument()
        if request.query.strip() and request.query.strip().upper() not in str(instrument.raw_symbol):
            return ()
        if request.instrument_ids and str(instrument.instrument_id) not in request.instrument_ids:
            return ()
        return (OnlyDataSourceInstrumentV1(instrument, "BTCUSDT", "TEST", "SPOT", ("BAR_1M_EXTERNAL_RAW",)),)


class _State:
    def __init__(self, integration: OnlyIntegration, revisions: tuple[OnlyIntegrationRevision, ...]) -> None:
        self.integration = integration
        self.revisions = {item.revision_fingerprint: item for item in revisions}
        self.integrations: list[OnlyIntegration] = [integration]
        self.loading_unavailable = False

    def load_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration:
        if self.loading_unavailable:
            raise RuntimeError("postgres down")
        if integration_id != self.integration.integration_id:
            raise LookupError("missing integration")
        return self.integration

    def load_revision(self, revision_fingerprint: str) -> OnlyIntegrationRevision:
        if revision_fingerprint not in self.revisions:
            raise LookupError("missing revision")
        return self.revisions[revision_fingerprint]

    def load_revision_secret_bindings(self, revision_fingerprint: str) -> tuple[OnlyIntegrationSecretBinding, ...]:
        if revision_fingerprint not in self.revisions:
            raise LookupError("missing revision")
        return ()

    def list_integrations(
        self,
        *,
        type_id: str | None = None,
        lifecycle_state: OnlyIntegrationLifecycleState | None = None,
    ) -> tuple[OnlyIntegration, ...]:
        return tuple(
            item
            for item in self.integrations
            if (type_id is None or item.type_id == type_id)
            and (lifecycle_state is None or item.lifecycle_state is lifecycle_state)
        )


class _Harness(NamedTuple):
    service: OnlyMarketDataProductService
    provider: _ProviderCalls
    catalog: OnlyInMemoryMarketDataCatalog
    factory: _FakeFactory
    state: _State
    revision_fingerprint: str
    faults: _Faults
    wal_root: Path


def _revision(sequence: int, configuration: Mapping[str, object]) -> OnlyIntegrationRevision:
    descriptor = _descriptor()
    return OnlyIntegrationRevision.from_resolved(
        integration_id=INTEGRATION_ID,
        revision_sequence=sequence,
        type_id=descriptor.type_id.value,
        type_descriptor_fingerprint=descriptor.fingerprint,
        type_descriptor_document=descriptor.to_dict(include_fingerprint=False),
        configuration_document=dict(configuration),
        probe_configuration_document=None,
        secret_bindings=(),
        created_at=NOW,
    )


def _service(
    tmp_path: Path,
    *,
    configurations: tuple[Mapping[str, object], ...] = ({},),
    faults: _Faults | None = None,
    native_minutes: tuple[int, ...] = (1,),
) -> _Harness:
    descriptor = _descriptor()
    faults = faults or _Faults()
    revisions = tuple(_revision(sequence, item) for sequence, item in enumerate(configurations, start=1))
    integration = OnlyIntegration(
        INTEGRATION_ID,
        descriptor.type_id.value,
        "Test",
        OnlyIntegrationLifecycleState.ACTIVE,
        revisions[-1].revision_fingerprint,
        NOW,
        NOW,
    )
    state = _State(integration, revisions)
    resolver = OnlyIntegrationRuntimeResolver(
        state,
        _Credentials(),
        _Catalog(descriptor),
    )
    provider = _ProviderCalls(faults)
    factory = _FakeFactory(descriptor, provider, faults)
    factory.native_minutes = native_minutes
    registry = OnlyDataSourceFactoryRegistry()
    registry.register(factory)
    catalog = _FaultyCatalog(faults)
    wal_root = tmp_path / "market-data"
    return _Harness(
        OnlyMarketDataProductService(
            resolver=resolver,
            integrations=state,
            data_sources=registry,
            catalog=catalog,
            fact_store=_FaultyFactStore(faults),
            wal_root=wal_root,
            clock=OnlyBacktestClock(BASE + timedelta(hours=1)),
            logger=__import__("logging").getLogger(__name__),
        ),
        provider,
        catalog,
        factory,
        state,
        revisions[-1].revision_fingerprint,
        faults,
        wal_root,
    )


def _reference(revision_fingerprint: str, expected_type_id: str | None = TYPE_ID) -> OnlyMarketDataSourceReferenceV1:
    return OnlyMarketDataSourceReferenceV1(str(INTEGRATION_ID), revision_fingerprint, expected_type_id)


def _range(minutes: int = 2) -> tuple[int, int]:
    start = int(BASE.timestamp()) * 1_000_000_000
    return start, start + minutes * MINUTE_NS


def test_instrument_query_uses_provider_reference_and_rejects_unknown_symbol(tmp_path: Path) -> None:
    harness = _service(tmp_path)

    projected = harness.service.list_instruments(_reference(harness.revision_fingerprint), query="btc")
    assert [item.instrument_id for item in projected.instruments] == [str(INSTRUMENT)]
    assert projected.instruments[0].market_data_capabilities == ("BAR_1M_EXTERNAL_RAW",)
    assert projected.source_selection.source_id == "test.spot.live"

    with pytest.raises(OnlyMarketDataProductError) as error:
        harness.service.list_instruments(_reference(harness.revision_fingerprint), instrument_ids=("ETHUSDT.TEST",))
    assert error.value.code == "MARKET_DATA_INSTRUMENT_NOT_FOUND"
    assert harness.provider.reference_lookups == 2


def test_source_selection_requires_the_exact_integration_revision(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    with pytest.raises(OnlyMarketDataProductError) as error:
        harness.service.list_instruments(_reference("a" * 64), query="BTC")
    assert error.value.code == "MARKET_DATA_SOURCE_SELECTION_UNRESOLVED"

    with pytest.raises(OnlyMarketDataProductError) as error:
        harness.service.list_instruments(_reference(harness.revision_fingerprint, "other.market_data"), query="BTC")
    assert error.value.code == "MARKET_DATA_SOURCE_SELECTION_MISMATCH"


def test_live_and_testnet_never_share_a_market_data_scope(tmp_path: Path) -> None:
    harness = _service(
        tmp_path,
        configurations=(
            {"environment": "LIVE", "timeout_seconds": 10},
            {"environment": "LIVE", "timeout_seconds": 5},
            {"environment": "SPOT_TESTNET", "timeout_seconds": 10},
        ),
    )
    live, live_timeout_changed, testnet = tuple(harness.state.revisions)
    start_ns, end_ns = _range()

    def source_id(fingerprint: str) -> str:
        return harness.service.list_instruments(_reference(fingerprint), query="btc").source_selection.source_id

    # Same semantic environment keeps one canonical Market Source identity even when a
    # non-semantic runtime setting (timeout) changes between exact Revision bindings.
    assert source_id(live) == source_id(live_timeout_changed) == "test.spot.live"
    assert source_id(testnet) == "test.spot.spot_testnet"

    live_scope = harness.service.query_bars(
        _reference(live), instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns
    )
    testnet_scope = harness.service.query_bars(
        _reference(testnet), instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns
    )
    assert live_scope.source_selection.environment == "LIVE"
    assert testnet_scope.source_selection.environment == "SPOT_TESTNET"
    assert live_scope.source_selection.source_id != testnet_scope.source_selection.source_id

    sealed = harness.service.acquire_bars(
        _reference(live), instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns
    )
    assert sealed.status == "COMPLETE"
    # LIVE facts never satisfy the Testnet scope.
    assert (
        harness.service.query_bars(
            _reference(testnet), instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns
        ).coverage.status
        == "INCOMPLETE"
    )


def test_eligible_sources_come_from_product_resolution_not_web_filtering(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    assert [(item.integration_id, item.source_id) for item in harness.service.list_sources()] == [
        (str(INTEGRATION_ID), "test.spot.live")
    ]
    capability = harness.service.list_sources()[0].time_bar_capability
    assert capability.derived_supported and capability.minimum_step_minutes == 1
    assert capability.maximum_step_minutes == 240

    harness.state.integrations.extend(
        (
            OnlyIntegration(
                OnlyIntegrationId("11111111-1111-4111-8111-111111111111"),
                "other.market_data",
                "Unimplemented",
                OnlyIntegrationLifecycleState.ACTIVE,
                "b" * 64,
                NOW,
                NOW,
            ),
            OnlyIntegration(
                OnlyIntegrationId("22222222-2222-4222-8222-222222222222"),
                TYPE_ID,
                "Disabled",
                OnlyIntegrationLifecycleState.DISABLED,
                harness.revision_fingerprint,
                NOW,
                NOW,
            ),
            OnlyIntegration(
                OnlyIntegrationId("33333333-3333-4333-8333-333333333333"),
                TYPE_ID,
                "Unpublished",
                OnlyIntegrationLifecycleState.ACTIVE,
                None,
                NOW,
                NOW,
            ),
        )
    )
    assert [item.integration_id for item in harness.service.list_sources()] == [str(INTEGRATION_ID)]

    # An unavailable Integration authority is an explicit failure, never "no eligible sources".
    harness.state.loading_unavailable = True
    with pytest.raises(OnlyMarketDataProductError) as error:
        harness.service.list_sources()
    assert error.value.code == "MARKET_DATA_SOURCE_CATALOG_UNAVAILABLE"


def test_bars_query_is_db_first_and_never_acquires(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range()

    projection = harness.service.query_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    assert projection.coverage.status == "INCOMPLETE"
    assert projection.bars == ()
    assert projection.revision_id is None
    assert tuple((item.start_ns, item.end_ns) for item in projection.coverage.planned_acquisition_ranges) == (
        (start_ns, end_ns),
    )
    assert harness.provider.bar_fetches == 0


def test_acquisition_seals_exact_revision_and_later_query_uses_database(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range()

    acquisition = harness.service.acquire_bars(
        reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns
    )
    assert acquisition.status == "COMPLETE"
    assert acquisition.coverage.status == "COMPLETE"
    assert acquisition.revision_id is not None
    assert acquisition.seal_id is not None
    assert harness.provider.bar_fetches == 1
    assert harness.provider.bar_steps == [1]
    assert acquisition.integration_binding_fingerprint is not None

    intent = harness.catalog.load_acquisition_intent(acquisition.acquisition_id)
    assert intent is not None
    assert intent.integration_binding_fingerprint == acquisition.integration_binding_fingerprint
    attempt = harness.catalog.latest_acquisition_attempt(acquisition.acquisition_id)
    assert attempt is not None and attempt.outcome.value == "COMPLETE" and attempt.attempt_number == 1

    fetches_after_acquisition = harness.provider.bar_fetches
    reloaded = harness.service.query_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    assert reloaded.coverage.status == "COMPLETE"
    assert len(reloaded.bars) == 2
    assert reloaded.revision_id == acquisition.revision_id
    assert all(item.closed for item in reloaded.bars)
    assert harness.provider.bar_fetches == fetches_after_acquisition

    repeated = harness.service.acquire_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    assert repeated.status == "COMPLETE"
    assert repeated.acquisition_id == acquisition.acquisition_id
    assert harness.provider.bar_fetches == fetches_after_acquisition


def test_complete_facts_without_exact_seal_do_not_claim_product_coverage(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range()
    harness.service.acquire_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    fetches = harness.provider.bar_fetches

    unsealed = harness.service.query_bars(
        reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=start_ns + MINUTE_NS
    )
    assert unsealed.coverage.status == "INCOMPLETE"
    assert unsealed.coverage.issues == ("SEALED_REVISION_NOT_FOUND",)
    assert unsealed.coverage.gaps == unsealed.coverage.planned_acquisition_ranges == ()
    assert unsealed.bars == () and unsealed.revision_id is None
    assert harness.provider.bar_fetches == fetches

    sealed = harness.service.acquire_bars(
        reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=start_ns + MINUTE_NS
    )
    reloaded = harness.service.query_bars(
        reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=start_ns + MINUTE_NS
    )
    assert sealed.status == reloaded.coverage.status == "COMPLETE"
    assert len(reloaded.bars) == 1 and reloaded.revision_id == sealed.revision_id
    assert harness.provider.bar_fetches == fetches


@pytest.mark.parametrize("step", (5, 7, 15, 37, 60))
def test_derived_history_uses_exact_sealed_base_revision_without_provider_fetch(tmp_path: Path, step: int) -> None:
    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range(minutes=step)
    acquired = harness.service.acquire_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    fetches = harness.provider.bar_fetches
    projected = harness.service.query_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start_ns,
        end_ns=end_ns,
        bar_specification=OnlyBarSpecification(step, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
    )
    assert projected.coverage.status == "COMPLETE"
    assert projected.aggregation_source == "INTERNAL"
    assert projected.revision_id == acquired.revision_id
    assert projected.revision_fingerprint == acquired.revision_fingerprint
    assert projected.aggregation_semantics_version == "TIME_BAR_V1"
    assert projected.calendar_fingerprint is not None
    assert [(bar.bar_start_ns, bar.bar_end_ns) for bar in projected.bars] == [(start_ns, end_ns)]
    assert Decimal(projected.bars[0].volume) == 2 * step
    assert harness.provider.bar_fetches == fetches


def test_derived_acquisition_fetches_only_its_external_base(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    start_ns, end_ns = _range(minutes=7)
    reference = _reference(harness.revision_fingerprint)
    target = OnlyBarSpecification(7, OnlyBarAggregation.TIME, OnlyPriceType.LAST)
    before = harness.service.query_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start_ns,
        end_ns=end_ns,
        bar_specification=target,
    )
    assert before.coverage.status == "INCOMPLETE"
    assert before.construction_fingerprint is None
    acquisition = harness.service.acquire_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start_ns,
        end_ns=end_ns,
        bar_specification=target,
    )
    assert acquisition.status == "COMPLETE"
    assert acquisition.bar_specification.step == 1
    assert harness.provider.bar_fetches == 1
    assert harness.provider.bar_steps == [1]
    after = harness.service.query_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start_ns,
        end_ns=end_ns,
        bar_specification=target,
    )
    assert after.coverage.status == "COMPLETE"
    assert after.base_revision_id == acquisition.revision_id
    assert after.construction_fingerprint is not None


def test_derived_query_rejects_partial_target_grid_without_acquiring(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    start_ns, end_ns = _range(minutes=7)
    with pytest.raises(OnlyMarketDataProductError, match="MARKET_DATA_DERIVED_RANGE_UNALIGNED"):
        harness.service.query_bars(
            _reference(harness.revision_fingerprint),
            instrument_id=str(INSTRUMENT),
            start_ns=start_ns + MINUTE_NS,
            end_ns=end_ns + MINUTE_NS,
            bar_specification=OnlyBarSpecification(7, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        )
    assert harness.provider.bar_fetches == 0
    assert harness.catalog.mutations == 0


def test_derived_query_rejects_partial_session_at_utc_midnight(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    start_ns, _ = _range(minutes=7)
    midnight_ns = start_ns + 86_400 * 1_000_000_000
    target = OnlyBarSpecification(7, OnlyBarAggregation.TIME, OnlyPriceType.LAST)
    with pytest.raises(OnlyMarketDataProductError, match="MARKET_DATA_DERIVED_RANGE_UNALIGNED"):
        harness.service.query_bars(
            _reference(harness.revision_fingerprint),
            instrument_id=str(INSTRUMENT),
            start_ns=start_ns,
            end_ns=midnight_ns,
            bar_specification=target,
        )
    assert harness.catalog.mutations == 0


def test_native_fifteen_minute_acquisition_and_query_use_native_authority(tmp_path: Path) -> None:
    harness = _service(tmp_path, native_minutes=(1, 15))
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range(minutes=60)
    specification = OnlyBarSpecification(15, OnlyBarAggregation.TIME, OnlyPriceType.LAST)
    cold = harness.service.query_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start_ns,
        end_ns=end_ns,
        bar_specification=specification,
    )
    assert cold.coverage.status == "INCOMPLETE" and cold.bars == ()
    assert harness.provider.bar_fetches == 0 and harness.catalog.mutations == 0
    acquired = harness.service.acquire_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start_ns,
        end_ns=end_ns,
        bar_specification=specification,
    )
    assert acquired.status == "COMPLETE"
    assert acquired.coverage.expected_bar_count == 4
    assert acquired.bar_specification == specification
    assert harness.provider.bar_steps == [15]
    fetched = harness.provider.bar_fetches
    queried = harness.service.query_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start_ns,
        end_ns=end_ns,
        bar_specification=specification,
    )
    assert queried.resolution_mode == "EXTERNAL_NATIVE"
    assert queried.coverage.status == "COMPLETE"
    assert queried.revision_id == acquired.revision_id
    assert len(queried.bars) == 4
    assert harness.provider.bar_fetches == fetched


def test_native_acquisition_failure_never_falls_back_to_sealed_base(tmp_path: Path) -> None:
    harness = _service(
        tmp_path,
        native_minutes=(1, 15),
        faults=_Faults(fetch_faults=(None, RuntimeError("native provider unavailable"))),
    )
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range(minutes=15)
    base = harness.service.acquire_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start_ns,
        end_ns=end_ns,
    )
    assert base.status == "COMPLETE"
    specification = OnlyBarSpecification(15, OnlyBarAggregation.TIME, OnlyPriceType.LAST)
    native = harness.service.acquire_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start_ns,
        end_ns=end_ns,
        bar_specification=specification,
    )
    assert native.status == "FAILED"
    queried = harness.service.query_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start_ns,
        end_ns=end_ns,
        bar_specification=specification,
    )
    assert queried.resolution_mode == "EXTERNAL_NATIVE"
    assert queried.coverage.status == "INCOMPLETE"
    assert queried.bars == ()
    assert harness.provider.bar_steps == [1, 15]


def test_native_stream_failure_does_not_subscribe_to_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _service(tmp_path, native_minutes=(1, 15))
    reference = _reference(harness.revision_fingerprint)
    attempted: list[int] = []

    class _FailingNativeSource(_FakeSource):
        def subscribe(self, request: object) -> OnlyMarketDataSubscriptionResult:
            attempted.append(next(iter(request.bar_types)).specification.step)  # type: ignore[attr-defined]
            raise RuntimeError("native websocket unavailable")

    monkeypatch.setattr(
        harness.factory, "create", lambda request: _FailingNativeSource(request, provider=harness.provider)
    )
    stream = OnlyMarketDataStreamProductService(
        historical=harness.service,
        catalog=harness.catalog,
        fact_store=harness.service._facts,
        wal_root=harness.wal_root,
        clock=OnlyBacktestClock(BASE + timedelta(hours=1)),
        logger=__import__("logging").getLogger(__name__),
    )
    with pytest.raises(OnlyMarketDataProductError, match="MARKET_DATA_STREAM_SUBSCRIBE_FAILED"):
        stream.open(
            reference,
            instrument_id=str(INSTRUMENT),
            bar_specification=OnlyBarSpecification(15, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
            resume_after_sequence=0,
        )
    assert attempted == [15]


def test_native_fifteen_minute_stream_uses_native_cursor_and_bar_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _service(tmp_path, native_minutes=(1, 15))
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range(minutes=15)
    specification = OnlyBarSpecification(15, OnlyBarAggregation.TIME, OnlyPriceType.LAST)
    acquired = harness.service.acquire_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start_ns,
        end_ns=end_ns,
        bar_specification=specification,
    )
    assert acquired.status == "COMPLETE"
    resolved = harness.service.resolve_runtime(reference)
    scope = harness.service._scope(
        resolved, str(INSTRUMENT), start_ns, end_ns, harness.service._plan(resolved, str(INSTRUMENT), specification)
    )
    segments = harness.catalog.list_durable_segments(scope)
    [fact] = harness.service._facts.read_segment_facts(segments, scope)
    update = OnlyMarketDataInboundUpdate.from_dict(fact.canonical_payload)
    requested_steps = []

    class _NativeSource(_FakeSource):
        def subscribe(self, request: object) -> OnlyMarketDataSubscriptionResult:
            requested_steps.append(next(iter(request.bar_types)).specification.step)  # type: ignore[attr-defined]
            self._request.market_data_sink(update)  # type: ignore[attr-defined]
            return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.ACCEPTED, "native")

        def unsubscribe(self, _request: object) -> None:
            return None

    monkeypatch.setattr(harness.factory, "create", lambda request: _NativeSource(request, provider=harness.provider))
    stream = OnlyMarketDataStreamProductService(
        historical=harness.service,
        catalog=harness.catalog,
        fact_store=harness.service._facts,
        wal_root=harness.wal_root,
        clock=OnlyBacktestClock(BASE + timedelta(hours=1)),
        logger=__import__("logging").getLogger(__name__),
    )
    with pytest.raises(OnlyMarketDataProductError, match="MARKET_DATA_RESUME_PLAN_MISMATCH"):
        stream.open(
            reference,
            instrument_id=str(INSTRUMENT),
            bar_specification=specification,
            resume_after_sequence=start_ns // (15 * MINUTE_NS),
            resume_plan_fingerprint=harness.service._plan(
                resolved, str(INSTRUMENT), _bar_type().specification
            ).fingerprint,
        )
    session = stream.open(
        reference,
        instrument_id=str(INSTRUMENT),
        bar_specification=specification,
        resume_after_sequence=start_ns // (15 * MINUTE_NS),
        resume_plan_fingerprint=harness.service._plan(resolved, str(INSTRUMENT), specification).fingerprint,
    )
    events = []
    while event := session.next_event(0):
        events.append(event)
    assert requested_steps == [15]
    assert events[0].payload["resolution_mode"] == "EXTERNAL_NATIVE"
    assert events[0].payload["cursor_bar_step_minutes"] == 15
    historical = harness.service.query_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start_ns,
        end_ns=end_ns,
        bar_specification=specification,
    )
    assert events[0].payload["resolution_plan_fingerprint"] == historical.resolution_plan_fingerprint
    assert any(event.event == "BAR_CLOSED" and event.payload["bar_specification"]["step"] == 15 for event in events)
    stream.close()


def test_acquisition_seals_complete_overlapping_bars_without_refetch(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range()
    first = harness.service.acquire_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    assert first.status == "COMPLETE"

    shifted_start_ns = start_ns + MINUTE_NS
    shifted = harness.service.acquire_bars(
        reference, instrument_id=str(INSTRUMENT), start_ns=shifted_start_ns, end_ns=end_ns
    )
    assert shifted.status == "COMPLETE"
    assert shifted.revision_id is not None and shifted.revision_id != first.revision_id
    assert shifted.seal_id is not None
    assert harness.provider.bar_fetches == 1
    bars = harness.service.query_bars(
        reference, instrument_id=str(INSTRUMENT), start_ns=shifted_start_ns, end_ns=end_ns
    )
    assert bars.coverage.status == "COMPLETE"
    assert len(bars.bars) == 1
    assert bars.revision_id == shifted.revision_id


def test_acquisition_status_projects_pending_and_unknown_acquisitions(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    with pytest.raises(OnlyMarketDataProductError) as error:
        harness.service.acquisition_status(_reference(harness.revision_fingerprint), "acquisition:" + "b" * 64)
    assert error.value.code == "MARKET_DATA_ACQUISITION_NOT_FOUND"


def test_started_attempt_without_terminal_outcome_remains_pending_after_interruption(tmp_path: Path) -> None:
    harness = _service(tmp_path, faults=_Faults(fetch_faults=(RuntimeError("provider down"),)))
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range()
    failed = harness.service.acquire_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    interrupted = harness.catalog.start_acquisition_attempt(failed.acquisition_id, started_at=NOW)

    assert interrupted.outcome is None and interrupted.completed_at is None
    assert harness.service.acquisition_status(reference, failed.acquisition_id).status == "PENDING"


def test_incomplete_gap_projection_uses_contiguous_acquisition_ranges(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range(minutes=4)
    first = harness.service.acquire_bars(
        reference,
        instrument_id=str(INSTRUMENT),
        start_ns=start_ns,
        end_ns=start_ns + 2 * MINUTE_NS,
    )
    assert first.status == "COMPLETE"

    wider = harness.service.query_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    assert wider.coverage.status == "INCOMPLETE"
    assert tuple((item.start_ns, item.end_ns) for item in wider.coverage.planned_acquisition_ranges) == (
        (start_ns + 2 * MINUTE_NS, end_ns),
    )
    assert harness.provider.bar_fetches == 1


def test_unsupported_bar_specification_and_unbounded_window_are_rejected(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range()

    with pytest.raises(OnlyMarketDataProductError) as error:
        harness.service.query_bars(
            reference,
            instrument_id=str(INSTRUMENT),
            start_ns=start_ns,
            end_ns=end_ns,
            bar_specification=OnlyBarSpecification(241, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        )
    assert error.value.code == "MARKET_DATA_BAR_SPECIFICATION_UNSUPPORTED"

    with pytest.raises(OnlyMarketDataProductError) as error:
        harness.service.acquire_bars(
            reference,
            instrument_id=str(INSTRUMENT),
            start_ns=start_ns - 8 * 86_400 * 1_000_000_000,
            end_ns=end_ns,
        )
    assert error.value.code == "MARKET_DATA_ACQUISITION_RANGE_TOO_LARGE"
    assert harness.provider.bar_fetches == 0


def test_instrument_must_belong_to_the_selected_source_venue(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    start_ns, end_ns = _range()
    with pytest.raises(OnlyMarketDataProductError) as error:
        harness.service.query_bars(
            _reference(harness.revision_fingerprint),
            instrument_id="BTCUSDT.BINANCE",
            start_ns=start_ns,
            end_ns=end_ns,
        )
    assert error.value.code == "MARKET_DATA_INSTRUMENT_SOURCE_MISMATCH"


def test_retry_reuses_one_intent_and_appends_every_execution_occurrence(tmp_path: Path) -> None:
    harness = _service(
        tmp_path,
        faults=_Faults(fetch_faults=(RuntimeError("provider down"), RuntimeError("provider down"), None)),
    )
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range()

    attempts = [
        harness.service.acquire_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
        for _ in range(3)
    ]
    assert [item.status for item in attempts] == ["FAILED", "FAILED", "COMPLETE"]
    assert {item.acquisition_id for item in attempts} == {attempts[0].acquisition_id}
    assert harness.provider.bar_fetches == 3

    intent = harness.catalog.load_acquisition_intent(attempts[0].acquisition_id)
    assert intent is not None
    occurrences = harness.catalog._acquisition_attempts[attempts[0].acquisition_id]
    assert [(item.attempt_number, item.outcome.value) for item in occurrences] == [
        (1, "FAILED"),
        (2, "FAILED"),
        (3, "COMPLETE"),
    ]
    assert len({item.attempt_id for item in occurrences}) == 3
    assert all(item.started_at <= item.completed_at for item in occurrences)
    assert harness.catalog.latest_acquisition_attempt(attempts[0].acquisition_id) is occurrences[-1]
    assert attempts[-1].revision_id is not None and attempts[-1].seal_id is not None


def test_a_new_integration_binding_is_a_distinct_legal_acquisition_for_the_same_scope(
    tmp_path: Path,
) -> None:
    harness = _service(
        tmp_path,
        configurations=({"environment": "LIVE", "timeout_seconds": 10}, {"environment": "LIVE", "timeout_seconds": 5}),
        faults=_Faults(fetch_faults=(RuntimeError("provider down"),)),
    )
    revision_a, revision_b = tuple(harness.state.revisions)
    start_ns, end_ns = _range()

    failed = harness.service.acquire_bars(
        _reference(revision_a), instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns
    )
    assert failed.status == "FAILED"
    completed = harness.service.acquire_bars(
        _reference(revision_b), instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns
    )
    assert completed.status == "COMPLETE"

    intent_a = harness.catalog.load_acquisition_intent(failed.acquisition_id)
    intent_b = harness.catalog.load_acquisition_intent(completed.acquisition_id)
    assert intent_a is not None and intent_b is not None
    # Distinct exact runtime bindings are distinct legal execution intents ...
    assert failed.acquisition_id != completed.acquisition_id
    assert intent_a.integration_binding_fingerprint != intent_b.integration_binding_fingerprint
    # The revision is part of Construction Identity; provider facts retain their own identity.
    assert intent_a.requested_scope != intent_b.requested_scope
    assert intent_a.requested_scope.bar_construction != intent_b.requested_scope.bar_construction
    converged = harness.service.query_bars(
        _reference(revision_a), instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns
    )
    assert converged.coverage.status == "INCOMPLETE"
    assert converged.revision_id is None


def test_the_execution_intent_is_durable_before_any_provider_side_effect(tmp_path: Path) -> None:
    wal_blocked = _service(tmp_path / "wal", faults=_Faults())
    (wal_blocked.wal_root / "test.spot.live").parent.mkdir(parents=True, exist_ok=True)
    (wal_blocked.wal_root / "test.spot.live").write_text("not a directory")
    cases: tuple[tuple[str, _Harness], ...] = (
        ("WAL initialization failure", wal_blocked),
        ("provider open failure", _service(tmp_path / "open", faults=_Faults(provider_open=RuntimeError("boom")))),
        (
            "reference lookup failure",
            _service(tmp_path / "reference", faults=_Faults(reference_lookup=RuntimeError("boom"))),
        ),
        (
            "provider fetch failure",
            _service(tmp_path / "fetch", faults=_Faults(fetch_faults=(RuntimeError("boom"),))),
        ),
    )
    for label, harness in cases:
        reference = _reference(harness.revision_fingerprint)
        start_ns, end_ns = _range()
        result = harness.service.acquire_bars(
            reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns
        )
        assert result.status == "FAILED", label
        intent = harness.catalog.load_acquisition_intent(result.acquisition_id)
        assert intent is not None, label
        occurrences = harness.catalog._acquisition_attempts[result.acquisition_id]
        assert [(item.attempt_number, item.outcome.value) for item in occurrences] == [(1, "FAILED")], label
        status = harness.service.acquisition_status(reference, result.acquisition_id)
        assert status.status == "FAILED", label


def test_product_never_claims_a_durable_failure_it_could_not_persist(tmp_path: Path) -> None:
    harness = _service(
        tmp_path,
        faults=_Faults(fetch_faults=(RuntimeError("provider down"),), attempt_write=RuntimeError("postgres down")),
    )
    start_ns, end_ns = _range()
    with pytest.raises(OnlyMarketDataProductError) as error:
        harness.service.acquire_bars(
            _reference(harness.revision_fingerprint),
            instrument_id=str(INSTRUMENT),
            start_ns=start_ns,
            end_ns=end_ns,
        )
    assert error.value.code == "MARKET_DATA_ACQUISITION_EVIDENCE_UNAVAILABLE"


def test_sealed_revision_stays_canonical_when_attempt_evidence_cannot_be_persisted(
    tmp_path: Path,
) -> None:
    harness = _service(tmp_path, faults=_Faults(attempt_write=RuntimeError("postgres down")))
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range()

    acquisition = harness.service.acquire_bars(
        reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns
    )
    assert acquisition.status == "COMPLETE"
    assert acquisition.revision_id is not None and acquisition.seal_id is not None
    assert (
        harness.service.query_bars(
            reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns
        ).coverage.status
        == "COMPLETE"
    )


def test_historical_query_fails_closed_and_never_acquires_on_database_failure(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range()

    harness.faults.sealed_lookup = RuntimeError("postgres down")
    with pytest.raises(OnlyMarketDataProductError) as query_error:
        harness.service.query_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    assert query_error.value.code == "MARKET_DATA_CATALOG_UNAVAILABLE"
    with pytest.raises(OnlyMarketDataProductError) as command_error:
        harness.service.acquire_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    assert command_error.value.code == "MARKET_DATA_CATALOG_UNAVAILABLE"
    assert harness.provider.bar_fetches == 0
    assert harness.provider.reference_lookups == 0

    # Only an explicit SEALED_REVISION_NOT_FOUND may be projected as "no data yet".
    harness.faults.sealed_lookup = KeyError("SEALED_REVISION_NOT_FOUND")
    assert (
        harness.service.query_bars(
            reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns
        ).coverage.status
        == "INCOMPLETE"
    )

    harness.faults.sealed_lookup = KeyError("SOMETHING_ELSE")
    with pytest.raises(OnlyMarketDataProductError) as corrupt_error:
        harness.service.query_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    assert corrupt_error.value.code == "MARKET_DATA_CATALOG_CORRUPT"


def test_query_fails_closed_on_corrupt_seal_and_fact_store_outage(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range()
    assert (
        harness.service.acquire_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns).status
        == "COMPLETE"
    )

    harness.faults.corrupt_seal = True
    with pytest.raises(OnlyMarketDataProductError) as corrupt_error:
        harness.service.query_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    assert corrupt_error.value.code == "MARKET_DATA_CATALOG_CORRUPT"

    harness.faults.corrupt_seal = False
    harness.faults.fact_read = RuntimeError("clickhouse down")
    with pytest.raises(OnlyMarketDataProductError) as store_error:
        harness.service.query_bars(reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    assert store_error.value.code == "MARKET_DATA_FACT_STORE_UNAVAILABLE"
    assert harness.provider.bar_fetches == 1


def test_historical_query_is_mutation_free(tmp_path: Path) -> None:
    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    start_ns, end_ns = _range()

    harness.service.list_sources()
    harness.service.list_instruments(reference, query="btc")
    assert (
        harness.service.query_bars(
            reference, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns
        ).coverage.status
        == "INCOMPLETE"
    )
    assert harness.catalog.mutations == 0
    assert harness.provider.bar_fetches == 0


def test_thirteen_minute_reconnect_repairs_gap_replays_once_then_reports_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _service(tmp_path)
    reference = _reference(harness.revision_fingerprint)
    resolved = harness.service.resolve_runtime(reference)
    base_ns = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp()) * 1_000_000_000
    target = OnlyBarSpecification(13, OnlyBarAggregation.TIME, OnlyPriceType.LAST)
    plan_fingerprint = harness.service._plan(resolved, str(INSTRUMENT), target).fingerprint
    stream = OnlyMarketDataStreamProductService(
        historical=harness.service,
        catalog=harness.catalog,
        fact_store=harness.service._facts,
        wal_root=harness.wal_root,
        clock=OnlyBacktestClock(datetime(2026, 1, 1, 1, tzinfo=UTC)),
        logger=__import__("logging").getLogger(__name__),
    )

    def acquire(start: int, end: int) -> None:
        result = harness.service.acquire_bars(
            reference,
            instrument_id=str(INSTRUMENT),
            start_ns=base_ns + start * MINUTE_NS,
            end_ns=base_ns + end * MINUTE_NS,
        )
        assert result.status == "COMPLETE"

    acquire(0, 4)
    cursor = base_ns // MINUTE_NS + 8
    with pytest.raises(OnlyMarketDataProductError, match="HISTORY_REFRESH_REQUIRED"):
        stream.open(
            reference,
            instrument_id=str(INSTRUMENT),
            bar_specification=target,
            resume_after_sequence=cursor,
            resume_plan_fingerprint=plan_fingerprint,
        )
    acquire(4, 13)
    scope = harness.service._scope(
        resolved,
        str(INSTRUMENT),
        base_ns + 9 * MINUTE_NS,
        base_ns + 13 * MINUTE_NS,
        harness.service._plan(resolved, str(INSTRUMENT), BASE_BAR_SPECIFICATION),
    )
    segments = harness.catalog.list_durable_segments(scope)
    facts = harness.service._facts.read_segment_facts(tuple(segments), scope)
    replay = tuple(OnlyMarketDataInboundUpdate.from_dict(fact.canonical_payload) for fact in facts)

    class _ReplaySource(_FakeSource):
        def subscribe(self, _request: object) -> OnlyMarketDataSubscriptionResult:
            for update in replay:
                self._request.market_data_sink(update)  # type: ignore[attr-defined]
            self._request.market_data_connection_sink(  # type: ignore[attr-defined]
                OnlyMarketDataConnectionSnapshot(
                    OnlyMarketDataGatewayId("test-replay"), OnlyMarketDataConnectionState.READY
                )
            )
            return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.ACCEPTED, "replay")

        def unsubscribe(self, _request: object) -> None:
            return None

    monkeypatch.setattr(harness.factory, "create", lambda request: _ReplaySource(request, provider=harness.provider))
    session = stream.open(
        reference,
        instrument_id=str(INSTRUMENT),
        bar_specification=target,
        resume_after_sequence=cursor,
        resume_plan_fingerprint=plan_fingerprint,
    )
    events = []
    while event := session.next_event(0):
        events.append(event)
    closed = [event for event in events if event.event == "BAR_CLOSED"]
    assert events[0].payload["resolution_plan_fingerprint"] == plan_fingerprint
    assert events[0].payload["cursor_bar_step_minutes"] == 1
    assert len(closed) == 1
    assert closed[0].payload["bar_specification"] == {"aggregation": "TIME", "step": 13, "price_type": "LAST"}
    assert closed[0].payload["bar"]["bar_start_ns"] == str(base_ns)  # type: ignore[index]
    assert closed[0].payload["bar"]["bar_end_ns"] == str(base_ns + 13 * MINUTE_NS)  # type: ignore[index]
    assert events[-1].event == "STATE" and events[-1].payload["state"] == "READY"
    assert harness.provider.bar_fetches == 2
    stream.close()
