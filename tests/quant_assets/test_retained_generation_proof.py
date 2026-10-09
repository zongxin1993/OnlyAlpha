"""Offline coherence of exact copied identities, never installed execution authentication."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from onlyalpha.calculation.predicate import only_predicate_type_definitions
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.distribution import (
    OnlyArtifactCalculationImplementation,
    OnlyArtifactSourceProvenanceAuthority,
    OnlyDistributionArtifactManifest,
    OnlyDistributionArtifactRole,
)
from onlyalpha.generation_identity import (
    OnlyCoreExecutionIdentity,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeGenerationValidationEvidence,
    OnlyRuntimeProviderBinding,
)
from onlyalpha.quant_assets import (
    OnlyQuantAssetCatalogGeneration,
    only_quant_asset_distribution_artifact_manifest,
)
from onlyalpha.quant_assets.retained_generation import OnlyRetainedRuntimeGenerationProofV1

pytestmark = pytest.mark.contract


def retained_proof_case():
    from onlyalpha_plugin_indicators.provider import quant_asset_provider

    from tests.research.calculation.test_execution_readiness_v2 import _graph

    core = OnlyCoreExecutionIdentity("onlyalpha", "0.9.9", "a" * 64)
    core_artifact = OnlyDistributionArtifactManifest(
        OnlyDistributionArtifactRole.CORE,
        OnlyArtifactSourceProvenanceAuthority.ONLYALPHA_GIT,
        "onlyalpha",
        "1" * 40,
        "onlyalpha",
        "0.9.9",
        "onlyalpha-0.9.9-py3-none-any.whl",
        "a" * 64,
        10,
    )
    provider = quant_asset_provider()
    asset_artifact = only_quant_asset_distribution_artifact_manifest(
        source_repository="onlyalpha",
        source_revision="1" * 40,
        artifact_logical_name=f"onlyalpha_plugin_indicators-{provider.manifest.distribution_version}-py3-none-any.whl",
        artifact_bytes=b"recorded-metadata-fixture-not-an-executable-wheel",
        tested_core_execution_fingerprint=core.fingerprint,
        provider=provider,
    )
    catalog = OnlyQuantAssetCatalogGeneration((provider,))
    manifests = tuple(sorted((core_artifact, asset_artifact), key=lambda item: item.manifest_fingerprint))
    generation = OnlyRuntimeGenerationManifest(
        core,
        tuple(item.manifest_fingerprint for item in manifests),
        tuple(sorted(item.artifact_sha256 for item in manifests)),
        (
            OnlyRuntimeProviderBinding(
                provider.manifest.provider_id,
                provider.manifest.provider_version,
                provider.content_fingerprint,
                asset_artifact.artifact_sha256,
            ),
        ),
        catalog.generation_fingerprint,
        (*asset_artifact.implementations, *_core_inventory()),
    )
    selected = next(
        item.implementation_manifest
        for item in provider.calculation_registrations
        if item.backend.value == "RESEARCH" and item.type_definition.type_id == "onlyalpha.indicator.sma"
    )
    graph = _graph()
    proof = OnlyRetainedRuntimeGenerationProofV1(
        generation,
        OnlyRuntimeGenerationValidationEvidence.from_manifest(generation),
        manifests,
        (selected,),
        only_canonical_json(catalog.descriptor()),
    )
    return proof, graph, ((graph.nodes[0].fingerprint, selected.implementation_fingerprint),)


def _core_inventory():
    """Recorded opaque identities: no primitive Registry construction or byte evaluation."""
    return tuple(
        OnlyArtifactCalculationImplementation(
            "PREDICATE",
            definition.type_id,
            definition.semantic_version,
            backend,
            only_canonical_fingerprint((definition.type_id, definition.semantic_version, backend)),
        )
        for definition in only_predicate_type_definitions()
        for backend in ("RESEARCH", "TRADING")
    )


def test_retained_proof_and_graph_round_trip_without_numeric_execution():
    proof, graph, bindings = retained_proof_case()
    assert OnlyRetainedRuntimeGenerationProofV1.from_dict(proof.to_dict()) == proof
    proof.require_graph_implementations(graph, bindings)
    assert "readiness_contract_versions" not in proof.catalog_json


@pytest.mark.parametrize("family", ("core_predicate", "unowned_factor", "unowned_indicator", "unknown_predicate"))
def test_retained_runtime_inventory_uses_family_relations_not_blanket_catalog_equality(family):
    proof, _, _ = retained_proof_case()
    kind, type_id = {
        "core_predicate": ("PREDICATE", "onlyalpha.predicate.internal.boolean.and"),
        "unowned_factor": ("FACTOR", "private.factor.unowned"),
        "unowned_indicator": ("INDICATOR", "onlyalpha.indicator.unowned"),
        "unknown_predicate": ("PREDICATE", "onlyalpha.predicate.internal.unowned"),
    }[family]
    entry = OnlyArtifactCalculationImplementation(kind, type_id, "1", "RESEARCH", "f" * 64)
    implementations = tuple(
        item
        for item in proof.generation.implementations
        if (item.kind, item.type_id, item.semantic_version, item.backend) != (kind, type_id, "1", "RESEARCH")
    )
    generation = replace(proof.generation, implementations=(*implementations, entry))
    payload = proof.to_dict()
    payload.update(
        generation=generation.to_dict(),
        validation=OnlyRuntimeGenerationValidationEvidence.from_manifest(generation).to_dict(),
    )
    if family == "core_predicate":
        assert OnlyRetainedRuntimeGenerationProofV1.from_dict(payload).generation == generation
    else:
        with pytest.raises(ValueError, match="owning family coverage differs"):
            OnlyRetainedRuntimeGenerationProofV1.from_dict(payload)


def _replace_proof_payload(proof, *, distributions=None, **generation_changes):
    distributions = tuple(sorted(distributions or proof.distributions, key=lambda item: item.manifest_fingerprint))
    generation = replace(
        proof.generation,
        artifact_manifest_fingerprints=tuple(item.manifest_fingerprint for item in distributions),
        artifact_sha256s=tuple(sorted(item.artifact_sha256 for item in distributions)),
        **generation_changes,
    )
    payload = proof.to_dict()
    payload.update(
        generation=generation.to_dict(),
        validation=OnlyRuntimeGenerationValidationEvidence.from_manifest(generation).to_dict(),
        distributions=[item.to_dict() for item in distributions],
    )
    return payload


@pytest.mark.parametrize(
    "alias", ("onlyalpha", "ONLYALPHA", "onlyalpha_plugin_indicators", "onlyalpha.plugin.indicators")
)
def test_rehashed_distribution_names_have_one_normalized_owner_regardless_of_version(alias):
    import re

    proof, _, _ = retained_proof_case()
    wheel_name = re.sub(r"[-_.]+", "_", alias).lower()
    support = OnlyDistributionArtifactManifest(
        OnlyDistributionArtifactRole.SUPPORT,
        OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
        "upstream",
        "release2",
        alias,
        "2",
        f"{wheel_name}-2-py3-none-any.whl",
        "b" * 64,
        3,
    )
    payload = _replace_proof_payload(proof, distributions=(*proof.distributions, support))
    with pytest.raises(ValueError, match="distribution ownership is ambiguous"):
        OnlyRetainedRuntimeGenerationProofV1.from_dict(payload)


@pytest.mark.parametrize(
    "mutation", ("missing_research", "missing_trading", "distribution_claim", "unsupported_core_type")
)
def test_rehashed_core_primitive_inventory_requires_complete_disjoint_owning_family(mutation):
    proof, _, _ = retained_proof_case()
    entry = next(
        item
        for item in proof.generation.implementations
        if item.kind == "PREDICATE" and item.backend == ("TRADING" if mutation == "missing_trading" else "RESEARCH")
    )
    implementations = proof.generation.implementations
    distributions = proof.distributions
    if mutation.startswith("missing_"):
        implementations = tuple(item for item in implementations if item != entry)
    elif mutation == "distribution_claim":
        calculation = OnlyDistributionArtifactManifest(
            OnlyDistributionArtifactRole.CALCULATION,
            OnlyArtifactSourceProvenanceAuthority.EXTERNAL_RELEASE,
            "upstream",
            "release1",
            "predicate-pretender",
            "1",
            "predicate_pretender-1-py3-none-any.whl",
            "b" * 64,
            3,
            tested_core_execution_fingerprint=proof.generation.core_execution.fingerprint,
            implementations=(entry,),
        )
        distributions = (*distributions, calculation)
    else:
        changed = replace(entry, type_id="onlyalpha.predicate.internal.unknown")
        implementations = tuple(changed if item == entry else item for item in implementations)
    payload = _replace_proof_payload(proof, distributions=distributions, implementations=implementations)
    with pytest.raises(ValueError, match="owning famil"):
        OnlyRetainedRuntimeGenerationProofV1.from_dict(payload)


@pytest.mark.parametrize("shape", ("tuple", "decimal", "float", "nonstring_key"))
def test_retained_catalog_raw_representation_is_validated_before_canonicalization(shape):
    from decimal import Decimal

    proof, _, _ = retained_proof_case()
    payload = proof.to_dict()
    if shape == "tuple":
        payload["catalog"]["providers"] = tuple(payload["catalog"]["providers"])
    elif shape == "nonstring_key":
        payload["catalog"][1] = "unsupported-key"
    else:
        payload["catalog"]["providers"][0]["calculations"][0]["type"]["numeric"]["output_quantum"] = (
            Decimal("0.00000001") if shape == "decimal" else 0.00000001
        )
    with pytest.raises(ValueError, match="noncanonical JSON representation"):
        OnlyRetainedRuntimeGenerationProofV1.from_dict(payload)


@pytest.mark.parametrize("owner", ("generation", "distribution"))
def test_retained_owning_parsers_reject_noncanonical_collection_even_with_canonical_identity(owner):
    proof, _, _ = retained_proof_case()
    if owner == "generation":
        payload = proof.generation.to_dict()
        payload["artifact_sha256s"].reverse()
        parser = OnlyRuntimeGenerationManifest.from_dict
    else:
        asset = next(item for item in proof.distributions if item.role is OnlyDistributionArtifactRole.QUANT_ASSET)
        payload = asset.to_dict()
        payload["implementations"].reverse()
        parser = OnlyDistributionArtifactManifest.from_dict
    with pytest.raises(ValueError, match="NONCANONICAL"):
        parser(payload)


@pytest.mark.parametrize(
    "mutation",
    (
        "whole",
        "owner",
        "validation",
        "duplicate_distribution",
        "missing_distribution",
        "wrong_manifest_to_bytes",
        "distribution_owner",
        "source",
        "tested_core",
        "asset_type",
        "implementation",
        "duplicate_implementation",
        "catalog",
        "bool_version",
        "unknown",
        "missing_context",
    ),
)
def test_retained_proof_structural_and_relation_mutations_fail_closed(mutation):
    proof, _, _ = retained_proof_case()
    payload = deepcopy(proof.to_dict())
    distributions = proof.distributions
    asset = next(item for item in distributions if item.role is OnlyDistributionArtifactRole.QUANT_ASSET)
    if mutation == "whole":
        payload = {"schema_version": 1}
    elif mutation == "owner":
        payload["generation"]["runtime_generation_fingerprint"] = "f" * 64
    elif mutation == "validation":
        payload["validation"]["core_execution_fingerprint"] = "f" * 64
    elif mutation == "duplicate_distribution":
        payload["distributions"].append(deepcopy(payload["distributions"][0]))
    elif mutation == "missing_distribution":
        payload["distributions"].pop()
    elif mutation == "wrong_manifest_to_bytes":
        altered = replace(asset, artifact_sha256="f" * 64)
        payload["distributions"] = [
            altered.to_dict() if item.manifest_fingerprint == asset.manifest_fingerprint else item.to_dict()
            for item in distributions
        ]
    elif mutation in {"distribution_owner", "source", "tested_core", "asset_type"}:
        changes = {
            "distribution_owner": {"provider_id": "different.provider.owner"},
            "source": {
                "distribution_name": "different_distribution",
                "artifact_logical_name": f"different_distribution-{asset.distribution_version}-py3-none-any.whl",
            },
            "tested_core": {"tested_core_execution_fingerprint": "f" * 64},
            "asset_type": {"assets": tuple(replace(item, content_fingerprint="f" * 64) for item in asset.assets)},
        }[mutation]
        altered = replace(asset, **changes)
        new_distributions = tuple(
            sorted(
                (altered if item is asset else item for item in distributions),
                key=lambda item: item.manifest_fingerprint,
            )
        )
        generation = replace(
            proof.generation,
            artifact_manifest_fingerprints=tuple(item.manifest_fingerprint for item in new_distributions),
        )
        payload.update(
            generation=generation.to_dict(),
            validation=OnlyRuntimeGenerationValidationEvidence.from_manifest(generation).to_dict(),
            distributions=[item.to_dict() for item in new_distributions],
        )
    elif mutation == "implementation":
        payload["implementation_manifests"][0]["resources"][0]["byte_sha256"] = "f" * 64
    elif mutation == "duplicate_implementation":
        payload["implementation_manifests"].append(deepcopy(payload["implementation_manifests"][0]))
    elif mutation == "catalog":
        payload["catalog"]["providers"][0]["calculations"][0]["type"]["outputs"][0]["data_type"] = "BOOL"
    elif mutation == "bool_version":
        payload["schema_version"] = True
    elif mutation == "unknown":
        payload["available"] = True
    else:
        payload["catalog"] = None
    with pytest.raises(ValueError):
        OnlyRetainedRuntimeGenerationProofV1.from_dict(payload)


@pytest.mark.parametrize("mutation", ("node", "missing", "duplicate", "wrong_implementation", "wrong_type", "output"))
def test_retained_graph_membership_and_selected_implementation_are_exact(mutation):
    proof, graph, bindings = retained_proof_case()
    if mutation == "node":
        bindings = (("f" * 64, bindings[0][1]),)
    elif mutation == "missing":
        bindings = ()
    elif mutation == "duplicate":
        bindings = (*bindings, *bindings)
    elif mutation == "wrong_implementation":
        bindings = ((bindings[0][0], "f" * 64),)
    else:
        definition = graph.nodes[0].definition
        if mutation == "wrong_type":
            definition = replace(definition, type_id="onlyalpha.indicator.different")
        else:
            definition = replace(
                definition, outputs=(replace(definition.outputs[0], nullable=not definition.outputs[0].nullable),)
            )
        graph = replace(graph, nodes=(replace(graph.nodes[0], definition=definition),))
        bindings = ((graph.nodes[0].fingerprint, bindings[0][1]),)
    with pytest.raises(ValueError):
        proof.require_graph_implementations(graph, bindings)
