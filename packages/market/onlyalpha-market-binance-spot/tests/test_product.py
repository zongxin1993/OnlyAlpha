from datetime import UTC, date, datetime
from decimal import Decimal
from importlib import metadata

from onlyalpha_market_binance_spot.capability import OnlyBinanceSpotCompatibilityStatus
from onlyalpha_market_binance_spot.factory import OnlyBinanceSpotMarketProductFactory
from onlyalpha_market_binance_spot.reference import OnlyBinanceSpotReference, OnlyBinanceSpotReferenceAuthority

from onlyalpha.plugin.api import (
    OnlyCanonicalMarketProductConfig,
    OnlyInstrumentId,
    OnlyMarketPolicyCompilationRequest,
    OnlyMarketProductConfig,
    OnlyMarketProductId,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductVersion,
    OnlyTradingDay,
)


def _authority() -> OnlyBinanceSpotReferenceAuthority:
    references = tuple(
        OnlyBinanceSpotReference.create(
            instrument_id=OnlyInstrumentId.parse(f"{symbol}.BINANCE"),
            raw_symbol=symbol,
            base_currency=base,
            quote_currency="USDT",
            provider_status="TRADING",
            spot_trading_allowed=True,
            price_tick=Decimal("0.01"),
            minimum_price=Decimal("0.01"),
            maximum_price=Decimal("1000000"),
            quantity_step=step,
            minimum_quantity=step,
            maximum_quantity=Decimal("9000"),
            market_quantity_step=None,
            market_minimum_quantity=None,
            market_maximum_quantity=None,
            minimum_notional=Decimal("5"),
            maximum_notional=None,
            venue_order_types=("LIMIT", "MARKET"),
            time_in_force=("GTC", "IOC", "FOK"),
            order_group_capabilities=("OCO", "OTO", "OPO"),
            default_stp_mode="NONE",
            allowed_stp_modes=("NONE",),
            permission_sets=(("SPOT",),),
            capabilities=(),
            rules=(),
            source_raw_fingerprints=("0" * 64,),
            compatibility_status=OnlyBinanceSpotCompatibilityStatus.COMPATIBLE,
            observed_at=datetime(2026, 8, 28, 12, tzinfo=UTC),
        )
        for symbol, base, step in (("BTCUSDT", "BTC", Decimal("0.00001")), ("ETHUSDT", "ETH", Decimal("0.0001")))
    )
    return OnlyBinanceSpotReferenceAuthority.create(references)


class _Resources:
    def __init__(self, authority):
        self.authority = authority

    def require_reference_authority(self, resource_id: str):
        assert resource_id == "sha256:test"
        return self.authority

    def require_market_fee_pack(self, pack_id: str, pack_version: str):
        raise AssertionError


def test_exact_offline_binding_and_crypto_spot_policy_are_deterministic() -> None:
    authority = _authority()
    raw = OnlyCanonicalMarketProductConfig(
        {
            "reference_resource_id": "sha256:test",
            "expected_reference_fingerprint": authority.identity.authority_fingerprint,
            "maker_fee_rate": "0.001",
            "taker_fee_rate": "0.001",
        }
    )
    config = OnlyMarketProductConfig(
        OnlyMarketProductPluginId("onlyalpha-market-binance-spot"),
        OnlyMarketProductId("BINANCE_SPOT"),
        OnlyMarketProductVersion("1"),
        raw,
    )
    factory = OnlyBinanceSpotMarketProductFactory()
    first = factory.resolve(config, OnlyMarketProductResolutionContext(_Resources(authority)))
    second = factory.resolve(config, OnlyMarketProductResolutionContext(_Resources(authority)))
    assert first.composition_identity == second.composition_identity
    policy = first.policy_compiler.compile(
        OnlyMarketPolicyCompilationRequest(
            OnlyInstrumentId.parse("BTCUSDT.BINANCE"), OnlyTradingDay(date(2026, 8, 29)), authority
        )
    )
    assert policy.session_policy.timezone == "UTC" and policy.session_policy.continuous_24x7
    assert policy.position_policy.mode.value == "LONG_ONLY" and policy.margin_policy is None
    assert policy.price_policy.tick_size == Decimal("0.01")
    assert policy.quantity_policy.buy_quantity_increment == Decimal("0.00001")
    assert policy.instrument_terms.trading_status.value == "TRADABLE"


def test_market_product_entry_point_is_discoverable() -> None:
    entries = metadata.entry_points().select(group="onlyalpha.market_products")
    matches = [item for item in entries if item.name == "binance-spot"]
    assert len(matches) == 1
    assert isinstance(matches[0].load()(), OnlyBinanceSpotMarketProductFactory)
