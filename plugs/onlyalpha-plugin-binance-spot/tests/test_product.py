from datetime import UTC, date, datetime
from decimal import Decimal
from importlib import metadata

import pytest
from onlyalpha_plugin_binance_spot.capability import OnlyBinanceSpotCompatibilityStatus
from onlyalpha_plugin_binance_spot.factory import OnlyBinanceSpotMarketProductFactory
from onlyalpha_plugin_binance_spot.reference import (
    OnlyBinanceSpotReference,
    OnlyBinanceSpotReferenceAuthority,
    OnlyBinanceSpotRule,
)

from onlyalpha.market.runtime_rules import OnlyMarketRuleEngine, OnlyPreTradeMarketContext
from onlyalpha.plugin.api import (
    OnlyCanonicalMarketProductConfig,
    OnlyCompiledMarketPolicy,
    OnlyCompiledNotionalPolicy,
    OnlyInstrumentId,
    OnlyMarketPolicyCompilationRequest,
    OnlyMarketProductConfig,
    OnlyMarketProductId,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductVersion,
    OnlyOrderSide,
    OnlyTradingDay,
)


def _authority(*, observed_at: datetime = datetime(2026, 8, 28, 12, tzinfo=UTC)) -> OnlyBinanceSpotReferenceAuthority:
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
            maximum_notional=Decimal("100"),
            minimum_notional_applies_to_market=True,
            maximum_notional_applies_to_market=False,
            notional_reference_window_minutes=5,
            venue_order_types=("LIMIT", "MARKET"),
            time_in_force=("GTC", "IOC", "FOK"),
            order_group_capabilities=("OCO", "OTO", "OPO"),
            default_stp_mode="NONE",
            allowed_stp_modes=("NONE",),
            permission_sets=(("SPOT",),),
            capabilities=(),
            rules=(
                OnlyBinanceSpotRule(
                    "PERCENT_PRICE",
                    "DYNAMIC",
                    (("avgPriceMins", 5), ("multiplierDown", "0.2"), ("multiplierUp", "5")),
                ),
            ),
            source_raw_fingerprints=("0" * 64,),
            compatibility_status=OnlyBinanceSpotCompatibilityStatus.COMPATIBLE,
            observed_at=observed_at,
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
        OnlyMarketProductPluginId("onlyalpha-plugin-binance-spot"),
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
    assert policy.position_mode.value == "NETTING" and policy.short_policy.mode.value == "DISABLED"
    assert policy.margin_policy is None
    assert policy.price_policy.tick_size == Decimal("0.01")
    assert policy.quantity_policy.buy_quantity_increment == Decimal("0.00001")
    assert policy.quantity_policy.market_maximum_quantity is None
    assert policy.notional_policy is not None
    assert policy.notional_policy.minimum_notional == Decimal("5")
    assert policy.notional_policy.maximum_notional == Decimal("100")
    assert policy.dynamic_price_requirements[0].rule_id == "PERCENT_PRICE"
    assert policy.dynamic_price_requirements[0].reference_kind == "VENUE_REFERENCE_PRICE_OR_TRADE_AVERAGE"
    assert policy.instrument_terms.trading_status.value == "TRADABLE"
    changed = OnlyCompiledMarketPolicy.create(
        instrument_id=policy.identity.instrument_id,
        trading_day=policy.identity.trading_day,
        reference_fingerprint=policy.identity.reference_fingerprint,
        compiler=policy.identity.compiler,
        instrument_terms=policy.instrument_terms,
        session_policy=policy.session_policy,
        price_policy=policy.price_policy,
        quantity_policy=policy.quantity_policy,
        position_policy=policy.position_policy,
        short_policy=policy.short_policy,
        settlement_policy=policy.settlement_policy,
        margin_policy=policy.margin_policy,
        notional_policy=OnlyCompiledNotionalPolicy(Decimal("6"), Decimal("100"), True, False, 5),
        dynamic_price_requirements=policy.dynamic_price_requirements,
    )
    assert changed.identity.policy_fingerprint != policy.identity.policy_fingerprint


def test_exact_as_of_boundary_and_runtime_cache_fail_closed() -> None:
    observed = datetime(2026, 8, 28, 10, tzinfo=UTC)
    authority = _authority(observed_at=observed)
    raw = OnlyCanonicalMarketProductConfig(
        {
            "reference_resource_id": "sha256:test",
            "expected_reference_fingerprint": authority.identity.authority_fingerprint,
            "maker_fee_rate": "0.001",
            "taker_fee_rate": "0.001",
        }
    )
    binding = OnlyBinanceSpotMarketProductFactory().resolve(
        OnlyMarketProductConfig(
            OnlyMarketProductPluginId("onlyalpha-plugin-binance-spot"),
            OnlyMarketProductId("BINANCE_SPOT"),
            OnlyMarketProductVersion("1"),
            raw,
        ),
        OnlyMarketProductResolutionContext(_Resources(authority)),
    )
    day = OnlyTradingDay(date(2026, 8, 28))

    def request(as_of: datetime) -> OnlyMarketPolicyCompilationRequest:
        return OnlyMarketPolicyCompilationRequest(OnlyInstrumentId.parse("BTCUSDT.BINANCE"), day, authority, as_of)

    with pytest.raises(ValueError, match="HISTORICAL_COVERAGE_UNPROVEN"):
        binding.policy_compiler.compile(request(datetime(2026, 8, 28, 9, 59, tzinfo=UTC)))
    assert binding.policy_compiler.compile(request(observed)).identity.reference_fingerprint
    assert binding.policy_compiler.compile(
        request(datetime(2026, 8, 28, 11, tzinfo=UTC))
    ).identity.reference_fingerprint

    engine = OnlyMarketRuleEngine(binding=binding, advance_trading_day=lambda value, lag: value)
    later = engine.evaluate_pre_trade(
        OnlyPreTradeMarketContext(
            "BTCUSDT.BINANCE",
            OnlyOrderSide.BUY,
            Decimal("1"),
            Decimal("10"),
            datetime(2026, 8, 28, 11, tzinfo=UTC),
            day,
            trade_available_cash=Decimal("100"),
        )
    )
    earlier = engine.evaluate_pre_trade(
        OnlyPreTradeMarketContext(
            "BTCUSDT.BINANCE",
            OnlyOrderSide.BUY,
            Decimal("1"),
            Decimal("10"),
            datetime(2026, 8, 28, 9, tzinfo=UTC),
            day,
            trade_available_cash=Decimal("100"),
        )
    )
    assert later.accepted
    assert not earlier.accepted and "HISTORICAL_COVERAGE_UNPROVEN" in str(earlier.reason_code)


@pytest.mark.parametrize(
    ("price", "expected_reason"),
    (
        (Decimal("4"), "NOTIONAL_BELOW_MINIMUM"),
        (Decimal("10"), None),
        (Decimal("101"), "NOTIONAL_ABOVE_MAXIMUM"),
    ),
)
def test_limit_notional_is_formally_enforced(price: Decimal, expected_reason: str | None) -> None:
    authority = _authority(observed_at=datetime(2026, 8, 27, 10, tzinfo=UTC))
    config = OnlyMarketProductConfig(
        OnlyMarketProductPluginId("onlyalpha-plugin-binance-spot"),
        OnlyMarketProductId("BINANCE_SPOT"),
        OnlyMarketProductVersion("1"),
        OnlyCanonicalMarketProductConfig(
            {
                "reference_resource_id": "sha256:test",
                "expected_reference_fingerprint": authority.identity.authority_fingerprint,
                "maker_fee_rate": "0.001",
                "taker_fee_rate": "0.001",
            }
        ),
    )
    binding = OnlyBinanceSpotMarketProductFactory().resolve(
        config, OnlyMarketProductResolutionContext(_Resources(authority))
    )
    engine = OnlyMarketRuleEngine(binding=binding, advance_trading_day=lambda value, lag: value)
    decision = engine.evaluate_pre_trade(
        OnlyPreTradeMarketContext(
            "BTCUSDT.BINANCE",
            OnlyOrderSide.BUY,
            Decimal("1"),
            price,
            datetime(2026, 8, 28, 11, tzinfo=UTC),
            OnlyTradingDay(date(2026, 8, 28)),
            trade_available_cash=Decimal("1000"),
        )
    )
    assert decision.accepted is (expected_reason is None)
    assert decision.reason_code == expected_reason


def test_market_product_entry_point_is_discoverable() -> None:
    entries = metadata.entry_points().select(group="onlyalpha.market_products")
    matches = [item for item in entries if item.name == "binance-spot"]
    assert len(matches) == 1
    assert isinstance(matches[0].load()(), OnlyBinanceSpotMarketProductFactory)
