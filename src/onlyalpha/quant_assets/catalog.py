"""Immutable catalog generations for versioned Operator/Indicator/Factor/Strategy asset providers."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib import metadata
from threading import RLock
from types import MappingProxyType

from onlyalpha.calculation.definition import OnlyCalculationKind
from onlyalpha.calculation.registry import OnlyCalculationBackendRegistration, OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.quant_assets.private_factor_execution import OnlyPrivateFactorProviderSnapshotV1

ONLYALPHA_QUANT_ASSET_ENTRY_POINT = "onlyalpha.quant_assets"
_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


class OnlyQuantAssetKind(StrEnum):
    OPERATOR = "OPERATOR"
    INDICATOR = "INDICATOR"
    FACTOR = "FACTOR"
    STRATEGY = "STRATEGY"


@dataclass(frozen=True, slots=True)
class OnlyDistributionProviderSource:
    distribution_name: str
    distribution_version: str

    def __post_init__(self) -> None:
        if _ID.fullmatch(self.distribution_name) is None or _VERSION.fullmatch(self.distribution_version) is None:
            raise ValueError("QUANT_ASSET_DISTRIBUTION_IDENTITY_INVALID")

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": "DISTRIBUTION",
            "distribution_name": self.distribution_name,
            "distribution_version": self.distribution_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyDistributionProviderSource:
        if set(payload) != {"kind", "distribution_name", "distribution_version"} or payload["kind"] != "DISTRIBUTION":
            raise ValueError("QUANT_ASSET_PROVIDER_SOURCE_INVALID")
        return cls(str(payload["distribution_name"]), str(payload["distribution_version"]))


@dataclass(frozen=True, slots=True)
class OnlyPrivateFactorSnapshotProviderSource:
    private_factor_provider_snapshot_fingerprint: str

    def __post_init__(self) -> None:
        if len(self.private_factor_provider_snapshot_fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in self.private_factor_provider_snapshot_fingerprint
        ):
            raise ValueError("QUANT_ASSET_PRIVATE_FACTOR_SNAPSHOT_INVALID")

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": "PRIVATE_FACTOR_SNAPSHOT",
            "private_factor_provider_snapshot_fingerprint": self.private_factor_provider_snapshot_fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyPrivateFactorSnapshotProviderSource:
        if (
            set(payload) != {"kind", "private_factor_provider_snapshot_fingerprint"}
            or payload["kind"] != "PRIVATE_FACTOR_SNAPSHOT"
        ):
            raise ValueError("QUANT_ASSET_PROVIDER_SOURCE_INVALID")
        return cls(str(payload["private_factor_provider_snapshot_fingerprint"]))


def only_quant_asset_provider_source_from_dict(payload: Mapping[str, object]) -> OnlyQuantAssetProviderSource:
    if payload.get("kind") == "DISTRIBUTION":
        return OnlyDistributionProviderSource.from_dict(payload)
    if payload.get("kind") == "PRIVATE_FACTOR_SNAPSHOT":
        return OnlyPrivateFactorSnapshotProviderSource.from_dict(payload)
    raise ValueError("QUANT_ASSET_PROVIDER_SOURCE_INVALID")


OnlyQuantAssetProviderSource = OnlyDistributionProviderSource | OnlyPrivateFactorSnapshotProviderSource


@dataclass(frozen=True, slots=True)
class OnlyQuantAssetProviderManifest:
    provider_id: str
    provider_version: str
    kind: OnlyQuantAssetKind
    source: OnlyQuantAssetProviderSource
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or _ID.fullmatch(self.provider_id) is None:
            raise ValueError("QUANT_ASSET_PROVIDER_ID_INVALID")
        if _VERSION.fullmatch(self.provider_version) is None:
            raise ValueError("QUANT_ASSET_PROVIDER_VERSION_INVALID")
        if not isinstance(self.source, (OnlyDistributionProviderSource, OnlyPrivateFactorSnapshotProviderSource)):
            raise ValueError("QUANT_ASSET_PROVIDER_SOURCE_INVALID")
        if (
            isinstance(self.source, OnlyPrivateFactorSnapshotProviderSource)
            and self.kind is not OnlyQuantAssetKind.FACTOR
        ):
            raise ValueError("QUANT_ASSET_PRIVATE_FACTOR_SNAPSHOT_INVALID")

    @property
    def distribution_name(self) -> str:
        if not isinstance(self.source, OnlyDistributionProviderSource):
            raise ValueError("QUANT_ASSET_PROVIDER_NOT_DISTRIBUTION_BACKED")
        return self.source.distribution_name

    @property
    def distribution_version(self) -> str:
        if not isinstance(self.source, OnlyDistributionProviderSource):
            raise ValueError("QUANT_ASSET_PROVIDER_NOT_DISTRIBUTION_BACKED")
        return self.source.distribution_version

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "kind": self.kind.value,
            "source": self.source.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class OnlyQuantAssetProvider:
    manifest: OnlyQuantAssetProviderManifest
    calculation_registrations: tuple[OnlyCalculationBackendRegistration, ...] = ()
    private_factor_snapshot: OnlyPrivateFactorProviderSnapshotV1 | None = None

    def __post_init__(self) -> None:
        if self.manifest.kind is OnlyQuantAssetKind.STRATEGY:
            raise ValueError("STRATEGY_PROVIDER_UNSUPPORTED")
        private_factor_source = (
            self.manifest.source if isinstance(self.manifest.source, OnlyPrivateFactorSnapshotProviderSource) else None
        )
        private_factor = private_factor_source is not None
        if private_factor_source is not None:
            if (
                self.private_factor_snapshot is None
                or self.private_factor_snapshot.snapshot_fingerprint
                != private_factor_source.private_factor_provider_snapshot_fingerprint
            ):
                raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_MISMATCH")
            entry_by_key = {
                (entry.factor_id, entry.semantic_version): entry for entry in self.private_factor_snapshot.entries
            }
            registrations_by_key: dict[tuple[str, str], list[OnlyCalculationBackendRegistration]] = {}
            for registration in self.calculation_registrations:
                key = (registration.type_definition.type_id, registration.type_definition.semantic_version)
                registrations_by_key.setdefault(key, []).append(registration)
            if set(registrations_by_key) != set(entry_by_key):
                raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_MISMATCH")
            for key, registrations in registrations_by_key.items():
                entry = entry_by_key[key]
                identities = {
                    registration.backend.value: (
                        None
                        if registration.implementation_manifest is None
                        else registration.implementation_manifest.implementation_fingerprint
                    )
                    for registration in registrations
                }
                if identities != {
                    "RESEARCH": entry.research_implementation_fingerprint,
                    "TRADING": entry.trading_implementation_fingerprint,
                }:
                    raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_MISMATCH")
        elif self.private_factor_snapshot is not None:
            raise ValueError("PRIVATE_FACTOR_PROVIDER_SNAPSHOT_MISMATCH")
        if not private_factor and not self.calculation_registrations:
            raise ValueError("CALCULATION_ASSET_PROVIDER_CONTENT_INVALID")
        if any(registration.implementation_manifest is None for registration in self.calculation_registrations):
            raise ValueError("QUANT_ASSET_IMPLEMENTATION_MANIFEST_REQUIRED")
        factor_kind = self.manifest.kind is OnlyQuantAssetKind.FACTOR
        if any(
            (registration.type_definition.kind is OnlyCalculationKind.FACTOR) is not factor_kind
            for registration in self.calculation_registrations
        ):
            raise ValueError("QUANT_ASSET_KIND_CLASSIFICATION_INVALID")

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
            "kind": self.manifest.kind.value,
            "calculations": sorted(calculations, key=only_canonical_fingerprint),
            "private_factor_snapshot": (
                None
                if self.private_factor_snapshot is None
                else {
                    "snapshot_fingerprint": self.private_factor_snapshot.snapshot_fingerprint,
                    "entries": [item.to_dict() for item in self.private_factor_snapshot.entries],
                }
            ),
        }

    def descriptor(self) -> dict[str, object]:
        content = self._content_descriptor()
        return {
            "manifest": self.manifest.to_dict(),
            "content_fingerprint": self.content_fingerprint,
            "calculations": content["calculations"],
            "private_factor_snapshot": content["private_factor_snapshot"],
        }


@dataclass(frozen=True, slots=True)
class OnlyQuantAssetCatalogGeneration:
    providers: tuple[OnlyQuantAssetProvider, ...]

    def __post_init__(self) -> None:
        canonical = tuple(
            sorted(
                self.providers,
                key=lambda item: (
                    item.manifest.kind.value,
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
