from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from onlyalpha_plugin_binance.usdm import (
    OnlyBinanceUsdmDataSource,
    OnlyBinanceUsdmDataSourceConfig,
    OnlyBinanceUsdmHistoricalNormalizer,
    OnlyBinanceUsdmPolicyCompiler,
    OnlyBinanceUsdmReference,
    OnlyBinanceUsdmReferenceAuthority,
    only_binance_usdm_order_parameters,
)

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.historical.models import OnlyHistoricalFactRequest
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.models import OnlyFundingRateUpdate, OnlyReferencePriceUpdate
from onlyalpha.domain.enums import OnlyOrderSide, OnlyTimeInForce
from onlyalpha.domain.identifiers import OnlyInstrumentId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.domain.trading import (
    OnlyExecutionIntent,
    OnlyExposureConstraint,
    OnlyPositionEffect,
    OnlyPositionMode,
    OnlyPositionSide,
    OnlyReferencePriceKind,
)
from onlyalpha.market.economics import OnlyEconomicModel, OnlyMarginRequirementTier
from onlyalpha.market.product import OnlyMarketPolicyCompilationRequest
from onlyalpha.market.runtime_rules import OnlyMarketRuleEngine, OnlyPreTradeMarketContext

INSTRUMENT = OnlyInstrumentId.parse("BINANCE.BTCUSDT-PERP")
NOW = datetime(2026, 9, 1, 8, 0, 1, tzinfo=UTC)


def test_usdm_mark_index_and_funding_normalize_to_canonical_facts() -> None:
    normalizer = OnlyBinanceUsdmHistoricalNormalizer()
    mark = normalizer.reference_price(
        {"T": 1788249600000, "p": "60000.10"},
        instrument_id=INSTRUMENT,
        kind=OnlyReferencePriceKind.MARK,
        data_version="fixture-v1",
        source_sequence=1,
        received_at=NOW,
    )
    index = normalizer.reference_price(
        {"T": 1788249600000, "i": "59999.90"},
        instrument_id=INSTRUMENT,
        kind=OnlyReferencePriceKind.INDEX,
        data_version="fixture-v1",
        source_sequence=2,
        received_at=NOW,
    )
    funding = normalizer.funding_rate(
        {"fundingTime": 1788249600000, "fundingRate": "0.0001"},
        instrument_id=INSTRUMENT,
        data_version="fixture-v1",
        source_sequence=3,
        received_at=NOW,
    )
    assert (mark.kind, mark.value.value, index.kind, index.value.value) == (
        OnlyReferencePriceKind.MARK,
        Decimal("60000.10"),
        OnlyReferencePriceKind.INDEX,
        Decimal("59999.90"),
    )
    assert funding.rate == Decimal("0.0001")
    assert (
        normalizer.funding_rate(
            {"fundingTime": 1788249600000, "fundingRate": "0.0001"},
            instrument_id=INSTRUMENT,
            data_version="fixture-v1",
            source_sequence=3,
            received_at=NOW,
        ).fact_id
        == funding.fact_id
    )


def test_usdm_wire_mapping_preserves_canonical_mode_and_reduce_only() -> None:
    close_short = OnlyExecutionIntent(
        OnlyOrderSide.BUY,
        OnlyPositionSide.SHORT,
        OnlyPositionEffect.CLOSE,
        exposure_constraint=OnlyExposureConstraint.REDUCE_ONLY,
    )
    assert only_binance_usdm_order_parameters(close_short, position_mode=OnlyPositionMode.NETTING) == {
        "side": "BUY",
        "positionSide": "BOTH",
        "reduceOnly": "true",
    }
    assert only_binance_usdm_order_parameters(close_short, position_mode=OnlyPositionMode.HEDGING) == {
        "side": "BUY",
        "positionSide": "SHORT",
    }
    unsafe_close = OnlyExecutionIntent(
        OnlyOrderSide.BUY,
        OnlyPositionSide.SHORT,
        OnlyPositionEffect.CLOSE,
    )
    with pytest.raises(ValueError, match="NETTING_CLOSE_REQUIRES_REDUCE_ONLY"):
        only_binance_usdm_order_parameters(unsafe_close, position_mode=OnlyPositionMode.NETTING)


def test_usdm_reference_compiles_to_canonical_derivative_economics() -> None:
    reference = OnlyBinanceUsdmReference.create(
        instrument_id=INSTRUMENT,
        settlement_currency="USDT",
        contract_multiplier=Decimal("1"),
        price_tick=Decimal("0.10"),
        quantity_step=Decimal("0.001"),
        minimum_quantity=Decimal("0.001"),
        maximum_quantity=Decimal("1000"),
        margin_tiers=(
            OnlyMarginRequirementTier(Decimal("100000"), Decimal("0.10"), Decimal("0.05")),
            OnlyMarginRequirementTier(None, Decimal("0.20"), Decimal("0.10")),
        ),
        observed_at=datetime(2026, 8, 31, tzinfo=UTC),
    )
    authority = OnlyBinanceUsdmReferenceAuthority.create((reference,))
    policy = OnlyBinanceUsdmPolicyCompiler().compile(
        OnlyMarketPolicyCompilationRequest(
            INSTRUMENT,
            OnlyTradingDay(date(2026, 9, 1)),
            authority,
            NOW,
        )
    )
    assert policy.economic_model is OnlyEconomicModel.MARGINED_DERIVATIVE
    assert policy.compiled_margin_policy is not None
    assert policy.compiled_margin_policy.requirement(Decimal("1000")) == (
        Decimal("100.00"),
        Decimal("50.00"),
    )
    assert policy.funding_policy is not None and policy.valuation_policy is not None

    engine = OnlyMarketRuleEngine(
        binding=SimpleNamespace(
            policy_compiler=OnlyBinanceUsdmPolicyCompiler(),
            reference_authority=authority,
        ),
        advance_trading_day=lambda day, lag: OnlyTradingDay(date.fromordinal(day.value.toordinal() + lag)),
    )
    rejected = engine.evaluate_pre_trade(
        OnlyPreTradeMarketContext(
            str(INSTRUMENT),
            OnlyOrderSide.BUY,
            Decimal("1"),
            Decimal("100"),
            NOW,
            OnlyTradingDay(date(2026, 9, 1)),
            trade_available_cash=Decimal("1000"),
            available_margin=Decimal("1000"),
            position_effect=OnlyPositionEffect.OPEN,
            time_in_force=OnlyTimeInForce.DAY,
            position_side=OnlyPositionSide.LONG,
        )
    )
    assert not rejected.accepted
    assert rejected.reason_code == "ORDER_CAPABILITY_NOT_SUPPORTED"


class _RecordedUsdmHistoricalClient:
    def klines(
        self,
        _symbol: str,
        start_ms: int,
        _end_ms: int,
        _limit: int,
        *,
        kind: OnlyReferencePriceKind | None = None,
    ) -> tuple[tuple[object, ...], ...]:
        assert kind is OnlyReferencePriceKind.MARK
        return (
            (
                start_ms,
                "60000.00",
                "60010.00",
                "59990.00",
                "60005.00",
                "10.000",
                start_ms + 59_999,
                "600050.00",
                10,
                "0",
                "0",
                "0",
            ),
        )

    def funding_rates(self, _symbol: str, start_ms: int, _end_ms: int, _limit: int) -> tuple[dict[str, object], ...]:
        return ({"symbol": "BTCUSDT", "fundingTime": start_ms, "fundingRate": "0.0001"},)


def test_usdm_historical_datasource_loads_recorded_mark_and_funding_facts() -> None:
    start = datetime(2026, 9, 1, 8, tzinfo=UTC)
    end = datetime(2026, 9, 1, 8, 1, tzinfo=UTC)
    instrument = SimpleNamespace(
        instrument_id=INSTRUMENT,
        raw_symbol="BTCUSDT",
        price_precision=2,
        quantity_precision=3,
    )
    request = SimpleNamespace(
        source_id=OnlyMarketDataSourceId("binance-usdm-fixture"),
        runtime_id=OnlyRuntimeId("runtime"),
        instruments={INSTRUMENT: instrument},
        calendars={},
    )
    source = OnlyBinanceUsdmDataSource(
        request,  # type: ignore[arg-type]
        OnlyBinanceUsdmDataSourceConfig(rest_page_size=10),
        historical_client=_RecordedUsdmHistoricalClient(),  # type: ignore[arg-type]
    )
    mark_stream = source.load_facts(
        OnlyHistoricalFactRequest(
            INSTRUMENT,
            OnlyMarketDataType.REFERENCE_PRICE,
            OnlyTimeRange(start, end),
            OnlyDataVersion("fixture-v1"),
            OnlyReferencePriceKind.MARK,
            10,
        )
    )
    funding_stream = source.load_facts(
        OnlyHistoricalFactRequest(
            INSTRUMENT,
            OnlyMarketDataType.FUNDING_RATE,
            OnlyTimeRange(start, end),
            OnlyDataVersion("fixture-v1"),
            batch_size=10,
        )
    )

    assert len(mark_stream.records) == len(funding_stream.records) == 1
    assert isinstance(mark_stream.records[0].payload, OnlyReferencePriceUpdate)
    assert mark_stream.records[0].payload.fact.value.value == Decimal("60000.00")
    assert mark_stream.records[0].ts_event == funding_stream.records[0].ts_event
    assert isinstance(funding_stream.records[0].payload, OnlyFundingRateUpdate)
    assert funding_stream.records[0].payload.fact.rate == Decimal("0.0001")
