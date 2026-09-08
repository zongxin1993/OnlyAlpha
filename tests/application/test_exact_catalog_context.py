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


def _context(generation: OnlyQuantAssetCatalogGeneration) -> OnlyExactCatalogContextV1:
    return OnlyExactCatalogContextQueryService(
        _Reader({generation.generation_fingerprint: generation.descriptor()})
    ).get_exact_catalog_context(generation.generation_fingerprint)


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


def test_projection_is_metadata_only_and_excludes_non_catalog_current_capabilities() -> None:
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
    for forbidden in (
        "relative_path",
        "resource_bytes",
        "research-definition.json",
        "module_path",
        "source_code",
        "ordered_registered_universes",
        "ordered_statistics_capabilities",
        "ordered_dataset_field_contracts",
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


class _Admission:
    def assert_mutation_ready(self) -> None:
        pass


def test_exact_query_uses_existing_product_query_dispatcher_topology() -> None:
    generation = _generation()
    service = OnlyExactCatalogContextQueryService(_Reader({generation.generation_fingerprint: generation.descriptor()}))
    boundary = only_compose_research_product_boundary(
        admission=_Admission(),
        commands=cast(OnlyResearchCommandService, object()),
        queries=cast(OnlyResearchRunQueryService, object()),
        exact_catalog_context=service,
    )
    result = boundary.queries.dispatch(OnlyGetExactCatalogContext(generation.generation_fingerprint))

    assert result == _context(generation)
