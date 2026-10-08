"""Read-only navigation relation over canonical registered Catalog projections."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from onlyalpha_http_server.research.catalog_context_routes import create_exact_catalog_context_router
from onlyalpha_http_server.research.runtime_generation_routes import create_runtime_generation_router
from onlyalpha_plugin_indicators.provider import quant_asset_provider

from onlyalpha.application.catalog_context import (
    OnlyExactCatalogCalculationReadinessCapabilityV1,
    OnlyExactCatalogContextQueryService,
    OnlyExactCatalogContextV1,
    OnlyExactCatalogReadinessProjectionV1,
    only_project_exact_catalog_context,
    only_project_exact_catalog_readiness,
)
from onlyalpha.quant_assets import OnlyQuantAssetCatalogGeneration


def test_chart_navigation_reads_distinct_runtime_binding_and_registered_sma_defaults_without_commands() -> None:
    provider = quant_asset_provider()
    generation = OnlyQuantAssetCatalogGeneration((provider,))
    context = only_project_exact_catalog_context(
        generation.generation_fingerprint,
        generation.descriptor(),
        dataset_field_contracts=(),
        registered_universes=(),
        statistics_capabilities=(),
    )
    registrations = {
        (item.type_definition.type_id, item.type_definition.semantic_version, item.backend): item
        for item in provider.calculation_registrations
    }
    readiness = only_project_exact_catalog_readiness(
        context,
        tuple(
            OnlyExactCatalogCalculationReadinessCapabilityV1(
                generation.generation_fingerprint,
                item.provider_id,
                item.provider_version,
                item.provider_kind,
                item.kind,
                item.type_id,
                item.semantic_version,
                item.backend,
                item.implementation_fingerprint,
                registrations[item.type_id, item.semantic_version, item.backend].readiness_contract_versions,
            )
            for item in context.ordered_calculation_capabilities
        ),
    )
    runtime = "a" * 64
    assert runtime != generation.generation_fingerprint
    reads: list[tuple[str, str]] = []

    class Runtimes:
        def projection(self) -> SimpleNamespace:
            return SimpleNamespace(active_for_new_work=runtime)

        def require_runtime_generation(self, fingerprint: str) -> SimpleNamespace:
            assert fingerprint == runtime
            reads.append(("runtime", fingerprint))
            return SimpleNamespace(
                runtime_generation_fingerprint=runtime, catalog_generation_fingerprint=generation.generation_fingerprint
            )

    class Catalogs(OnlyExactCatalogContextQueryService):
        def __init__(self) -> None:
            pass

        def get_exact_catalog_context(self, fingerprint: str) -> OnlyExactCatalogContextV1:
            assert fingerprint == generation.generation_fingerprint
            reads.append(("catalog", fingerprint))
            return context

        def get_exact_catalog_readiness(self, fingerprint: str) -> OnlyExactCatalogReadinessProjectionV1:
            assert fingerprint == generation.generation_fingerprint
            reads.append(("readiness", fingerprint))
            return readiness

    app = FastAPI()
    app.include_router(create_runtime_generation_router(Runtimes()))
    app.include_router(create_exact_catalog_context_router(Catalogs()))
    client = TestClient(app)
    active = client.get("/api/v2/research/runtime-generations/active").json()
    binding = client.get(f"/api/v2/research/runtime-generations/{active['runtime_generation_fingerprint']}").json()
    catalog = binding["catalog_generation_fingerprint"]
    result = client.get(f"/api/v2/research/catalog-context/exact/{catalog}").json()
    witness = client.get(f"/api/v2/research/catalog-context/exact/{catalog}/readiness").json()
    assert result == context.to_dict()
    assert witness == readiness.to_dict()
    assert reads == [("runtime", runtime), ("catalog", catalog), ("readiness", catalog)]
    supported = [
        item
        for item in witness["ordered_calculation_readiness_capabilities"]
        if 1 in item["readiness_contract_versions"]
    ]
    assert [(item["kind"], item["type_id"], item["semantic_version"], item["backend"]) for item in supported] == [
        ("INDICATOR", "onlyalpha.indicator.sma", "1", "RESEARCH")
    ]
    registered = next(
        item
        for item in result["ordered_calculation_capabilities"]
        if item["type_id"] == "onlyalpha.indicator.sma" and item["backend"] == "RESEARCH"
    )
    assert {item["name"]: item["default"] for item in registered["type_descriptor"]["parameters"]} == {
        "period": 20,
        "price_field": "CLOSE",
    }
    assert [item["name"] for item in registered["type_descriptor"]["outputs"]] == ["value"]
    assert all("post" not in methods for methods in app.openapi()["paths"].values())
