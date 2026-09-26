"""Market Data Product boundary: exact source selection, DB-first query, acquisition."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
    OnlyMarketDataProductError,
    OnlyMarketDataProductService,
    OnlyMarketDataSourceReferenceV1,
)
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.enums import OnlyDataSequenceSemantics, OnlyMarketDataType
from onlyalpha.data.evidence import OnlyRawProviderObservation
from onlyalpha.data.factory import OnlyDataSourceFactoryRegistry
from onlyalpha.data.identifiers import OnlyDataSequence
from onlyalpha.data.identity import only_bar_update_id
from onlyalpha.data.models import (
    OnlyBarUpdate,
    OnlyHistoricalDataStream,
    OnlyMarketDataInboundUpdate,
)
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
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.instrument import OnlyInstrument
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp
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
        fault = self._provider.fetch_fault()
        if fault is not None:
            raise fault
        start_ns = OnlyTimestamp.from_datetime(request.data_range.start_time).unix_nanos  # type: ignore[attr-defined]
        end_ns = OnlyTimestamp.from_datetime(request.data_range.end_time).unix_nanos  # type: ignore[attr-defined]
        updates = tuple(self._update(item) for item in range(start_ns, end_ns, MINUTE_NS))
        self._record(start_ns, end_ns, updates)
        return OnlyHistoricalDataStream(updates, 1024)

    def load_trades(self, request: object) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        raise AssertionError("market-data acquisition must not request trades")

    def load_quotes(self, request: object) -> OnlyHistoricalDataStream[OnlyMarketDataInboundUpdate]:
        raise AssertionError("market-data acquisition must not request quotes")

    def _update(self, start_ns: int) -> OnlyMarketDataInboundUpdate:
        request = self._request
        bar_type = _bar_type()
        start = OnlyTimestamp.from_unix_nanos(start_ns).to_datetime()
        end = OnlyTimestamp.from_unix_nanos(start_ns + MINUTE_NS).to_datetime()
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
            bar_specification="1h",
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
    # ... while the canonical market scope (and therefore market fact identity) converges.
    assert intent_a.requested_scope == intent_b.requested_scope
    converged = harness.service.query_bars(
        _reference(revision_a), instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns
    )
    assert converged.coverage.status == "COMPLETE"
    assert converged.revision_id == completed.revision_id


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
