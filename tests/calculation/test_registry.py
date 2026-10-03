from dataclasses import fields, replace

import pytest

from onlyalpha.calculation import (
    OnlyCalculationBackendKind,
    OnlyCalculationBackendRegistration,
    OnlyCalculationDataType,
    OnlyCalculationKind,
    OnlyCalculationReference,
    OnlyCalculationRegistry,
    OnlyCalculationTypeDefinition,
    OnlyCalculationTypeReference,
    OnlyInputDefinition,
    OnlyMissingValuePolicy,
    OnlyNumericDefinition,
    OnlyOutputDefinition,
    OnlyParameterSchema,
    OnlyPreReadyOutput,
    OnlyTimestampSemantic,
    OnlyWarmupDefinition,
    only_implementation_manifest_from_bytes,
)
from onlyalpha.research.calculation import (
    OnlyResearchCalculationBackendResolver,
    OnlyResearchCalculationError,
    OnlyResearchCalculationPublicationContract,
)


def _type():
    return OnlyCalculationTypeDefinition(
        OnlyCalculationKind.INDICATOR,
        "vendor.indicator.mean",
        "1",
        OnlyParameterSchema(()),
        (OnlyInputDefinition("value", OnlyCalculationDataType.DECIMAL),),
        (OnlyOutputDefinition("value", OnlyCalculationDataType.DECIMAL, False),),
        OnlyMissingValuePolicy.FAIL,
        OnlyTimestampSemantic.EVENT_TIME,
        OnlyNumericDefinition(),
    )


def _definition():
    return _type().resolve(
        {},
        {"value": OnlyCalculationReference(None, "value", "bar.close")},
        OnlyWarmupDefinition(1, "samples >= 1", OnlyPreReadyOutput.PARTIAL, "PARTIAL_WINDOW"),
    )


class _LegacyBackend:
    def execute(self, definition, inputs):
        raise AssertionError("resolution must not execute")


class _ReadinessBackend(_LegacyBackend):
    def execute_with_readiness(self, definition, inputs):
        raise AssertionError("resolution must not execute")


def _registration(provider, versions=()):
    definition = _type()
    manifest = only_implementation_manifest_from_bytes(
        calculation_type_reference=OnlyCalculationTypeReference(
            definition.kind, definition.type_id, definition.semantic_version
        ),
        backend_kind=OnlyCalculationBackendKind.RESEARCH,
        entrypoint_identity="tests.backend:Readiness",
        resources={"backend.py": b"exact implementation"},
    )
    return OnlyCalculationBackendRegistration(
        definition,
        OnlyCalculationBackendKind.RESEARCH,
        provider,
        implementation_manifest=manifest,
        readiness_contract_versions=versions,
    )


def test_research_registration_declares_canonical_readiness_contract_versions() -> None:
    legacy = OnlyCalculationBackendRegistration(_type(), OnlyCalculationBackendKind.RESEARCH, object())
    assert legacy.readiness_contract_versions == ()
    assert _registration(_ReadinessBackend(), (1, 2)).readiness_contract_versions == (1, 2)
    assert fields(OnlyCalculationBackendRegistration)[-1].name == "readiness_contract_versions"
    trading = OnlyCalculationBackendRegistration(_type(), OnlyCalculationBackendKind.TRADING, object())
    assert trading.readiness_contract_versions == ()
    with pytest.raises(ValueError, match="RESEARCH"):
        replace(trading, readiness_contract_versions=(1,))


@pytest.mark.parametrize("versions", ([1], None, "1", (True,), (1.0,), (0,), (-1,), (1, 1), (2, 1), ("1",)))
def test_readiness_contract_versions_reject_bool_zero_duplicate_and_unsorted(versions) -> None:
    with pytest.raises((TypeError, ValueError), match="readiness"):
        _registration(_ReadinessBackend(), versions)


def test_readiness_resolver_returns_exact_provider_and_manifest_without_execution() -> None:
    registration = _registration(_ReadinessBackend(), (1,))
    registry = OnlyCalculationRegistry()
    registry.register(registration)
    resolved = OnlyResearchCalculationBackendResolver(registry).resolve_readiness(
        _definition(), OnlyResearchCalculationPublicationContract()
    )
    assert resolved.provider is registration.provider
    assert resolved.implementation_manifest is registration.implementation_manifest


@pytest.mark.parametrize("method", ("absent", None, 1))
def test_readiness_resolver_rejects_missing_or_noncallable_method(method) -> None:
    provider = _LegacyBackend()
    if method != "absent":
        provider.execute_with_readiness = method
    registry = OnlyCalculationRegistry()
    registry.register(_registration(provider, (1,)))
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_BACKEND_INVALID"):
        OnlyResearchCalculationBackendResolver(registry).resolve_readiness(
            _definition(), OnlyResearchCalculationPublicationContract()
        )


def test_legacy_resolution_succeeds_but_undeclared_readiness_never_falls_back() -> None:
    registry = OnlyCalculationRegistry()
    registration = _registration(_LegacyBackend())
    registry.register(registration)
    resolver = OnlyResearchCalculationBackendResolver(registry)
    assert resolver.resolve(_definition()).provider is registration.provider
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_READINESS_BACKEND_UNAVAILABLE"):
        resolver.resolve_readiness(_definition(), OnlyResearchCalculationPublicationContract())


def test_readiness_resolver_rejects_missing_implementation_identity() -> None:
    registry = OnlyCalculationRegistry()
    registry.register(replace(_registration(_ReadinessBackend(), (1,)), implementation_manifest=None))
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_IMPLEMENTATION_IDENTITY_UNRESOLVED"):
        OnlyResearchCalculationBackendResolver(registry).resolve_readiness(
            _definition(), OnlyResearchCalculationPublicationContract()
        )


def test_readiness_resolver_rejects_absent_registration_context() -> None:
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_READINESS_BACKEND_UNAVAILABLE"):
        OnlyResearchCalculationBackendResolver(OnlyCalculationRegistry()).resolve_readiness(
            _definition(), OnlyResearchCalculationPublicationContract()
        )


@pytest.mark.parametrize("mutation", ("version", "type", "kind", "backend"))
def test_readiness_resolver_requires_exact_registration(mutation) -> None:
    registry = OnlyCalculationRegistry()
    registration = _registration(_ReadinessBackend(), (1,))
    definition = _definition()
    if mutation == "backend":
        registration = replace(
            registration,
            backend=OnlyCalculationBackendKind.TRADING,
            implementation_manifest=None,
            readiness_contract_versions=(),
        )
    elif mutation == "version":
        definition = replace(definition, semantic_version="2")
    elif mutation == "type":
        definition = replace(definition, type_id="vendor.indicator.other")
    else:
        definition = replace(definition, kind=OnlyCalculationKind.TARGET)
    registry.register(registration)
    with pytest.raises(OnlyResearchCalculationError, match="RESEARCH_READINESS_BACKEND_UNAVAILABLE"):
        OnlyResearchCalculationBackendResolver(registry).resolve_readiness(
            definition, OnlyResearchCalculationPublicationContract()
        )


def test_registry_rejects_wrong_manifest_and_duplicate_owner() -> None:
    registry = OnlyCalculationRegistry()
    registration = _registration(_ReadinessBackend(), (1,))
    registry.register(registration)
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(registration)
    with pytest.raises(ValueError, match="manifest mismatch"):
        OnlyCalculationRegistry().register(
            replace(registration, type_definition=replace(_type(), semantic_version="2"))
        )
