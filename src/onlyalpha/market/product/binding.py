"""Immutable resolved authority bundle consumed by a Trading Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self

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
        authority_identity = (
            self.product_identity,
            self.reference_authority.identity,
            self.policy_compiler.identity,
            self.market_fee_pack.identity,
        )
        composition_authority = (
            self.composition_identity.product_identity,
            self.composition_identity.reference_authority,
            self.composition_identity.policy_compiler,
            self.composition_identity.market_fee_pack,
        )
        if authority_identity != composition_authority:
            raise OnlyMarketProductAuthorityConflictError(
                "MARKET_PRODUCT_BINDING_IDENTITY_CONFLICT",
                "binding authorities do not match composition identity",
            )

    @classmethod
    def create(
        cls,
        *,
        product_identity: OnlyMarketProductIdentity,
        provider_plugin_id: OnlyMarketProductPluginId,
        reference_authority: OnlyMarketReferenceAuthority,
        policy_compiler: OnlyMarketPolicyCompiler,
        market_fee_pack: OnlyMarketFeePack,
        effective_config_fingerprint: str,
    ) -> Self:
        composition_identity = OnlyMarketProductCompositionIdentity.create(
            product_identity=product_identity,
            reference_authority=reference_authority.identity,
            policy_compiler=policy_compiler.identity,
            market_fee_pack=market_fee_pack.identity,
            effective_config_fingerprint=effective_config_fingerprint,
        )
        return cls(
            product_identity,
            provider_plugin_id,
            reference_authority,
            policy_compiler,
            market_fee_pack,
            composition_identity,
        )


__all__ = ["OnlyResolvedMarketProductBinding"]
