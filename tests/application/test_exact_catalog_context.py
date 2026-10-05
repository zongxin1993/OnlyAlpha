from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import cast

import pytest
from onlyalpha_plugin_indicators.provider import quant_asset_provider as indicator_provider
from onlyalpha_plugin_operators.provider import quant_asset_provider as operator_provider
from onlyalpha_plugin_targets.registration import registrations as target_registrations
from onlyalpha_test_factor_provider.provider import quant_asset_provider as factor_provider

from onlyalpha.application import catalog_context as catalog_models
from onlyalpha.application.catalog_context import (
    EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT,
    OnlyExactCatalogContextCorrupt,
    OnlyExactCatalogContextProjectionMismatch,
    OnlyExactCatalogContextQueryService,
    OnlyExactCatalogContextSchemaUnsupported,
    OnlyExactCatalogContextUnavailable,
    OnlyExactCatalogContextV1,
    OnlyExactDatasetFieldContractV1,
    OnlyExactRegisteredUniverseV1,
    OnlyExactStatisticsCapabilityV1,
)
from onlyalpha.application.product_boundary import (
    OnlyGetExactCatalogContext,
    only_compose_research_product_boundary,
)
from onlyalpha.calculation import OnlyCalculationBackendKind
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration, OnlyQuantAssetProvider
from onlyalpha.research.command.query import OnlyResearchRunQueryService
from onlyalpha.research.command.service import OnlyResearchCommandService


def _generation(
    *, reverse_providers: bool = False, reverse_registrations: bool = False
) -> OnlyQuantAssetCatalogGeneration:
    operator = operator_provider()
    if reverse_registrations:
        operator = replace(operator, calculation_registrations=tuple(reversed(operator.calculation_registrations)))
    providers: tuple[OnlyQuantAssetProvider, ...] = (operator, indicator_provider(), factor_provider())
    if reverse_providers:
        providers = tuple(reversed(providers))
    return OnlyQuantAssetCatalogGeneration(providers)


class _Reader:
    def __init__(self, descriptors: Mapping[str, Mapping[str, object]]) -> None:
        self._descriptors = descriptors

    def load_verified_catalog_descriptor(self, fingerprint: str) -> Mapping[str, object]:
        return self._descriptors[fingerprint]

    def load_exact_dataset_field_contracts(self, fingerprint: str):  # type: ignore[no-untyped-def]
        return (
            OnlyExactDatasetFieldContractV1(
                fingerprint,
                "bar.close",
                "close",
                "DECIMAL",
                ("NUMERIC_SERIES", "PRICE"),
                ("TIME",),
                None,
                "1" * 64,
            ),
        )

    def load_exact_registered_universes(self, fingerprint: str):  # type: ignore[no-untyped-def]
        return (OnlyExactRegisteredUniverseV1(fingerprint, "csi300", "REGISTERED_UNIVERSE", "2" * 64),)

    def load_exact_statistics_capabilities(self, fingerprint: str):  # type: ignore[no-untyped-def]
        return (
            OnlyExactStatisticsCapabilityV1(
                fingerprint,
                "IC",
                ("FACTOR",),
                ("FACTOR_VALUE",),
                ("TARGET_VALUE",),
                True,
                True,
                "3" * 64,
            ),
        )


class _MismatchedReader(_Reader):
    def load_exact_registered_universes(self, fingerprint: str):  # type: ignore[no-untyped-def]
        return (OnlyExactRegisteredUniverseV1("f" * 64, "csi300", "REGISTERED_UNIVERSE", "2" * 64),)


def _context(generation: OnlyQuantAssetCatalogGeneration) -> OnlyExactCatalogContextV1:
    reader = _Reader({generation.generation_fingerprint: generation.descriptor()})
    return OnlyExactCatalogContextQueryService(reader, reader, reader, reader).get_exact_catalog_context(
        generation.generation_fingerprint
    )


def test_projection_is_deterministic_and_independent_of_provider_and_registration_order() -> None:
    first_generation = _generation()
    second_generation = _generation(reverse_providers=True, reverse_registrations=True)
    first = _context(first_generation)
    second = _context(second_generation)

    assert first_generation.generation_fingerprint == second_generation.generation_fingerprint
    assert first == second
    assert first.projection_fingerprint == second.projection_fingerprint
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.projection_schema_fingerprint == EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT
    assert tuple(item.sort_key for item in first.ordered_providers) == tuple(
        sorted(item.sort_key for item in first.ordered_providers)
    )
    assert tuple(item.sort_key for item in first.ordered_calculation_capabilities) == tuple(
        sorted(item.sort_key for item in first.ordered_calculation_capabilities)
    )
    expected_implementations = {
        registration.implementation_manifest.implementation_fingerprint
        for provider in first_generation.providers
        for registration in provider.calculation_registrations
        if registration.implementation_manifest is not None
    }
    assert {
        item.implementation_fingerprint for item in first.ordered_calculation_capabilities
    } == expected_implementations


def test_projection_is_complete_and_includes_exact_authority_capabilities() -> None:
    context = _context(_generation())
    encoded = context.canonical_bytes().decode("utf-8")

    assert {item.provider_id for item in context.ordered_providers} == {
        "onlyalpha.operator.library",
        "onlyalpha.indicator.library",
        "example.factor.library",
    }
    assert {item.type_id for item in context.ordered_calculation_capabilities}
    assert not {item.type_definition.type_id for item in target_registrations()} & {
        item.type_id for item in context.ordered_calculation_capabilities
    }
    assert [item.source_id for item in context.ordered_dataset_field_contracts] == ["bar.close"]
    assert [item.registered_id for item in context.ordered_registered_universes] == ["csi300"]
    assert [item.statistic_type for item in context.ordered_statistics_capabilities] == ["IC"]
    for forbidden in (
        "relative_path",
        "resource_bytes",
        "research-definition.json",
        "module_path",
        "source_code",
        "runtime_generation_fingerprint",
    ):
        assert forbidden not in encoded


def test_strict_round_trip_rejects_tamper_unknown_fields_and_unsupported_schema() -> None:
    context = _context(_generation())
    payload = context.to_dict()
    assert OnlyExactCatalogContextV1.from_dict(payload) == context

    tampered = context.to_dict()
    capabilities = cast(list[dict[str, object]], tampered["ordered_calculation_capabilities"])
    capabilities[0]["implementation_fingerprint"] = "f" * 64
    with pytest.raises(OnlyExactCatalogContextProjectionMismatch):
        OnlyExactCatalogContextV1.from_dict(tampered)

    unknown = context.to_dict()
    unknown["current"] = True
    with pytest.raises(OnlyExactCatalogContextCorrupt):
        OnlyExactCatalogContextV1.from_dict(unknown)

    missing = context.to_dict()
    del missing["ordered_providers"]
    with pytest.raises(OnlyExactCatalogContextCorrupt):
        OnlyExactCatalogContextV1.from_dict(missing)

    malformed = context.to_dict()
    malformed["catalog_generation_fingerprint"] = "A" * 64
    with pytest.raises(OnlyExactCatalogContextCorrupt):
        OnlyExactCatalogContextV1.from_dict(malformed)

    unsupported = context.to_dict()
    unsupported["schema_version"] = 2
    with pytest.raises(OnlyExactCatalogContextSchemaUnsupported):
        OnlyExactCatalogContextV1.from_dict(unsupported)


def test_each_formal_capability_family_changes_projection_identity() -> None:
    generation = _generation()
    reader = _Reader({generation.generation_fingerprint: generation.descriptor()})
    baseline = OnlyExactCatalogContextQueryService(reader, reader, reader, reader).get_exact_catalog_context(
        generation.generation_fingerprint
    )
    changed = []
    for method, replacement in (
        (
            "load_exact_dataset_field_contracts",
            (
                replace(
                    reader.load_exact_dataset_field_contracts(generation.generation_fingerprint)[0],
                    source_contract_fingerprint="4" * 64,
                ),
            ),
        ),
        (
            "load_exact_registered_universes",
            (
                replace(
                    reader.load_exact_registered_universes(generation.generation_fingerprint)[0],
                    universe_fingerprint="5" * 64,
                ),
            ),
        ),
        (
            "load_exact_statistics_capabilities",
            (
                replace(
                    reader.load_exact_statistics_capabilities(generation.generation_fingerprint)[0],
                    capability_fingerprint="6" * 64,
                ),
            ),
        ),
    ):
        variant = _Reader({generation.generation_fingerprint: generation.descriptor()})
        setattr(variant, method, lambda _fingerprint, value=replacement: value)
        changed.append(
            OnlyExactCatalogContextQueryService(variant, variant, variant, variant)
            .get_exact_catalog_context(generation.generation_fingerprint)
            .projection_fingerprint
        )
    calculation_changed = replace(
        baseline,
        ordered_calculation_capabilities=(
            replace(baseline.ordered_calculation_capabilities[0], implementation_fingerprint="7" * 64),
            *baseline.ordered_calculation_capabilities[1:],
        ),
    )
    assert baseline.projection_fingerprint not in changed
    assert len(set(changed)) == 3
    assert calculation_changed.projection_fingerprint != baseline.projection_fingerprint


def test_cross_authority_generation_mismatch_fails_closed() -> None:
    generation = _generation()
    reader = _MismatchedReader({generation.generation_fingerprint: generation.descriptor()})
    with pytest.raises(OnlyExactCatalogContextCorrupt):
        OnlyExactCatalogContextQueryService(reader, reader, reader, reader).get_exact_catalog_context(
            generation.generation_fingerprint
        )


class _Admission:
    def assert_mutation_ready(self) -> None:
        pass


def test_exact_query_uses_existing_product_query_dispatcher_topology() -> None:
    generation = _generation()
    reader = _Reader({generation.generation_fingerprint: generation.descriptor()})
    service = OnlyExactCatalogContextQueryService(reader, reader, reader, reader)
    boundary = only_compose_research_product_boundary(
        admission=_Admission(),
        commands=cast(OnlyResearchCommandService, object()),
        queries=cast(OnlyResearchRunQueryService, object()),
        exact_catalog_context=service,
    )
    result = boundary.queries.dispatch(OnlyGetExactCatalogContext(generation.generation_fingerprint))

    assert result == _context(generation)


def test_exact_catalog_v1_schema_fingerprint_remains_frozen() -> None:
    assert EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT == (
        "333cd389d54bc21338308b42f804fd3b8d765d7be0556b8c6be198f7ecb706ee"
    )


def _readiness_rows(context: OnlyExactCatalogContextV1):  # type: ignore[no-untyped-def]
    model = catalog_models.OnlyExactCatalogCalculationReadinessCapabilityV1
    return tuple(
        model(
            catalog_generation_fingerprint=context.catalog_generation_fingerprint,
            provider_id=item.provider_id,
            provider_version=item.provider_version,
            provider_kind=item.provider_kind,
            kind=item.kind,
            type_id=item.type_id,
            semantic_version=item.semantic_version,
            backend=item.backend,
            implementation_fingerprint=item.implementation_fingerprint,
            readiness_contract_versions=(1,)
            if item.type_id == "onlyalpha.indicator.sma" and item.backend is OnlyCalculationBackendKind.RESEARCH
            else (),
        )
        for item in context.ordered_calculation_capabilities
    )


class _ReadinessReader(_Reader):
    def __init__(self, generation: OnlyQuantAssetCatalogGeneration, rows: tuple[object, ...]) -> None:
        super().__init__({generation.generation_fingerprint: generation.descriptor()})
        self.rows = rows

    def load_exact_calculation_readiness_capabilities(self, fingerprint: str):  # type: ignore[no-untyped-def]
        assert fingerprint in self._descriptors
        return self.rows


def _readiness_service(generation: OnlyQuantAssetCatalogGeneration, rows: tuple[object, ...]):  # type: ignore[no-untyped-def]
    reader = _ReadinessReader(generation, rows)
    return OnlyExactCatalogContextQueryService(reader, reader, reader, reader, reader)


def test_readiness_capability_round_trip_is_strict_and_fingerprinted() -> None:
    row = next(item for item in _readiness_rows(_context(_generation())) if item.readiness_contract_versions)
    assert type(row).from_dict(row.to_dict()) == row
    assert len(row.capability_fingerprint) == 64
    assert replace(row, readiness_contract_versions=(1, 2)).capability_fingerprint != row.capability_fingerprint
    for field, value in (("unknown", True), ("schema_version", True), ("implementation_fingerprint", "X" * 64)):
        payload = row.to_dict()
        payload[field] = value
        with pytest.raises(catalog_models.OnlyExactCatalogContextError):
            type(row).from_dict(payload)
    payload = row.to_dict()
    payload["capability_fingerprint"] = "f" * 64
    with pytest.raises(OnlyExactCatalogContextProjectionMismatch):
        type(row).from_dict(payload)


@pytest.mark.parametrize("versions", ([1], (True,), (0,), (2, 1), (1, 1), ("1",)))
def test_readiness_capability_rejects_noncanonical_versions(versions: object) -> None:
    row = next(item for item in _readiness_rows(_context(_generation())) if item.readiness_contract_versions)
    with pytest.raises(OnlyExactCatalogContextCorrupt):
        replace(row, readiness_contract_versions=versions)


def test_non_research_capability_cannot_advertise_readiness() -> None:
    row = next(
        item for item in _readiness_rows(_context(_generation())) if item.backend is OnlyCalculationBackendKind.TRADING
    )
    with pytest.raises(OnlyExactCatalogContextCorrupt):
        replace(row, readiness_contract_versions=(1,))


def test_readiness_projection_binds_exact_v1_context_and_complete_registration_set() -> None:
    generation = _generation()
    context = _context(generation)
    rows = _readiness_rows(context)
    projection = _readiness_service(generation, rows).get_exact_catalog_readiness(generation.generation_fingerprint)
    assert projection.catalog_generation_fingerprint == context.catalog_generation_fingerprint
    assert projection.exact_catalog_context_projection_schema_fingerprint == context.projection_schema_fingerprint
    assert projection.exact_catalog_context_projection_fingerprint == context.projection_fingerprint
    assert projection.ordered_calculation_readiness_capabilities == rows
    assert tuple(item.sort_key for item in rows) == tuple(
        item.sort_key for item in context.ordered_calculation_capabilities
    )
    assert type(projection).from_dict(projection.to_dict()) == projection


@pytest.mark.parametrize(
    "mutation", ("missing", "extra", "duplicate", "implementation", "generation", "order", "owner", "family")
)
def test_readiness_projection_rejects_incomplete_or_wrong_registration_relation(mutation: str) -> None:
    generation = _generation()
    rows = _readiness_rows(_context(generation))
    if mutation == "missing":
        changed = rows[1:]
    elif mutation == "extra":
        changed = (*rows, replace(rows[-1], type_id="unregistered.type"))
    elif mutation == "duplicate":
        changed = (*rows, rows[-1])
    elif mutation == "implementation":
        changed = (replace(rows[0], implementation_fingerprint="f" * 64), *rows[1:])
    elif mutation == "generation":
        changed = (replace(rows[0], catalog_generation_fingerprint="f" * 64), *rows[1:])
    elif mutation == "order":
        changed = tuple(reversed(rows))
    elif mutation == "owner":
        changed = (replace(rows[0], provider_id="different.owner"), *rows[1:])
    else:
        changed = (replace(rows[0], backend=OnlyCalculationBackendKind.TRADING), *rows[1:])
    with pytest.raises(OnlyExactCatalogContextCorrupt):
        _readiness_service(generation, changed).get_exact_catalog_readiness(generation.generation_fingerprint)


def test_readiness_change_changes_only_new_projection_identity() -> None:
    generation = _generation()
    descriptor = generation.descriptor()
    context = _context(generation)
    old_bytes = context.canonical_bytes()
    rows = _readiness_rows(context)
    changed = tuple(replace(item, readiness_contract_versions=()) for item in rows)
    before = _readiness_service(generation, rows).get_exact_catalog_readiness(generation.generation_fingerprint)
    after = _readiness_service(generation, changed).get_exact_catalog_readiness(generation.generation_fingerprint)
    assert before.projection_fingerprint != after.projection_fingerprint
    assert before.exact_catalog_context_projection_fingerprint == after.exact_catalog_context_projection_fingerprint
    assert _context(generation).canonical_bytes() == old_bytes
    assert generation.descriptor() == descriptor


def test_exact_readiness_query_without_reader_fails_closed_but_v1_remains_usable() -> None:
    generation = _generation()
    reader = _Reader({generation.generation_fingerprint: generation.descriptor()})
    service = OnlyExactCatalogContextQueryService(reader, reader, reader, reader)
    assert service.get_exact_catalog_context(generation.generation_fingerprint) == _context(generation)
    with pytest.raises(OnlyExactCatalogContextUnavailable):
        service.get_exact_catalog_readiness(generation.generation_fingerprint)


def test_product_query_returns_exact_readiness_projection_without_mutation_admission() -> None:
    from onlyalpha.application.product_boundary import OnlyGetExactCatalogReadiness

    class NoMutationAdmission:
        def assert_mutation_ready(self) -> None:
            raise AssertionError("A read-only query must not authorize mutation")

    generation = _generation()
    service = _readiness_service(generation, _readiness_rows(_context(generation)))
    boundary = only_compose_research_product_boundary(
        admission=NoMutationAdmission(),
        commands=cast(OnlyResearchCommandService, object()),
        queries=cast(OnlyResearchRunQueryService, object()),
        exact_catalog_context=service,
    )
    assert boundary.queries.dispatch(OnlyGetExactCatalogReadiness(generation.generation_fingerprint)) == (
        service.get_exact_catalog_readiness(generation.generation_fingerprint)
    )
