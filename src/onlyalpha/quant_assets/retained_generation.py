"""Pure relation closure for retained Runtime attestations; not executable validation or permission."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from onlyalpha.calculation.definition import OnlyParameterSchema, only_calculation_execution_shape
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition
from onlyalpha.calculation.implementation import OnlyCalculationImplementationManifest
from onlyalpha.calculation.predicate import only_predicate_type_definitions
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json, only_canonical_payload
from onlyalpha.distribution import (
    OnlyArtifactAssetIdentity,
    OnlyArtifactCalculationImplementation,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)
from onlyalpha.generation_identity import OnlyRuntimeGenerationManifest, OnlyRuntimeGenerationValidationEvidence

from .catalog import OnlyDistributionProviderSource, _normalize_distribution
from .exact_catalog import _validate_parameter_descriptor, only_project_exact_catalog_context
from .private_factor_provider_snapshot import OnlyPrivateFactorProviderSnapshotV1


@dataclass(frozen=True, slots=True)
class OnlyRetainedRuntimeGenerationProofV1:
    """Complete copied identities with one canonical manifest-to-byte relation.

    The DTO proves coherence, not authenticity, installed bytes, an execution seal,
    historical Work eligibility or Run ownership. It never discovers a Provider.
    """

    generation: OnlyRuntimeGenerationManifest
    validation: OnlyRuntimeGenerationValidationEvidence
    distributions: tuple[OnlyDistributionArtifactManifest, ...]
    implementation_manifests: tuple[OnlyCalculationImplementationManifest, ...]
    catalog_json: str

    def __post_init__(self) -> None:
        # Use owning parsers, including nested canonical ordering, before comparing relations.
        if (
            type(self.generation) is not OnlyRuntimeGenerationManifest
            or type(self.validation) is not OnlyRuntimeGenerationValidationEvidence
        ):
            raise ValueError("retained generation proof requires exact owning contracts")
        if OnlyRuntimeGenerationManifest.from_dict(self.generation.to_dict()) != self.generation:
            raise ValueError("retained generation manifest differs")
        if OnlyRuntimeGenerationValidationEvidence.from_dict(
            self.validation.to_dict()
        ) != self.validation or not self.validation.verifies(self.generation):
            raise ValueError("retained Validation Evidence relation differs")
        if type(self.distributions) is not tuple or type(self.implementation_manifests) is not tuple:
            raise ValueError("retained generation inventories must be canonical tuples")
        for value in self.distributions:
            if (
                type(value) is not OnlyDistributionArtifactManifest
                or OnlyDistributionArtifactManifest.from_dict(value.to_dict()) != value
            ):
                raise ValueError("retained distribution manifest differs")
        for implementation_manifest in self.implementation_manifests:
            if (
                type(implementation_manifest) is not OnlyCalculationImplementationManifest
                or OnlyCalculationImplementationManifest.from_dict(implementation_manifest.to_dict())
                != implementation_manifest
            ):
                raise ValueError("retained implementation manifest differs")
        if (
            tuple(item.manifest_fingerprint for item in self.distributions)
            != self.generation.artifact_manifest_fingerprints
        ):
            raise ValueError("retained distribution inventory differs")
        by_bytes = {item.artifact_sha256: item for item in self.distributions}
        if len(by_bytes) != len(self.distributions) or tuple(sorted(by_bytes)) != self.generation.artifact_sha256s:
            raise ValueError("retained manifest-to-byte bijection differs")
        names = [_normalize_distribution(item.distribution_name) for item in self.distributions]
        if len(set(names)) != len(names):
            raise ValueError("retained distribution ownership is ambiguous")
        core = self.generation.core_execution
        cores = tuple(item for item in self.distributions if item.role is OnlyDistributionArtifactRole.CORE)
        if len(cores) != 1 or (cores[0].distribution_name, cores[0].distribution_version, cores[0].artifact_sha256) != (
            core.distribution_name,
            core.distribution_version,
            core.artifact_sha256,
        ):
            raise ValueError("retained Core identity differs")
        for item in self.distributions:
            if (
                item.tested_core_execution_fingerprint is not None
                and item.tested_core_execution_fingerprint != core.fingerprint
            ):
                raise ValueError("retained tested Core relation differs")
        selected = tuple(item.implementation_fingerprint for item in self.implementation_manifests)
        if not selected or selected != tuple(sorted(set(selected))):
            raise ValueError("retained selected implementations are not canonical")
        inventory_keys = [
            (item.kind, item.type_id, item.semantic_version, item.backend) for item in self.generation.implementations
        ]
        if len(set(inventory_keys)) != len(inventory_keys):
            raise ValueError("retained Runtime implementation owner is ambiguous")
        distribution_implementations = [entry for item in self.distributions for entry in item.implementations]
        keys = [(item.kind, item.type_id, item.semantic_version, item.backend) for item in distribution_implementations]
        if len(keys) != len(set(keys)) or not set(distribution_implementations) <= set(self.generation.implementations):
            raise ValueError("retained distribution implementation relation differs")
        catalog = self.catalog_descriptor
        if only_canonical_json(catalog) != self.catalog_json:
            raise ValueError("retained Catalog JSON is not canonical")
        context = only_project_exact_catalog_context(
            self.generation.catalog_generation_fingerprint,
            catalog,
            dataset_field_contracts=(),
            registered_universes=(),
            statistics_capabilities=(),
        )
        providers = {item.provider_id: item for item in context.ordered_providers}
        bindings = {item.provider_id: item for item in self.generation.providers}
        if len(bindings) != len(self.generation.providers):
            raise ValueError("retained Runtime provider owner is ambiguous")
        distribution_providers = {
            key: value
            for key, value in providers.items()
            if isinstance(value.provider_source, OnlyDistributionProviderSource)
        }
        if set(bindings) != set(distribution_providers):
            raise ValueError("retained Runtime provider coverage differs")
        quant = [item for item in self.distributions if item.role is OnlyDistributionArtifactRole.QUANT_ASSET]
        if len(quant) != len(bindings):
            raise ValueError("retained distribution provider coverage differs")
        for key, binding in bindings.items():
            provider = distribution_providers[key]
            artifact = by_bytes.get(binding.artifact_sha256)
            source = cast(OnlyDistributionProviderSource, provider.provider_source)
            if (
                artifact is None
                or artifact.role is not OnlyDistributionArtifactRole.QUANT_ASSET
                or (
                    binding.provider_version,
                    binding.provider_content_fingerprint,
                    artifact.provider_id,
                    artifact.provider_version,
                    artifact.provider_content_fingerprint,
                    artifact.distribution_name,
                    artifact.distribution_version,
                )
                != (
                    provider.provider_version,
                    provider.provider_content_fingerprint,
                    provider.provider_id,
                    provider.provider_version,
                    provider.provider_content_fingerprint,
                    source.distribution_name,
                    source.distribution_version,
                )
            ):
                raise ValueError("retained provider-to-distribution relation differs")
            capabilities = tuple(item for item in context.ordered_calculation_capabilities if item.provider_id == key)
            expected_implementations = tuple(
                sorted(
                    OnlyArtifactCalculationImplementation(
                        item.kind.value,
                        item.type_id,
                        item.semantic_version,
                        item.backend.value,
                        item.implementation_fingerprint,
                    )
                    for item in capabilities
                )
            )
            expected_assets = tuple(
                sorted(
                    set(
                        OnlyArtifactAssetIdentity(
                            item.kind.value,
                            item.type_id,
                            item.semantic_version,
                            only_canonical_fingerprint(item.type_descriptor),
                        )
                        for item in capabilities
                    )
                )
            )
            if expected_implementations != artifact.implementations or expected_assets != artifact.assets:
                raise ValueError("retained Catalog asset/implementation distribution relation differs")
        snapshots = {}
        for raw in cast(list[dict[str, object]], catalog["providers"]):
            if raw["private_factor_snapshot"] is not None:
                snapshot = OnlyPrivateFactorProviderSnapshotV1.from_dict(
                    cast(Mapping[str, object], raw["private_factor_snapshot"])
                )
                snapshots[snapshot.snapshot_fingerprint] = snapshot
        expected_private = {
            (snapshot.snapshot_fingerprint, entry.factor_id): entry
            for snapshot in snapshots.values()
            for entry in snapshot.entries
        }
        actual_private = {
            (item.provider_snapshot_fingerprint, item.entry.factor_id): item.entry
            for item in self.generation.private_factor_bindings
        }
        if len(actual_private) != len(self.generation.private_factor_bindings) or expected_private != actual_private:
            raise ValueError("retained private snapshot Runtime binding relation differs")
        for fingerprint in sorted(
            {item.runtime_artifact_fingerprint for item in self.generation.private_factor_bindings}
        ):
            group = tuple(
                item
                for item in self.generation.private_factor_bindings
                if item.runtime_artifact_fingerprint == fingerprint
            )
            snapshot_ids = {item.provider_snapshot_fingerprint for item in group}
            if len(snapshot_ids) != 1:
                raise ValueError("retained private Runtime artifact has ambiguous snapshot ownership")
            snapshot = snapshots[next(iter(snapshot_ids))]
            if tuple(sorted(item.entry for item in group)) != snapshot.entries:
                raise ValueError("retained private Runtime artifact snapshot coverage is incomplete")
        private_implementations = {
            OnlyArtifactCalculationImplementation(
                "FACTOR", entry.factor_id, entry.semantic_version, backend, fingerprint
            )
            for entry in expected_private.values()
            for backend, fingerprint in (
                ("RESEARCH", entry.research_implementation_fingerprint),
                ("TRADING", entry.trading_implementation_fingerprint),
            )
        }
        if not private_implementations <= set(self.generation.implementations):
            raise ValueError("retained private implementation Runtime coverage differs")
        core_predicate_keys = {
            ("PREDICATE", definition.type_id, definition.semantic_version, backend)
            for definition in only_predicate_type_definitions()
            for backend in ("RESEARCH", "TRADING")
        }
        private_keys = {
            (item.kind, item.type_id, item.semantic_version, item.backend) for item in private_implementations
        }
        distribution_keys = set(keys)
        if distribution_keys & private_keys or core_predicate_keys & (distribution_keys | private_keys):
            raise ValueError("retained Runtime implementation owning families overlap")
        if set(inventory_keys) != distribution_keys | private_keys | core_predicate_keys:
            raise ValueError("retained Runtime implementation owning family coverage differs")
        for implementation in self.implementation_manifests:
            entry = _implementation_entry(implementation)
            if entry not in self.generation.implementations:
                raise ValueError("retained selected implementation is outside Runtime inventory")
            matches = [
                item
                for item in context.ordered_calculation_capabilities
                if (
                    item.kind.value,
                    item.type_id,
                    item.semantic_version,
                    item.backend.value,
                    item.implementation_fingerprint,
                )
                == (entry.kind, entry.type_id, entry.semantic_version, entry.backend, entry.implementation_fingerprint)
            ]
            if len(matches) != 1:
                raise ValueError("retained selected implementation Catalog relation differs")
            if entry in private_implementations:
                native_entry = next(
                    item
                    for item in expected_private.values()
                    if item.factor_id == entry.type_id and item.semantic_version == entry.semantic_version
                )
                native_entry.require_implementation_manifest(implementation)

    @property
    def catalog_descriptor(self) -> Mapping[str, object]:
        import json

        # The stored string is canonical and immutable; duplicate fields cannot be normalized away.
        def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("retained Catalog has duplicate JSON fields")
                result[key] = value
            return result

        raw = json.loads(self.catalog_json, object_pairs_hook=unique)
        if not isinstance(raw, dict):
            raise ValueError("retained Catalog must be an object")
        return raw

    def require_graph_implementations(
        self, graph: OnlyCalculationGraphDefinition, bindings: tuple[tuple[str, str], ...]
    ) -> None:
        """Prove Graph type/node/implementation relations without resolving or evaluating anything."""
        if (
            type(graph) is not OnlyCalculationGraphDefinition
            or OnlyCalculationGraphDefinition.from_dict(graph.to_dict()) != graph
        ):
            raise ValueError("retained Graph is not canonical")
        if type(bindings) is not tuple or any(
            type(item) is not tuple or len(item) != 2 or any(type(value) is not str for value in item)
            for item in bindings
        ):
            raise ValueError("retained Graph implementation proof is incomplete")
        if bindings != tuple(sorted(set(bindings))) or tuple(node for node, _ in bindings) != tuple(
            sorted(item.fingerprint for item in graph.nodes)
        ):
            raise ValueError("retained Graph implementation bijection differs")
        by_fingerprint = {item.implementation_fingerprint: item for item in self.implementation_manifests}
        binding_by_node = dict(bindings)
        context = only_project_exact_catalog_context(
            self.generation.catalog_generation_fingerprint,
            self.catalog_descriptor,
            dataset_field_contracts=(),
            registered_universes=(),
            statistics_capabilities=(),
        )
        for node in graph.nodes:
            fingerprint = binding_by_node[node.fingerprint]
            manifest = by_fingerprint.get(fingerprint)
            if manifest is None:
                raise ValueError("retained Graph implementation manifest is missing")
            definition = node.definition
            entry = _implementation_entry(manifest)
            if (entry.kind, entry.type_id, entry.semantic_version, entry.backend) != (
                definition.kind.value,
                definition.type_id,
                definition.semantic_version,
                "RESEARCH",
            ):
                raise ValueError("retained Graph implementation type/backend differs")
            capability = next(
                item
                for item in context.ordered_calculation_capabilities
                if item.implementation_fingerprint == fingerprint
            )
            descriptor = capability.type_descriptor
            if only_calculation_execution_shape(definition).value != descriptor["execution_shape"]:
                raise ValueError("retained Graph execution shape differs")
            parameters = OnlyParameterSchema(
                tuple(
                    _validate_parameter_descriptor(item)
                    for item in cast(tuple[Mapping[str, object], ...], descriptor["parameters"])
                )
            )
            if only_canonical_payload(parameters.normalize(definition.parameters)) != only_canonical_payload(
                definition.parameters
            ):
                raise ValueError("retained Graph parameter contract differs")
            for name in ("inputs", "outputs", "numeric", "missing_values", "timestamp", "factor_kind"):
                if only_canonical_payload(getattr(definition, name)) != only_canonical_payload(descriptor[name]):
                    raise ValueError("retained Graph type descriptor relation differs")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "generation": self.generation.to_dict(),
            "validation": self.validation.to_dict(),
            "distributions": [item.to_dict() for item in self.distributions],
            "implementation_manifests": [item.to_dict() for item in self.implementation_manifests],
            "catalog": dict(self.catalog_descriptor),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyRetainedRuntimeGenerationProofV1:
        fields = {"schema_version", "generation", "validation", "distributions", "implementation_manifests", "catalog"}
        if set(payload) != fields or type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
            raise ValueError("retained generation proof fields/version differ")
        for name in ("generation", "validation", "catalog"):
            if not isinstance(payload[name], Mapping):
                raise ValueError("retained generation proof context is incomplete")
        for name in ("distributions", "implementation_manifests"):
            inventory = payload[name]
            if type(inventory) is not list or any(not isinstance(item, Mapping) for item in inventory):
                raise ValueError("retained generation proof inventory is incomplete")
        _require_json_representation(payload["catalog"])
        catalog = cast(Mapping[str, object], payload["catalog"])
        generation = OnlyRuntimeGenerationManifest.from_dict(cast(Mapping[str, object], payload["generation"]))
        only_project_exact_catalog_context(
            generation.catalog_generation_fingerprint,
            catalog,
            dataset_field_contracts=(),
            registered_universes=(),
            statistics_capabilities=(),
        )
        return cls(
            generation,
            OnlyRuntimeGenerationValidationEvidence.from_dict(cast(Mapping[str, object], payload["validation"])),
            tuple(
                OnlyDistributionArtifactManifest.from_dict(item)
                for item in cast(list[Mapping[str, object]], payload["distributions"])
            ),
            tuple(
                OnlyCalculationImplementationManifest.from_dict(item)
                for item in cast(list[Mapping[str, object]], payload["implementation_manifests"])
            ),
            only_canonical_json(payload["catalog"]),
        )


def _implementation_entry(manifest: OnlyCalculationImplementationManifest) -> OnlyArtifactCalculationImplementation:
    reference = manifest.calculation_type_reference
    return OnlyArtifactCalculationImplementation(
        reference.kind.value,
        reference.type_id,
        reference.semantic_version,
        manifest.backend_kind.value,
        manifest.implementation_fingerprint,
    )


def _require_json_representation(value: object) -> None:
    """Reject unsupported wire shapes before canonical serialization can coerce them."""
    if value is None or type(value) in {str, int, bool}:
        return
    if isinstance(value, Mapping) and all(type(key) is str for key in value):
        for item in value.values():
            _require_json_representation(item)
        return
    if type(value) is list:
        for item in value:
            _require_json_representation(item)
        return
    raise ValueError("retained Catalog contains a noncanonical JSON representation")
