"""Concrete Market Product factory and immutable binding composition."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from onlyalpha.plugin.api import (
    OnlyMarketProductCompositionIdentity,
    OnlyMarketProductConfig,
    OnlyMarketProductId,
    OnlyMarketProductIdentity,
    OnlyMarketProductPluginId,
    OnlyMarketProductResolutionContext,
    OnlyMarketProductVersion,
    OnlyResolvedMarketProductBinding,
    OnlyUnsupportedMarketProductError,
    OnlyUnsupportedMarketProductVersionError,
    only_canonical_fingerprint,
)
from onlyalpha_market_generic_t0_cash.compiler import OnlyGenericT0CashPolicyCompiler
from onlyalpha_market_generic_t0_cash.config import OnlyGenericT0CashConfig
from onlyalpha_market_generic_t0_cash.fee_pack import only_generic_t0_cash_market_fee_pack
from onlyalpha_market_generic_t0_cash.reference import (
    OnlyGenericT0CashReference,
    OnlyGenericT0CashReferenceAuthority,
)

PLUGIN_ID = OnlyMarketProductPluginId("onlyalpha-market-generic-t0-cash")
PRODUCT_ID = OnlyMarketProductId("GENERIC_T0_CASH")
PRODUCT_VERSION = OnlyMarketProductVersion("1")


@dataclass(frozen=True, slots=True)
class OnlyGenericT0CashMarketProductFactory:
    plugin_id: OnlyMarketProductPluginId = PLUGIN_ID
    _compiler: OnlyGenericT0CashPolicyCompiler = field(default_factory=OnlyGenericT0CashPolicyCompiler)

    def resolve(
        self,
        config: OnlyMarketProductConfig,
        context: OnlyMarketProductResolutionContext,
    ) -> OnlyResolvedMarketProductBinding:
        if config.plugin_id != self.plugin_id:
            raise ValueError("GENERIC_T0_CASH_PROVIDER_IDENTITY_MISMATCH")
        if config.product_id != PRODUCT_ID:
            raise OnlyUnsupportedMarketProductError(
                "UNSUPPORTED_MARKET_PRODUCT",
                str(config.product_id),
            )
        if config.product_version != PRODUCT_VERSION:
            raise OnlyUnsupportedMarketProductVersionError(
                "UNSUPPORTED_MARKET_PRODUCT_VERSION",
                str(config.product_version),
            )
        OnlyGenericT0CashConfig.parse(config.config)
        if not context.instruments:
            raise ValueError("GENERIC_T0_CASH_INSTRUMENT_RESOURCES_REQUIRED")
        reference_authority = OnlyGenericT0CashReferenceAuthority.create(
            authority_id="GENERIC_T0_CASH",
            authority_version="1",
            references=tuple(
                OnlyGenericT0CashReference.create(
                    instrument_id=item.instrument_id,
                    asset_class=item.asset_class,
                    settlement_currency=item.settlement_currency.code,
                    contract_multiplier=item.contract_multiplier.value,
                    tick_size=item.tick_size.value,
                    quantity_step=item.step_size.value,
                    minimum_quantity=None if item.minimum_quantity is None else item.minimum_quantity.value,
                    maximum_quantity=None if item.maximum_quantity is None else item.maximum_quantity.value,
                    effective_from=(item.effective_from.date() if item.effective_from else date(1970, 1, 1)),
                    effective_to=None if item.effective_to is None else item.effective_to.date(),
                    active=item.status.value == "ACTIVE",
                )
                for item in context.instruments
            ),
        )
        fee_pack = only_generic_t0_cash_market_fee_pack()
        identity = OnlyMarketProductIdentity(PRODUCT_ID, PRODUCT_VERSION)
        composition = OnlyMarketProductCompositionIdentity.create(
            product_identity=identity,
            reference_authority=reference_authority.identity,
            policy_compiler=self._compiler.identity,
            market_fee_pack=fee_pack.identity,
            effective_config_fingerprint=only_canonical_fingerprint(()),
        )
        return OnlyResolvedMarketProductBinding(
            identity,
            self.plugin_id,
            reference_authority,
            self._compiler,
            fee_pack,
            composition,
        )


__all__ = ["OnlyGenericT0CashMarketProductFactory"]
