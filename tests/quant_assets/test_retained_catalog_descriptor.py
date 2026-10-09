"""Rehashed Catalog mutations must fail on relationships, not merely outer hashes."""

from __future__ import annotations

from copy import deepcopy

import pytest

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.quant_assets.exact_catalog import OnlyExactCatalogContextCorrupt, only_project_exact_catalog_context
from tests.quant_assets.test_retained_generation_proof import retained_proof_case

pytestmark = pytest.mark.contract


def _rehash(payload):
    for provider in payload["providers"]:
        provider["calculations"].sort(key=only_canonical_fingerprint)
        provider["content_fingerprint"] = only_canonical_fingerprint(
            {
                "kind": provider["manifest"]["kind"],
                "calculations": provider["calculations"],
                "private_factor_snapshot": provider["private_factor_snapshot"],
            }
        )
    payload["providers"].sort(
        key=lambda item: (
            item["manifest"]["kind"],
            item["manifest"]["provider_id"],
            item["manifest"]["provider_version"],
        )
    )
    payload["generation_fingerprint"] = only_canonical_fingerprint(
        {"schema_version": 1, "providers": payload["providers"]}
    )
    return payload


def _parse(payload):
    return only_project_exact_catalog_context(
        payload["generation_fingerprint"],
        payload,
        dataset_field_contracts=(),
        registered_universes=(),
        statistics_capabilities=(),
    )


@pytest.mark.parametrize(
    "mutation",
    (
        "duplicate_provider",
        "same_provider_other_version",
        "duplicate_registration",
        "cross_provider_registration",
        "different_type_across_backends",
        "duplicate_output",
        "missing_output",
        "duplicate_parameter",
        "research_state",
        "bad_checkpoint",
        "wrong_family",
        "source_coercion",
        "unknown_nested",
        "bool_version",
        "missing_snapshot",
        "parameter_bound",
        "parameter_default",
        "parameter_enum",
        "parameter_range",
        "numeric_quantum",
        "semantic_bounds",
        "provider_identity",
        "quantum_exponent",
    ),
)
def test_rehashed_catalog_requires_complete_unambiguous_structural_relations(mutation):
    proof, _, _ = retained_proof_case()
    payload = deepcopy(proof.catalog_descriptor)
    provider = payload["providers"][0]
    calculation = provider["calculations"][0]
    if mutation in {"duplicate_provider", "same_provider_other_version", "cross_provider_registration"}:
        duplicate = deepcopy(provider)
        if mutation == "same_provider_other_version":
            duplicate["manifest"]["provider_version"] = "different"
        elif mutation == "cross_provider_registration":
            duplicate["manifest"]["provider_id"] = "different.provider.owner"
        payload["providers"].append(duplicate)
    elif mutation == "duplicate_registration":
        provider["calculations"].append(deepcopy(calculation))
    elif mutation == "different_type_across_backends":
        pair = next(
            item
            for item in provider["calculations"]
            if item["type"]["type_id"] == calculation["type"]["type_id"] and item["backend"] != calculation["backend"]
        )
        pair["type"]["outputs"][0]["unit"] = "different-unit"
    elif mutation == "duplicate_output":
        calculation["type"]["outputs"].append(deepcopy(calculation["type"]["outputs"][0]))
    elif mutation == "missing_output":
        calculation["type"]["outputs"] = []
    elif mutation == "duplicate_parameter":
        selected = next(item for item in provider["calculations"] if item["type"]["parameters"])
        selected["type"]["parameters"].append(deepcopy(selected["type"]["parameters"][0]))
    elif mutation == "research_state":
        calculation["backend"] = "RESEARCH"
        calculation["state_capability"] = "STATELESS"
    elif mutation == "bad_checkpoint":
        calculation["backend"] = "TRADING"
        calculation["state_capability"] = "CHECKPOINTABLE"
        calculation["checkpoint_schema_version"] = True
    elif mutation == "wrong_family":
        provider["manifest"]["kind"] = "FACTOR"
    elif mutation == "source_coercion":
        provider["manifest"]["source"]["distribution_version"] = 999
    elif mutation == "unknown_nested":
        calculation["type"]["numeric"]["available"] = True
    elif mutation == "bool_version":
        provider["manifest"]["schema_version"] = True
    elif mutation.startswith("parameter_"):
        parameter = next(item for item in provider["calculations"] if item["type"]["parameters"])["type"]["parameters"][
            0
        ]
        if mutation == "parameter_bound":
            parameter["minimum"] = True
        elif mutation == "parameter_default":
            parameter["default"] = {"value": 3}
        elif mutation == "parameter_enum":
            parameter["enum_values"] = [{"value": 3}]
        else:
            parameter["minimum"], parameter["maximum"] = 5, 2
    elif mutation == "numeric_quantum":
        calculation["type"]["numeric"]["output_quantum"] = "NaN"
    elif mutation == "provider_identity":
        provider["manifest"]["provider_id"] = "InvalidProviderID"
    elif mutation == "quantum_exponent":
        calculation["type"]["numeric"]["output_quantum"] = "1E-8"
    elif mutation == "semantic_bounds":
        calculation["type"]["semantic_bounds"][calculation["type"]["outputs"][0]["name"]] = ["0", "1"]
    else:
        provider["manifest"]["source"] = {
            "kind": "PRIVATE_FACTOR_SNAPSHOT",
            "private_factor_provider_snapshot_fingerprint": "a" * 64,
        }
        provider["manifest"]["kind"] = "FACTOR"
    with pytest.raises(OnlyExactCatalogContextCorrupt):
        _parse(_rehash(payload))


def _native_catalog():
    from onlyalpha_test_factor_provider.provider import quant_asset_provider

    from onlyalpha.quant_assets.private_factor_provider_snapshot import (
        OnlyPrivateFactorProviderSnapshotEntryV1,
        OnlyPrivateFactorProviderSnapshotV1,
    )

    provider = quant_asset_provider().descriptor()
    types = {}
    for registration in provider["calculations"]:
        key = registration["type"]["type_id"], registration["type"]["semantic_version"]
        types.setdefault(key, {})[registration["backend"]] = registration["implementation_fingerprint"]
    snapshot = OnlyPrivateFactorProviderSnapshotV1(
        tuple(
            OnlyPrivateFactorProviderSnapshotEntryV1(
                key[0],
                key[1],
                "1" * 64,
                "2" * 64,
                "3" * 64,
                1,
                "4" * 64,
                "5" * 64,
                "6" * 64,
                fingerprints["RESEARCH"],
                fingerprints["TRADING"],
                "9" * 64,
            )
            for key, fingerprints in sorted(types.items())
        )
    )
    provider["manifest"]["source"] = {
        "kind": "PRIVATE_FACTOR_SNAPSHOT",
        "private_factor_provider_snapshot_fingerprint": snapshot.snapshot_fingerprint,
    }
    provider["private_factor_snapshot"] = snapshot.to_dict()
    return _rehash({"schema_version": 1, "providers": [provider], "generation_fingerprint": "a" * 64})


def test_private_snapshot_catalog_can_be_read_without_rebuilding_provider():
    context = _parse(_native_catalog())
    assert context.ordered_providers[0].provider_source.to_dict()["kind"] == "PRIVATE_FACTOR_SNAPSHOT"


@pytest.mark.parametrize("mutation", ("whole", "source", "entry", "duplicate_owner", "missing_backend", "binding"))
def test_rehashed_private_snapshot_catalog_requires_full_source_and_backend_closure(mutation):
    payload = _native_catalog()
    provider = payload["providers"][0]
    snapshot = provider["private_factor_snapshot"]
    if mutation == "whole":
        provider["private_factor_snapshot"] = None
    elif mutation == "source":
        provider["manifest"]["source"]["private_factor_provider_snapshot_fingerprint"] = "f" * 64
    elif mutation == "entry":
        snapshot["entries"][0]["source_sha256"] = "malformed"
    elif mutation == "duplicate_owner":
        snapshot["entries"].append(deepcopy(snapshot["entries"][0]))
    elif mutation == "missing_backend":
        provider["calculations"].pop()
    else:
        provider["calculations"][0]["implementation_fingerprint"] = "f" * 64
    with pytest.raises(OnlyExactCatalogContextCorrupt):
        _parse(_rehash(payload))
