from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest
from onlyalpha_market_generic_t0_cash.compiler import OnlyGenericT0CashPolicyCompiler
from onlyalpha_market_generic_t0_cash.factory import OnlyGenericT0CashMarketProductFactory
from onlyalpha_market_generic_t0_cash.reference import (
    OnlyGenericT0CashReference,
    OnlyGenericT0CashReferenceAuthority,
)

from onlyalpha.domain.enums import OnlyMarketType
from onlyalpha.domain.identifiers import OnlyRawSymbol
from onlyalpha.domain.instrument import OnlyEquity
from onlyalpha.domain.value import OnlyCurrency, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.plugin.api import (
    OnlyAssetClass,
    OnlyCanonicalMarketProductConfig,
    OnlyInstrumentId,
    OnlyInstrumentTradingStatus,
    OnlyInvalidMarketProductConfigurationError,
    OnlyMarketPolicyCompilationRequest,
    OnlyMarketProductConfig,
    OnlyMarketProductId,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductResolutionError,
    OnlyMarketProductVersion,
    OnlyTradingDay,
    OnlyUnsupportedMarketProductError,
    OnlyUnsupportedMarketProductVersionError,
)

INSTRUMENT = OnlyInstrumentId.parse("TEST.GENERIC")
DAY = OnlyTradingDay(date(2026, 8, 11))


def _reference(
    *,
    tick_size: Decimal = Decimal("0.01"),
    quantity_step: Decimal = Decimal("0.001"),
    minimum_quantity: Decimal | None = Decimal("0.005"),
    maximum_quantity: Decimal | None = Decimal("1000000"),
    active: bool = True,
    suspended: bool = False,
    effective_from: date = date(1970, 1, 1),
    effective_to: date | None = None,
) -> OnlyGenericT0CashReference:
    return OnlyGenericT0CashReference.create(
        instrument_id=INSTRUMENT,
        asset_class=OnlyAssetClass.EQUITY,
        settlement_currency="CNY",
        contract_multiplier=Decimal("1"),
        tick_size=tick_size,
        quantity_step=quantity_step,
        minimum_quantity=minimum_quantity,
        maximum_quantity=maximum_quantity,
        effective_from=effective_from,
        effective_to=effective_to,
        active=active,
        suspended=suspended,
    )


def _authority(
    *references: OnlyGenericT0CashReference,
    authority_id: str = "generic-reference",
) -> OnlyGenericT0CashReferenceAuthority:
    return OnlyGenericT0CashReferenceAuthority.create(
        authority_id=authority_id,
        authority_version="1",
        references=tuple(references) or (_reference(),),
    )


class _NoResources:
    def require_reference_authority(self, resource_id: str) -> None:
        raise AssertionError(resource_id)

    def require_market_fee_pack(self, pack_id: str, pack_version: str) -> None:
        raise AssertionError(f"Generic plugin must own its Market Fee Pack, not request {pack_id}@{pack_version}")


def _instrument(*, tick_size: Decimal = Decimal("0.01")) -> OnlyEquity:
    return OnlyEquity(
        instrument_id=INSTRUMENT,
        raw_symbol=OnlyRawSymbol("TEST"),
        market_type=OnlyMarketType.CASH,
        quote_currency=OnlyCurrency("CNY"),
        settlement_currency=OnlyCurrency("CNY"),
        price_precision=2,
        quantity_precision=3,
        tick_size=OnlyPrice(tick_size, 2),
        step_size=OnlyQuantity(Decimal("0.001"), 3),
        contract_multiplier=OnlyMultiplier(Decimal("1"), 0),
        minimum_quantity=OnlyQuantity(Decimal("0.005"), 3),
        maximum_quantity=OnlyQuantity(Decimal("1000000.000"), 3),
    )


def _config(
    *,
    product_id: str = "GENERIC_T0_CASH",
    version: str = "1",
    values: dict[str, object] | None = None,
) -> OnlyMarketProductConfig:
    return OnlyMarketProductConfig(
        OnlyMarketProductPluginId("onlyalpha-market-generic-t0-cash"),
        OnlyMarketProductId(product_id),
        OnlyMarketProductVersion(version),
        OnlyCanonicalMarketProductConfig(values or {}),
    )


def _binding() -> object:
    return OnlyGenericT0CashMarketProductFactory().resolve(
        _config(),
        OnlyMarketProductResolutionContext(_NoResources(), (_instrument(),)),
    )


def test_factory_resolves_immutable_binding_and_effective_identity() -> None:
    factory = OnlyGenericT0CashMarketProductFactory()
    first = factory.resolve(_config(), OnlyMarketProductResolutionContext(_NoResources(), (_instrument(),)))
    repeated = factory.resolve(_config(), OnlyMarketProductResolutionContext(_NoResources(), (_instrument(),)))
    changed = factory.resolve(
        _config(),
        OnlyMarketProductResolutionContext(_NoResources(), (_instrument(tick_size=Decimal("0.02")),)),
    )

    assert first.product_identity.canonical_name == "GENERIC_T0_CASH@1"
    assert first.composition_identity == repeated.composition_identity
    assert first.composition_identity != changed.composition_identity
    with pytest.raises(FrozenInstanceError):
        first.product_identity = repeated.product_identity  # type: ignore[misc]


@pytest.mark.parametrize(
    ("config", "error", "code"),
    [
        (_config(product_id="OTHER"), OnlyUnsupportedMarketProductError, "UNSUPPORTED_MARKET_PRODUCT"),
        (_config(version="2"), OnlyUnsupportedMarketProductVersionError, "UNSUPPORTED_MARKET_PRODUCT_VERSION"),
        (
            _config(values={"settlement": "T1"}),
            OnlyInvalidMarketProductConfigurationError,
            "INVALID_GENERIC_T0_CASH_CONFIGURATION",
        ),
    ],
)
def test_factory_fails_closed_for_wrong_identity_or_invalid_config(
    config: OnlyMarketProductConfig,
    error: type[Exception],
    code: str,
) -> None:
    with pytest.raises(error, match=code):
        OnlyGenericT0CashMarketProductFactory().resolve(
            config,
            OnlyMarketProductResolutionContext(_NoResources(), (_instrument(),)),
        )


def test_missing_and_ambiguous_reference_fail_closed() -> None:
    with pytest.raises(ValueError, match="GENERIC_T0_CASH_INSTRUMENT_RESOURCES_REQUIRED"):
        OnlyGenericT0CashMarketProductFactory().resolve(
            _config(),
            OnlyMarketProductResolutionContext(_NoResources()),
        )

    ambiguous = _authority(
        _reference(effective_from=date(2020, 1, 1)),
        _reference(effective_from=date(2021, 1, 1)),
    )
    with pytest.raises(OnlyMarketProductResolutionError, match="GENERIC_T0_CASH_REFERENCE_AMBIGUOUS"):
        ambiguous.resolve(INSTRUMENT, DAY)


def test_policy_is_deterministic_and_contains_only_market_economics() -> None:
    authority = _authority()
    compiler = OnlyGenericT0CashPolicyCompiler()
    request = OnlyMarketPolicyCompilationRequest(INSTRUMENT, DAY, authority)
    first = compiler.compile(request)
    repeated = compiler.compile(request)

    assert first == repeated
    assert first.session_policy.model_id == "GENERIC_DAY"
    assert first.price_policy.tick_size == Decimal("0.01")
    assert first.price_policy.daily_limit_rate is None
    assert first.price_policy.previous_close is None
    assert first.quantity_policy.minimum_buy_quantity == Decimal("0.005")
    assert first.quantity_policy.buy_quantity_increment == Decimal("0.001")
    assert first.quantity_policy.allow_fractional is True
    assert first.position_policy.mode.value == "LONG_ONLY"
    assert first.short_policy.mode.value == "DISABLED"
    assert first.settlement_policy.compile().legal_settlement_lag == 0
    assert first.margin_policy is None
    assert first.instrument_terms.settlement_currency == "CNY"
    assert first.instrument_terms.contract_multiplier == Decimal("1")
    assert first.instrument_terms.trading_status is OnlyInstrumentTradingStatus.TRADABLE
    assert not any(hasattr(first, field) for field in ("matching_policy", "slippage_policy", "liquidity_policy"))


@pytest.mark.parametrize(
    ("active", "suspended", "status"),
    [
        (True, False, OnlyInstrumentTradingStatus.TRADABLE),
        (True, True, OnlyInstrumentTradingStatus.SUSPENDED),
        (False, False, OnlyInstrumentTradingStatus.INACTIVE),
    ],
)
def test_reference_lifecycle_compiles_to_canonical_status(
    active: bool,
    suspended: bool,
    status: OnlyInstrumentTradingStatus,
) -> None:
    authority = _authority(_reference(active=active, suspended=suspended))
    policy = OnlyGenericT0CashPolicyCompiler().compile(OnlyMarketPolicyCompilationRequest(INSTRUMENT, DAY, authority))
    assert policy.instrument_terms.trading_status is status
