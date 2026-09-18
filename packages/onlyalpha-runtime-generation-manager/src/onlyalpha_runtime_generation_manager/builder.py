"""Candidate-first clean-environment Runtime Generation construction."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from onlyalpha.calculation import OnlyCalculationBackendKind
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.distribution import (
    OnlyArtifactCalculationImplementation,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)
from onlyalpha.quant_assets import (
    OnlyPrivateAlphaAdapterV1,
    OnlyPrivateAlphaExecutableClosureV1,
    OnlyPrivateAlphaIsolatedProgramHost,
    OnlyPrivateAlphaProviderSnapshotV1,
    OnlyPrivateAlphaResearchTradingEquivalenceEvidenceV1,
    OnlyPrivateAlphaSnapshotProviderSource,
    OnlyPrivateAlphaSourceArtifactManifestV1,
    OnlyQuantAssetCatalogGeneration,
    OnlyQuantAssetKind,
    OnlyQuantAssetProvider,
    OnlyQuantAssetProviderManifest,
    only_private_alpha_backend_registrations,
)
from onlyalpha.quant_assets.private import OnlyPrivateAlphaRevision
from onlyalpha.runtime.generation import (
    OnlyCoreExecutionIdentity,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeGenerationValidationEvidence,
    OnlyRuntimePrivateAlphaBinding,
    OnlyRuntimeProviderBinding,
)

from .artifact_store import OnlyLocalImmutableArtifactStore

_PROBE = r"""
from importlib import metadata
from onlyalpha.calculation import OnlyCalculationRegistry
from onlyalpha.canonical import only_canonical_json
from onlyalpha.quant_assets import only_discover_quant_asset_providers
from onlyalpha.research.calculation.predicate import only_register_research_predicate_primitives
from onlyalpha.runtime.trading.predicate import only_register_trading_predicate_primitives

def normalized_distribution_name(value):
    import re
    return re.sub(r"[-_.]+", "-", value).lower()

catalog = only_discover_quant_asset_providers()
registry = OnlyCalculationRegistry()
entries = metadata.entry_points().select(group="onlyalpha.calculations")
implementation_distributions = []
for entry in sorted(entries, key=lambda item: (item.name, item.value)):
    if entry.dist is None:
        raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
    loaded = entry.load()
    registrations = loaded() if callable(loaded) else tuple(loaded)
    for registration in registrations:
        registry.register(registration)
        manifest = registration.implementation_manifest
        if manifest is None:
            raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
        definition = registration.type_definition
        implementation_distributions.append({
            "distribution_name": normalized_distribution_name(entry.dist.name),
            "distribution_version": entry.dist.version,
            "implementation": {
                "kind": definition.kind.value,
                "type_id": definition.type_id,
                "semantic_version": definition.semantic_version,
                "backend": registration.backend.value,
                "implementation_fingerprint": manifest.implementation_fingerprint,
            },
        })
only_register_research_predicate_primitives(registry)
only_register_trading_predicate_primitives(registry)
implementations = []
for registration in registry.backend_registrations():
    manifest = registration.implementation_manifest
    if manifest is None:
        raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
    definition = registration.type_definition
    implementations.append({
        "kind": definition.kind.value,
        "type_id": definition.type_id,
        "semantic_version": definition.semantic_version,
        "backend": registration.backend.value,
        "implementation_fingerprint": manifest.implementation_fingerprint,
    })
distributions = [
    {
        "distribution_name": normalized_distribution_name(distribution.metadata["Name"]),
        "distribution_version": distribution.version,
    }
    for distribution in metadata.distributions()
]
print(only_canonical_json({
    "catalog": catalog.descriptor(),
    "distributions": distributions,
    "implementation_distributions": implementation_distributions,
    "implementations": implementations,
}))
"""

_CATALOG_PROBE = r"""
import json
from pathlib import Path
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.research.calculation.binding import only_research_dataset_source_contracts
from onlyalpha.research.evaluation.capability import only_research_statistics_capabilities
from onlyalpha.runtime.generation import OnlyRuntimeGenerationValidationEvidence
from onlyalpha_runtime_generation_manager.hosted import only_load_hosted_quant_asset_catalog

evidence = OnlyRuntimeGenerationValidationEvidence.from_dict(json.loads(
    Path("onlyalpha-runtime-generation-validation.json").read_text(encoding="utf-8")
))
catalog = only_load_hosted_quant_asset_catalog(evidence)

dataset_fields = []
for source_id, item in only_research_dataset_source_contracts():
    dataset_fields.append({
        "source_id": source_id, "column": item.column, "data_type": item.data_type.value,
        "semantic_roles": sorted(item.semantic_roles), "dimensions": list(item.dimensions), "unit": item.unit,
        "source_contract_fingerprint": item.source_contract_fingerprint,
    })
statistics = []
for item in only_research_statistics_capabilities():
    value = {
        "statistic_type": item.method.value,
        "variable_kinds": sorted(value.value for value in item.variable_kinds),
        "variable_semantic_roles": sorted(item.variable_semantic_types),
        "target_semantic_roles": sorted(item.target_semantic_types),
        "target_required": item.target_required, "executable": item.executable,
    }
    value["capability_fingerprint"] = only_canonical_fingerprint({
        "domain": "onlyalpha.research.statistics-capability", **value,
    })
    statistics.append(value)
print(only_canonical_json({
    "catalog": catalog.descriptor(),
    "dataset_fields": dataset_fields,
    "registered_universes": [],
    "statistics": statistics,
}))
"""

_HOSTED_GENERATION_SEAL = "onlyalpha-runtime-generation-validation.json"
_PRIVATE_ALPHA_ARTIFACT_ROOT = "private-alpha-artifacts"


@dataclass(frozen=True, slots=True)
class OnlyValidatedRuntimeGeneration:
    manifest: OnlyRuntimeGenerationManifest
    validation_evidence: OnlyRuntimeGenerationValidationEvidence

    def __post_init__(self) -> None:
        if not self.validation_evidence.verifies(self.manifest):
            raise ValueError("RUNTIME_GENERATION_VALIDATION_EVIDENCE_MISMATCH")


@dataclass(frozen=True, slots=True)
class OnlyRuntimeGenerationBuilder:
    artifact_store: OnlyLocalImmutableArtifactStore
    python_executable: Path

    def build(
        self,
        *,
        artifacts: tuple[OnlyDistributionArtifactManifest, ...],
        expected_catalog: OnlyQuantAssetCatalogGeneration,
        environment_root: Path,
    ) -> OnlyRuntimeGenerationManifest:
        canonical = tuple(sorted(artifacts, key=lambda item: item.manifest_fingerprint))
        if not canonical or len({item.artifact_sha256 for item in canonical}) != len(canonical):
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MISMATCH")
        distribution_identities = tuple(
            (_normalized_distribution_name(item.distribution_name), item.distribution_version) for item in canonical
        )
        if len(set(name for name, _ in distribution_identities)) != len(distribution_identities):
            raise ValueError("RUNTIME_GENERATION_ARTIFACT_MISMATCH")
        core = self._core_identity(canonical)
        for artifact in canonical:
            self.artifact_store.verify_exact(artifact)
            if (
                artifact.role in {OnlyDistributionArtifactRole.QUANT_ASSET, OnlyDistributionArtifactRole.CALCULATION}
                and artifact.tested_core_execution_fingerprint != core.fingerprint
            ):
                raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
        if environment_root.exists():
            raise FileExistsError("RUNTIME_GENERATION_ENVIRONMENT_EXISTS")
        environment_root.parent.mkdir(parents=True, exist_ok=True)
        try:
            created = subprocess.run(
                [str(self.python_executable), "-I", "-m", "venv", str(environment_root)],
                capture_output=True,
                text=True,
                check=False,
                env=self._isolated_environment(),
            )
            if created.returncode != 0:
                raise ValueError("RUNTIME_GENERATION_ENVIRONMENT_INVALID") from RuntimeError(created.stderr)
            wheels = self._materialize(canonical, environment_root / "artifacts")
            python = self._environment_python(environment_root)
            installed = subprocess.run(
                [str(python), "-I", "-m", "pip", "install", "--no-index", "--no-deps", *map(str, wheels)],
                capture_output=True,
                text=True,
                check=False,
                env=self._isolated_environment(),
            )
            if installed.returncode != 0:
                raise ValueError("RUNTIME_GENERATION_ARTIFACT_INSTALL_FAILED") from RuntimeError(installed.stderr)
            probed = subprocess.run(
                [str(python), "-I", "-c", _PROBE],
                capture_output=True,
                text=True,
                check=False,
                env=self._isolated_environment(),
            )
            if probed.returncode != 0:
                raise ValueError("RUNTIME_GENERATION_PROVIDER_MISMATCH") from RuntimeError(probed.stderr)
            try:
                actual: Any = json.loads(probed.stdout)
            except json.JSONDecodeError as exc:
                raise ValueError("RUNTIME_GENERATION_PROVIDER_MISMATCH") from exc
            if not isinstance(actual, dict) or actual.get("catalog") != json.loads(
                only_canonical_json(expected_catalog.descriptor())
            ):
                raise ValueError("RUNTIME_GENERATION_CATALOG_MISMATCH")
            actual_distributions = actual.get("distributions")
            if not isinstance(actual_distributions, list) or not set(distribution_identities) <= {
                (item.get("distribution_name"), item.get("distribution_version"))
                for item in actual_distributions
                if isinstance(item, dict)
            }:
                raise ValueError("RUNTIME_GENERATION_ARTIFACT_MISMATCH")
            supplied_implementations = sorted(
                (
                    {
                        "distribution_name": _normalized_distribution_name(artifact.distribution_name),
                        "distribution_version": artifact.distribution_version,
                        "implementation": item.to_dict(),
                    }
                    for artifact in canonical
                    for item in artifact.implementations
                ),
                key=only_canonical_json,
            )
            actual_implementations = actual.get("implementation_distributions")
            if (
                not isinstance(actual_implementations, list)
                or sorted(actual_implementations, key=only_canonical_json) != supplied_implementations
            ):
                raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
            runtime_implementations = self._runtime_implementations(actual)
            if not {item.implementation_fingerprint for artifact in canonical for item in artifact.implementations} <= {
                item.implementation_fingerprint for item in runtime_implementations
            }:
                raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
            return self._manifest(core, canonical, expected_catalog, runtime_implementations)
        except Exception:
            shutil.rmtree(environment_root, ignore_errors=True)
            raise

    def build_validated(
        self,
        *,
        artifacts: tuple[OnlyDistributionArtifactManifest, ...],
        expected_catalog: OnlyQuantAssetCatalogGeneration,
        environment_root: Path,
    ) -> OnlyValidatedRuntimeGeneration:
        manifest = self.build(
            artifacts=artifacts,
            expected_catalog=expected_catalog,
            environment_root=environment_root,
        )
        validated = OnlyValidatedRuntimeGeneration(
            manifest,
            OnlyRuntimeGenerationValidationEvidence.from_manifest(manifest),
        )
        self._seal_environment(environment_root, validated.validation_evidence)
        self._verify_hosted_environment(environment_root, validated.validation_evidence)
        return validated

    def rebuild_validated(
        self,
        *,
        expected_manifest: OnlyRuntimeGenerationManifest,
        environment_root: Path,
    ) -> OnlyValidatedRuntimeGeneration:
        """Reconstruct one historical generation solely from its exact stored artifacts."""

        try:
            self.verify_exact_artifacts(expected_manifest)
            artifacts = tuple(
                self.artifact_store.fetch_exact(artifact_sha256)[0]
                for artifact_sha256 in expected_manifest.artifact_sha256s
            )
            canonical = tuple(sorted(artifacts, key=lambda item: item.manifest_fingerprint))
            if (
                tuple(sorted(item.manifest_fingerprint for item in canonical))
                != expected_manifest.artifact_manifest_fingerprints
            ):
                raise ValueError("RUNTIME_GENERATION_ARTIFACT_MISMATCH")
            core = self._core_identity(canonical)
            if core != expected_manifest.core_execution:
                raise ValueError("RUNTIME_GENERATION_CORE_IDENTITY_INVALID")
            for artifact in canonical:
                self.artifact_store.verify_exact(artifact)
                if (
                    artifact.role
                    in {OnlyDistributionArtifactRole.QUANT_ASSET, OnlyDistributionArtifactRole.CALCULATION}
                    and artifact.tested_core_execution_fingerprint != core.fingerprint
                ):
                    raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
            if environment_root.exists():
                raise FileExistsError("RUNTIME_GENERATION_ENVIRONMENT_EXISTS")
            environment_root.parent.mkdir(parents=True, exist_ok=True)
            created = subprocess.run(
                [str(self.python_executable), "-I", "-m", "venv", str(environment_root)],
                capture_output=True,
                text=True,
                check=False,
                env=self._isolated_environment(),
            )
            if created.returncode != 0:
                raise ValueError("RUNTIME_GENERATION_ENVIRONMENT_INVALID") from RuntimeError(created.stderr)
            wheels = self._materialize(canonical, environment_root / "artifacts")
            python = self._environment_python(environment_root)
            installed = subprocess.run(
                [str(python), "-I", "-m", "pip", "install", "--no-index", "--no-deps", *map(str, wheels)],
                capture_output=True,
                text=True,
                check=False,
                env=self._isolated_environment(),
            )
            if installed.returncode != 0:
                raise ValueError("RUNTIME_GENERATION_ARTIFACT_INSTALL_FAILED") from RuntimeError(installed.stderr)
            probed = subprocess.run(
                [str(python), "-I", "-c", _PROBE],
                capture_output=True,
                text=True,
                check=False,
                env=self._isolated_environment(),
            )
            if probed.returncode != 0:
                raise ValueError("RUNTIME_GENERATION_PROVIDER_MISMATCH") from RuntimeError(probed.stderr)
            actual: Any = json.loads(probed.stdout)
            distribution_catalog = actual.get("catalog") if isinstance(actual, dict) else None
            catalog = (
                self._catalog_with_private_alpha(distribution_catalog, expected_manifest)
                if isinstance(distribution_catalog, dict)
                else None
            )
            if (
                not isinstance(catalog, dict)
                or catalog.get("generation_fingerprint") != expected_manifest.catalog_generation_fingerprint
            ):
                raise ValueError("RUNTIME_GENERATION_CATALOG_MISMATCH")
            if not isinstance(distribution_catalog, dict):
                raise ValueError("RUNTIME_GENERATION_CATALOG_MISMATCH")
            actual_providers = tuple(
                sorted(
                    OnlyRuntimeProviderBinding(
                        item["manifest"]["provider_id"],
                        item["manifest"]["provider_version"],
                        item["content_fingerprint"],
                        next(
                            artifact.artifact_sha256
                            for artifact in canonical
                            if artifact.provider_id == item["manifest"]["provider_id"]
                            and artifact.provider_version == item["manifest"]["provider_version"]
                            and artifact.provider_content_fingerprint == item["content_fingerprint"]
                        ),
                    )
                    for item in distribution_catalog.get("providers", [])
                )
            )
            if actual_providers != expected_manifest.providers:
                raise ValueError("RUNTIME_GENERATION_PROVIDER_MISMATCH")
            supplied_implementations = sorted(
                (
                    {
                        "distribution_name": _normalized_distribution_name(artifact.distribution_name),
                        "distribution_version": artifact.distribution_version,
                        "implementation": item.to_dict(),
                    }
                    for artifact in canonical
                    for item in artifact.implementations
                ),
                key=only_canonical_json,
            )
            if (
                sorted(actual.get("implementation_distributions", []), key=only_canonical_json)
                != supplied_implementations
            ):
                raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
            runtime_implementations = tuple(
                sorted(
                    (*self._runtime_implementations(actual), *self._private_alpha_implementations(expected_manifest))
                )
            )
            if runtime_implementations != expected_manifest.implementations:
                raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
            rebuilt = OnlyRuntimeGenerationManifest(
                core_execution=core,
                artifact_manifest_fingerprints=tuple(item.manifest_fingerprint for item in canonical),
                artifact_sha256s=tuple(item.artifact_sha256 for item in canonical),
                providers=actual_providers,
                catalog_generation_fingerprint=cast(str, catalog["generation_fingerprint"]),
                implementations=runtime_implementations,
                private_alpha_bindings=expected_manifest.private_alpha_bindings,
            )
            if rebuilt != expected_manifest:
                raise ValueError("RUNTIME_GENERATION_MANIFEST_MISMATCH")
            validated = OnlyValidatedRuntimeGeneration(
                rebuilt,
                OnlyRuntimeGenerationValidationEvidence.from_manifest(rebuilt),
            )
            self._materialize_private_alpha_artifacts(
                rebuilt.private_alpha_bindings,
                environment_root / _PRIVATE_ALPHA_ARTIFACT_ROOT,
            )
            self._seal_environment(environment_root, validated.validation_evidence)
            self._verify_hosted_environment(environment_root, validated.validation_evidence)
            return validated
        except Exception:
            shutil.rmtree(environment_root, ignore_errors=True)
            raise

    def rebuild_catalog_descriptor(
        self,
        *,
        expected_manifest: OnlyRuntimeGenerationManifest,
        environment_root: Path,
    ) -> dict[str, object]:
        """Reconstruct and probe exact Catalog metadata without importing it in this process."""

        return cast(
            dict[str, object],
            self.rebuild_catalog_context_bundle(expected_manifest=expected_manifest, environment_root=environment_root)[
                "catalog"
            ],
        )

    def verify_exact_artifacts(self, expected_manifest: OnlyRuntimeGenerationManifest) -> None:
        """Verify that every artifact bound by an exact Runtime Generation still exists unchanged."""

        for artifact_sha256 in expected_manifest.artifact_sha256s:
            self.artifact_store.fetch_exact(artifact_sha256)
        for binding in expected_manifest.private_alpha_bindings:
            runtime = self.artifact_store.fetch_private_alpha_runtime(binding.runtime_artifact_fingerprint)
            snapshot = OnlyPrivateAlphaProviderSnapshotV1.from_dict(
                cast(dict[str, object], runtime["provider_snapshot"])
            )
            if (
                snapshot.snapshot_fingerprint != binding.provider_snapshot_fingerprint
                or binding.entry not in snapshot.entries
            ):
                raise ValueError("RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH")
            artifact, _ = self.artifact_store.fetch_private_alpha_source(binding.entry.source_artifact_fingerprint)
            if (
                artifact.alpha_id != binding.entry.alpha_id
                or artifact.semantic_version != binding.entry.semantic_version
                or artifact.revision_fingerprint != binding.entry.revision_fingerprint
                or artifact.source_sha256 != binding.entry.source_sha256
                or artifact.alpha_api_contract_fingerprint != binding.entry.alpha_api_contract_fingerprint
            ):
                raise ValueError("RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH")

    def bind_private_alpha_closure(
        self,
        *,
        base_manifest: OnlyRuntimeGenerationManifest,
        expected_catalog: OnlyQuantAssetCatalogGeneration,
        closure: OnlyPrivateAlphaExecutableClosureV1,
    ) -> OnlyRuntimeGenerationManifest:
        matching = tuple(
            provider
            for provider in expected_catalog.providers
            if provider.private_alpha_snapshot == closure.provider_snapshot
        )
        if len(matching) != 1:
            raise ValueError("RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH")
        provider = matching[0]
        expected_base = {
            (
                item.manifest.provider_id,
                item.manifest.provider_version,
                item.content_fingerprint,
            )
            for item in expected_catalog.providers
            if item.private_alpha_snapshot is None
        }
        if {
            (item.provider_id, item.provider_version, item.provider_content_fingerprint)
            for item in base_manifest.providers
        } != expected_base:
            raise ValueError("RUNTIME_GENERATION_PROVIDER_MISMATCH")
        self.artifact_store.put_private_alpha_source(closure.source_artifact, closure.source)
        runtime_artifact_fingerprint = self.artifact_store.put_private_alpha_runtime(closure, provider)
        bindings = tuple(
            OnlyRuntimePrivateAlphaBinding(
                closure.provider_snapshot.snapshot_fingerprint,
                runtime_artifact_fingerprint,
                entry,
            )
            for entry in closure.provider_snapshot.entries
        )
        implementations = tuple(
            sorted((*base_manifest.implementations, *self._private_alpha_implementations_from_bindings(bindings)))
        )
        candidate = replace(
            base_manifest,
            catalog_generation_fingerprint=expected_catalog.generation_fingerprint,
            implementations=implementations,
            private_alpha_bindings=bindings,
        )
        self.verify_exact_artifacts(candidate)
        if only_canonical_json(
            self._catalog_with_private_alpha(self._base_catalog_descriptor(expected_catalog), candidate)
        ) != only_canonical_json(expected_catalog.descriptor()):
            raise ValueError("RUNTIME_GENERATION_CATALOG_MISMATCH")
        return candidate

    def rebuild_catalog_context_bundle(
        self,
        *,
        expected_manifest: OnlyRuntimeGenerationManifest,
        environment_root: Path,
    ) -> dict[str, object]:
        """Reconstruct exact Catalog and Research capability facts in the isolated generation."""

        self.rebuild_validated(expected_manifest=expected_manifest, environment_root=environment_root)
        probed = subprocess.run(
            [str(self._environment_python(environment_root)), "-I", "-c", _CATALOG_PROBE],
            cwd=environment_root,
            capture_output=True,
            text=True,
            check=False,
            env=self._isolated_environment(),
        )
        if probed.returncode != 0:
            raise ValueError("RUNTIME_GENERATION_CATALOG_MISMATCH")
        try:
            bundle: Any = json.loads(probed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("RUNTIME_GENERATION_CATALOG_MISMATCH") from exc
        if not isinstance(bundle, dict) or not isinstance(bundle.get("catalog"), dict):
            raise ValueError("RUNTIME_GENERATION_CATALOG_MISMATCH")
        if (
            cast(dict[str, object], bundle["catalog"]).get("generation_fingerprint")
            != expected_manifest.catalog_generation_fingerprint
        ):
            raise ValueError("RUNTIME_GENERATION_CATALOG_MISMATCH")
        return cast(dict[str, object], bundle)

    def rebuild_private_alpha_providers(
        self, expected_manifest: OnlyRuntimeGenerationManifest
    ) -> tuple[OnlyQuantAssetProvider, ...]:
        return self.rebuild_private_alpha_providers_from_bindings(expected_manifest.private_alpha_bindings)

    def rebuild_private_alpha_providers_from_bindings(
        self, bindings: tuple[OnlyRuntimePrivateAlphaBinding, ...]
    ) -> tuple[OnlyQuantAssetProvider, ...]:
        providers = []
        for fingerprint in sorted({item.runtime_artifact_fingerprint for item in bindings}):
            provider = self._private_alpha_provider(fingerprint)
            expected = tuple(
                sorted(item.entry for item in bindings if item.runtime_artifact_fingerprint == fingerprint)
            )
            if (
                provider.private_alpha_snapshot is None
                or provider.private_alpha_snapshot.entries != expected
                or any(
                    item.provider_snapshot_fingerprint != provider.private_alpha_snapshot.snapshot_fingerprint
                    for item in bindings
                    if item.runtime_artifact_fingerprint == fingerprint
                )
            ):
                raise ValueError("RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH")
            providers.append(provider)
        return tuple(providers)

    def _private_alpha_provider(self, fingerprint: str) -> OnlyQuantAssetProvider:
        payload = self.artifact_store.fetch_private_alpha_runtime(fingerprint)
        source_artifact = OnlyPrivateAlphaSourceArtifactManifestV1.from_dict(
            cast(dict[str, object], payload["source_artifact"])
        )
        stored_artifact, source = self.artifact_store.fetch_private_alpha_source(
            source_artifact.source_artifact_fingerprint
        )
        if stored_artifact != source_artifact:
            raise ValueError("RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH")
        revision_payload = dict(cast(dict[str, object], payload["revision_metadata"]))
        try:
            revision_payload["source_text"] = source.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH") from exc
        revision = OnlyPrivateAlphaRevision.from_dict(revision_payload)
        snapshot = OnlyPrivateAlphaProviderSnapshotV1.from_dict(cast(dict[str, object], payload["provider_snapshot"]))
        evidence = OnlyPrivateAlphaResearchTradingEquivalenceEvidenceV1.from_dict(
            cast(dict[str, object], payload["equivalence_evidence"])
        )
        if len(snapshot.entries) != 1:
            raise ValueError("RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH")
        entry = snapshot.entries[0]
        if evidence.equivalence_evidence_fingerprint != entry.equivalence_evidence_fingerprint:
            raise ValueError("RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH")
        host = OnlyPrivateAlphaIsolatedProgramHost()
        registrations = only_private_alpha_backend_registrations(
            revision,
            source_artifact,
            source,
            OnlyPrivateAlphaAdapterV1("RESEARCH", entry.research_adapter_fingerprint, host),
            OnlyPrivateAlphaAdapterV1("TRADING", entry.trading_adapter_fingerprint, host),
        )
        provider_payload = cast(dict[str, object], payload["provider"])
        manifest_payload = cast(dict[str, object], provider_payload["manifest"])
        source_payload = cast(dict[str, object], manifest_payload["source"])
        schema_version = manifest_payload["schema_version"]
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise ValueError("RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH")
        provider = OnlyQuantAssetProvider(
            OnlyQuantAssetProviderManifest(
                str(manifest_payload["provider_id"]),
                str(manifest_payload["provider_version"]),
                OnlyQuantAssetKind(str(manifest_payload["kind"])),
                OnlyPrivateAlphaSnapshotProviderSource(
                    str(source_payload["private_alpha_provider_snapshot_fingerprint"])
                ),
                schema_version,
            ),
            calculation_registrations=registrations,
            private_alpha_snapshot=snapshot,
        )
        if only_canonical_json(provider.descriptor()) != only_canonical_json(provider_payload):
            raise ValueError("RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH")
        return provider

    def _catalog_with_private_alpha(
        self,
        catalog: dict[str, object],
        manifest: OnlyRuntimeGenerationManifest,
    ) -> dict[str, object]:
        providers = catalog.get("providers")
        if not isinstance(providers, list):
            raise ValueError("RUNTIME_GENERATION_CATALOG_MISMATCH")
        native: list[dict[str, object]] = []
        for fingerprint in sorted({item.runtime_artifact_fingerprint for item in manifest.private_alpha_bindings}):
            descriptor = self.artifact_store.fetch_private_alpha_runtime(fingerprint).get("provider")
            if not isinstance(descriptor, dict):
                raise ValueError("RUNTIME_GENERATION_PRIVATE_ALPHA_MISMATCH")
            native.append(cast(dict[str, object], descriptor))
        combined = sorted(
            [*providers, *native],
            key=lambda item: (
                cast(dict[str, object], item)["manifest"]["kind"],  # type: ignore[index]
                cast(dict[str, object], item)["manifest"]["provider_id"],  # type: ignore[index]
                cast(dict[str, object], item)["manifest"]["provider_version"],  # type: ignore[index]
            ),
        )
        result: dict[str, object] = {"schema_version": 1, "providers": combined}
        result["generation_fingerprint"] = only_canonical_fingerprint(result)
        return result

    @staticmethod
    def _base_catalog_descriptor(catalog: OnlyQuantAssetCatalogGeneration) -> dict[str, object]:
        return OnlyQuantAssetCatalogGeneration(
            tuple(provider for provider in catalog.providers if provider.private_alpha_snapshot is None)
        ).descriptor()

    def _private_alpha_implementations(
        self, manifest: OnlyRuntimeGenerationManifest
    ) -> tuple[OnlyArtifactCalculationImplementation, ...]:
        return self._private_alpha_implementations_from_bindings(manifest.private_alpha_bindings)

    @staticmethod
    def _private_alpha_implementations_from_bindings(
        bindings: tuple[OnlyRuntimePrivateAlphaBinding, ...],
    ) -> tuple[OnlyArtifactCalculationImplementation, ...]:
        return tuple(
            sorted(
                implementation
                for binding in bindings
                for implementation in (
                    OnlyArtifactCalculationImplementation(
                        "FACTOR",
                        binding.entry.alpha_id,
                        binding.entry.semantic_version,
                        OnlyCalculationBackendKind.RESEARCH.value,
                        binding.entry.research_implementation_fingerprint,
                    ),
                    OnlyArtifactCalculationImplementation(
                        "FACTOR",
                        binding.entry.alpha_id,
                        binding.entry.semantic_version,
                        OnlyCalculationBackendKind.TRADING.value,
                        binding.entry.trading_implementation_fingerprint,
                    ),
                )
            )
        )

    @staticmethod
    def _core_identity(artifacts: tuple[OnlyDistributionArtifactManifest, ...]) -> OnlyCoreExecutionIdentity:
        cores = tuple(item for item in artifacts if item.role is OnlyDistributionArtifactRole.CORE)
        if len(cores) != 1:
            raise ValueError("RUNTIME_GENERATION_CORE_IDENTITY_INVALID")
        core = cores[0]
        return OnlyCoreExecutionIdentity(core.distribution_name, core.distribution_version, core.artifact_sha256)

    @staticmethod
    def _manifest(
        core: OnlyCoreExecutionIdentity,
        artifacts: tuple[OnlyDistributionArtifactManifest, ...],
        catalog: OnlyQuantAssetCatalogGeneration,
        runtime_implementations: tuple[OnlyArtifactCalculationImplementation, ...],
    ) -> OnlyRuntimeGenerationManifest:
        quant = tuple(item for item in artifacts if item.role is OnlyDistributionArtifactRole.QUANT_ASSET)
        providers: list[OnlyRuntimeProviderBinding] = []
        for provider in catalog.providers:
            matches = tuple(
                item
                for item in quant
                if item.provider_id == provider.manifest.provider_id
                and item.provider_version == provider.manifest.provider_version
                and item.provider_content_fingerprint == provider.content_fingerprint
            )
            if len(matches) != 1:
                raise ValueError("RUNTIME_GENERATION_PROVIDER_MISMATCH")
            artifact = matches[0]
            providers.append(
                OnlyRuntimeProviderBinding(
                    provider.manifest.provider_id,
                    provider.manifest.provider_version,
                    provider.content_fingerprint,
                    artifact.artifact_sha256,
                )
            )
            expected = tuple(sorted(artifact.implementations))
            actual = tuple(
                sorted(
                    OnlyArtifactCalculationImplementation(
                        registration.type_definition.kind.value,
                        registration.type_definition.type_id,
                        registration.type_definition.semantic_version,
                        registration.backend.value,
                        registration.implementation_manifest.implementation_fingerprint,
                    )
                    for registration in provider.calculation_registrations
                    if registration.implementation_manifest is not None
                )
            )
            if actual != expected or len(actual) != len(provider.calculation_registrations):
                raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
        if len(quant) != len(catalog.providers):
            raise ValueError("RUNTIME_GENERATION_PROVIDER_MISMATCH")
        return OnlyRuntimeGenerationManifest(
            core_execution=core,
            artifact_manifest_fingerprints=tuple(item.manifest_fingerprint for item in artifacts),
            artifact_sha256s=tuple(item.artifact_sha256 for item in artifacts),
            providers=tuple(providers),
            catalog_generation_fingerprint=catalog.generation_fingerprint,
            implementations=runtime_implementations,
        )

    @staticmethod
    def _runtime_implementations(actual: dict[str, object]) -> tuple[OnlyArtifactCalculationImplementation, ...]:
        raw = actual.get("implementations")
        if not isinstance(raw, list):
            raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
        try:
            implementations = tuple(
                sorted(OnlyArtifactCalculationImplementation.from_dict(item) for item in raw if isinstance(item, dict))
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH") from exc
        if len(implementations) != len(raw) or len(implementations) != len(set(implementations)):
            raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
        return implementations

    def _materialize(self, artifacts: tuple[OnlyDistributionArtifactManifest, ...], root: Path) -> tuple[Path, ...]:
        root.mkdir(parents=True, exist_ok=False)
        result = []
        for artifact in artifacts:
            _, content = self.artifact_store.fetch_exact(artifact.artifact_sha256)
            target = root / artifact.artifact_logical_name
            if target.exists():
                raise ValueError("RUNTIME_GENERATION_ARTIFACT_MISMATCH")
            target.write_bytes(content)
            result.append(target)
        return tuple(result)

    def _materialize_private_alpha_artifacts(
        self,
        bindings: tuple[OnlyRuntimePrivateAlphaBinding, ...],
        root: Path,
    ) -> None:
        target_store = OnlyLocalImmutableArtifactStore(root)
        for binding in bindings:
            source_manifest, source = self.artifact_store.fetch_private_alpha_source(
                binding.entry.source_artifact_fingerprint
            )
            target_store.put_private_alpha_source(source_manifest, source)
        for fingerprint in sorted({item.runtime_artifact_fingerprint for item in bindings}):
            payload = self.artifact_store.fetch_private_alpha_runtime(fingerprint)
            target = target_store._private_alpha_runtime_path(fingerprint)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(only_canonical_json(payload) + "\n", encoding="utf-8")
            target_store.fetch_private_alpha_runtime(fingerprint)

    def _environment_python(self, root: Path) -> Path:
        executable = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not executable.is_file():
            raise ValueError("RUNTIME_GENERATION_ENVIRONMENT_INVALID")
        return executable

    def _verify_hosted_environment(
        self,
        environment_root: Path,
        evidence: OnlyRuntimeGenerationValidationEvidence,
    ) -> None:
        verified = subprocess.run(
            [
                str(self._environment_python(environment_root)),
                "-I",
                "-c",
                (
                    "from onlyalpha.runtime.generation import OnlyRuntimeGenerationValidationEvidence; "
                    "from onlyalpha_runtime_generation_manager.hosted import only_verify_hosted_runtime_generation; "
                    f"only_verify_hosted_runtime_generation(OnlyRuntimeGenerationValidationEvidence.from_dict({evidence.to_dict()!r}))"
                ),
            ],
            cwd=environment_root,
            capture_output=True,
            text=True,
            check=False,
            env=self._isolated_environment(),
        )
        if verified.returncode != 0:
            raise ValueError("RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH") from RuntimeError(verified.stderr)

    @staticmethod
    def _isolated_environment() -> dict[str, str]:
        allowed = ("PATH", "SYSTEMROOT", "WINDIR", "TMPDIR", "TEMP", "TMP")
        environment = {key: value for key in allowed if (value := os.environ.get(key)) is not None}
        environment.update({"PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        return environment

    @staticmethod
    def _seal_environment(
        environment_root: Path,
        evidence: OnlyRuntimeGenerationValidationEvidence,
    ) -> None:
        target = environment_root / _HOSTED_GENERATION_SEAL
        if target.exists():
            raise ValueError("RUNTIME_GENERATION_ENVIRONMENT_INVALID")
        target.write_text(only_canonical_json(evidence.to_dict()) + "\n", encoding="utf-8")


def _normalized_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()
