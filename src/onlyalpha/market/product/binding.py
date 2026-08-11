"""Immutable resolved authority bundle consumed by a Trading Runtime."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.fee.market_pack import OnlyMarketFeePack
from onlyalpha.market.product.errors import OnlyMarketProductAuthorityConflictError
from onlyalpha.market.product.identity import (
    OnlyMarketProductCompositionIdentity,
    OnlyMarketProductIdentity,
    OnlyMarketProductPluginId,
)
from onlyalpha.market.product.ports import OnlyMarketPolicyCompiler, OnlyMarketReferenceAuthority


@dataclass(frozen=True, slots=True)
class OnlyResolvedMarketProductBinding:
    product_identity: OnlyMarketProductIdentity
    provider_plugin_id: OnlyMarketProductPluginId
    reference_authority: OnlyMarketReferenceAuthority
    policy_compiler: OnlyMarketPolicyCompiler
    market_fee_pack: OnlyMarketFeePack
    composition_identity: OnlyMarketProductCompositionIdentity

    def __post_init__(self) -> None:
        expected = OnlyMarketProductCompositionIdentity.create(
            product_identity=self.product_identity,
            reference_authority=self.reference_authority.identity,
            policy_compiler=self.policy_compiler.identity,
            market_fee_pack=self.market_fee_pack.identity,
            effective_config_fingerprint=self.composition_identity.effective_config_fingerprint,
        )
        if self.composition_identity != expected:
            raise OnlyMarketProductAuthorityConflictError(
                "MARKET_PRODUCT_BINDING_IDENTITY_CONFLICT",
                "binding authorities do not match composition identity",
            )


__all__ = ["OnlyResolvedMarketProductBinding"]
