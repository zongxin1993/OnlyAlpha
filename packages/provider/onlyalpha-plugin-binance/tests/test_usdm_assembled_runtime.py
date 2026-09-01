import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from importlib import metadata
from pathlib import Path

from onlyalpha_market_binance_usdm import OnlyBinanceUsdmMarketProductFactory
from onlyalpha_plugin_binance.usdm import OnlyBinanceUsdmReferenceCapture
from onlyalpha_plugin_binance.usdm.data_source import (
    OnlyBinanceUsdmDataSource,
    OnlyBinanceUsdmDataSourceFactory,
)
from onlyalpha_plugin_broker_virtual import OnlyVirtualBrokerConfig, OnlyVirtualBrokerGateway

from onlyalpha.account.enums import OnlyAccountEconomicCashflowType, OnlyAccountType
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.inbound import OnlyBoundedBrokerInboundQueue
from onlyalpha.cluster.bar_context import OnlyBarContext
from onlyalpha.cluster.base import OnlyCluster, OnlyClusterConfig
from onlyalpha.config.models import OnlyDataSourceCoverageConfig
from onlyalpha.config.persistence import (
    OnlyRuntimeCheckpointConfig,
    OnlyRuntimePersistenceBackend,
    OnlyRuntimePersistenceConfig,
)
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.historical.models import OnlyHistoricalFactRequest
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.models import (
    OnlyFundingRateUpdate,
    OnlyHistoricalBarRequest,
    OnlyHistoricalDataRange,
    OnlyReferencePriceUpdate,
)
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import (
    OnlyAggregationSource,
    OnlyBarAggregation,
    OnlyContractType,
    OnlyCurrencyType,
    OnlyMarketType,
    OnlyOffset,
    OnlyOrderSide,
    OnlyOrderType,
    OnlyPriceType,
    OnlyRuntimeMode,
    OnlySessionType,
    OnlyTimeInForce,
)
from onlyalpha.domain.execution import OnlyOrderRequest
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyCalendarId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderRequestId,
    OnlyRawSymbol,
    OnlyRuntimeId,
)
from onlyalpha.domain.instrument import OnlyCryptoPerpetual
from onlyalpha.domain.market import OnlyBarSpecification, OnlyBarType
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone, OnlyTradingDay
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.fee.basis import only_default_fee_basis_provider_registry
from onlyalpha.fee.broker_contract import only_simulation_zero_broker_fee_contract
from onlyalpha.identity import only_identity_fingerprint
from onlyalpha.market.product import (
    OnlyCanonicalMarketProductConfig,
    OnlyMarketProductConfig,
    OnlyMarketProductId,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductVersion,
)
from onlyalpha.market.runtime_rules import OnlyMarketRuleEngine
from onlyalpha.market_data.subscriptions import OnlyBarSubscription
from onlyalpha.plugin.capabilities import OnlyDataSourceCapabilities
from onlyalpha.plugin.data_source import OnlyDataSourceCreateRequest
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig

START = datetime(2026, 9, 1, 7, 57, tzinfo=UTC)
END = datetime(2026, 9, 1, 8, 2, tzinfo=UTC)
FUNDING_TIME = datetime(2026, 9, 1, 8, tzinfo=UTC)
INSTRUMENT = OnlyInstrumentId.parse("BTCUSDT-PERP.BINANCE")
RUNTIME = OnlyRuntimeId("binance-usdm-runtime")
ACCOUNT = OnlyAccountId("binance-usdm-runtime-DEFAULT")
CLUSTER = OnlyClusterId("binance-usdm-cluster")
USDT = OnlyCurrency("USDT", 8, OnlyCurrencyType.CRYPTO)


class _OrderCluster(OnlyCluster):
    def __init__(self, bar_type: OnlyBarType) -> None:
        super().__init__(OnlyClusterConfig(str(CLUSTER), OnlyBarSubscription((bar_type,))))
        self.pending_order: OnlyOrderRequest | None = None
        self.submit_results: list[object] = []

    def on_bar(self, bar, context: OnlyBarContext) -> None:  # type: ignore[no-untyped-def]
        del bar, context
        if self.pending_order is not None:
            if self.context is None:
                raise RuntimeError("assembled USD-M Cluster Context is unavailable")
            self.submit_results.append(self.context.orders.submit(self.pending_order))
            self.pending_order = None


def _bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _capture() -> OnlyBinanceUsdmReferenceCapture:
    exchange = {
        "serverTime": 1788249600000,
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "contractType": "PERPETUAL",
                "marginAsset": "USDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "minPrice": "0.10", "maxPrice": "1000000", "tickSize": "0.10"},
                    {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "1000", "stepSize": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                ],
            }
        ],
    }
    brackets = [
        {
            "symbol": "BTCUSDT",
            "brackets": [
                {
                    "bracket": 1,
                    "initialLeverage": 125,
                    "notionalFloor": "0",
                    "notionalCap": "100000",
                    "maintMarginRatio": "0.004",
                    "cum": "0",
                }
            ],
        }
    ]
    account = {
        "positionMode": "NETTING",
        "symbols": [{"symbol": "BTCUSDT", "marginMode": "CROSS", "leverage": "10"}],
    }
    return OnlyBinanceUsdmReferenceCapture.create(
        _bytes(exchange),
        _bytes([{"symbol": "BTCUSDT", "fundingIntervalHours": 4}]),
        _bytes(brackets),
        _bytes(account),
        captured_at=END,
        coverage_start=datetime(2026, 8, 1, tzinfo=UTC),
    )


class _Resources:
    def __init__(self, capture: OnlyBinanceUsdmReferenceCapture) -> None:
        self._values = {"public": capture.public_authority, "account": capture.account_authority}

    def require_reference_authority(self, resource_id: str):  # type: ignore[no-untyped-def]
        return self._values[resource_id]

    def require_market_fee_pack(self, pack_id: str, pack_version: str):  # type: ignore[no-untyped-def]
        raise AssertionError((pack_id, pack_version))


def _binding(capture: OnlyBinanceUsdmReferenceCapture):  # type: ignore[no-untyped-def]
    entry = tuple(metadata.entry_points().select(group="onlyalpha.market_products", name="binance-usdm"))
    assert len(entry) == 1
    factory = entry[0].load()()
    assert isinstance(factory, OnlyBinanceUsdmMarketProductFactory)
    config = OnlyMarketProductConfig(
        OnlyMarketProductPluginId("onlyalpha-market-binance-usdm"),
        OnlyMarketProductId("BINANCE_USDM"),
        OnlyMarketProductVersion("2"),
        OnlyCanonicalMarketProductConfig(
            {
                "public_reference_resource_id": "public",
                "expected_public_reference_fingerprint": capture.public_authority.identity.authority_fingerprint,
                "account_reference_resource_id": "account",
                "expected_account_reference_fingerprint": capture.account_authority.identity.authority_fingerprint,
                "requested_position_mode": "NETTING",
                "requested_margin_mode": "CROSS",
                "requested_leverage": "10",
                "maker_fee_rate": "0.0002",
                "taker_fee_rate": "0.0005",
            }
        ),
    )
    return factory.resolve(config, OnlyMarketProductResolutionContext(_Resources(capture)))


def _instrument() -> OnlyCryptoPerpetual:
    return OnlyCryptoPerpetual(
        instrument_id=INSTRUMENT,
        raw_symbol=OnlyRawSymbol("BTCUSDT"),
        market_type=OnlyMarketType.DERIVATIVE,
        quote_currency=USDT,
        settlement_currency=USDT,
        margin_currency=USDT,
        base_currency=OnlyCurrency("BTC", 8, OnlyCurrencyType.CRYPTO),
        price_precision=2,
        quantity_precision=3,
        tick_size=OnlyPrice(Decimal("0.10"), 2),
        step_size=OnlyQuantity(Decimal("0.001"), 3),
        contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
        contract_type=OnlyContractType.LINEAR,
        trading_calendar_id=OnlyCalendarId("BINANCE-24X7"),
    )


@dataclass
class _RecordedHistorical:
    def contract_klines(self, symbol: str, start_ms: int, end_ms: int, limit: int):  # type: ignore[no-untyped-def]
        del symbol, limit
        rows = []
        for minute in range(5):
            timestamp = int(START.timestamp() * 1000) + minute * 60_000
            if start_ms <= timestamp < end_ms:
                rows.append(
                    [timestamp, "60000.00", "60000.00", "60000.00", "60000.00", "1.000", 0, "60000.00", 1, 0, 0]
                )
        return tuple(rows)

    def mark_price_klines(self, symbol: str, start_ms: int, end_ms: int, limit: int):  # type: ignore[no-untyped-def]
        del symbol, limit
        rows = []
        for minute in range(1, 6):
            if minute == 3:
                continue
            timestamp = int(START.timestamp() * 1000) + minute * 60_000
            if start_ms <= timestamp < end_ms:
                rows.append([timestamp, "60000.00"])
        return tuple(rows)

    def index_price_klines(self, pair: str, start_ms: int, end_ms: int, limit: int):  # type: ignore[no-untyped-def]
        del pair, start_ms, end_ms, limit
        return ()

    def funding_rates(self, symbol: str, start_ms: int, end_ms: int, limit: int):  # type: ignore[no-untyped-def]
        del limit
        timestamp = int(FUNDING_TIME.timestamp() * 1000)
        if not start_ms <= timestamp < end_ms:
            return ()
        return (
            {
                "symbol": symbol,
                "fundingTime": timestamp,
                "fundingRate": "0.0001",
                "markPrice": "60000.00",
                "rateType": "REGULAR",
            },
        )


def _source(tmp_path: Path, instrument: OnlyCryptoPerpetual, bar_type: OnlyBarType) -> OnlyBinanceUsdmDataSource:
    entries = tuple(metadata.entry_points().select(group="onlyalpha.data_sources", name="binance-usdm"))
    assert len(entries) == 1
    discovered = entries[0].load()
    assert isinstance(discovered, OnlyBinanceUsdmDataSourceFactory)
    factory = type(discovered)(_RecordedHistorical())
    config = factory.parse_config({"rest_page_size": 100})
    request = OnlyDataSourceCreateRequest(
        OnlyMarketDataSourceId("binance-usdm-recorded"),
        config,
        "BACKTEST",
        OnlyDataSourceCapabilities(
            historical_bars=True,
            historical_reference_prices=True,
            historical_funding_rates=True,
            instruments=True,
            calendars=True,
        ),
        OnlyBacktestClock(START),
        OnlyEventBus(),
        {INSTRUMENT: instrument},
        {INSTRUMENT: bar_type},
        {},
        (),
        OnlyDataSourceCoverageConfig(instrument_ids=(INSTRUMENT,)),
        RUNTIME,
        OnlyDataVersion("binance-usdm-recorded-v1"),
        100,
        tmp_path,
        logging.getLogger(__name__),
    )
    assert factory.validate_request(request) == ()
    return factory.create(request)


def _runtime(
    tmp_path: Path,
    store: OnlyInMemoryRuntimePersistenceStore | None = None,
    *,
    recoverable: bool = False,
    maximum_fill_quantity: OnlyQuantity | None = None,
) -> tuple[OnlyBacktestRuntime, _OrderCluster, OnlyBinanceUsdmDataSource, OnlyBarType]:
    capture = _capture()
    binding = _binding(capture)
    rules = OnlyMarketRuleEngine(
        binding=binding,
        advance_trading_day=lambda day, lag: OnlyTradingDay(date.fromordinal(day.value.toordinal() + lag)),
    )
    instrument = _instrument()
    calendar = OnlyTradingCalendar(
        OnlyCalendarId("BINANCE-24X7"),
        INSTRUMENT.venue,
        OnlyTimeZone("UTC"),
        (OnlyTradingSession("continuous", time(0), time(0), OnlySessionType.CONTINUOUS),),
    )
    bar_type = OnlyBarType(
        INSTRUMENT,
        OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )
    source = _source(tmp_path, instrument, bar_type)
    clock = OnlyBacktestClock(START)
    queue = OnlyBoundedBrokerInboundQueue()
    broker_config = OnlyVirtualBrokerConfig(
        OnlyBrokerGatewayId("virtual-binance-usdm"),
        ACCOUNT,
        USDT,
        OnlyMoney(Decimal("100000.00000000"), USDT),
        maximum_fill_quantity=maximum_fill_quantity,
        long_only=False,
    )
    broker = OnlyVirtualBrokerGateway(broker_config, RUNTIME, clock, queue.put)
    runtime = OnlyBacktestRuntime(
        OnlyRuntimeAssemblyConfig(
            "binance-usdm-engine",
            str(RUNTIME),
            OnlyRuntimeMode.BACKTEST,
            strategy_base_currency=USDT,
            strategy_capitals={CLUSTER: broker_config.initial_cash},
            market_rule_engine=rules,
            market_fee_pack=binding.market_fee_pack,
            broker_fee_contract=only_simulation_zero_broker_fee_contract("virtual"),
            broker_fee_authority_id="virtual",
            fee_basis_providers=only_default_fee_basis_provider_registry(),
            broker_gateway_id=broker_config.gateway_id,
            account_initial_cash=broker_config.initial_cash,
            account_type=OnlyAccountType.MARGIN,
        ),
        calendar,
        START,
        run_plan=object() if recoverable else None,
        owned_clock=clock,
        broker_gateway=broker,
        deterministic_broker_driver=broker,
        broker_inbound_queue=queue,
        runtime_persistence_store=store or OnlyInMemoryRuntimePersistenceStore(),
        persistence_config=OnlyRuntimePersistenceConfig(
            OnlyRuntimePersistenceBackend.SQLITE,
            checkpoint=OnlyRuntimeCheckpointConfig(True),
        ),
        config_fingerprint=only_identity_fingerprint((binding.composition_identity, "ASSEMBLED_USDM_V1")),
        plugin_resources=(broker, source),
    )
    cluster = _OrderCluster(bar_type)
    runtime.register_instrument(instrument)
    runtime.add_cluster("binance-usdm-engine", cluster)
    return runtime, cluster, source, bar_type


def _ordered_updates(source: OnlyBinanceUsdmDataSource, bar_type: OnlyBarType):  # type: ignore[no-untyped-def]
    version = OnlyDataVersion("binance-usdm-recorded-v1")
    bars = OnlyHistoricalBarRequest(
        "assembled-usdm-bars",
        frozenset({INSTRUMENT}),
        frozenset({bar_type}),
        OnlyHistoricalDataRange(START, END),
        version,
    )
    funding = OnlyHistoricalFactRequest(
        INSTRUMENT,
        OnlyMarketDataType.FUNDING_RATE,
        OnlyTimeRange(START, END),
        version,
    )
    marks = OnlyHistoricalFactRequest(
        INSTRUMENT,
        OnlyMarketDataType.REFERENCE_PRICE,
        OnlyTimeRange(START, END),
        version,
        reference_price_kind=OnlyReferencePriceKind.MARK,
    )
    updates = source.load_bars(bars).records + source.load_facts(marks).records + source.load_facts(funding).records
    return tuple(
        sorted(
            updates,
            key=lambda item: (
                item.ts_event.unix_nanos,
                0
                if isinstance(item.payload, OnlyReferencePriceUpdate)
                else 2
                if isinstance(item.payload, OnlyFundingRateUpdate)
                else 1,
            ),
        )
    )


def _drive(runtime: OnlyBacktestRuntime, updates) -> None:  # type: ignore[no-untyped-def]
    for update in updates:
        runtime._services.clock.advance_to(update.ts_event.to_datetime())  # type: ignore[attr-defined]
        runtime.receive_market_data_update(update)
        results = runtime.drain_market_data_inbound()
        runtime.drain_broker_inbound()
        assert all(item.status.value == "APPLIED" for item in results), tuple(
            (item.status.value, item.validation, item.failure) for item in results if item.status.value != "APPLIED"
        )


def _world(runtime: OnlyBacktestRuntime) -> tuple[object, ...]:
    return (
        runtime.order_manager.snapshot_all(),
        runtime.position_manager.snapshot_all(),
        runtime.allocation_manager.snapshot_all(),
        runtime.margin_manager.active_reservations,
        runtime.account_manager.list_accounts(),
        runtime.account_manager.economic_cashflows,
        runtime.strategy_ledger_manager.list_ledgers(),
        runtime._capture_economic_facts_checkpoint(),  # type: ignore[attr-defined]
        runtime.margin_manager.capture_checkpoint(),
    )


def test_discovered_usdm_data_and_market_product_execute_exact_funding_through_backtest_runtime(
    tmp_path: Path,
) -> None:
    runtime, cluster, source, bar_type = _runtime(tmp_path, maximum_fill_quantity=OnlyQuantity(Decimal("0.001"), 3))
    runtime.start()
    try:
        runtime._services.market_data_source_registry.register(source)  # type: ignore[attr-defined]
        cluster.pending_order = OnlyOrderRequest(
            OnlyOrderRequestId("usdm-long-open"),
            INSTRUMENT,
            OnlyOrderSide.BUY,
            OnlyOrderType.LIMIT,
            OnlyQuantity(Decimal("0.002"), 3),
            OnlyTimeInForce.GTC,
            offset=OnlyOffset.OPEN,
            price=OnlyPrice(Decimal("60000.00"), 2),
        )
        ordered = _ordered_updates(source, bar_type)
        _drive(runtime, ordered)
        assert len(runtime.position_manager.snapshot_all()) == 1, (
            tuple((item.created, item.submitted, item.error) for item in cluster.submit_results),
            tuple(item.status for item in runtime.order_manager.snapshot_all()),
            tuple(item.status for item in runtime.broker_gateway.query_orders(ACCOUNT))
            if runtime.broker_gateway is not None
            else (),
            tuple((item.status, item.failure) for item in runtime.broker_results),
        )
        assert runtime.position_manager.snapshot_all()[0].total_quantity.value == Decimal("0.002")
        assert len(tuple(item for item in runtime.broker_results if item.audit_record.trade_id is not None)) == 2
        economic = runtime._capture_economic_facts_checkpoint()  # type: ignore[attr-defined]
        assert len(economic["reference_prices"]) == 4
        assert len(economic["funding_rates"]) == 1
        funding_cashflows = tuple(
            item
            for item in runtime.account_manager.economic_cashflows
            if item.cashflow_type is OnlyAccountEconomicCashflowType.FUNDING
        )
        assert len(funding_cashflows) == 1
        mark_json = economic["reference_prices"][0]
        funding_json = economic["funding_rates"][0]
        assert "provider_evidence_id" in mark_json and "provider_evidence_id" in funding_json

        funding_update = next(item for item in ordered if isinstance(item.payload, OnlyFundingRateUpdate))
        runtime.receive_market_data_update(funding_update)
        (duplicate,) = runtime.drain_market_data_inbound()
        assert duplicate.status.value == "DUPLICATE"
        assert len(runtime.account_manager.economic_cashflows) == 1
    finally:
        runtime.stop()


def test_assembled_usdm_uninterrupted_equals_checkpoint_restore(tmp_path: Path) -> None:
    uninterrupted, cluster_a, source_a, bar_type_a = _runtime(tmp_path / "a")
    uninterrupted.start()
    cluster_a.pending_order = OnlyOrderRequest(
        OnlyOrderRequestId("usdm-long-open"),
        INSTRUMENT,
        OnlyOrderSide.BUY,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("0.001"), 3),
        OnlyTimeInForce.GTC,
        offset=OnlyOffset.OPEN,
        price=OnlyPrice(Decimal("60000.00"), 2),
    )
    uninterrupted._services.market_data_source_registry.register(source_a)  # type: ignore[attr-defined]
    updates_a = _ordered_updates(source_a, bar_type_a)
    _drive(uninterrupted, updates_a)
    expected = _world(uninterrupted)
    uninterrupted.stop()

    store = OnlyInMemoryRuntimePersistenceStore()
    first, cluster_b, source_b, bar_type_b = _runtime(tmp_path / "b", store, recoverable=True)
    first.start()
    cluster_b.pending_order = OnlyOrderRequest(
        OnlyOrderRequestId("usdm-long-open"),
        INSTRUMENT,
        OnlyOrderSide.BUY,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("0.001"), 3),
        OnlyTimeInForce.GTC,
        offset=OnlyOffset.OPEN,
        price=OnlyPrice(Decimal("60000.00"), 2),
    )
    first._services.market_data_source_registry.register(source_b)  # type: ignore[attr-defined]
    updates_b = _ordered_updates(source_b, bar_type_b)
    split = next(index for index, item in enumerate(updates_b) if isinstance(item.payload, OnlyFundingRateUpdate))
    _drive(first, updates_b[:split])
    first._checkpoint_service.create(  # type: ignore[attr-defined]
        OnlyTimestamp.from_unix_nanos(first._services.clock.timestamp_ns())  # type: ignore[attr-defined]
    )
    first.stop()

    recovered, _, recovered_source, recovered_bar_type = _runtime(tmp_path / "b", store, recoverable=True)
    recovered.start()
    try:
        recovered._services.market_data_source_registry.register(recovered_source)  # type: ignore[attr-defined]
        recovered_updates = _ordered_updates(recovered_source, recovered_bar_type)
        _drive(recovered, recovered_updates[split:])
        assert _world(recovered) == expected
    finally:
        recovered.stop()
