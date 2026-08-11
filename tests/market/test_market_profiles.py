from datetime import date

import pytest

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.market.product import OnlyMarketPolicyCompilationRequest, OnlyMarketProductPluginId
from onlyalpha.runtime.defaults import only_default_engine_services
from tests.runtime_support.market_product import only_cn_ashare_market_product, only_generic_market_product


def _instrument():  # type: ignore[no-untyped-def]
    return OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json").reference_data.instruments[0]


def _policy(binding, day: date):  # type: ignore[no-untyped-def]
    trading_day = OnlyTradingDay(day)
    return binding.policy_compiler.compile(
        OnlyMarketPolicyCompilationRequest(_instrument().instrument_id, trading_day, binding.reference_authority)
    )


def test_profile_production_modules_are_retired() -> None:
    with pytest.raises(ModuleNotFoundError):
        __import__("onlyalpha.market.profiles")
    with pytest.raises(ModuleNotFoundError):
        __import__("onlyalpha.market.registry")


def test_t0_and_a_share_t1_are_compiled_by_independent_products() -> None:
    generic = _policy(only_generic_market_product(_instrument()), date(2026, 1, 5))
    ashare = _policy(only_cn_ashare_market_product(_instrument(), previous_close="10.00"), date(2026, 1, 5))
    assert generic.settlement_policy.compile().legal_settlement_lag == 0
    assert ashare.settlement_policy.compile().legal_settlement_lag == 1


def test_uninstalled_crypto_product_fails_closed_without_generic_fallback() -> None:
    registry = only_default_engine_services().assembler.components.market_products
    with pytest.raises(ValueError, match="MARKET_PRODUCT_PLUGIN_NOT_REGISTERED"):
        registry.require(OnlyMarketProductPluginId("onlyalpha-market-crypto-spot"))


def test_uninstalled_futures_product_fails_closed_without_core_profile() -> None:
    registry = only_default_engine_services().assembler.components.market_products
    with pytest.raises(ValueError, match="MARKET_PRODUCT_PLUGIN_NOT_REGISTERED"):
        registry.require(OnlyMarketProductPluginId("onlyalpha-market-generic-futures"))


def test_a_share_versions_freeze_distinct_compiler_authorities() -> None:
    old = only_cn_ashare_market_product(_instrument(), previous_close="10.00", product_version="2025.1")
    current = only_cn_ashare_market_product(_instrument(), previous_close="10.00", product_version="2026.07")
    assert old.policy_compiler.identity != current.policy_compiler.identity
    assert _policy(old, date(2026, 1, 5)).session_policy == _policy(old, date(2026, 1, 5)).session_policy


def test_canonical_market_policy_excludes_simulation_liquidity() -> None:
    policy = _policy(only_generic_market_product(_instrument()), date(2026, 1, 5))
    assert not any(hasattr(policy, name) for name in ("liquidity_model", "matching_model", "slippage_model"))
