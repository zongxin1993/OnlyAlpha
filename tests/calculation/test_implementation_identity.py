from dataclasses import replace

import pytest

from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationSemanticDependency,
    only_implementation_manifest_from_bytes,
    only_python_stdlib_semantic_dependency,
)
from tests.strategy.product_support import strategy_product_case


def _read_manifest():
    from onlyalpha.calculation.definition import OnlyCalculationKind, OnlyCalculationTypeReference

    return only_implementation_manifest_from_bytes(
        calculation_type_reference=OnlyCalculationTypeReference(
            OnlyCalculationKind.INDICATOR, "onlyalpha.indicator.sma", "1"
        ),
        backend_kind=OnlyCalculationBackendKind.RESEARCH,
        entrypoint_identity="tests.backend:Factory",
        resources={"first.py": b"1", "second.py": b"2"},
        semantic_dependencies=(OnlyCalculationSemanticDependency("numeric", "1", "a" * 64),),
    )


def test_implementation_manifest_canonical_read_round_trip() -> None:
    from onlyalpha.calculation.implementation import OnlyCalculationImplementationManifest

    manifest = _read_manifest()
    assert OnlyCalculationImplementationManifest.from_dict(manifest.to_dict()) == manifest


@pytest.mark.parametrize(
    "mutation", ("version_bool", "unknown", "resource_order", "duplicate_resource", "wrong_hash", "nested_unknown")
)
def test_implementation_manifest_reader_rejects_structural_mutations(mutation) -> None:
    from onlyalpha.calculation.implementation import OnlyCalculationImplementationManifest

    payload = _read_manifest().to_dict()
    if mutation == "version_bool":
        payload["schema_version"] = True
    elif mutation == "unknown":
        payload["unknown"] = "value"
    elif mutation == "resource_order":
        payload["resources"].reverse()
    elif mutation == "duplicate_resource":
        payload["resources"].append(payload["resources"][0])
    elif mutation == "wrong_hash":
        payload["implementation_fingerprint"] = "0" * 64
    else:
        payload["semantic_dependencies"][0]["unknown"] = "value"
    with pytest.raises(ValueError):
        OnlyCalculationImplementationManifest.from_dict(payload)


def test_implementation_identity_binds_resources_and_semantic_dependencies(tmp_path) -> None:
    case = strategy_product_case(tmp_path)
    node = case.revision.decision_graph.ordered_nodes[0]
    registration = case.registry.resolve(
        node.definition.kind,
        node.definition.type_id,
        node.definition.semantic_version,
        OnlyCalculationBackendKind.TRADING,
    )
    manifest = registration.implementation_manifest
    assert manifest is not None
    reference = manifest.calculation_type_reference
    base = only_implementation_manifest_from_bytes(
        calculation_type_reference=reference,
        backend_kind=OnlyCalculationBackendKind.TRADING,
        entrypoint_identity="tests.backend:Factory",
        resources={"backend.py": b"return 1"},
        semantic_dependencies=(OnlyCalculationSemanticDependency("numeric", "1", "a" * 64),),
    )
    reordered = only_implementation_manifest_from_bytes(
        calculation_type_reference=reference,
        backend_kind=OnlyCalculationBackendKind.TRADING,
        entrypoint_identity="tests.backend:Factory",
        resources={"backend.py": b"return 1"},
        semantic_dependencies=(OnlyCalculationSemanticDependency("numeric", "1", "a" * 64),),
    )

    assert base.implementation_fingerprint == reordered.implementation_fingerprint
    assert (
        base.implementation_fingerprint
        != replace(
            base,
            resources=only_implementation_manifest_from_bytes(
                calculation_type_reference=reference,
                backend_kind=OnlyCalculationBackendKind.TRADING,
                entrypoint_identity="tests.backend:Factory",
                resources={"backend.py": b"return 2"},
            ).resources,
        ).implementation_fingerprint
    )
    assert (
        base.implementation_fingerprint
        != replace(
            base,
            semantic_dependencies=(OnlyCalculationSemanticDependency("numeric", "2", "a" * 64),),
        ).implementation_fingerprint
    )
    assert (
        base.implementation_fingerprint
        != replace(
            base,
            semantic_dependencies=(OnlyCalculationSemanticDependency("numeric", "1", "b" * 64),),
        ).implementation_fingerprint
    )


def test_every_official_registration_binds_external_numeric_runtime(tmp_path) -> None:
    case = strategy_product_case(tmp_path)
    for node in case.revision.decision_graph.nodes:
        for backend in (OnlyCalculationBackendKind.RESEARCH, OnlyCalculationBackendKind.TRADING):
            registration = case.registry.resolve(
                node.definition.kind,
                node.definition.type_id,
                node.definition.semantic_version,
                backend,
            )
            assert registration.implementation_manifest is not None
            assert registration.implementation_manifest.semantic_dependencies


def test_stdlib_semantic_dependency_uses_supported_major_minor_contract(monkeypatch) -> None:
    monkeypatch.setattr("platform.python_implementation", lambda: "CPython")
    monkeypatch.setattr("platform.python_version_tuple", lambda: ("3", "12", "3"))
    first = only_python_stdlib_semantic_dependency("decimal")
    monkeypatch.setattr("platform.python_version_tuple", lambda: ("3", "12", "12"))
    patched = only_python_stdlib_semantic_dependency("decimal")
    monkeypatch.setattr("platform.python_version_tuple", lambda: ("3", "13", "0"))
    changed_minor = only_python_stdlib_semantic_dependency("decimal")

    assert first == patched == OnlyCalculationSemanticDependency("cpython.decimal", "3.12")
    assert changed_minor == OnlyCalculationSemanticDependency("cpython.decimal", "3.13")
