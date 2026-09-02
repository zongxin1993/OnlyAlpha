import json
from datetime import UTC, date, datetime
from decimal import Decimal
from importlib import metadata
from types import SimpleNamespace

import pytest
from onlyalpha_plugin_binance.usdm import (
    OnlyBinanceUsdmDataSource,
    OnlyBinanceUsdmDataSourceConfig,
    OnlyBinanceUsdmHistoricalClient,
    OnlyBinanceUsdmHistoricalNormalizer,
    OnlyBinanceUsdmReferenceCapture,
    only_binance_usdm_order_parameters,
)
from onlyalpha_plugin_binance_usdm import OnlyBinanceUsdmMarketProductFactory
from onlyalpha_plugin_binance_usdm.resource_provider import OnlyBinanceUsdmBacktestResourceProvider

from onlyalpha.core.ranges import OnlyTimeRange
from onlyalpha.data.enums import OnlyMarketDataType
from onlyalpha.data.historical.models import OnlyHistoricalFactRequest
from onlyalpha.data.identifiers import OnlyDataVersion, OnlyMarketDataSourceId
from onlyalpha.data.models import OnlyFundingRateUpdate, OnlyReferencePriceUpdate
from onlyalpha.domain.enums import OnlyOrderSide
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
from onlyalpha.market.product import (
    OnlyCanonicalMarketProductConfig,
    OnlyMarketProductConfig,
    OnlyMarketProductId,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductVersion,
)
from onlyalpha.market.runtime_rules import OnlyMarketRuleEngine

INSTRUMENT = OnlyInstrumentId.parse("BTCUSDT-PERP.BINANCE")
NOW = datetime(2026, 9, 1, 8, 0, 1, tzinfo=UTC)


def _bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _capture(
    *,
    position_mode: str = "NETTING",
    margin_mode: str = "CROSS",
    interval_hours: int = 4,
    coverage_start: datetime = datetime(2026, 8, 1, tzinfo=UTC),
) -> OnlyBinanceUsdmReferenceCapture:
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
    funding = [{"symbol": "BTCUSDT", "fundingIntervalHours": interval_hours}]
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
                },
                {
                    "bracket": 2,
                    "initialLeverage": 100,
                    "notionalFloor": "100000",
                    "notionalCap": "500000",
                    "maintMarginRatio": "0.005",
                    "cum": "100",
                },
            ],
        }
    ]
    account = {
        "positionMode": position_mode,
        "symbols": [{"symbol": "BTCUSDT", "marginMode": margin_mode, "leverage": "10"}],
    }
    return OnlyBinanceUsdmReferenceCapture.create(
        _bytes(exchange),
        _bytes(funding),
        _bytes(brackets),
        _bytes(account),
        captured_at=NOW,
        coverage_start=coverage_start,
    )


class _Resources:
    def __init__(self, capture: OnlyBinanceUsdmReferenceCapture) -> None:
        self._resources = {"public": capture.public_authority, "account": capture.account_authority}

    def require_reference_authority(self, resource_id: str):  # type: ignore[no-untyped-def]
        return self._resources[resource_id]

    def require_market_fee_pack(self, pack_id: str, pack_version: str):  # type: ignore[no-untyped-def]
        raise AssertionError((pack_id, pack_version))


def _binding(capture: OnlyBinanceUsdmReferenceCapture, *, position: str = "NETTING", margin: str = "CROSS"):
    config = OnlyMarketProductConfig(
        OnlyMarketProductPluginId("onlyalpha-plugin-binance-usdm"),
        OnlyMarketProductId("BINANCE_USDM"),
        OnlyMarketProductVersion("2"),
        OnlyCanonicalMarketProductConfig(
            {
                "public_reference_resource_id": "public",
                "expected_public_reference_fingerprint": capture.public_authority.identity.authority_fingerprint,
                "account_reference_resource_id": "account",
                "expected_account_reference_fingerprint": capture.account_authority.identity.authority_fingerprint,
                "requested_position_mode": position,
                "requested_margin_mode": margin,
                "requested_leverage": "10",
                "maker_fee_rate": "0.0002",
                "taker_fee_rate": "0.0005",
            }
        ),
    )
    return OnlyBinanceUsdmMarketProductFactory().resolve(
        config, OnlyMarketProductResolutionContext(_Resources(capture))
    )


def test_raw_capture_normalizes_separate_public_and_account_authorities() -> None:
    first = _capture()
    repeated = _capture()
    shifted = _capture(coverage_start=datetime(2026, 8, 2, tzinfo=UTC))
    assert first == repeated
    assert len(first.evidence) == 4
    assert (
        first.public_authority.references[0].content_fingerprint
        == shifted.public_authority.references[0].content_fingerprint
    )
    assert first.public_authority.identity != shifted.public_authority.identity
    point = datetime(2026, 8, 3, tzinfo=UTC)
    resolved = first.public_authority.resolve(INSTRUMENT, OnlyTradingDay(point.date()), as_of=point)
    repeated_resolved = repeated.public_authority.resolve(INSTRUMENT, OnlyTradingDay(point.date()), as_of=point)
    assert first.public_authority.identity == repeated.public_authority.identity
    assert resolved == repeated_resolved
    assert resolved.funding_schedule.interval_seconds == 4 * 60 * 60
    assert first.account_authority.effective_inputs.position_mode is OnlyPositionMode.NETTING


def test_usdm_backtest_resource_provider_round_trips_public_and_account_authorities() -> None:
    capture = _capture()
    provider = OnlyBinanceUsdmBacktestResourceProvider()

    assert provider.load_reference(provider.dump_reference(capture.public_authority)) == capture.public_authority
    assert provider.load_reference(provider.dump_reference(capture.account_authority)) == capture.account_authority

    tampered = provider.dump_reference(capture.public_authority)
    tampered["authority_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="FINGERPRINT_CONFLICT"):
        provider.load_reference(tampered)


def test_normal_entry_point_factory_compiles_one_effective_profile_and_lossless_margin_curve() -> None:
    entries = metadata.entry_points().select(group="onlyalpha.market_products", name="binance-usdm")
    assert len(tuple(entries)) == 1
    factory = tuple(metadata.entry_points().select(group="onlyalpha.market_products", name="binance-usdm"))[0].load()()
    assert isinstance(factory, OnlyBinanceUsdmMarketProductFactory)
    capture = _capture()
    binding = _binding(capture)
    assert binding.effective_trading_profile is not None
    assert binding.effective_trading_profile.position_mode is OnlyPositionMode.NETTING
    engine = OnlyMarketRuleEngine(binding=binding, advance_trading_day=lambda day, lag: day)
    policy = engine.compiled_rules(str(INSTRUMENT), OnlyTradingDay(date(2026, 9, 1)), as_of=NOW)
    assert policy.effective_trading_profile is binding.effective_trading_profile
    assert policy.funding_policy is not None and policy.funding_policy.interval_seconds == 14_400
    curve = policy.compiled_margin_policy
    assert curve is not None
    epsilon = Decimal("0.01")
    assert curve.requirement(Decimal("100000") - epsilon) == (
        Decimal("9999.999"),
        Decimal("399.99996"),
    )
    assert curve.requirement(Decimal("100000")) == (Decimal("10000.0"), Decimal("400.000"))
    assert curve.requirement(Decimal("100000") + epsilon) == (
        Decimal("10000.001"),
        Decimal("400.00005"),
    )


def test_requested_and_account_effective_modes_cannot_silently_fallback() -> None:
    isolated = _capture(position_mode="HEDGING", margin_mode="ISOLATED")
    binding = _binding(isolated, position="HEDGING", margin="ISOLATED")
    assert binding.effective_trading_profile is not None
    assert binding.effective_trading_profile.position_mode is OnlyPositionMode.HEDGING
    assert binding.composition_identity.effective_trading_profile_fingerprint
    with pytest.raises(ValueError, match="ACCOUNT_EFFECTIVE_TRADING_PROFILE_MISMATCH"):
        _binding(isolated, position="NETTING", margin="CROSS")
    netting = _binding(_capture())
    assert netting.composition_identity != binding.composition_identity
    assert (
        netting.composition_identity.effective_trading_profile_fingerprint
        != binding.composition_identity.effective_trading_profile_fingerprint
    )


def test_usdm_funding_record_preserves_exact_mark_and_shared_lineage() -> None:
    normalizer = OnlyBinanceUsdmHistoricalNormalizer()
    mark, funding = normalizer.funding_boundary_facts(
        {
            "symbol": "BTCUSDT",
            "fundingTime": 1788249600000,
            "fundingRate": "0.0001",
            "markPrice": "60000.10",
            "rateType": "REGULAR",
        },
        instrument_id=INSTRUMENT,
        data_version="fixture-v2",
        source_sequence=7,
        received_at=NOW,
    )
    assert mark.kind is OnlyReferencePriceKind.MARK and mark.revision == 1
    assert mark.value.value == Decimal("60000.10") and funding.rate == Decimal("0.0001")
    assert mark.provider_evidence_id == funding.provider_evidence_id
    assert mark.source_record_hash == funding.source_record_hash
    assert mark.stable_order < funding.stable_order
    with pytest.raises(ValueError, match="RATE_TYPE_UNSUPPORTED"):
        normalizer.funding_boundary_facts(
            {
                "fundingTime": 1788249600000,
                "fundingRate": "0.0001",
                "markPrice": "60000.10",
                "rateType": "SPECIAL",
            },
            instrument_id=INSTRUMENT,
            data_version="fixture-v2",
            source_sequence=7,
            received_at=NOW,
        )
    with pytest.raises(ValueError, match="MARKPRICE_REQUIRED"):
        normalizer.funding_boundary_facts(
            {
                "fundingTime": 1788249600000,
                "fundingRate": "0.0001",
                "rateType": "REGULAR",
            },
            instrument_id=INSTRUMENT,
            data_version="fixture-v2",
            source_sequence=7,
            received_at=NOW,
        )


def test_usdm_reference_and_margin_authorities_fail_closed_at_missing_or_invalid_domains() -> None:
    capture = _capture()
    binding = _binding(capture)
    engine = OnlyMarketRuleEngine(binding=binding, advance_trading_day=lambda day, lag: day)
    policy = engine.compiled_rules(str(INSTRUMENT), OnlyTradingDay(date(2026, 9, 1)), as_of=NOW)
    assert policy.compiled_margin_policy is not None
    with pytest.raises(ValueError, match="MARGIN_NOTIONAL_OUTSIDE_COMPILED_DOMAIN"):
        policy.compiled_margin_policy.requirement(Decimal("500000.01"))

    class MissingAccountResources(_Resources):
        def require_reference_authority(self, resource_id: str):  # type: ignore[no-untyped-def]
            if resource_id == "account":
                raise ValueError("ACCOUNT_EFFECTIVE_REFERENCE_REQUIRED")
            return super().require_reference_authority(resource_id)

    config = OnlyMarketProductConfig(
        OnlyMarketProductPluginId("onlyalpha-plugin-binance-usdm"),
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
    with pytest.raises(ValueError, match="ACCOUNT_EFFECTIVE_REFERENCE_REQUIRED"):
        OnlyBinanceUsdmMarketProductFactory().resolve(
            config, OnlyMarketProductResolutionContext(MissingAccountResources(capture))
        )

    with pytest.raises(ValueError, match="REFERENCE_INVALID"):
        OnlyBinanceUsdmReferenceCapture.create(
            capture.evidence[0].raw_bytes,
            capture.evidence[1].raw_bytes,
            capture.evidence[2].raw_bytes,
            capture.evidence[3].raw_bytes,
            captured_at=NOW,
            coverage_start=NOW,
            coverage_end=NOW,
        )


class _RecordedHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_json(self, endpoint: str, parameters=None):  # type: ignore[no-untyped-def]
        self.calls.append((endpoint, {} if parameters is None else parameters))
        return b"[]"


def test_explicit_kline_http_contracts_preserve_endpoint_parameter_names() -> None:
    http = _RecordedHttp()
    client = OnlyBinanceUsdmHistoricalClient(http)  # type: ignore[arg-type]
    client.contract_klines("BTCUSDT", 1, 2, 3)
    client.mark_price_klines("BTCUSDT", 1, 2, 3)
    client.index_price_klines("BTCUSDT", 1, 2, 3)
    assert [(endpoint, sorted(parameters)) for endpoint, parameters in http.calls] == [
        ("/fapi/v1/klines", ["endTime", "interval", "limit", "startTime", "symbol"]),
        ("/fapi/v1/markPriceKlines", ["endTime", "interval", "limit", "startTime", "symbol"]),
        ("/fapi/v1/indexPriceKlines", ["endTime", "interval", "limit", "pair", "startTime"]),
    ]


class _RecordedUsdmHistoricalClient:
    def contract_klines(self, *args):  # type: ignore[no-untyped-def]
        return ()

    def mark_price_klines(self, symbol, start_ms, end_ms, limit):  # type: ignore[no-untyped-def]
        return ()

    def index_price_klines(self, pair, start_ms, end_ms, limit):  # type: ignore[no-untyped-def]
        return ()

    def funding_rates(self, symbol, start_ms, end_ms, limit):  # type: ignore[no-untyped-def]
        return (
            {
                "symbol": symbol,
                "fundingTime": start_ms,
                "fundingRate": "0.0001",
                "markPrice": "60000.00",
            },
        )


def test_funding_history_stream_orders_exact_mark_before_funding() -> None:
    start = datetime(2026, 9, 1, 8, tzinfo=UTC)
    end = datetime(2026, 9, 1, 8, 1, tzinfo=UTC)
    instrument = SimpleNamespace(
        instrument_id=INSTRUMENT, raw_symbol="BTCUSDT", price_precision=2, quantity_precision=3
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
    stream = source.load_facts(
        OnlyHistoricalFactRequest(
            INSTRUMENT,
            OnlyMarketDataType.FUNDING_RATE,
            OnlyTimeRange(start, end),
            OnlyDataVersion("fixture-v2"),
            batch_size=10,
        )
    )
    assert len(stream.records) == 2
    assert isinstance(stream.records[0].payload, OnlyReferencePriceUpdate)
    assert isinstance(stream.records[1].payload, OnlyFundingRateUpdate)
    assert stream.records[0].payload.fact.provider_evidence_id == stream.records[1].payload.fact.provider_evidence_id


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
