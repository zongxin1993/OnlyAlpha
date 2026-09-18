"""Verified process-generation composition outside the OnlyAlpha Core package."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import cast

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.quant_assets import (
    OnlyPrivateFactorAdapterV1,
    OnlyPrivateFactorExecutableClosureV1,
    OnlyPrivateFactorIsolatedProgramHost,
    OnlyPrivateFactorProviderSnapshotEntryV1,
    OnlyPrivateFactorProviderSnapshotV1,
    OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1,
    OnlyPrivateFactorRevision,
    OnlyPrivateFactorSnapshotProviderSource,
    OnlyPrivateFactorSourceArtifactManifestV1,
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
)
from onlyalpha.quant_assets.catalog import only_quant_asset_provider_source_from_dict
from onlyalpha.quant_assets.private import (
    OnlyPrivateAssetAuthorityUnavailableError,
    OnlyPrivateAssetKind,
    OnlyPrivateAssetRevisionBindingResolver,
    OnlyPrivateAssetRevisionCorruptError,
    OnlyPrivateAssetRevisionNotFoundError,
    OnlyPrivateAssetRevisionReferenceV1,
)
from onlyalpha.quant_assets.private_factor_execution import (
    _ADAPTER_FINGERPRINTS,
    only_private_factor_backend_registrations,
    only_validate_private_factor_revision,
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
    private_factor_executable_closure: OnlyPrivateFactorExecutableClosureV1

    @classmethod
    def create_verified(
        cls,
        *,
        experiment_id: str,
        private_asset_revision_reference: OnlyPrivateAssetRevisionReferenceV1,
        private_asset_revisions: OnlyPrivateAssetRevisionBindingResolver,
        private_factor_executable_closure: OnlyPrivateFactorExecutableClosureV1,
        candidate_provider_id: str,
        base_catalog: OnlyQuantAssetCatalogGeneration,
    ) -> OnlyAuthoringExecutionGeneration:
        binding = private_asset_revisions.resolve(private_asset_revision_reference)
        if binding.private_asset_kind is not OnlyPrivateAssetKind.FACTOR:
            raise ValueError("AUTHORING_EXECUTION_PRIVATE_ASSET_KIND_UNSUPPORTED")
        closure = private_factor_executable_closure
        OnlyPrivateFactorExecutableClosureV1.verify_canonical(closure)
        revision = closure.revision
        if (
            revision.factor_id != binding.private_asset_id
            or revision.semantic_version != binding.semantic_version
            or revision.revision_fingerprint != binding.private_asset_revision_fingerprint
            or revision.source_sha256 != binding.private_asset_content_fingerprint
            or revision.factor_api_version != binding.factor_api_version
            or revision.factor_api_contract_fingerprint != binding.factor_api_contract_fingerprint
        ):
            raise ValueError("AUTHORING_PRIVATE_FACTOR_EXECUTION_BINDING_MISMATCH")
        if any(provider.manifest.provider_id == candidate_provider_id for provider in base_catalog.providers):
            raise ValueError("AUTHORING_CANDIDATE_PROVIDER_DUPLICATE")
        provider = OnlyQuantAssetProvider(
            OnlyQuantAssetProviderManifest(
                candidate_provider_id,
                revision.revision_fingerprint,
                OnlyQuantAssetKind.FACTOR,
                OnlyPrivateFactorSnapshotProviderSource(closure.provider_snapshot.snapshot_fingerprint),
            ),
            calculation_registrations=closure.registrations,
            private_factor_snapshot=closure.provider_snapshot,
        )
        catalog = OnlyQuantAssetCatalogGeneration((*base_catalog.providers, provider))
        provenance = OnlyResearchAuthoringProvenance(
            schema_version=1,
            experiment_id=experiment_id,
            private_asset_kind=OnlyPrivateAssetKind.FACTOR,
            private_asset_id=binding.private_asset_id,
            private_asset_revision_fingerprint=binding.private_asset_revision_fingerprint,
            private_asset_content_fingerprint=binding.private_asset_content_fingerprint,
            candidate_provider_id=provider.manifest.provider_id,
            candidate_provider_version=provider.manifest.provider_version,
            candidate_provider_content_fingerprint=provider.content_fingerprint,
            catalog_generation_fingerprint=catalog.generation_fingerprint,
            execution_generation_fingerprint=only_research_execution_generation_fingerprint(
                experiment_id=experiment_id,
                private_asset_kind=OnlyPrivateAssetKind.FACTOR,
                private_asset_id=binding.private_asset_id,
                private_asset_revision_fingerprint=binding.private_asset_revision_fingerprint,
                private_asset_content_fingerprint=binding.private_asset_content_fingerprint,
                candidate_provider_id=provider.manifest.provider_id,
                candidate_provider_version=provider.manifest.provider_version,
                candidate_provider_content_fingerprint=provider.content_fingerprint,
                catalog_generation_fingerprint=catalog.generation_fingerprint,
            ),
        )
        return cls._from_verified(provenance, catalog, closure)

    @classmethod
    def _from_verified(
        cls,
        provenance: OnlyResearchAuthoringProvenance,
        catalog: OnlyQuantAssetCatalogGeneration,
        closure: OnlyPrivateFactorExecutableClosureV1,
    ) -> OnlyAuthoringExecutionGeneration:
        self = object.__new__(cls)
        object.__setattr__(self, "provenance", provenance)
        object.__setattr__(self, "catalog", catalog)
        object.__setattr__(self, "private_factor_executable_closure", closure)
        self._verify_composition()
        return self

    def _verify_composition(self) -> None:
        if self.catalog.generation_fingerprint != self.provenance.catalog_generation_fingerprint:
            raise ValueError("AUTHORING_CATALOG_GENERATION_MISMATCH")
        if self.provenance.private_asset_kind is not OnlyPrivateAssetKind.FACTOR:
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
        if matches[0].manifest.kind is not OnlyQuantAssetKind.FACTOR:
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
            "private_factor_execution": {
                "source_artifact": self.private_factor_executable_closure.source_artifact.to_dict(),
                "equivalence_evidence": self.private_factor_executable_closure.equivalence_evidence.to_dict(),
                "certification_vectors": [
                    dict(item) for item in self.private_factor_executable_closure.certification_vectors
                ],
                "certification_parameters": dict(self.private_factor_executable_closure.certification_parameters),
            },
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
                or set(descriptor)
                != {
                    "schema_version",
                    "execution_generation_fingerprint",
                    "provenance",
                    "catalog",
                    "private_factor_execution",
                }
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
                or matches[0]["manifest"].get("kind") != OnlyQuantAssetKind.FACTOR.value
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
        try:
            revision = self._private_asset_revisions.resolve_factor_revision(reference)
            self._verify_native_factor_closure(descriptor, provenance, revision)
        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise OnlyAuthoringPrivateAssetBindingMismatchError() from exc
        return descriptor, provenance

    @staticmethod
    def _verify_native_factor_closure(
        descriptor: Mapping[str, object],
        provenance: OnlyResearchAuthoringProvenance,
        revision: object,
    ) -> None:
        if not hasattr(revision, "factor_id"):
            raise ValueError("AUTHORING_PRIVATE_FACTOR_REVISION_INVALID")
        factor_revision = cast(OnlyPrivateFactorRevision, revision)
        catalog = descriptor["catalog"]
        execution = descriptor["private_factor_execution"]
        if not isinstance(catalog, Mapping) or not isinstance(execution, Mapping):
            raise ValueError("AUTHORING_PRIVATE_FACTOR_CLOSURE_INVALID")
        if set(execution) != {
            "source_artifact",
            "equivalence_evidence",
            "certification_vectors",
            "certification_parameters",
        }:
            raise ValueError("AUTHORING_PRIVATE_FACTOR_CLOSURE_INVALID")
        providers = catalog.get("providers")
        if not isinstance(providers, list):
            raise ValueError("AUTHORING_PRIVATE_FACTOR_CLOSURE_INVALID")
        candidates = [
            provider
            for provider in providers
            if isinstance(provider, Mapping)
            and isinstance(provider.get("manifest"), Mapping)
            and provider["manifest"].get("provider_id") == provenance.candidate_provider_id
            and provider["manifest"].get("provider_version") == provenance.candidate_provider_version
        ]
        if len(candidates) != 1 or not isinstance(candidates[0], Mapping):
            raise ValueError("AUTHORING_PRIVATE_FACTOR_PROVIDER_INVALID")
        candidate = candidates[0]
        manifest_raw = candidate.get("manifest")
        source_raw = manifest_raw.get("source") if isinstance(manifest_raw, Mapping) else None
        if (
            not isinstance(manifest_raw, Mapping)
            or manifest_raw.get("kind") != OnlyQuantAssetKind.FACTOR.value
            or not isinstance(source_raw, Mapping)
            or source_raw.get("kind") != "PRIVATE_FACTOR_SNAPSHOT"
        ):
            raise ValueError("AUTHORING_PRIVATE_FACTOR_PROVIDER_INVALID")
        snapshot_raw = candidate.get("private_factor_snapshot")
        if not isinstance(snapshot_raw, Mapping):
            raise ValueError("AUTHORING_PRIVATE_FACTOR_SNAPSHOT_INVALID")
        snapshot = OnlyPrivateFactorProviderSnapshotV1.from_dict(snapshot_raw)
        if len(snapshot.entries) != 1:
            raise ValueError("AUTHORING_PRIVATE_FACTOR_SNAPSHOT_INVALID")
        entry = snapshot.entries[0]
        if (
            entry.factor_id != factor_revision.factor_id
            or entry.semantic_version != factor_revision.semantic_version
            or entry.revision_fingerprint != factor_revision.revision_fingerprint
            or entry.source_sha256 != factor_revision.source_sha256
            or entry.factor_api_version != factor_revision.factor_api_version
            or entry.factor_api_contract_fingerprint != factor_revision.factor_api_contract_fingerprint
            or entry.factor_id != provenance.private_asset_id
            or entry.revision_fingerprint != provenance.private_asset_revision_fingerprint
        ):
            raise ValueError("AUTHORING_PRIVATE_FACTOR_SNAPSHOT_MISMATCH")
        expected_validation = only_validate_private_factor_revision(factor_revision)
        expected_artifact, source = OnlyPrivateFactorSourceArtifactManifestV1.materialize(
            factor_revision, expected_validation
        )
        artifact_raw = execution.get("source_artifact")
        evidence_raw = execution.get("equivalence_evidence")
        vectors = execution.get("certification_vectors")
        parameters = execution.get("certification_parameters")
        if (
            not isinstance(artifact_raw, Mapping)
            or not isinstance(evidence_raw, Mapping)
            or not isinstance(vectors, list)
            or any(not isinstance(item, Mapping) for item in vectors)
            or not isinstance(parameters, Mapping)
        ):
            raise ValueError("AUTHORING_PRIVATE_FACTOR_CLOSURE_INVALID")
        artifact = OnlyPrivateFactorSourceArtifactManifestV1.from_dict(artifact_raw)
        evidence = OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1.from_dict(evidence_raw)
        if artifact != expected_artifact:
            raise ValueError("AUTHORING_PRIVATE_FACTOR_SOURCE_ARTIFACT_MISMATCH")
        research = OnlyPrivateFactorAdapterV1(
            "RESEARCH", _ADAPTER_FINGERPRINTS["RESEARCH"], OnlyPrivateFactorIsolatedProgramHost()
        )
        trading = OnlyPrivateFactorAdapterV1(
            "TRADING", _ADAPTER_FINGERPRINTS["TRADING"], OnlyPrivateFactorIsolatedProgramHost()
        )
        registrations = only_private_factor_backend_registrations(factor_revision, artifact, source, research, trading)
        recomputed_evidence = OnlyPrivateFactorResearchTradingEquivalenceEvidenceV1.certify(
            artifact,
            source,
            registrations,
            tuple(
                _restore_factor_values(cast(Mapping[str, object], item), factor_revision.input_contract)
                for item in vectors
            ),
            _restore_factor_values(parameters, factor_revision.parameter_contract),
        )
        expected_snapshot = OnlyPrivateFactorProviderSnapshotV1(
            (OnlyPrivateFactorProviderSnapshotEntryV1.derive(expected_artifact, recomputed_evidence),)
        )
        if evidence != recomputed_evidence or snapshot != expected_snapshot:
            raise ValueError("AUTHORING_PRIVATE_FACTOR_EQUIVALENCE_MISMATCH")
        manifest = OnlyQuantAssetProviderManifest(
            cast(str, manifest_raw["provider_id"]),
            cast(str, manifest_raw["provider_version"]),
            OnlyQuantAssetKind.FACTOR,
            only_quant_asset_provider_source_from_dict(source_raw),
            cast(int, manifest_raw.get("schema_version", 1)),
        )
        provider = OnlyQuantAssetProvider(
            manifest,
            calculation_registrations=registrations,
            private_factor_snapshot=snapshot,
        )
        if (
            provider.content_fingerprint != provenance.candidate_provider_content_fingerprint
            or only_canonical_fingerprint(provider.descriptor()) != only_canonical_fingerprint(candidate)
        ):
            raise ValueError("AUTHORING_PRIVATE_FACTOR_PROVIDER_MISMATCH")


def _restore_factor_values(values: Mapping[str, object], contract: Mapping[str, object]) -> dict[str, object]:
    restored: dict[str, object] = {}
    if set(values) != set(contract):
        raise ValueError("AUTHORING_PRIVATE_FACTOR_CERTIFICATION_INPUT_MISMATCH")
    for name, value in values.items():
        definition = contract[name]
        if not isinstance(definition, Mapping) or not isinstance(definition.get("type"), str):
            raise ValueError("AUTHORING_PRIVATE_FACTOR_CERTIFICATION_CONTRACT_INVALID")
        data_type = definition["type"]
        if value is None or data_type in {"STRING", "BOOLEAN"}:
            restored[name] = value
        elif data_type == "DECIMAL":
            restored[name] = Decimal(value) if isinstance(value, str) else value
        elif data_type == "INTEGER":
            restored[name] = int(value) if isinstance(value, str) else value
        else:
            raise ValueError("AUTHORING_PRIVATE_FACTOR_CERTIFICATION_CONTRACT_INVALID")
    return restored


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
