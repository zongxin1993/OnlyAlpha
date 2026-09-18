"""Verified process-generation composition outside the OnlyAlpha Core package."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.quant_assets import (
    OnlyPrivateAlphaExecutableClosureV1,
    OnlyPrivateAlphaSnapshotProviderSource,
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
)
from onlyalpha.quant_assets.private import (
    OnlyPrivateAssetAuthorityUnavailableError,
    OnlyPrivateAssetKind,
    OnlyPrivateAssetRevisionBindingResolver,
    OnlyPrivateAssetRevisionCorruptError,
    OnlyPrivateAssetRevisionNotFoundError,
    OnlyPrivateAssetRevisionReferenceV1,
)
from onlyalpha.research.provenance import (
    OnlyResearchAuthoringProvenance,
    only_research_execution_generation_fingerprint,
)
from onlyalpha.research.run.errors import OnlyResearchRunAdmissionError
from onlyalpha.research.specification.model import OnlyResearchSpecification
from onlyalpha.research.specification.resolver import (
    OnlyResearchSpecificationResolution,
    OnlyResearchSpecificationResolver,
)
from onlyalpha.runtime.defaults import OnlyEngineServices, only_default_engine_services


class OnlyAuthoringGenerationError(ValueError):
    code = "AUTHORING_GENERATION_ERROR"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(f"{self.code}: {detail}" if detail else self.code)


class OnlyAuthoringPrivateAssetRevisionUnavailableError(OnlyAuthoringGenerationError):
    code = "AUTHORING_PRIVATE_ASSET_REVISION_UNAVAILABLE"


class OnlyAuthoringPrivateAssetAuthorityUnavailableError(OnlyAuthoringGenerationError):
    code = "AUTHORING_PRIVATE_ASSET_AUTHORITY_UNAVAILABLE"


class OnlyAuthoringPrivateAssetRevisionCorruptError(OnlyAuthoringGenerationError):
    code = "AUTHORING_PRIVATE_ASSET_REVISION_CORRUPT"


class OnlyAuthoringPrivateAssetBindingMismatchError(OnlyAuthoringGenerationError):
    code = "AUTHORING_PRIVATE_ASSET_BINDING_MISMATCH"


@dataclass(frozen=True, slots=True, init=False)
class OnlyAuthoringExecutionGeneration:
    """One exact candidate Catalog bound to one durable authoring provenance identity."""

    provenance: OnlyResearchAuthoringProvenance
    catalog: OnlyQuantAssetCatalogGeneration

    @classmethod
    def create_verified(
        cls,
        *,
        experiment_id: str,
        private_asset_revision_reference: OnlyPrivateAssetRevisionReferenceV1,
        private_asset_revisions: OnlyPrivateAssetRevisionBindingResolver,
        private_alpha_executable_closure: OnlyPrivateAlphaExecutableClosureV1,
        candidate_provider_id: str,
        base_catalog: OnlyQuantAssetCatalogGeneration,
    ) -> OnlyAuthoringExecutionGeneration:
        binding = private_asset_revisions.resolve(private_asset_revision_reference)
        if binding.private_asset_kind is not OnlyPrivateAssetKind.ALPHA:
            raise ValueError("AUTHORING_EXECUTION_PRIVATE_ASSET_KIND_UNSUPPORTED")
        closure = private_alpha_executable_closure
        OnlyPrivateAlphaExecutableClosureV1.verify_canonical(closure)
        revision = closure.revision
        if (
            revision.alpha_id != binding.private_asset_id
            or revision.semantic_version != binding.semantic_version
            or revision.revision_fingerprint != binding.private_asset_revision_fingerprint
            or revision.source_sha256 != binding.private_asset_content_fingerprint
            or revision.alpha_api_version != binding.alpha_api_version
            or revision.alpha_api_contract_fingerprint != binding.alpha_api_contract_fingerprint
        ):
            raise ValueError("AUTHORING_PRIVATE_ALPHA_EXECUTION_BINDING_MISMATCH")
        if any(provider.manifest.provider_id == candidate_provider_id for provider in base_catalog.providers):
            raise ValueError("AUTHORING_CANDIDATE_PROVIDER_DUPLICATE")
        provider = OnlyQuantAssetProvider(
            OnlyQuantAssetProviderManifest(
                candidate_provider_id,
                revision.revision_fingerprint,
                OnlyQuantAssetKind.ALPHA,
                OnlyPrivateAlphaSnapshotProviderSource(closure.provider_snapshot.snapshot_fingerprint),
            ),
            calculation_registrations=closure.registrations,
            private_alpha_snapshot=closure.provider_snapshot,
        )
        catalog = OnlyQuantAssetCatalogGeneration((*base_catalog.providers, provider))
        provenance = OnlyResearchAuthoringProvenance(
            schema_version=1,
            experiment_id=experiment_id,
            private_asset_kind=OnlyPrivateAssetKind.ALPHA,
            private_asset_id=binding.private_asset_id,
            private_asset_revision_fingerprint=binding.private_asset_revision_fingerprint,
            private_asset_content_fingerprint=binding.private_asset_content_fingerprint,
            candidate_provider_id=provider.manifest.provider_id,
            candidate_provider_version=provider.manifest.provider_version,
            candidate_provider_content_fingerprint=provider.content_fingerprint,
            catalog_generation_fingerprint=catalog.generation_fingerprint,
            execution_generation_fingerprint=only_research_execution_generation_fingerprint(
                experiment_id=experiment_id,
                private_asset_kind=OnlyPrivateAssetKind.ALPHA,
                private_asset_id=binding.private_asset_id,
                private_asset_revision_fingerprint=binding.private_asset_revision_fingerprint,
                private_asset_content_fingerprint=binding.private_asset_content_fingerprint,
                candidate_provider_id=provider.manifest.provider_id,
                candidate_provider_version=provider.manifest.provider_version,
                candidate_provider_content_fingerprint=provider.content_fingerprint,
                catalog_generation_fingerprint=catalog.generation_fingerprint,
            ),
        )
        return cls._from_verified(provenance, catalog)

    @classmethod
    def _from_verified(
        cls,
        provenance: OnlyResearchAuthoringProvenance,
        catalog: OnlyQuantAssetCatalogGeneration,
    ) -> OnlyAuthoringExecutionGeneration:
        self = object.__new__(cls)
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "catalog", catalog)
        self._verify_composition()
        return self

    def _verify_composition(self) -> None:
        if self.catalog.generation_fingerprint != self.provenance.catalog_generation_fingerprint:
            raise ValueError("AUTHORING_CATALOG_GENERATION_MISMATCH")
        if self.provenance.private_asset_kind is not OnlyPrivateAssetKind.ALPHA:
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
        if matches[0].manifest.kind is not OnlyQuantAssetKind.ALPHA:
            raise ValueError("AUTHORING_CANDIDATE_PROVIDER_KIND_MISMATCH")

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
                or matches[0]["manifest"].get("kind") != OnlyQuantAssetKind.ALPHA.value
            ):
                raise ValueError("descriptor identity")
            return descriptor
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError("AUTHORING_EXECUTION_GENERATION_NOT_FOUND_OR_CORRUPT") from exc


class OnlyVerifiedAuthoringGenerationReader:
    """Re-anchor immutable descriptor evidence to the owning Private Asset Authority."""

    def __init__(
        self,
        store: OnlyAuthoringExecutionGenerationStore,
        private_asset_revisions: OnlyPrivateAssetRevisionBindingResolver,
    ) -> None:
        self._store = store
        self._private_asset_revisions = private_asset_revisions

    def load_verified(self, fingerprint: str) -> OnlyResearchAuthoringProvenance:
        _, provenance = self._load_verified_generation(fingerprint)
        return provenance

    def load_descriptor_verified(self, fingerprint: str) -> dict[str, object]:
        """Return descriptor evidence only after re-anchoring its Private Asset Revision."""

        descriptor, _ = self._load_verified_generation(fingerprint)
        return descriptor

    def _load_verified_generation(self, fingerprint: str) -> tuple[dict[str, object], OnlyResearchAuthoringProvenance]:
        descriptor = self._store.load_descriptor_verified(fingerprint)
        provenance = OnlyResearchAuthoringProvenance.from_dict(descriptor["provenance"])  # type: ignore[arg-type]
        reference = OnlyPrivateAssetRevisionReferenceV1(
            OnlyPrivateAssetKind(provenance.private_asset_kind.value),
            provenance.private_asset_id,
            provenance.private_asset_revision_fingerprint,
        )
        try:
            binding = self._private_asset_revisions.resolve(reference)
        except OnlyPrivateAssetRevisionNotFoundError as exc:
            raise OnlyAuthoringPrivateAssetRevisionUnavailableError() from exc
        except OnlyPrivateAssetAuthorityUnavailableError as exc:
            raise OnlyAuthoringPrivateAssetAuthorityUnavailableError() from exc
        except OnlyPrivateAssetRevisionCorruptError as exc:
            raise OnlyAuthoringPrivateAssetRevisionCorruptError() from exc
        if (
            binding.private_asset_kind.value != provenance.private_asset_kind.value
            or binding.private_asset_id != provenance.private_asset_id
            or binding.private_asset_revision_fingerprint != provenance.private_asset_revision_fingerprint
            or binding.private_asset_content_fingerprint != provenance.private_asset_content_fingerprint
        ):
            raise OnlyAuthoringPrivateAssetBindingMismatchError()
        return descriptor, provenance


class OnlyAuthoringExecutionGenerationRegistry:
    """Immutable Product-admission resolver for verified process generations."""

    def __init__(
        self,
        generations: tuple[OnlyAuthoringExecutionGeneration, ...],
        verified_reader: OnlyVerifiedAuthoringGenerationReader,
    ) -> None:
        if len(generations) != 1:
            raise ValueError("AUTHORING_PROCESS_REQUIRES_EXACTLY_ONE_GENERATION")
        indexed = {generation.fingerprint: generation for generation in generations}
        self._generations = indexed
        self._verified_reader = verified_reader
        self._resolvers = {
            fingerprint: OnlyResearchSpecificationResolver(
                generation.engine_services().assembler.components.calculations
            )
            for fingerprint, generation in indexed.items()
        }

    def load_verified(self, fingerprint: str) -> OnlyResearchAuthoringProvenance:
        try:
            generation = self._generations[fingerprint]
        except KeyError as exc:
            raise OnlyResearchRunAdmissionError(
                "Authoring execution generation was not admitted",
                code="RESEARCH_EXECUTION_GENERATION_UNAVAILABLE",
            ) from exc
        provenance = self._verified_reader.load_verified(fingerprint)
        if provenance != generation.provenance:
            raise OnlyResearchRunAdmissionError(
                "Authoring execution generation provenance differs",
                code="RESEARCH_EXECUTION_GENERATION_MISMATCH",
            )
        return provenance

    def resolve(
        self,
        authoring_generation_fingerprint: str,
        specification: OnlyResearchSpecification,
    ) -> OnlyResearchSpecificationResolution:
        self.load_verified(authoring_generation_fingerprint)
        generation = self._generations[authoring_generation_fingerprint]
        return self._resolvers[generation.fingerprint].resolve(specification)


__all__ = [
    "OnlyAuthoringExecutionGeneration",
    "OnlyAuthoringGenerationError",
    "OnlyAuthoringPrivateAssetAuthorityUnavailableError",
    "OnlyAuthoringPrivateAssetBindingMismatchError",
    "OnlyAuthoringPrivateAssetRevisionCorruptError",
    "OnlyAuthoringPrivateAssetRevisionUnavailableError",
    "OnlyAuthoringExecutionGenerationRegistry",
    "OnlyAuthoringExecutionGenerationStore",
    "OnlyVerifiedAuthoringGenerationReader",
]
