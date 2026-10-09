"""Retained native source/API/adapter and Runtime artifact ownership relations."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import replace

import pytest

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationReference,
    OnlyCalculationTypeReference,
    OnlyPreReadyOutput,
    OnlyWarmupDefinition,
)
from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition, OnlyCalculationNodeDefinition
from onlyalpha.calculation.implementation import (
    OnlyCalculationSemanticDependency,
    only_implementation_manifest_from_bytes,
)
from onlyalpha.canonical import only_canonical_json
from onlyalpha.distribution import OnlyArtifactCalculationImplementation
from onlyalpha.generation_identity import OnlyRuntimeGenerationValidationEvidence, OnlyRuntimePrivateFactorBinding
from onlyalpha.quant_assets.private_factor_provider_snapshot import (
    OnlyPrivateFactorProviderSnapshotEntryV1,
    OnlyPrivateFactorProviderSnapshotV1,
)
from onlyalpha.quant_assets.retained_generation import OnlyRetainedRuntimeGenerationProofV1
from tests.quant_assets.test_retained_catalog_descriptor import _rehash
from tests.quant_assets.test_retained_generation_proof import _replace_proof_payload, retained_proof_case

pytestmark = pytest.mark.contract


def _native_case(*, separate_snapshots=False):
    from onlyalpha_test_factor_provider.provider import quant_asset_provider

    proof, _, _ = retained_proof_case()
    provider = quant_asset_provider()
    first_definition = provider.calculation_registrations[0].type_definition
    definitions = (first_definition, replace(first_definition, type_id="example.factor.other"))
    source = b"retained-source-fixture"
    entries, manifests, registrations = [], [], []
    for definition in definitions:
        implementations = []
        for backend, adapter_identity in (
            (OnlyCalculationBackendKind.RESEARCH, "5" * 64),
            (OnlyCalculationBackendKind.TRADING, "6" * 64),
        ):
            prefix = backend.value.lower()
            entrypoint = (
                "OnlyPrivateFactorResearchBackendV1"
                if prefix == "research"
                else "OnlyPrivateFactorTradingBackendFactoryV1"
            )
            manifest = only_implementation_manifest_from_bytes(
                calculation_type_reference=OnlyCalculationTypeReference(
                    definition.kind, definition.type_id, definition.semantic_version
                ),
                backend_kind=backend,
                entrypoint_identity=f"onlyalpha.quant_assets.private_factor_execution:{entrypoint}",
                resources={
                    "private_factor/source.py": source,
                    f"private_factor/{prefix}-adapter.py": b"retained-adapter-fixture",
                    f"private_factor/{prefix}-identity.txt": adapter_identity.encode(),
                },
                semantic_dependencies=(
                    OnlyCalculationSemanticDependency("onlyalpha.private-factor.api", "1", "4" * 64),
                    OnlyCalculationSemanticDependency("onlyalpha.private-factor.source-artifact", "1", "3" * 64),
                ),
            )
            manifests.append(manifest)
            implementations.append(manifest.implementation_fingerprint)
            registrations.append(
                {
                    "type": definition.descriptor(),
                    "backend": backend.value,
                    "implementation_fingerprint": manifest.implementation_fingerprint,
                    "state_capability": None if prefix == "research" else "STATELESS",
                    "checkpoint_schema_version": None,
                }
            )
        entries.append(
            OnlyPrivateFactorProviderSnapshotEntryV1(
                definition.type_id,
                definition.semantic_version,
                "1" * 64,
                hashlib.sha256(source).hexdigest(),
                "3" * 64,
                1,
                "4" * 64,
                "5" * 64,
                "6" * 64,
                *implementations,
                "9" * 64,
            )
        )
    snapshots = (
        tuple(OnlyPrivateFactorProviderSnapshotV1((entry,)) for entry in entries)
        if separate_snapshots
        else (OnlyPrivateFactorProviderSnapshotV1(tuple(entries)),)
    )
    catalog = deepcopy(proof.catalog_descriptor)
    for index, snapshot in enumerate(snapshots):
        keys = {(entry.factor_id, entry.semantic_version) for entry in snapshot.entries}
        catalog["providers"].append(
            {
                "manifest": {
                    "schema_version": 1,
                    "provider_id": f"private.factor.library{index}",
                    "provider_version": "1",
                    "kind": "FACTOR",
                    "source": {
                        "kind": "PRIVATE_FACTOR_SNAPSHOT",
                        "private_factor_provider_snapshot_fingerprint": snapshot.snapshot_fingerprint,
                    },
                },
                "content_fingerprint": "a" * 64,
                "calculations": [
                    item
                    for item in registrations
                    if (item["type"]["type_id"], item["type"]["semantic_version"]) in keys
                ],
                "private_factor_snapshot": snapshot.to_dict(),
            }
        )
    catalog = _rehash(catalog)
    bindings = tuple(
        OnlyRuntimePrivateFactorBinding(snapshot.snapshot_fingerprint, str(index + 1) * 64, entry)
        for index, snapshot in enumerate(snapshots)
        for entry in snapshot.entries
    )
    native_implementations = tuple(
        OnlyArtifactCalculationImplementation(
            "FACTOR",
            item.calculation_type_reference.type_id,
            item.calculation_type_reference.semantic_version,
            item.backend_kind.value,
            item.implementation_fingerprint,
        )
        for item in manifests
    )
    generation = replace(
        proof.generation,
        catalog_generation_fingerprint=catalog["generation_fingerprint"],
        implementations=(*proof.generation.implementations, *native_implementations),
        private_factor_bindings=bindings,
    )
    selected = manifests[0]
    retained = OnlyRetainedRuntimeGenerationProofV1(
        generation,
        OnlyRuntimeGenerationValidationEvidence.from_manifest(generation),
        proof.distributions,
        (selected,),
        only_canonical_json(catalog),
    )
    definition = definitions[0].resolve(
        {},
        {
            item.name: OnlyCalculationReference(None, item.name, f"fixture.{item.name}")
            for item in definitions[0].inputs
        },
        OnlyWarmupDefinition(1, "fixture inputs", OnlyPreReadyOutput.NULL, "STATELESS"),
    )
    graph = OnlyCalculationGraphDefinition((OnlyCalculationNodeDefinition(definition),))
    return retained, graph, ((graph.nodes[0].fingerprint, selected.implementation_fingerprint),)


@pytest.mark.parametrize("separate_snapshots", (False, True))
def test_retained_native_selected_graph_has_complete_source_and_backend_relations(separate_snapshots):
    proof, graph, bindings = _native_case(separate_snapshots=separate_snapshots)
    assert OnlyRetainedRuntimeGenerationProofV1.from_dict(proof.to_dict()) == proof
    proof.require_graph_implementations(graph, bindings)


@pytest.mark.parametrize("mutation", ("shared_artifact", "split_snapshot"))
def test_rehashed_private_runtime_artifact_requires_one_complete_snapshot(mutation):
    proof, _, _ = _native_case(separate_snapshots=mutation == "shared_artifact")
    bindings = tuple(
        replace(item, runtime_artifact_fingerprint="f" * 64 if index == 0 else item.runtime_artifact_fingerprint)
        for index, item in enumerate(proof.generation.private_factor_bindings)
    )
    if mutation == "shared_artifact":
        bindings = tuple(replace(item, runtime_artifact_fingerprint="f" * 64) for item in bindings)
    payload = _replace_proof_payload(proof, private_factor_bindings=bindings)
    with pytest.raises(ValueError, match="Runtime artifact"):
        OnlyRetainedRuntimeGenerationProofV1.from_dict(payload)


@pytest.mark.parametrize(
    "dimension",
    ("source", "api", "source_artifact", "adapter", "backend", "missing_adapter", "missing_dependency", "entrypoint"),
)
def test_rehashed_selected_native_manifest_must_agree_with_snapshot_source_api_and_adapter(dimension):
    proof, _, _ = _native_case()
    manifest = proof.implementation_manifests[0]
    if dimension in {"source", "adapter", "missing_adapter"}:
        resources = tuple(
            replace(item, byte_sha256="f" * 64)
            if item.relative_path
            == ("private_factor/source.py" if dimension == "source" else "private_factor/research-identity.txt")
            else item
            for item in manifest.resources
            if dimension != "missing_adapter" or item.relative_path != "private_factor/research-adapter.py"
        )
        manifest = replace(manifest, resources=resources)
    elif dimension in {"api", "source_artifact", "missing_dependency"}:
        dependency_id = (
            "onlyalpha.private-factor.api" if dimension == "api" else "onlyalpha.private-factor.source-artifact"
        )
        manifest = replace(
            manifest,
            semantic_dependencies=tuple(
                replace(item, artifact_fingerprint="f" * 64) if item.dependency_id == dependency_id else item
                for item in manifest.semantic_dependencies
                if dimension != "missing_dependency" or item.dependency_id != dependency_id
            ),
        )
    else:
        manifest = replace(
            manifest,
            entrypoint_identity="onlyalpha.quant_assets.private_factor_execution:OnlyPrivateFactorTradingBackendFactoryV1"
            if dimension == "backend"
            else "wrong.module:WrongEntry",
        )
    original = proof.implementation_manifests[0].implementation_fingerprint
    catalog = deepcopy(proof.catalog_descriptor)
    for provider in catalog["providers"]:
        snapshot = provider["private_factor_snapshot"]
        if snapshot is not None:
            entries = tuple(
                replace(
                    OnlyPrivateFactorProviderSnapshotEntryV1.from_dict(item),
                    research_implementation_fingerprint=manifest.implementation_fingerprint,
                )
                if item["research_implementation_fingerprint"] == original
                else OnlyPrivateFactorProviderSnapshotEntryV1.from_dict(item)
                for item in snapshot["entries"]
            )
            snapshot = OnlyPrivateFactorProviderSnapshotV1(entries)
            provider["private_factor_snapshot"] = snapshot.to_dict()
            provider["manifest"]["source"]["private_factor_provider_snapshot_fingerprint"] = (
                snapshot.snapshot_fingerprint
            )
        for registration in provider["calculations"]:
            if registration["implementation_fingerprint"] == original:
                registration["implementation_fingerprint"] = manifest.implementation_fingerprint
    catalog = _rehash(catalog)
    snapshot = OnlyPrivateFactorProviderSnapshotV1.from_dict(
        next(
            item["private_factor_snapshot"]
            for item in catalog["providers"]
            if item["private_factor_snapshot"] is not None
        )
    )
    bindings = tuple(
        replace(
            item,
            provider_snapshot_fingerprint=snapshot.snapshot_fingerprint,
            entry=next(entry for entry in snapshot.entries if entry.factor_id == item.entry.factor_id),
        )
        for item in proof.generation.private_factor_bindings
    )
    implementations = tuple(
        replace(item, implementation_fingerprint=manifest.implementation_fingerprint)
        if item.implementation_fingerprint == original
        else item
        for item in proof.generation.implementations
    )
    payload = _replace_proof_payload(
        proof,
        catalog_generation_fingerprint=catalog["generation_fingerprint"],
        private_factor_bindings=bindings,
        implementations=implementations,
    )
    payload.update(catalog=catalog, implementation_manifests=[manifest.to_dict()])
    with pytest.raises(ValueError, match="PRIVATE_FACTOR_IMPLEMENTATION_MANIFEST_MISMATCH"):
        OnlyRetainedRuntimeGenerationProofV1.from_dict(payload)
