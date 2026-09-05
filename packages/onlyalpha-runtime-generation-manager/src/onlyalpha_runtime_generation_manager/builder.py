"""Candidate-first clean-environment Runtime Generation construction."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from onlyalpha.canonical import only_canonical_json
from onlyalpha.distribution import (
    OnlyArtifactCalculationImplementation,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration
from onlyalpha.runtime.generation import (
    OnlyCoreExecutionIdentity,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeGenerationValidationEvidence,
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

_HOSTED_GENERATION_SEAL = "onlyalpha-runtime-generation-validation.json"


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
        return validated

    def rebuild_validated(
        self,
        *,
        expected_manifest: OnlyRuntimeGenerationManifest,
        environment_root: Path,
    ) -> OnlyValidatedRuntimeGeneration:
        """Reconstruct one historical generation solely from its exact stored artifacts."""

        try:
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
            catalog = actual.get("catalog") if isinstance(actual, dict) else None
            if (
                not isinstance(catalog, dict)
                or catalog.get("generation_fingerprint") != expected_manifest.catalog_generation_fingerprint
            ):
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
                    for item in catalog.get("providers", [])
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
            runtime_implementations = self._runtime_implementations(actual)
            if runtime_implementations != expected_manifest.implementations:
                raise ValueError("RUNTIME_GENERATION_IMPLEMENTATION_MISMATCH")
            rebuilt = OnlyRuntimeGenerationManifest(
                core_execution=core,
                artifact_manifest_fingerprints=tuple(item.manifest_fingerprint for item in canonical),
                artifact_sha256s=tuple(item.artifact_sha256 for item in canonical),
                providers=actual_providers,
                catalog_generation_fingerprint=catalog["generation_fingerprint"],
                implementations=runtime_implementations,
            )
            if rebuilt != expected_manifest:
                raise ValueError("RUNTIME_GENERATION_MANIFEST_MISMATCH")
            validated = OnlyValidatedRuntimeGeneration(
                rebuilt,
                OnlyRuntimeGenerationValidationEvidence.from_manifest(rebuilt),
            )
            self._seal_environment(environment_root, validated.validation_evidence)
            return validated
        except Exception:
            shutil.rmtree(environment_root, ignore_errors=True)
            raise

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

    def _environment_python(self, root: Path) -> Path:
        executable = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not executable.is_file():
            raise ValueError("RUNTIME_GENERATION_ENVIRONMENT_INVALID")
        return executable

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
