"""Market Data Product boundary: exact source selection, DB-first query, acquisition."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

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
    OnlyMarketDataSourceSelectionV1,
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
    OnlyInMemoryMarketDataCatalog,
    OnlyInMemoryMarketFactStore,
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


class _State:
    def __init__(self, integration: OnlyIntegration, revision: OnlyIntegrationRevision) -> None:
        self.integration = integration
        self.revision = revision

    def load_integration(self, integration_id: OnlyIntegrationId) -> OnlyIntegration:
        if integration_id != self.integration.integration_id:
            raise LookupError("missing integration")
        return self.integration

    def load_revision(self, revision_fingerprint: str) -> OnlyIntegrationRevision:
        if revision_fingerprint != self.revision.revision_fingerprint:
            raise LookupError("missing revision")
        return self.revision

    def load_revision_secret_bindings(self, revision_fingerprint: str) -> tuple[OnlyIntegrationSecretBinding, ...]:
        if revision_fingerprint != self.revision.revision_fingerprint:
            raise LookupError("missing revision")
        return ()


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
    def __init__(self) -> None:
        self.bar_fetches = 0
        self.reference_lookups = 0


class _FakeFactory:
    def __init__(self, descriptor: OnlyIntegrationTypeDescriptorV1, provider: _ProviderCalls) -> None:
        self.integration_type = descriptor
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
        return _FakeSource(request, provider=self._provider)

    def market_identity(self, plugin_config: object) -> OnlyDataSourceMarketIdentityV1:
        del plugin_config
        return OnlyDataSourceMarketIdentityV1("TEST", "SPOT")

    def list_instruments(
        self, request: OnlyDataSourceInstrumentCatalogRequestV1
    ) -> tuple[OnlyDataSourceInstrumentV1, ...]:
        self._provider.reference_lookups += 1
        instrument = _instrument()
        if request.query.strip() and request.query.strip().upper() not in str(instrument.raw_symbol):
            return ()
        if request.instrument_ids and str(instrument.instrument_id) not in request.instrument_ids:
            return ()
        return (OnlyDataSourceInstrumentV1(instrument, "BTCUSDT", "TEST", "SPOT", ("BAR_1M_EXTERNAL_RAW",)),)


def _service(
    tmp_path: Path,
) -> tuple[OnlyMarketDataProductService, _ProviderCalls, OnlyInMemoryMarketDataCatalog, str]:
    descriptor = _descriptor()
    revision = OnlyIntegrationRevision.from_resolved(
        integration_id=INTEGRATION_ID,
        revision_sequence=1,
        type_id=descriptor.type_id.value,
        type_descriptor_fingerprint=descriptor.fingerprint,
        type_descriptor_document=descriptor.to_dict(include_fingerprint=False),
        configuration_document={},
        probe_configuration_document=None,
        secret_bindings=(),
        created_at=NOW,
    )
    integration = OnlyIntegration(
        INTEGRATION_ID,
        descriptor.type_id.value,
        "Test",
        OnlyIntegrationLifecycleState.ACTIVE,
        revision.revision_fingerprint,
        NOW,
        NOW,
    )
    resolver = OnlyIntegrationRuntimeResolver(
        _State(integration, revision),
        _Credentials(),
        _Catalog(descriptor),
    )
    provider = _ProviderCalls()
    factory = _FakeFactory(descriptor, provider)
    registry = OnlyDataSourceFactoryRegistry()
    registry.register(factory)
    catalog = OnlyInMemoryMarketDataCatalog()
    service = OnlyMarketDataProductService(
        resolver=resolver,
        data_sources=registry,
        catalog=catalog,
        fact_store=OnlyInMemoryMarketFactStore(),
        wal_root=tmp_path / "market-data",
        clock=OnlyBacktestClock(BASE + timedelta(hours=1)),
        logger=__import__("logging").getLogger(__name__),
    )
    return service, provider, catalog, revision.revision_fingerprint


def _selection(revision_fingerprint: str, **overrides: str) -> OnlyMarketDataSourceSelectionV1:
    values = {
        "integration_id": str(INTEGRATION_ID),
        "integration_revision_fingerprint": revision_fingerprint,
        "type_id": TYPE_ID,
        "source_id": TYPE_ID,
    }
    values.update(overrides)
    return OnlyMarketDataSourceSelectionV1(**values)  # type: ignore[arg-type]


def _range(minutes: int = 2) -> tuple[int, int]:
    start = int(BASE.timestamp()) * 1_000_000_000
    return start, start + minutes * MINUTE_NS


def test_instrument_query_uses_provider_reference_and_rejects_unknown_symbol(tmp_path: Path) -> None:
    service, provider, _catalog, fingerprint = _service(tmp_path)
    selection = _selection(fingerprint)

    instruments = service.list_instruments(selection, query="btc")
    assert [item.instrument_id for item in instruments] == [str(INSTRUMENT)]
    assert instruments[0].market_data_capabilities == ("BAR_1M_EXTERNAL_RAW",)

    unknown = "ETHUSDT.TEST"
    with pytest.raises(OnlyMarketDataProductError) as error:
        service.list_instruments(selection, instrument_ids=(unknown,))
    assert error.value.code == "MARKET_DATA_INSTRUMENT_NOT_FOUND"
    assert provider.reference_lookups == 2


def test_source_selection_requires_the_exact_integration_revision(tmp_path: Path) -> None:
    service, _provider, _catalog, fingerprint = _service(tmp_path)
    stale = _selection("a" * 64)
    with pytest.raises(OnlyMarketDataProductError) as error:
        service.list_instruments(stale, query="BTC")
    assert error.value.code == "MARKET_DATA_SOURCE_SELECTION_UNRESOLVED"

    mismatched = _selection(fingerprint, type_id="other.market_data")
    with pytest.raises(OnlyMarketDataProductError) as error:
        service.list_instruments(mismatched, query="BTC")
    assert error.value.code == "MARKET_DATA_SOURCE_SELECTION_MISMATCH"


def test_bars_query_is_db_first_and_never_acquires(tmp_path: Path) -> None:
    service, provider, _catalog, fingerprint = _service(tmp_path)
    selection = _selection(fingerprint)
    start_ns, end_ns = _range()

    projection = service.query_bars(selection, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    assert projection.coverage.status == "INCOMPLETE"
    assert projection.bars == ()
    assert projection.revision_id is None
    assert tuple((item.start_ns, item.end_ns) for item in projection.coverage.planned_acquisition_ranges) == (
        (start_ns, end_ns),
    )
    assert provider.bar_fetches == 0


def test_acquisition_seals_exact_revision_and_later_query_uses_database(tmp_path: Path) -> None:
    service, provider, catalog, fingerprint = _service(tmp_path)
    selection = _selection(fingerprint)
    start_ns, end_ns = _range()

    acquisition = service.acquire_bars(selection, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    assert acquisition.status == "COMPLETE"
    assert acquisition.coverage.status == "COMPLETE"
    assert acquisition.revision_id is not None
    assert acquisition.seal_id is not None
    assert provider.bar_fetches == 1
    assert acquisition.integration_binding_fingerprint is not None

    intent = catalog.load_acquisition_intent(acquisition.acquisition_id)
    assert intent is not None
    assert intent.integration_binding_fingerprint == acquisition.integration_binding_fingerprint
    attempt = catalog.latest_acquisition_attempt(acquisition.acquisition_id)
    assert attempt is not None and attempt.outcome.value == "COMPLETE"

    fetches_after_acquisition = provider.bar_fetches
    reloaded = service.query_bars(selection, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    assert reloaded.coverage.status == "COMPLETE"
    assert len(reloaded.bars) == 2
    assert reloaded.revision_id == acquisition.revision_id
    assert all(item.closed for item in reloaded.bars)
    assert provider.bar_fetches == fetches_after_acquisition

    repeated = service.acquire_bars(selection, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    assert repeated.status == "COMPLETE"
    assert repeated.acquisition_id == acquisition.acquisition_id
    assert provider.bar_fetches == fetches_after_acquisition


def test_acquisition_status_projects_pending_and_unknown_acquisitions(tmp_path: Path) -> None:
    service, _provider, _catalog, fingerprint = _service(tmp_path)
    selection = _selection(fingerprint)
    with pytest.raises(OnlyMarketDataProductError) as error:
        service.acquisition_status(selection, "acquisition:" + "b" * 64)
    assert error.value.code == "MARKET_DATA_ACQUISITION_NOT_FOUND"


def test_incomplete_gap_projection_uses_contiguous_acquisition_ranges(tmp_path: Path) -> None:
    service, provider, catalog, fingerprint = _service(tmp_path)
    selection = _selection(fingerprint)
    start_ns, end_ns = _range(minutes=4)
    first = service.acquire_bars(
        selection,
        instrument_id=str(INSTRUMENT),
        start_ns=start_ns,
        end_ns=start_ns + 2 * MINUTE_NS,
    )
    assert first.status == "COMPLETE"

    wider = service.query_bars(selection, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns)
    assert wider.coverage.status == "INCOMPLETE"
    assert tuple((item.start_ns, item.end_ns) for item in wider.coverage.planned_acquisition_ranges) == (
        (start_ns + 2 * MINUTE_NS, end_ns),
    )
    assert provider.bar_fetches == 1
    assert catalog is not None


def test_unsupported_bar_specification_and_unbounded_window_are_rejected(tmp_path: Path) -> None:
    service, provider, _catalog, fingerprint = _service(tmp_path)
    selection = _selection(fingerprint)
    start_ns, end_ns = _range()

    with pytest.raises(OnlyMarketDataProductError) as error:
        service.query_bars(
            selection, instrument_id=str(INSTRUMENT), start_ns=start_ns, end_ns=end_ns, bar_specification="1h"
        )
    assert error.value.code == "MARKET_DATA_BAR_SPECIFICATION_UNSUPPORTED"

    with pytest.raises(OnlyMarketDataProductError) as error:
        service.acquire_bars(
            selection,
            instrument_id=str(INSTRUMENT),
            start_ns=start_ns - 8 * 86_400 * 1_000_000_000,
            end_ns=end_ns,
        )
    assert error.value.code == "MARKET_DATA_ACQUISITION_RANGE_TOO_LARGE"
    assert provider.bar_fetches == 0


def test_instrument_must_belong_to_the_selected_source_venue(tmp_path: Path) -> None:
    service, _provider, _catalog, fingerprint = _service(tmp_path)
    selection = _selection(fingerprint)
    start_ns, end_ns = _range()
    with pytest.raises(OnlyMarketDataProductError) as error:
        service.query_bars(selection, instrument_id="BTCUSDT.BINANCE", start_ns=start_ns, end_ns=end_ns)
    assert error.value.code == "MARKET_DATA_INSTRUMENT_SOURCE_MISMATCH"
