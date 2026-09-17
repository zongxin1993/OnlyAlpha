"""Verified process-generation composition outside the OnlyAlpha Core package."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration
from onlyalpha.research.provenance import (
    OnlyResearchAuthoringProvenance,
    OnlyResearchPrivateAssetKind,
)
from onlyalpha.research.run.errors import OnlyResearchRunAdmissionError
from onlyalpha.research.specification.model import OnlyResearchSpecification
from onlyalpha.research.specification.resolver import (
    OnlyResearchSpecificationResolution,
    OnlyResearchSpecificationResolver,
)
from onlyalpha.runtime.defaults import OnlyEngineServices, only_default_engine_services


@dataclass(frozen=True, slots=True)
class OnlyAuthoringExecutionGeneration:
    """One exact candidate Catalog bound to one durable authoring provenance identity."""

    provenance: OnlyResearchAuthoringProvenance
    catalog: OnlyQuantAssetCatalogGeneration

    def __post_init__(self) -> None:
        if self.catalog.generation_fingerprint != self.provenance.catalog_generation_fingerprint:
            raise ValueError("AUTHORING_CATALOG_GENERATION_MISMATCH")
        if self.provenance.private_asset_kind is not OnlyResearchPrivateAssetKind.L3_FACTOR:
            raise ValueError("AUTHORING_EXECUTION_PRIVATE_ASSET_KIND_UNSUPPORTED")
        matches = tuple(
            provider
            for provider in self.catalog.providers
            if provider.manifest.provider_id == self.provenance.candidate_provider_id
            and provider.manifest.provider_version == self.provenance.candidate_provider_version
        )
        if (
            len(matches) != 1
            or matches[0].content_fingerprint != self.provenance.candidate_provider_content_fingerprint
        ):
            raise ValueError("AUTHORING_CANDIDATE_PROVIDER_MISMATCH")

    @property
    def fingerprint(self) -> str:
        return self.provenance.execution_generation_fingerprint

    def descriptor(self) -> dict[str, object]:
        return {
            "schema_version": self.provenance.schema_version,
            "execution_generation_fingerprint": self.fingerprint,
            "provenance": self.provenance.identity_dict(),
            "catalog": self.catalog.descriptor(),
        }

    def engine_services(self) -> OnlyEngineServices:
        """Build one process composition with Catalog-owned distributions fixed to this generation."""

        return only_default_engine_services(calculation_catalog_generation=self.catalog, fail_fast=True)


@dataclass(frozen=True, slots=True)
class OnlyAuthoringExecutionGenerationStore:
    """Immutable descriptor evidence; executable content is reconstructed from the exact source/artifact authority."""

    root: Path

    def commit(self, generation: OnlyAuthoringExecutionGeneration) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / f"{generation.fingerprint}.json"
        content = (only_canonical_json(generation.descriptor()) + "\n").encode()
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if target.read_bytes() != content:
                raise ValueError("AUTHORING_EXECUTION_GENERATION_CONFLICT") from None
            return target
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        return target

    def verify(self, generation: OnlyAuthoringExecutionGeneration) -> Path:
        target = self.root / f"{generation.fingerprint}.json"
        expected = (only_canonical_json(generation.descriptor()) + "\n").encode()
        try:
            actual = target.read_bytes()
        except OSError as exc:
            raise ValueError("AUTHORING_EXECUTION_GENERATION_NOT_FOUND_OR_CORRUPT") from exc
        if actual != expected:
            raise ValueError("AUTHORING_EXECUTION_GENERATION_MISMATCH")
        return target

    def load_descriptor_verified(self, fingerprint: str) -> dict[str, object]:
        """Read immutable generation admission evidence by exact identity, without hosting code."""
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise ValueError("AUTHORING_EXECUTION_GENERATION_IDENTITY_INVALID")
        target = self.root / f"{fingerprint}.json"
        if self.root.is_symlink() or target.is_symlink():
            raise ValueError("AUTHORING_EXECUTION_GENERATION_MISMATCH")
        try:
            raw = target.read_text(encoding="utf-8")
            descriptor = json.loads(raw)
            if (
                not isinstance(descriptor, dict)
                or set(descriptor) != {"schema_version", "execution_generation_fingerprint", "provenance", "catalog"}
                or raw != only_canonical_json(descriptor) + "\n"
            ):
                raise ValueError("descriptor is not canonical")
            provenance_raw = descriptor["provenance"]
            catalog = descriptor["catalog"]
            if not isinstance(provenance_raw, dict) or not isinstance(catalog, dict):
                raise ValueError("descriptor fields")
            provenance = OnlyResearchAuthoringProvenance.from_dict(provenance_raw)
            providers = catalog.get("providers")
            if not isinstance(providers, list):
                raise ValueError("catalog providers")
            matches = [
                provider
                for provider in providers
                if isinstance(provider, dict)
                and isinstance(provider.get("manifest"), dict)
                and provider["manifest"].get("provider_id") == provenance.candidate_provider_id
                and provider["manifest"].get("provider_version") == provenance.candidate_provider_version
                and provider.get("content_fingerprint") == provenance.candidate_provider_content_fingerprint
            ]
            if (
                descriptor["schema_version"] != provenance.schema_version
                or descriptor["execution_generation_fingerprint"] != fingerprint
                or provenance.identity_dict() != provenance_raw
                or provenance.execution_generation_fingerprint != fingerprint
                or catalog.get("generation_fingerprint") != provenance.catalog_generation_fingerprint
                or only_canonical_fingerprint(
                    {key: value for key, value in catalog.items() if key != "generation_fingerprint"}
                )
                != provenance.catalog_generation_fingerprint
                or len(matches) != 1
            ):
                raise ValueError("descriptor identity")
            return descriptor
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError("AUTHORING_EXECUTION_GENERATION_NOT_FOUND_OR_CORRUPT") from exc


class OnlyAuthoringExecutionGenerationRegistry:
    """Immutable Product-admission resolver for verified process generations."""

    def __init__(self, generations: tuple[OnlyAuthoringExecutionGeneration, ...]) -> None:
        if len(generations) != 1:
            raise ValueError("AUTHORING_PROCESS_REQUIRES_EXACTLY_ONE_GENERATION")
        indexed = {generation.fingerprint: generation for generation in generations}
        self._generations = indexed
        self._resolvers = {
            fingerprint: OnlyResearchSpecificationResolver(
                generation.engine_services().assembler.components.calculations
            )
            for fingerprint, generation in indexed.items()
        }

    def resolve(
        self,
        provenance: OnlyResearchAuthoringProvenance,
        specification: OnlyResearchSpecification,
    ) -> OnlyResearchSpecificationResolution:
        try:
            generation = self._generations[provenance.execution_generation_fingerprint]
        except KeyError as exc:
            raise OnlyResearchRunAdmissionError(
                "Authoring execution generation was not admitted",
                code="RESEARCH_EXECUTION_GENERATION_UNAVAILABLE",
            ) from exc
        if generation.provenance.identity_dict() != provenance.identity_dict():
            raise OnlyResearchRunAdmissionError(
                "Authoring execution generation provenance differs",
                code="RESEARCH_EXECUTION_GENERATION_MISMATCH",
            )
        return self._resolvers[generation.fingerprint].resolve(specification)


__all__ = [
    "OnlyAuthoringExecutionGeneration",
    "OnlyAuthoringExecutionGenerationRegistry",
    "OnlyAuthoringExecutionGenerationStore",
]
