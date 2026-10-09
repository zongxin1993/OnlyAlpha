"""Product Query orchestration over shared pure Exact Catalog contracts."""

from onlyalpha.calculation.definition import (
    OnlyCalculationBackendKind,
    OnlyCalculationDataType,
    OnlyCalculationKind,
    OnlyFactorKind,
    OnlyMissingValuePolicy,
    OnlyParameterDefinition,
    OnlyParameterType,
    OnlyTimestampSemantic,
    only_calculation_semantic_bounds,
)
from onlyalpha.calculation.implementation import OnlyCalculationStateCapability
from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json
from onlyalpha.quant_assets.catalog import (
    OnlyPrivateFactorSnapshotProviderSource,
    OnlyQuantAssetKind,
    OnlyQuantAssetProviderManifest,
    OnlyQuantAssetProviderSource,
    only_quant_asset_provider_source_from_dict,
)
from onlyalpha.quant_assets.exact_catalog import (
    EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT,
    EXACT_CATALOG_CONTEXT_SCHEMA_VERSION,
    EXACT_CATALOG_READINESS_CAPABILITY_SCHEMA_VERSION,
    EXACT_CATALOG_READINESS_PROJECTION_SCHEMA_FINGERPRINT,
    EXACT_CATALOG_READINESS_PROJECTION_SCHEMA_VERSION,
    OnlyExactCatalogCalculationCapabilityV1,
    OnlyExactCatalogCalculationReadinessCapabilityV1,
    OnlyExactCatalogCalculationReadinessReader,
    OnlyExactCatalogContextCorrupt,
    OnlyExactCatalogContextError,
    OnlyExactCatalogContextNotFound,
    OnlyExactCatalogContextProjectionMismatch,
    OnlyExactCatalogContextSchemaUnsupported,
    OnlyExactCatalogContextUnavailable,
    OnlyExactCatalogContextV1,
    OnlyExactCatalogGenerationDescriptorReader,
    OnlyExactCatalogProviderV1,
    OnlyExactCatalogReadinessProjectionV1,
    OnlyExactDatasetFieldContractReader,
    OnlyExactDatasetFieldContractV1,
    OnlyExactRegisteredUniverseReader,
    OnlyExactRegisteredUniverseV1,
    OnlyExactStatisticsCapabilityReader,
    OnlyExactStatisticsCapabilityV1,
    _require_sha,
    only_project_exact_catalog_context,
    only_project_exact_catalog_readiness,
)
from onlyalpha.quant_assets.private_factor_provider_snapshot import OnlyPrivateFactorProviderSnapshotV1


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


__all__ = [
    "EXACT_CATALOG_CONTEXT_PROJECTION_SCHEMA_FINGERPRINT",
    "EXACT_CATALOG_CONTEXT_SCHEMA_VERSION",
    "EXACT_CATALOG_READINESS_CAPABILITY_SCHEMA_VERSION",
    "EXACT_CATALOG_READINESS_PROJECTION_SCHEMA_FINGERPRINT",
    "EXACT_CATALOG_READINESS_PROJECTION_SCHEMA_VERSION",
    "OnlyCalculationBackendKind",
    "OnlyCalculationDataType",
    "OnlyCalculationKind",
    "OnlyCalculationStateCapability",
    "OnlyExactCatalogCalculationCapabilityV1",
    "OnlyExactCatalogCalculationReadinessCapabilityV1",
    "OnlyExactCatalogCalculationReadinessReader",
    "OnlyExactCatalogContextCorrupt",
    "OnlyExactCatalogContextError",
    "OnlyExactCatalogContextNotFound",
    "OnlyExactCatalogContextProjectionMismatch",
    "OnlyExactCatalogContextQueryService",
    "OnlyExactCatalogContextSchemaUnsupported",
    "OnlyExactCatalogContextUnavailable",
    "OnlyExactCatalogContextV1",
    "OnlyExactCatalogGenerationDescriptorReader",
    "OnlyExactCatalogProviderV1",
    "OnlyExactCatalogReadinessProjectionV1",
    "OnlyExactDatasetFieldContractReader",
    "OnlyExactDatasetFieldContractV1",
    "OnlyExactRegisteredUniverseReader",
    "OnlyExactRegisteredUniverseV1",
    "OnlyExactStatisticsCapabilityReader",
    "OnlyExactStatisticsCapabilityV1",
    "OnlyFactorKind",
    "OnlyMissingValuePolicy",
    "OnlyParameterDefinition",
    "OnlyParameterType",
    "OnlyPrivateFactorProviderSnapshotV1",
    "OnlyPrivateFactorSnapshotProviderSource",
    "OnlyQuantAssetKind",
    "OnlyQuantAssetProviderManifest",
    "OnlyQuantAssetProviderSource",
    "OnlyTimestampSemantic",
    "only_calculation_semantic_bounds",
    "only_canonical_fingerprint",
    "only_canonical_json",
    "only_project_exact_catalog_context",
    "only_project_exact_catalog_readiness",
    "only_quant_asset_provider_source_from_dict",
]
