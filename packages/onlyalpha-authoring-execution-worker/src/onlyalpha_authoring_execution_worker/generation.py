"""Verified process-generation composition outside the OnlyAlpha Core package."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from onlyalpha.canonical import only_canonical_json
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration
from onlyalpha.research.provenance import OnlyResearchAuthoringProvenance
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
            "schema_version": 1,
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
