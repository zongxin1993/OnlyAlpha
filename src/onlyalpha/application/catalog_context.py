"""Product Query orchestration over shared pure Exact Catalog contracts."""
# ruff: noqa: F401

from onlyalpha.quant_assets.exact_catalog import *  # noqa: F403
from onlyalpha.quant_assets.exact_catalog import (
    OnlyExactCatalogCalculationReadinessReader,
    OnlyExactCatalogContextError,
    OnlyExactCatalogContextUnavailable,
    OnlyExactCatalogContextV1,
    OnlyExactCatalogGenerationDescriptorReader,
    OnlyExactCatalogReadinessProjectionV1,
    OnlyExactDatasetFieldContractReader,
    OnlyExactRegisteredUniverseReader,
    OnlyExactStatisticsCapabilityReader,
    _require_sha,
    only_project_exact_catalog_context,
    only_project_exact_catalog_readiness,
)


class OnlyExactCatalogContextQueryService:
    def __init__(
        self,
        catalog_reader: OnlyExactCatalogGenerationDescriptorReader,
        dataset_fields: OnlyExactDatasetFieldContractReader,
        universes: OnlyExactRegisteredUniverseReader,
        statistics: OnlyExactStatisticsCapabilityReader,
        readiness: OnlyExactCatalogCalculationReadinessReader | None = None,
    ) -> None:
        self._catalog_reader = catalog_reader
        self._dataset_fields = dataset_fields
        self._universes = universes
        self._statistics = statistics
        self._readiness = readiness

    def get_exact_catalog_readiness(self, catalog_generation_fingerprint: str) -> OnlyExactCatalogReadinessProjectionV1:
        context = self.get_exact_catalog_context(catalog_generation_fingerprint)
        if self._readiness is None:
            raise OnlyExactCatalogContextUnavailable
        try:
            rows = self._readiness.load_exact_calculation_readiness_capabilities(catalog_generation_fingerprint)
        except OnlyExactCatalogContextError:
            raise
        except Exception as exc:
            raise OnlyExactCatalogContextUnavailable from exc
        return only_project_exact_catalog_readiness(context, rows)

    def get_exact_catalog_context(self, catalog_generation_fingerprint: str) -> OnlyExactCatalogContextV1:
        _require_sha(catalog_generation_fingerprint)
        try:
            descriptor = self._catalog_reader.load_verified_catalog_descriptor(catalog_generation_fingerprint)
        except OnlyExactCatalogContextError:
            raise
        except Exception as exc:
            raise OnlyExactCatalogContextUnavailable from exc
        try:
            datasets = tuple(self._dataset_fields.load_exact_dataset_field_contracts(catalog_generation_fingerprint))
            universes = tuple(self._universes.load_exact_registered_universes(catalog_generation_fingerprint))
            statistics = tuple(self._statistics.load_exact_statistics_capabilities(catalog_generation_fingerprint))
        except OnlyExactCatalogContextError:
            raise
        except Exception as exc:
            raise OnlyExactCatalogContextUnavailable from exc
        return only_project_exact_catalog_context(
            catalog_generation_fingerprint,
            descriptor,
            dataset_field_contracts=datasets,
            registered_universes=universes,
            statistics_capabilities=statistics,
        )


__all__ = [name for name in globals() if name.startswith(("Only", "only_", "EXACT_"))]
