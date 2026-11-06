"""Exact type resolution through the actual maintained Target registration."""

from dataclasses import replace

import pytest
from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationReference,
    OnlyCalculationTypeReference,
)
from onlyalpha.calculation.implementation import OnlyCalculationStateCapability
from onlyalpha.calculation.registry import OnlyCalculationRegistry
from onlyalpha_backend_algorithms.targets.registration import registrations


def test_registry_preserves_exact_type_and_parameter_derived_definition():
    registration = registrations()[0]
    registry = OnlyCalculationRegistry()
    registry.register(registration)
    kind, identity, version = (
        registration.type_definition.kind,
        registration.type_definition.type_id,
        registration.type_definition.semantic_version,
    )
    reference = OnlyCalculationTypeReference(kind, identity, version)
    assert registry.type_definitions() == (registration.type_definition,)
    assert registry.backend_registrations() == (registration,)
    assert registry.descriptors() == (registration.type_definition.descriptor(),)
    assert registry.resolve(kind, identity, version, OnlyCalculationBackendKind.RESEARCH) is registration
    assert registry.resolve_type(reference) == registration.type_definition
    bindings = {name: OnlyCalculationReference(None, name, "bar.close") for name in ("entry_price", "exit_price")}
    short = registry.rematerialize_definition(reference, {"exit_offset": 2}, bindings)
    long = registry.rematerialize_definition(reference, {"exit_offset": 5}, bindings)
    assert short.parameters["exit_offset"] == 2 and long.parameters["exit_offset"] == 5
    assert short.fingerprint != long.fingerprint
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(registration)
    for altered, error in [
        (replace(reference, semantic_version="missing"), "unknown semantic version"),
        (replace(reference, type_id="unknown.target"), "unknown calculation type"),
    ]:
        with pytest.raises(ValueError, match=error):
            registry.resolve_type(altered)
    with pytest.raises(ValueError, match="unsupported backend"):
        registry.resolve(kind, identity, version, OnlyCalculationBackendKind.TRADING)
    missing = OnlyCalculationRegistry()
    missing.register(replace(registration, definition_resolver=None))
    with pytest.raises(ValueError, match="resolver is unavailable"):
        missing.rematerialize_definition(reference, {}, bindings)


def test_registry_rejects_conflicting_manifests_and_non_resolvers_before_use():
    registration = registrations()[0]
    for changed, error in [
        (replace(registration, provider=None), "provider is required"),
        (replace(registration, definition_resolver=object()), "resolver contract is invalid"),
        (
            replace(registration, type_definition=replace(registration.type_definition, semantic_version="other")),
            "implementation manifest mismatch",
        ),
    ]:
        with pytest.raises((TypeError, ValueError), match=error):
            OnlyCalculationRegistry().register(changed)
    registry = OnlyCalculationRegistry()
    registry.register(registration)
    altered = replace(
        registration,
        backend=OnlyCalculationBackendKind.TRADING,
        type_definition=replace(
            registration.type_definition, numeric=replace(registration.type_definition.numeric, precision=37)
        ),
    )
    with pytest.raises(ValueError, match="differs across backends"):
        registry.register(altered)


@pytest.mark.parametrize("versions", [(2, 1), (1, 1), (True,), (1.0,), [1], (0,)])
def test_registration_readiness_versions_reject_ambiguous_plain_integer_contract(versions):
    with pytest.raises(ValueError, match="readiness contract versions"):
        replace(registrations()[0], readiness_contract_versions=versions)


def test_state_and_readiness_contracts_cannot_cross_backend_boundaries():
    registration = registrations()[0]
    for mutation in [
        {"state_capability": OnlyCalculationStateCapability.STATELESS},
        {"checkpoint_schema_version": 1},
        {"backend": OnlyCalculationBackendKind.TRADING, "readiness_contract_versions": (1,)},
        {
            "backend": OnlyCalculationBackendKind.TRADING,
            "state_capability": OnlyCalculationStateCapability.STATELESS,
            "checkpoint_schema_version": 1,
        },
        {
            "backend": OnlyCalculationBackendKind.TRADING,
            "state_capability": OnlyCalculationStateCapability.CHECKPOINTABLE,
        },
        {
            "backend": OnlyCalculationBackendKind.TRADING,
            "state_capability": OnlyCalculationStateCapability.CHECKPOINTABLE,
            "checkpoint_schema_version": True,
        },
        {"backend": OnlyCalculationBackendKind.TRADING, "checkpoint_schema_version": 1},
    ]:
        with pytest.raises(ValueError):
            replace(registration, **mutation)
