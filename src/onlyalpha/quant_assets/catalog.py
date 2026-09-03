"""Immutable catalog generations for versioned L1/L2/L3/L4 asset providers."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from importlib import metadata
from threading import RLock
from types import MappingProxyType

from onlyalpha.calculation.definition import OnlyCalculationKind
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration, OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_fingerprint

ONLYALPHA_QUANT_ASSET_ENTRY_POINT = "onlyalpha.quant_assets"
_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_RESOURCE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]*$")


class OnlyQuantAssetLayer(StrEnum):
    OPERATOR = "L1_OPERATOR"
    INDICATOR = "L2_INDICATOR"
    FACTOR = "L3_FACTOR"
    STRATEGY = "L4_STRATEGY"


@dataclass(frozen=True, slots=True)
class OnlyQuantAssetProviderManifest:
    provider_id: str
    provider_version: str
    layer: OnlyQuantAssetLayer
    distribution_name: str
    distribution_version: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or _ID.fullmatch(self.provider_id) is None:
            raise ValueError("QUANT_ASSET_PROVIDER_ID_INVALID")
        if _VERSION.fullmatch(self.provider_version) is None:
            raise ValueError("QUANT_ASSET_PROVIDER_VERSION_INVALID")
        if _ID.fullmatch(self.distribution_name) is None or _VERSION.fullmatch(self.distribution_version) is None:
            raise ValueError("QUANT_ASSET_DISTRIBUTION_IDENTITY_INVALID")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "layer": self.layer.value,
            "distribution_name": self.distribution_name,
            "distribution_version": self.distribution_version,
        }


@dataclass(frozen=True, slots=True)
class OnlyStrategyAuthoringResource:
    relative_path: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if (
            _RESOURCE.fullmatch(self.relative_path) is None
            or self.relative_path.startswith("/")
            or ".." in self.relative_path.split("/")
            or not self.content
        ):
            raise ValueError("STRATEGY_AUTHORING_RESOURCE_INVALID")

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    def descriptor(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "content_sha256": self.content_sha256,
            "size": len(self.content),
        }


@dataclass(frozen=True, slots=True)
class OnlyStrategyAuthoringAsset:
    asset_id: str
    semantic_version: str
    resources: tuple[OnlyStrategyAuthoringResource, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or _ID.fullmatch(self.asset_id) is None:
            raise ValueError("STRATEGY_AUTHORING_ASSET_ID_INVALID")
        if _VERSION.fullmatch(self.semantic_version) is None:
            raise ValueError("STRATEGY_AUTHORING_ASSET_VERSION_INVALID")
        canonical = tuple(sorted(self.resources, key=lambda item: item.relative_path))
        if not canonical or len({item.relative_path for item in canonical}) != len(canonical):
            raise ValueError("STRATEGY_AUTHORING_ASSET_RESOURCES_INVALID")
        if "research-definition.json" not in {item.relative_path for item in canonical}:
            raise ValueError("STRATEGY_AUTHORING_DEFINITION_REQUIRED")
        object.__setattr__(self, "resources", canonical)

    @property
    def content_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.descriptor())

    def descriptor(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "asset_id": self.asset_id,
            "semantic_version": self.semantic_version,
            "resources": [item.descriptor() for item in self.resources],
        }

    def resource_bytes(self, relative_path: str) -> bytes:
        for resource in self.resources:
            if resource.relative_path == relative_path:
                return resource.content
        raise KeyError(relative_path)


@dataclass(frozen=True, slots=True)
class OnlyQuantAssetProvider:
    manifest: OnlyQuantAssetProviderManifest
    calculation_registrations: tuple[OnlyCalculationBackendRegistration, ...] = ()
    strategy_assets: tuple[OnlyStrategyAuthoringAsset, ...] = ()

    def __post_init__(self) -> None:
        calculation_layer = self.manifest.layer is not OnlyQuantAssetLayer.STRATEGY
        if calculation_layer and (not self.calculation_registrations or self.strategy_assets):
            raise ValueError("CALCULATION_ASSET_PROVIDER_CONTENT_INVALID")
        if not calculation_layer and (self.calculation_registrations or not self.strategy_assets):
            raise ValueError("STRATEGY_ASSET_PROVIDER_CONTENT_INVALID")
        if calculation_layer and any(
            registration.implementation_manifest is None for registration in self.calculation_registrations
        ):
            raise ValueError("QUANT_ASSET_IMPLEMENTATION_MANIFEST_REQUIRED")
        factor_layer = self.manifest.layer is OnlyQuantAssetLayer.FACTOR
        if calculation_layer and any(
            (registration.type_definition.kind is OnlyCalculationKind.FACTOR) is not factor_layer
            for registration in self.calculation_registrations
        ):
            raise ValueError("QUANT_ASSET_LAYER_CLASSIFICATION_INVALID")
        asset_keys = {(item.asset_id, item.semantic_version) for item in self.strategy_assets}
        if len(asset_keys) != len(self.strategy_assets):
            raise ValueError("STRATEGY_AUTHORING_ASSET_DUPLICATE")

    @property
    def content_fingerprint(self) -> str:
        return only_canonical_fingerprint(self._content_descriptor())

    def _content_descriptor(self) -> dict[str, object]:
        calculations = []
        for registration in self.calculation_registrations:
            manifest = registration.implementation_manifest
            calculations.append(
                {
                    "type": registration.type_definition.descriptor(),
                    "backend": registration.backend.value,
                    "implementation_fingerprint": None if manifest is None else manifest.implementation_fingerprint,
                    "state_capability": (
                        None if registration.state_capability is None else registration.state_capability.value
                    ),
                    "checkpoint_schema_version": registration.checkpoint_schema_version,
                }
            )
        return {
            "layer": self.manifest.layer.value,
            "calculations": sorted(calculations, key=only_canonical_fingerprint),
            "strategies": sorted(
                (item.descriptor() for item in self.strategy_assets),
                key=only_canonical_fingerprint,
            ),
        }

    def descriptor(self) -> dict[str, object]:
        content = self._content_descriptor()
        return {
            "manifest": self.manifest.to_dict(),
            "content_fingerprint": self.content_fingerprint,
            "calculations": content["calculations"],
            "strategies": content["strategies"],
        }


@dataclass(frozen=True, slots=True)
class OnlyQuantAssetCatalogGeneration:
    providers: tuple[OnlyQuantAssetProvider, ...]

    def __post_init__(self) -> None:
        canonical = tuple(
            sorted(
                self.providers,
                key=lambda item: (
                    item.manifest.layer.value,
                    item.manifest.provider_id,
                    item.manifest.provider_version,
                ),
            )
        )
        keys = {(item.manifest.provider_id, item.manifest.provider_version) for item in canonical}
        if len(keys) != len(canonical):
            raise ValueError("QUANT_ASSET_PROVIDER_VERSION_DUPLICATE")
        registry = OnlyCalculationRegistry()
        for provider in canonical:
            for registration in provider.calculation_registrations:
                registry.register(registration)
        object.__setattr__(self, "providers", canonical)

    @property
    def generation_fingerprint(self) -> str:
        return only_canonical_fingerprint(self.descriptor(include_fingerprint=False))

    def descriptor(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        descriptor: dict[str, object] = {
            "schema_version": 1,
            "providers": [provider.descriptor() for provider in self.providers],
        }
        if include_fingerprint:
            descriptor["generation_fingerprint"] = self.generation_fingerprint
        return descriptor

    def calculation_registry(self) -> OnlyCalculationRegistry:
        registry = OnlyCalculationRegistry()
        for provider in self.providers:
            for registration in provider.calculation_registrations:
                registry.register(registration)
        return registry

    def resolve_strategy_asset(
        self,
        provider_id: str,
        provider_version: str,
        asset_id: str,
        semantic_version: str,
    ) -> OnlyStrategyAuthoringAsset:
        matches = (
            asset
            for provider in self.providers
            if provider.manifest.provider_id == provider_id and provider.manifest.provider_version == provider_version
            for asset in provider.strategy_assets
            if asset.asset_id == asset_id and asset.semantic_version == semantic_version
        )
        try:
            return next(matches)
        except StopIteration as exc:
            raise KeyError((provider_id, provider_version, asset_id, semantic_version)) from exc


class OnlyQuantAssetCatalogManager:
    """Atomic generation switch; existing holders retain their immutable snapshot."""

    def __init__(self, initial: OnlyQuantAssetCatalogGeneration) -> None:
        self._lock = RLock()
        self._current = initial
        self._history = {initial.generation_fingerprint: initial}
        self._provider_versions = {
            (item.manifest.provider_id, item.manifest.provider_version): item.content_fingerprint
            for item in initial.providers
        }

    def snapshot(self) -> OnlyQuantAssetCatalogGeneration:
        with self._lock:
            return self._current

    def generation(self, fingerprint: str) -> OnlyQuantAssetCatalogGeneration:
        with self._lock:
            try:
                return self._history[fingerprint]
            except KeyError as exc:
                raise KeyError(fingerprint) from exc

    def refresh(
        self,
        loader: Callable[[], OnlyQuantAssetCatalogGeneration],
    ) -> OnlyQuantAssetCatalogGeneration:
        candidate = loader()
        with self._lock:
            for provider in candidate.providers:
                key = (provider.manifest.provider_id, provider.manifest.provider_version)
                previous = self._provider_versions.get(key)
                if previous is not None and previous != provider.content_fingerprint:
                    raise ValueError("QUANT_ASSET_PROVIDER_VERSION_CONTENT_DRIFT")
            self._current = candidate
            self._history.setdefault(candidate.generation_fingerprint, candidate)
            self._provider_versions.update(
                {
                    (item.manifest.provider_id, item.manifest.provider_version): item.content_fingerprint
                    for item in candidate.providers
                }
            )
            return candidate

    @property
    def generations(self) -> MappingProxyType[str, OnlyQuantAssetCatalogGeneration]:
        with self._lock:
            return MappingProxyType(dict(self._history))


def only_discover_quant_asset_providers(
    explicit_providers: Iterable[OnlyQuantAssetProvider] = (),
    *,
    include_installed: bool = True,
) -> OnlyQuantAssetCatalogGeneration:
    providers = list(explicit_providers)
    entries = metadata.entry_points().select(group=ONLYALPHA_QUANT_ASSET_ENTRY_POINT) if include_installed else ()
    for entry in sorted(entries, key=lambda item: (item.name, item.value)):
        loaded = entry.load()
        provider = loaded() if callable(loaded) else loaded
        if not isinstance(provider, OnlyQuantAssetProvider):
            raise TypeError(f"quant asset provider is invalid: {entry.name}")
        distribution = entry.dist
        if distribution is None or (
            _normalize_distribution(distribution.name) != _normalize_distribution(provider.manifest.distribution_name)
            or distribution.version != provider.manifest.distribution_version
        ):
            raise ValueError(f"quant asset distribution identity differs: {entry.name}")
        providers.append(provider)
    return OnlyQuantAssetCatalogGeneration(tuple(providers))


def _normalize_distribution(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


__all__ = [name for name in globals() if name.startswith(("Only", "only_", "ONLYALPHA_"))]
