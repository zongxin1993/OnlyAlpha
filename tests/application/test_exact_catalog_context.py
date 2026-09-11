from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import cast

import pytest
from onlyalpha_example_alpha.provider import quant_asset_provider as alpha_provider
from onlyalpha_example_strategies.provider import quant_asset_provider as strategy_provider
from onlyalpha_plugin_indicators.provider import quant_asset_provider as indicator_provider
from onlyalpha_plugin_operators.provider import quant_asset_provider as operator_provider
from onlyalpha_plugin_targets.registration import registrations as target_registrations

from onlyalpha.application.catalog_context import (
    EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT,
    OnlyExactCatalogContextCorrupt,
    OnlyExactCatalogContextProjectionMismatch,
    OnlyExactCatalogContextQueryService,
    OnlyExactCatalogContextSchemaUnsupported,
    OnlyExactCatalogContextV1,
    OnlyExactDatasetFieldContractV1,
    OnlyExactRegisteredUniverseV1,
    OnlyExactStatisticsCapabilityV1,
)
from onlyalpha.application.product_boundary import (
    OnlyGetExactCatalogContext,
    only_compose_research_product_boundary,
)
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration
from onlyalpha.research.command.query import OnlyResearchRunQueryService
from onlyalpha.research.command.service import OnlyResearchCommandService


def _generation(
    *, reverse_providers: bool = False, reverse_registrations: bool = False
) -> OnlyQuantAssetCatalogGeneration:
    operator = operator_provider()
    if reverse_registrations:
        operator = replace(operator, calculation_registrations=tuple(reversed(operator.calculation_registrations)))
    providers = (operator, indicator_provider(), alpha_provider(), strategy_provider())
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
        "example.alpha.library",
        "example.strategy.library",
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
