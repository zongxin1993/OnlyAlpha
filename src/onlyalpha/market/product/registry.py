"""Explicit, fail-closed Market Product factory lookup authority."""

from __future__ import annotations

from onlyalpha.market.product.binding import OnlyResolvedMarketProductBinding
from onlyalpha.market.product.config import OnlyMarketProductConfig
from onlyalpha.market.product.contracts import (
    OnlyMarketProductFactory,
    OnlyMarketProductResolutionContext,
)
from onlyalpha.market.product.errors import (
    OnlyDuplicateMarketProductPluginError,
    OnlyMarketProductAuthorityConflictError,
    OnlyMarketProductResolutionError,
    OnlyUnknownMarketProductPluginError,
)
from onlyalpha.market.product.identity import OnlyMarketProductAuthorityIdentity, OnlyMarketProductPluginId


class OnlyMarketProductFactoryRegistry:
    def __init__(self) -> None:
        self._factories: dict[OnlyMarketProductPluginId, OnlyMarketProductFactory] = {}
        self._authority_fingerprints: dict[tuple[str, str, str], str] = {}
        self._product_definitions: dict[tuple[str, str, str], tuple[object, object]] = {}

    def register(self, factory: OnlyMarketProductFactory) -> None:
        plugin_id = factory.plugin_id
        if not isinstance(plugin_id, OnlyMarketProductPluginId):
            raise OnlyMarketProductResolutionError(
                "INVALID_MARKET_PRODUCT_FACTORY_IDENTITY",
                "factory must expose an OnlyMarketProductPluginId",
            )
        current = self._factories.get(plugin_id)
        if current is factory:
            return
        if current is not None:
            raise OnlyDuplicateMarketProductPluginError(
                "MARKET_PRODUCT_PLUGIN_CONFLICT",
                f"plugin {plugin_id} is already registered by a different factory",
            )
        self._factories[plugin_id] = factory

    def require(self, plugin_id: OnlyMarketProductPluginId) -> OnlyMarketProductFactory:
        try:
            return self._factories[plugin_id]
        except KeyError as exc:
            raise OnlyUnknownMarketProductPluginError(
                "MARKET_PRODUCT_PLUGIN_NOT_REGISTERED",
                f"plugin {plugin_id} is not registered",
            ) from exc

    def plugin_ids(self) -> tuple[OnlyMarketProductPluginId, ...]:
        return tuple(sorted(self._factories))

    def resolve(
        self,
        config: OnlyMarketProductConfig,
        context: OnlyMarketProductResolutionContext,
    ) -> OnlyResolvedMarketProductBinding:
        factory = self.require(config.plugin_id)
        if factory.plugin_id != config.plugin_id:
            raise OnlyMarketProductResolutionError(
                "MARKET_PRODUCT_FACTORY_IDENTITY_MISMATCH",
                "selected factory identity does not match configuration",
            )
        binding = factory.resolve(config, context)
        if binding is None:
            raise OnlyMarketProductResolutionError(
                "MARKET_PRODUCT_RESOLUTION_RETURNED_NONE",
                "factory must return an immutable resolved binding",
            )
        if binding.provider_plugin_id != config.plugin_id:
            raise OnlyMarketProductResolutionError(
                "MARKET_PRODUCT_PROVIDER_IDENTITY_MISMATCH",
                "resolved binding provider does not match selected factory",
            )
        requested_identity = (config.product_id, config.product_version)
        resolved_identity = (
            binding.product_identity.product_id,
            binding.product_identity.product_version,
        )
        if resolved_identity != requested_identity:
            raise OnlyMarketProductResolutionError(
                "MARKET_PRODUCT_IDENTITY_MISMATCH",
                "resolved binding product does not match requested product",
            )
        self._register_product_definition(binding)
        self._register_authority(binding.reference_authority.identity)
        self._register_authority(binding.policy_compiler.identity)
        self._register_authority(
            OnlyMarketProductAuthorityIdentity(
                "MARKET_FEE_PACK",
                binding.market_fee_pack.identity.pack_id,
                binding.market_fee_pack.identity.pack_version,
                binding.market_fee_pack.identity.fingerprint,
            )
        )
        return binding

    def _register_authority(self, identity: OnlyMarketProductAuthorityIdentity) -> None:
        key = identity.version_key
        current = self._authority_fingerprints.get(key)
        if current is not None and current != identity.authority_fingerprint:
            raise OnlyMarketProductAuthorityConflictError(
                "MARKET_PRODUCT_AUTHORITY_VERSION_CONFLICT",
                f"authority {identity.authority_kind}:{identity.authority_id}@{identity.authority_version} "
                "has conflicting semantic fingerprints",
            )
        self._authority_fingerprints[key] = identity.authority_fingerprint

    def _register_product_definition(self, binding: OnlyResolvedMarketProductBinding) -> None:
        key = (
            str(binding.provider_plugin_id),
            str(binding.product_identity.product_id),
            str(binding.product_identity.product_version),
        )
        definition = (binding.policy_compiler.identity, binding.market_fee_pack.identity)
        current = self._product_definitions.get(key)
        if current is not None and current != definition:
            raise OnlyMarketProductAuthorityConflictError(
                "MARKET_PRODUCT_VERSION_SEMANTICS_CONFLICT",
                f"product {key[1]}@{key[2]} from provider {key[0]} has conflicting versioned semantics",
            )
        self._product_definitions[key] = definition


__all__ = ["OnlyMarketProductFactoryRegistry"]
