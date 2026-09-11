"""Historical Exact Catalog Context reader over Runtime Generation authorities."""

from __future__ import annotations

import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from onlyalpha.application.catalog_context import (
    OnlyExactCatalogContextCorrupt,
    OnlyExactCatalogContextNotFound,
    OnlyExactCatalogContextProjectionMismatch,
    OnlyExactCatalogContextUnavailable,
    OnlyExactDatasetFieldContractV1,
    OnlyExactRegisteredUniverseV1,
    OnlyExactStatisticsCapabilityV1,
)
from onlyalpha.canonical import only_canonical_json

from .builder import OnlyRuntimeGenerationBuilder
from .registry import OnlyGenerationState, OnlyRuntimeGenerationRegistry

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class OnlyRuntimeGenerationExactCatalogDescriptorReader:
    registry: OnlyRuntimeGenerationRegistry
    builder: OnlyRuntimeGenerationBuilder
    environment_parent: Path
    _bundle_cache: dict[str, dict[str, object]] = field(default_factory=dict, init=False, repr=False, compare=False)

    def load_verified_catalog_descriptor(self, catalog_generation_fingerprint: str) -> dict[str, object]:
        value = self._load_bundle(catalog_generation_fingerprint)["catalog"]
        if not isinstance(value, Mapping):
            raise OnlyExactCatalogContextCorrupt
        return {str(name): item for name, item in value.items()}

    def load_exact_dataset_field_contracts(
        self, catalog_generation_fingerprint: str
    ) -> tuple[OnlyExactDatasetFieldContractV1, ...]:
        values = _entries(self._load_bundle(catalog_generation_fingerprint), "dataset_fields")
        return tuple(
            OnlyExactDatasetFieldContractV1.from_dict(
                {"catalog_generation_fingerprint": catalog_generation_fingerprint, **item}
            )
            for item in values
        )

    def load_exact_registered_universes(
        self, catalog_generation_fingerprint: str
    ) -> tuple[OnlyExactRegisteredUniverseV1, ...]:
        values = _entries(self._load_bundle(catalog_generation_fingerprint), "registered_universes")
        return tuple(
            OnlyExactRegisteredUniverseV1.from_dict(
                {"catalog_generation_fingerprint": catalog_generation_fingerprint, **item}
            )
            for item in values
        )

    def load_exact_statistics_capabilities(
        self, catalog_generation_fingerprint: str
    ) -> tuple[OnlyExactStatisticsCapabilityV1, ...]:
        values = _entries(self._load_bundle(catalog_generation_fingerprint), "statistics")
        return tuple(
            OnlyExactStatisticsCapabilityV1.from_dict(
                {"catalog_generation_fingerprint": catalog_generation_fingerprint, **item}
            )
            for item in values
        )

    def _load_bundle(self, catalog_generation_fingerprint: str) -> dict[str, object]:
        if _SHA256.fullmatch(catalog_generation_fingerprint) is None:
            raise OnlyExactCatalogContextCorrupt
        try:
            projection = self.registry.projection()
            manifests = tuple(self.registry.load_manifest(fingerprint) for fingerprint in sorted(projection.states))
        except Exception as exc:
            raise OnlyExactCatalogContextCorrupt from exc
        candidates = tuple(
            manifest
            for manifest in manifests
            if manifest.catalog_generation_fingerprint == catalog_generation_fingerprint
        )
        if not candidates:
            raise OnlyExactCatalogContextNotFound

        usable = tuple(
            manifest
            for manifest in candidates
            if projection.states[manifest.runtime_generation_fingerprint]
            not in {OnlyGenerationState.PREPARING, OnlyGenerationState.REJECTED}
        )
        bundles: list[dict[str, object]] = []
        self.environment_parent.mkdir(parents=True, exist_ok=True)
        for manifest in usable:
            try:
                evidence = self.registry.load_validation_evidence(manifest.runtime_generation_fingerprint)
                if not evidence.verifies(manifest):
                    raise ValueError("RUNTIME_GENERATION_VALIDATION_EVIDENCE_MISMATCH")
                self.builder.verify_exact_artifacts(manifest)
                bundle = self._bundle_cache.get(manifest.runtime_generation_fingerprint)
                if bundle is None:
                    with tempfile.TemporaryDirectory(
                        prefix="exact-catalog-context-",
                        dir=self.environment_parent,
                    ) as temporary:
                        bundle = self.builder.rebuild_catalog_context_bundle(
                            expected_manifest=manifest,
                            environment_root=Path(temporary) / "runtime",
                        )
                    self._bundle_cache[manifest.runtime_generation_fingerprint] = bundle
                catalog = bundle.get("catalog")
                if (
                    not isinstance(catalog, dict)
                    or catalog.get("generation_fingerprint") != catalog_generation_fingerprint
                ):
                    raise ValueError("RUNTIME_GENERATION_CATALOG_MISMATCH")
                bundles.append(bundle)
            except Exception:
                continue
        if not bundles:
            raise OnlyExactCatalogContextUnavailable
        canonical = {only_canonical_json(item) for item in bundles}
        if len(canonical) != 1:
            raise OnlyExactCatalogContextProjectionMismatch
        return bundles[0]


def _entries(bundle: Mapping[str, object], name: str) -> tuple[Mapping[str, object], ...]:
    value = bundle.get(name)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise OnlyExactCatalogContextCorrupt
    result: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping) or any(not isinstance(key, str) for key in item):
            raise OnlyExactCatalogContextCorrupt
        result.append(cast(Mapping[str, object], item))
    return tuple(result)


__all__ = ["OnlyRuntimeGenerationExactCatalogDescriptorReader"]
