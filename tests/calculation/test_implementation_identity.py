from dataclasses import replace

from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationSemanticDependency,
    only_implementation_manifest_from_bytes,
    only_python_stdlib_semantic_dependency,
)
from tests.strategy.p9_support import p9_strategy_case


def test_implementation_identity_binds_resources_and_semantic_dependencies(tmp_path) -> None:
    case = p9_strategy_case(tmp_path)
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


def test_every_official_p9_registration_binds_external_numeric_runtime(tmp_path) -> None:
    case = p9_strategy_case(tmp_path)
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
