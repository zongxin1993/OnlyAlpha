from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
from datetime import date
from decimal import Decimal

import pytest
from onlyalpha_market_generic_t0_cash.compiler import OnlyGenericT0CashPolicyCompiler
from onlyalpha_market_generic_t0_cash.factory import OnlyGenericT0CashMarketProductFactory
from onlyalpha_market_generic_t0_cash.reference import (
    OnlyGenericT0CashReference,
    OnlyGenericT0CashReferenceAuthority,
)

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


@dataclass(frozen=True, slots=True)
class _Resources:
    authorities: dict[str, OnlyGenericT0CashReferenceAuthority]

    def require_reference_authority(self, resource_id: str) -> OnlyGenericT0CashReferenceAuthority:
        try:
            return self.authorities[resource_id]
        except KeyError as exc:
            raise OnlyMarketProductResolutionError("MARKET_REFERENCE_AUTHORITY_NOT_FOUND", resource_id) from exc

    def require_market_fee_pack(self, pack_id: str, pack_version: str) -> None:
        raise AssertionError(f"Generic plugin must own its Market Fee Pack, not request {pack_id}@{pack_version}")


def _config(
    *,
    resource_id: str = "primary",
    product_id: str = "GENERIC_T0_CASH",
    version: str = "1",
    values: dict[str, object] | None = None,
) -> OnlyMarketProductConfig:
    return OnlyMarketProductConfig(
        OnlyMarketProductPluginId("onlyalpha-market-generic-t0-cash"),
        OnlyMarketProductId(product_id),
        OnlyMarketProductVersion(version),
        OnlyCanonicalMarketProductConfig(values if values is not None else {"reference_resource_id": resource_id}),
    )


def _binding(
    authority: OnlyGenericT0CashReferenceAuthority | None = None,
    *,
    resource_id: str = "primary",
) -> object:
    selected = authority or _authority()
    return OnlyGenericT0CashMarketProductFactory().resolve(
        _config(resource_id=resource_id),
        OnlyMarketProductResolutionContext(_Resources({resource_id: selected})),
    )


def test_factory_resolves_immutable_binding_and_effective_identity() -> None:
    authority = _authority()
    resources = _Resources({"alias-a": authority, "alias-b": authority})
    factory = OnlyGenericT0CashMarketProductFactory()
    first = factory.resolve(_config(resource_id="alias-a"), OnlyMarketProductResolutionContext(resources))
    repeated = factory.resolve(_config(resource_id="alias-b"), OnlyMarketProductResolutionContext(resources))
    changed = factory.resolve(
        _config(resource_id="changed"),
        OnlyMarketProductResolutionContext(_Resources({"changed": _authority(authority_id="changed-reference")})),
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
            _config(values={"reference_resource_id": "primary", "settlement": "T1"}),
            OnlyInvalidMarketProductConfigurationError,
            "INVALID_GENERIC_T0_CASH_CONFIGURATION",
        ),
        (
            _config(values={}),
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
            OnlyMarketProductResolutionContext(_Resources({"primary": _authority()})),
        )


def test_missing_and_ambiguous_reference_fail_closed() -> None:
    with pytest.raises(OnlyMarketProductResolutionError, match="MARKET_REFERENCE_AUTHORITY_NOT_FOUND"):
        OnlyGenericT0CashMarketProductFactory().resolve(
            _config(resource_id="missing"),
            OnlyMarketProductResolutionContext(_Resources({})),
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
