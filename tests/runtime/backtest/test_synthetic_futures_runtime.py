from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from onlyalpha_market_generic_t0_cash.fee_pack import only_generic_t0_cash_market_fee_pack
from onlyalpha_plugin_broker_virtual import OnlyVirtualBrokerConfig, OnlyVirtualBrokerGateway

from onlyalpha.account.enums import OnlyAccountEconomicCashflowType, OnlyAccountType
from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.inbound import OnlyBoundedBrokerInboundQueue
from onlyalpha.config.persistence import (
    OnlyRuntimeCheckpointConfig,
    OnlyRuntimePersistenceBackend,
    OnlyRuntimePersistenceConfig,
)
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.identifiers import (
    OnlyDataSequence,
    OnlyDataVersion,
    OnlyMarketDataSourceId,
    OnlyMarketDataUpdateId,
)
from onlyalpha.data.models import OnlyMarketDataInboundUpdate, OnlyReferencePriceUpdate
from onlyalpha.domain.calendar import OnlyTradingCalendar, OnlyTradingSession
from onlyalpha.domain.enums import (
    OnlyAdjustmentType,
    OnlyAggregationSource,
    OnlyAssetClass,
    OnlyBarAggregation,
    OnlyMarginMode,
    OnlyMarketType,
    OnlyOffset,
    OnlyOrderSide,
    OnlyOrderType,
    OnlyPriceType,
    OnlyRuntimeMode,
    OnlySessionType,
    OnlySettlementType,
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
    OnlySymbol,
    OnlyVenueId,
)
from onlyalpha.domain.instrument import OnlyFuture
from onlyalpha.domain.market import OnlyBar, OnlyBarSpecification, OnlyBarType, OnlyReferencePriceFact
from onlyalpha.domain.time import OnlyTimestamp, OnlyTimeZone, OnlyTradingDay
from onlyalpha.domain.trading import (
    OnlyExecutionIntent,
    OnlyPositionEffect,
    OnlyPositionMode,
    OnlyPositionSide,
    OnlyReferencePriceKind,
)
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.fee.basis import only_default_fee_basis_provider_registry
from onlyalpha.fee.broker_contract import only_simulation_zero_broker_fee_contract
from onlyalpha.fee.market_pack import OnlyMarketFeePack
from onlyalpha.identity import only_identity_fingerprint
from onlyalpha.market.product import (
    OnlyMarketProductId,
    OnlyMarketProductPluginId,
    OnlyMarketProductVersion,
    OnlyResolvedMarketProductBinding,
)
from onlyalpha.market.product.identity import OnlyMarketProductIdentity
from onlyalpha.market.runtime_rules import OnlyMarketRuleEngine
from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig
from tests.conformance.support.synthetic_futures import (
    OnlySyntheticFuturesPolicyCompiler,
    OnlySyntheticFuturesReferenceAuthority,
    only_synthetic_futures_effective_profile,
)
from tests.integration_demo.environment import OnlyIntegrationCluster

ENGINE = "synthetic-futures-engine"
RUNTIME = OnlyRuntimeId("synthetic-futures-runtime")
ACCOUNT = OnlyAccountId("synthetic-futures-runtime-DEFAULT")
CLUSTER = OnlyClusterId("synthetic-futures-cluster")
INSTRUMENT = OnlyInstrumentId(OnlySymbol("TEST-LINEAR-202612"), OnlyVenueId("TEST"))
USD = OnlyCurrency("USD", 2)
START = datetime(2026, 9, 1, 9, tzinfo=UTC)


def _occupied_margin(runtime: OnlyBacktestRuntime) -> Decimal:
    return sum(
        (
            reservation.occupied
            for reservation in runtime.margin_manager.active_reservations
            if reservation.account_id == ACCOUNT
            and reservation.instrument_id == INSTRUMENT
            and reservation.currency == USD
        ),
        Decimal(0),
    )


def _runtime(
    store: OnlyInMemoryRuntimePersistenceStore | None = None,
    *,
    recoverable: bool = False,
    position_mode: OnlyPositionMode = OnlyPositionMode.NETTING,
    margin_mode: OnlyMarginMode = OnlyMarginMode.CROSS,
) -> tuple[OnlyBacktestRuntime, OnlyIntegrationCluster, OnlyBarType]:
    calendar = OnlyTradingCalendar(
        OnlyCalendarId("TEST"),
        OnlyVenueId("TEST"),
        OnlyTimeZone("UTC"),
        (OnlyTradingSession("day", time(9), time(17), OnlySessionType.CONTINUOUS),),
    )
    instrument = OnlyFuture(
        instrument_id=INSTRUMENT,
        raw_symbol=OnlyRawSymbol("TEST-LINEAR-202612"),
        asset_class=OnlyAssetClass.COMMODITY,
        market_type=OnlyMarketType.DERIVATIVE,
        quote_currency=USD,
        settlement_currency=USD,
        margin_currency=USD,
        price_precision=2,
        quantity_precision=0,
        tick_size=OnlyPrice(Decimal("0.01"), 2),
        step_size=OnlyQuantity(Decimal("1"), 0),
        contract_multiplier=OnlyMultiplier(Decimal("10"), 0),
        underlying=OnlyInstrumentId.parse("TEST-UNDERLYING.TEST"),
        expiration_time=datetime(2026, 12, 31, tzinfo=UTC),
        last_trade_time=datetime(2026, 12, 30, tzinfo=UTC),
        settlement_type=OnlySettlementType.CASH,
        trading_calendar_id=OnlyCalendarId("TEST"),
    )
    generic_fees = only_generic_t0_cash_market_fee_pack()
    futures_fee_schedule = replace(generic_fees.schedules[0], currency=USD, instrument_class="FUTURES")
    fee_pack = OnlyMarketFeePack.create(
        pack_id="TEST_LINEAR_FUTURES_FEES",
        pack_version="1",
        compatible_market_products=("TEST_LINEAR_FUTURE",),
        schedules=(futures_fee_schedule,),
    )
    binding = OnlyResolvedMarketProductBinding.create(
        product_identity=OnlyMarketProductIdentity(
            OnlyMarketProductId("TEST_LINEAR_FUTURE"),
            OnlyMarketProductVersion("1"),
        ),
        provider_plugin_id=OnlyMarketProductPluginId("test-synthetic-futures"),
        reference_authority=OnlySyntheticFuturesReferenceAuthority(),
        policy_compiler=OnlySyntheticFuturesPolicyCompiler(),
        market_fee_pack=fee_pack,
        effective_config_fingerprint=only_identity_fingerprint(("TEST_LINEAR_FUTURE", "1", position_mode, margin_mode)),
        effective_trading_profile=only_synthetic_futures_effective_profile(position_mode, margin_mode),
    )
    rules = OnlyMarketRuleEngine(
        binding=binding,
        advance_trading_day=lambda day, lag: OnlyTradingDay(date.fromordinal(day.value.toordinal() + lag)),
    )
    clock = OnlyBacktestClock(START)
    queue = OnlyBoundedBrokerInboundQueue()
    broker_config = OnlyVirtualBrokerConfig(
        OnlyBrokerGatewayId("virtual-synthetic-futures"),
        ACCOUNT,
        USD,
        OnlyMoney(Decimal("100000.00"), USD),
        long_only=False,
    )
    broker = OnlyVirtualBrokerGateway(broker_config, RUNTIME, clock, queue.put)
    runtime = OnlyBacktestRuntime(
        OnlyRuntimeAssemblyConfig(
            ENGINE,
            str(RUNTIME),
            OnlyRuntimeMode.BACKTEST,
            strategy_base_currency=USD,
            strategy_capitals={CLUSTER: broker_config.initial_cash},
            market_rule_engine=rules,
            market_fee_pack=fee_pack,
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
        runtime_persistence_store=(store if store is not None else OnlyInMemoryRuntimePersistenceStore()),
        persistence_config=OnlyRuntimePersistenceConfig(
            OnlyRuntimePersistenceBackend.SQLITE,
            checkpoint=OnlyRuntimeCheckpointConfig(True),
        ),
        config_fingerprint=only_identity_fingerprint(
            (ENGINE, str(RUNTIME), "synthetic-futures-v2", position_mode, margin_mode)
        ),
        plugin_resources=(broker,),
    )
    bar_type = OnlyBarType(
        INSTRUMENT,
        OnlyBarSpecification(1, OnlyBarAggregation.TIME, OnlyPriceType.LAST),
        OnlyAggregationSource.EXTERNAL,
    )
    cluster = OnlyIntegrationCluster((bar_type,), cluster_id=CLUSTER)
    runtime.register_instrument(instrument)
    runtime.add_cluster(ENGINE, cluster)
    return runtime, cluster, bar_type


def _bar(bar_type: OnlyBarType, minute: int, price: str) -> OnlyBar:
    start = START + timedelta(minutes=minute)
    value = Decimal(price)
    return OnlyBar(
        bar_type=bar_type,
        open=OnlyPrice(value, 2),
        high=OnlyPrice(value, 2),
        low=OnlyPrice(value, 2),
        close=OnlyPrice(value, 2),
        volume=OnlyQuantity(Decimal("100"), 0),
        quote_volume=None,
        turnover=None,
        trade_count=1,
        open_interest=None,
        bar_start=start,
        bar_end=start + timedelta(minutes=1),
        ts_event=start + timedelta(minutes=1),
        ts_init=start + timedelta(minutes=1),
        is_closed=True,
        revision=0,
        trading_day=START.date(),
        session_type=OnlySessionType.CONTINUOUS,
        adjustment_type=OnlyAdjustmentType.RAW,
    )


def _settlement(runtime: OnlyBacktestRuntime, minute: int, price: str) -> None:
    timestamp = START + timedelta(minutes=minute)
    fact = OnlyReferencePriceFact(
        f"settlement-{minute}",
        INSTRUMENT,
        OnlyReferencePriceKind.SETTLEMENT,
        OnlyPrice(Decimal(price), 2),
        timestamp,
        timestamp,
        "synthetic-fixture",
        minute,
        "fixture-v1",
    )
    stamp = OnlyTimestamp.from_datetime(timestamp)
    runtime._apply_canonical_economic_fact(  # type: ignore[attr-defined]
        OnlyMarketDataInboundUpdate(
            OnlyMarketDataUpdateId(f"settlement-update-{minute}"),
            RUNTIME,
            OnlyMarketDataSourceId("synthetic-fixture"),
            OnlyDataSequence(minute),
            OnlyDataVersion("fixture-v1"),
            INSTRUMENT,
            OnlyMarketDataType.SETTLEMENT,
            OnlyReferencePriceUpdate(fact),
            stamp,
            stamp,
        )
    )


def test_synthetic_futures_round_trip_and_daily_mtm_use_one_runtime_and_virtual_broker() -> None:
    runtime, cluster, bar_type = _runtime()
    runtime.start()
    try:
        _settlement(runtime, 0, "100.00")
        cluster.pending_order = OnlyOrderRequest(
            OnlyOrderRequestId("long-open"),
            INSTRUMENT,
            OnlyOrderSide.BUY,
            OnlyOrderType.LIMIT,
            OnlyQuantity(Decimal("1"), 0),
            OnlyTimeInForce.GTC,
            offset=OnlyOffset.OPEN,
            price=OnlyPrice(Decimal("100.00"), 2),
        )
        runtime.process_bar(_bar(bar_type, 0, "100.00"))
        runtime.process_bar(_bar(bar_type, 1, "100.00"))
        runtime.drain_broker_inbound()
        assert runtime.position_manager.snapshot_all()[0].total_quantity.value == Decimal("1")
        assert _occupied_margin(runtime) == Decimal("120.00")

        _settlement(runtime, 2, "110.00")
        account_after_settlement = runtime.account_manager.require_snapshot(ACCOUNT)
        assert account_after_settlement.cash.ledger_cash.amount == Decimal("100099.00")
        assert account_after_settlement.realized_pnl.amount == Decimal("100.00")

        cluster.pending_order = OnlyOrderRequest(
            OnlyOrderRequestId("long-close"),
            INSTRUMENT,
            OnlyOrderSide.SELL,
            OnlyOrderType.LIMIT,
            OnlyQuantity(Decimal("1"), 0),
            OnlyTimeInForce.GTC,
            offset=OnlyOffset.CLOSE,
            price=OnlyPrice(Decimal("110.00"), 2),
        )
        runtime.process_bar(_bar(bar_type, 2, "110.00"))
        runtime.process_bar(_bar(bar_type, 3, "110.00"))
        runtime.drain_broker_inbound()

        assert runtime.position_manager.snapshot_all() == ()
        assert _occupied_margin(runtime) == Decimal("0.00")
        account = runtime.account_manager.require_snapshot(ACCOUNT)
        ledger = runtime.strategy_ledger_manager.list_ledgers()[0]
        assert account.cash.ledger_cash.amount == ledger.cash.ledger_cash.amount == Decimal("100097.90")
        assert account.realized_pnl.amount == ledger.pnl.realized_pnl.amount == Decimal("100.00")
        assert tuple(item.cashflow_type for item in runtime.account_manager.economic_cashflows) == (
            OnlyAccountEconomicCashflowType.VARIATION_MARGIN,
        )
        checkpoint = runtime._capture_economic_facts_checkpoint()  # type: ignore[attr-defined]
        assert len(checkpoint["reference_prices"]) == 2  # type: ignore[index]
    finally:
        runtime.stop()


def test_synthetic_futures_checkpoint_restores_equal_world_and_can_continue_close() -> None:
    store = OnlyInMemoryRuntimePersistenceStore()
    first, first_cluster, bar_type = _runtime(store, recoverable=True)
    first.start()
    _settlement(first, 0, "100.00")
    first_cluster.pending_order = OnlyOrderRequest(
        OnlyOrderRequestId("restart-long-open"),
        INSTRUMENT,
        OnlyOrderSide.BUY,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("1"), 0),
        OnlyTimeInForce.GTC,
        offset=OnlyOffset.OPEN,
        price=OnlyPrice(Decimal("100.00"), 2),
    )
    first.process_bar(_bar(bar_type, 0, "100.00"))
    first.process_bar(_bar(bar_type, 1, "100.00"))
    _settlement(first, 2, "110.00")
    first._checkpoint_service.create(  # type: ignore[attr-defined]
        OnlyTimestamp.from_unix_nanos(first._services.clock.timestamp_ns())  # type: ignore[attr-defined]
    )
    expected = (
        first.order_manager.snapshot_all(),
        first.position_manager.snapshot_all(),
        first.allocation_manager.snapshot_all(),
        first.account_manager.list_accounts(),
        first.strategy_ledger_manager.list_ledgers(),
        first.margin_manager.active_reservations,
        first._capture_economic_facts_checkpoint(),  # type: ignore[attr-defined]
    )
    first.stop()

    recovered, recovered_cluster, recovered_bar_type = _runtime(store, recoverable=True)
    recovered.start()
    try:
        actual = (
            recovered.order_manager.snapshot_all(),
            recovered.position_manager.snapshot_all(),
            recovered.allocation_manager.snapshot_all(),
            recovered.account_manager.list_accounts(),
            recovered.strategy_ledger_manager.list_ledgers(),
            recovered.margin_manager.active_reservations,
            recovered._capture_economic_facts_checkpoint(),  # type: ignore[attr-defined]
        )
        assert actual == expected

        close_request = OnlyOrderRequest(
            OnlyOrderRequestId("restart-long-close"),
            INSTRUMENT,
            OnlyOrderSide.SELL,
            OnlyOrderType.LIMIT,
            OnlyQuantity(Decimal("1"), 0),
            OnlyTimeInForce.GTC,
            offset=OnlyOffset.CLOSE,
            price=OnlyPrice(Decimal("110.00"), 2),
        )
        assert recovered_cluster.context is not None
        close_result = recovered_cluster.context.orders.submit(close_request)
        assert close_result.submitted
        assert recovered._deterministic_broker_driver is not None  # type: ignore[attr-defined]
        first_close_bar = _bar(recovered_bar_type, 3, "110.00")
        recovered._services.clock.advance_to(first_close_bar.ts_event)  # type: ignore[attr-defined]
        recovered._deterministic_broker_driver.on_bar(first_close_bar)  # type: ignore[attr-defined]
        recovered.drain_broker_inbound()
        second_close_bar = _bar(recovered_bar_type, 4, "110.00")
        recovered._services.clock.advance_to(second_close_bar.ts_event)  # type: ignore[attr-defined]
        recovered._deterministic_broker_driver.on_bar(second_close_bar)  # type: ignore[attr-defined]
        recovered.drain_broker_inbound()
        assert recovered.position_manager.snapshot_all() == ()
        assert recovered.margin_manager.occupied(str(ACCOUNT), str(INSTRUMENT), USD.code) == Decimal("0.00")
    finally:
        recovered.stop()


@pytest.mark.parametrize("position_mode", tuple(OnlyPositionMode))
@pytest.mark.parametrize("margin_mode", (OnlyMarginMode.CROSS, OnlyMarginMode.ISOLATED))
def test_synthetic_futures_effective_modes_execute_short_round_trip_without_provider_branch(
    position_mode: OnlyPositionMode, margin_mode: OnlyMarginMode
) -> None:
    runtime, cluster, bar_type = _runtime(position_mode=position_mode, margin_mode=margin_mode)
    runtime.start()
    try:
        _settlement(runtime, 0, "100.00")
        cluster.pending_order = OnlyOrderRequest(
            OnlyOrderRequestId(f"short-open-{position_mode.value}-{margin_mode.value}"),
            INSTRUMENT,
            OnlyOrderSide.SELL,
            OnlyOrderType.LIMIT,
            OnlyQuantity(Decimal("1"), 0),
            OnlyTimeInForce.GTC,
            offset=OnlyOffset.OPEN,
            price=OnlyPrice(Decimal("100.00"), 2),
            execution_intent=OnlyExecutionIntent(
                OnlyOrderSide.SELL,
                OnlyPositionSide.SHORT,
                OnlyPositionEffect.OPEN,
                position_mode=position_mode,
            ),
        )
        runtime.process_bar(_bar(bar_type, 0, "100.00"))
        runtime.process_bar(_bar(bar_type, 1, "100.00"))
        runtime.drain_broker_inbound()
        (position,) = runtime.position_manager.snapshot_all()
        assert position.position_side.value == "SHORT"
        assert _occupied_margin(runtime) == Decimal("120.00")

        cluster.pending_order = OnlyOrderRequest(
            OnlyOrderRequestId(f"short-close-{position_mode.value}-{margin_mode.value}"),
            INSTRUMENT,
            OnlyOrderSide.BUY,
            OnlyOrderType.LIMIT,
            OnlyQuantity(Decimal("1"), 0),
            OnlyTimeInForce.GTC,
            offset=OnlyOffset.CLOSE,
            price=OnlyPrice(Decimal("100.00"), 2),
            execution_intent=OnlyExecutionIntent(
                OnlyOrderSide.BUY,
                OnlyPositionSide.SHORT,
                OnlyPositionEffect.CLOSE,
                position_mode=position_mode,
            ),
        )
        runtime.process_bar(_bar(bar_type, 2, "100.00"))
        runtime.process_bar(_bar(bar_type, 3, "100.00"))
        runtime.drain_broker_inbound()
        assert runtime.position_manager.snapshot_all() == ()
        assert _occupied_margin(runtime) == Decimal("0.00")
    finally:
        runtime.stop()


def test_checkpointed_partial_settlement_is_forward_recovered_before_runtime_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = OnlyInMemoryRuntimePersistenceStore()
    first, cluster, bar_type = _runtime(store, recoverable=True)
    first.start()
    _settlement(first, 0, "100.00")
    cluster.pending_order = OnlyOrderRequest(
        OnlyOrderRequestId("pending-settlement-open"),
        INSTRUMENT,
        OnlyOrderSide.BUY,
        OnlyOrderType.LIMIT,
        OnlyQuantity(Decimal("1"), 0),
        OnlyTimeInForce.GTC,
        offset=OnlyOffset.OPEN,
        price=OnlyPrice(Decimal("100.00"), 2),
    )
    first.process_bar(_bar(bar_type, 0, "100.00"))
    first.process_bar(_bar(bar_type, 1, "100.00"))
    original = first.allocation_manager.apply_settlement
    failed = False

    def fail_once(settlement):  # type: ignore[no-untyped-def]
        nonlocal failed
        if not failed:
            failed = True
            raise RuntimeError("injected allocation settlement failure")
        return original(settlement)

    monkeypatch.setattr(first.allocation_manager, "apply_settlement", fail_once)
    with pytest.raises(RuntimeError, match="injected allocation settlement failure"):
        _settlement(first, 2, "110.00")
    assert "settlement-2" in first._pending_economic_fact_applications  # type: ignore[attr-defined]
    assert "settlement-2" not in first._reference_price_facts  # type: ignore[attr-defined]
    first._checkpoint_service.create(  # type: ignore[attr-defined]
        OnlyTimestamp.from_unix_nanos(first._services.clock.timestamp_ns())  # type: ignore[attr-defined]
    )
    first.stop()

    recovered, _, _ = _runtime(store, recoverable=True)
    recovered.start()
    try:
        assert recovered._pending_economic_fact_applications == {}  # type: ignore[attr-defined]
        assert "settlement-2" in recovered._reference_price_facts  # type: ignore[attr-defined]
        account = recovered.account_manager.require_snapshot(ACCOUNT)
        ledger = recovered.strategy_ledger_manager.list_ledgers()[0]
        assert account.cash.ledger_cash == ledger.cash.ledger_cash
        assert account.cash.ledger_cash.amount == Decimal("100099.00")
    finally:
        recovered.stop()
