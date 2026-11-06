import pytest
from onlyalpha.calculation.definition import OnlyCalculationBackendKind
from onlyalpha.calculation.implementation import (
    OnlyCalculationSemanticDependency,
    only_implementation_manifest_from_bytes,
    only_python_stdlib_semantic_dependency,
)


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
