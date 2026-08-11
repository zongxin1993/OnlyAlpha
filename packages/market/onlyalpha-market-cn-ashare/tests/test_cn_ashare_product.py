from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest
from onlyalpha_market_cn_ashare.factory import OnlyCnAshareMarketProductFactory
from onlyalpha_market_cn_ashare.reference import OnlyCnAshareReferenceAuthority

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.market.product import (
    OnlyCanonicalMarketProductConfig,
    OnlyMarketPolicyCompilationRequest,
    OnlyMarketProductConfig,
    OnlyMarketProductId,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductVersion,
)


class _NoResources:
    def require_reference_authority(self, resource_id: str) -> None:
        raise AssertionError(resource_id)

    def require_market_fee_pack(self, pack_id: str, pack_version: str) -> None:
        raise AssertionError((pack_id, pack_version))


def _reference(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "instrument_id": "600000.XSHG",
        "exchange": "SSE",
        "security_type": "COMMON_STOCK",
        "board": "SSE_MAIN",
        "lot_size": "100",
        "price_tick": "0.01",
        "st_status": False,
        "suspended": False,
        "previous_close": "10.00",
        "effective_from": "2025-01-01",
        "effective_to": None,
        "source": "GOLDEN_DATASET",
        "source_version": "plugin-test-v1",
        "data_version": "plugin-test-v1",
    }
    value.update(changes)
    return value


def _config(*, product_id: str = "CN_A_SHARE_CASH", version: str = "2025.1", config=None):  # type: ignore[no-untyped-def]
    values = {"references": [_reference()]} if config is None else config
    return OnlyMarketProductConfig(
        OnlyMarketProductPluginId("onlyalpha-market-cn-ashare"),
        OnlyMarketProductId(product_id),
        OnlyMarketProductVersion(version),
        OnlyCanonicalMarketProductConfig(values),  # type: ignore[arg-type]
    )


def _binding(*, version: str = "2025.1", reference=None):  # type: ignore[no-untyped-def]
    values = {"references": [_reference() if reference is None else reference]}
    return OnlyCnAshareMarketProductFactory().resolve(
        _config(version=version, config=values), OnlyMarketProductResolutionContext(_NoResources())
    )


def test_factory_returns_one_immutable_effective_authority_bundle() -> None:
    first = _binding()
    repeated = _binding()
    assert first == repeated
    assert first.composition_identity.fingerprint
    assert isinstance(first.reference_authority, OnlyCnAshareReferenceAuthority)
    with pytest.raises(FrozenInstanceError):
        first.provider_plugin_id = OnlyMarketProductPluginId("changed")  # type: ignore[misc]


@pytest.mark.parametrize(
    ("config", "code"),
    [
        (_config(product_id="OTHER"), "UNSUPPORTED_MARKET_PRODUCT"),
        (_config(version="2099.1"), "UNSUPPORTED_MARKET_PRODUCT_VERSION"),
        (_config(config={}), "INVALID_CN_A_SHARE_CONFIGURATION"),
        (_config(config={"references": [_reference()], "fallback": True}), "INVALID_CN_A_SHARE_CONFIGURATION"),
    ],
)
def test_factory_fails_closed_for_unknown_identity_version_or_config(config, code: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match=code):
        OnlyCnAshareMarketProductFactory().resolve(config, OnlyMarketProductResolutionContext(_NoResources()))


def test_reference_identity_is_order_independent_and_conflicts_fail_closed() -> None:
    first = _reference(effective_to="2025-01-02")
    second = _reference(
        effective_from="2025-01-02",
        source_version="plugin-test-v2",
        previous_close="10.10",
    )
    left = _config(config={"references": [first, second]})
    right = _config(config={"references": [second, first]})
    factory = OnlyCnAshareMarketProductFactory()
    assert (
        factory.resolve(left, OnlyMarketProductResolutionContext(_NoResources())).composition_identity
        == factory.resolve(right, OnlyMarketProductResolutionContext(_NoResources())).composition_identity
    )
    with pytest.raises(ValueError, match="REFERENCE_EFFECTIVE_RANGE_OVERLAP"):
        _binding(reference=_reference(effective_to=None))
        factory.resolve(
            _config(config={"references": [_reference(), _reference(previous_close="9.99")]}),
            OnlyMarketProductResolutionContext(_NoResources()),
        )


def test_compiler_freezes_session_price_quantity_status_and_t1_semantics() -> None:
    binding = _binding()
    day = OnlyTradingDay(date(2026, 1, 5))
    policy = binding.policy_compiler.compile(
        OnlyMarketPolicyCompilationRequest(OnlyInstrumentId.parse("600000.XSHG"), day, binding.reference_authority)
    )
    assert policy.price_policy.daily_limit_rate == Decimal("0.10")
    assert policy.price_policy.previous_close == Decimal("10.00")
    assert policy.quantity_policy.minimum_buy_quantity == Decimal("100")
    assert policy.quantity_policy.buy_quantity_increment == Decimal("100")
    assert policy.quantity_policy.odd_lot_liquidation_allowed
    assert policy.settlement_policy.compile().legal_settlement_lag == 1
    assert policy.session_policy.model_id.startswith("CN_A_SHARE")


def test_market_fee_pack_is_sell_stamp_duty_and_bilateral_transfer_fee() -> None:
    pack = _binding().market_fee_pack
    stamp = tuple(rule for schedule in pack.schedules for rule in schedule.rules if "STAMP" in schedule.schedule_id)
    transfer = tuple(
        rule for schedule in pack.schedules for rule in schedule.rules if "TRANSFER" in schedule.schedule_id
    )
    assert stamp and all(rule.side is OnlyOrderSide.SELL for rule in stamp)
    assert transfer and all(rule.side is None for rule in transfer)
