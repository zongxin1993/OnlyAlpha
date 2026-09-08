"""Historical Exact Catalog Context reader over Runtime Generation authorities."""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from onlyalpha.application.catalog_context import (
    OnlyExactCatalogContextCorrupt,
    OnlyExactCatalogContextNotFound,
    OnlyExactCatalogContextProjectionMismatch,
    OnlyExactCatalogContextUnavailable,
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

    def load_verified_catalog_descriptor(self, catalog_generation_fingerprint: str) -> dict[str, object]:
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
        descriptors: list[dict[str, object]] = []
        self.environment_parent.mkdir(parents=True, exist_ok=True)
        for manifest in usable:
            try:
                evidence = self.registry.load_validation_evidence(manifest.runtime_generation_fingerprint)
                if not evidence.verifies(manifest):
                    raise ValueError("RUNTIME_GENERATION_VALIDATION_EVIDENCE_MISMATCH")
                with tempfile.TemporaryDirectory(
                    prefix="exact-catalog-context-",
                    dir=self.environment_parent,
                ) as temporary:
                    descriptor = self.builder.rebuild_catalog_descriptor(
                        expected_manifest=manifest,
                        environment_root=Path(temporary) / "runtime",
                    )
                if descriptor.get("generation_fingerprint") != catalog_generation_fingerprint:
                    raise ValueError("RUNTIME_GENERATION_CATALOG_MISMATCH")
                descriptors.append(descriptor)
            except Exception:
                continue
        if not descriptors:
            raise OnlyExactCatalogContextUnavailable
        canonical = {only_canonical_json(item) for item in descriptors}
        if len(canonical) != 1:
            raise OnlyExactCatalogContextProjectionMismatch
        return descriptors[0]


__all__ = ["OnlyRuntimeGenerationExactCatalogDescriptorReader"]
