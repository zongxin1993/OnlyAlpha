"""Lazy public facades retain owning object identity and star-export contracts."""

from importlib import import_module

import pytest

pytestmark = pytest.mark.contract


@pytest.mark.parametrize(
    "package,owner,names",
    (
        (
            "dataset",
            "market_data_materializer",
            (
                "OnlySealedMarketDataDatasetMaterializer",
                "OnlySealedMarketDataMaterializationPlan",
                "OnlySealedMarketDataMaterializationResult",
            ),
        ),
        ("dataset", "materializer", ("OnlyResearchDatasetMaterializer",)),
        ("dataset", "plan", ("OnlyResearchDatasetMaterializationPlan",)),
        ("dataset", "economic", ("OnlyEconomicFactManifest", "OnlyResearchDatasetEconomicBinding")),
        ("dataset", "economic_store", ("OnlyDatasetEconomicBindingStore", "OnlyDatasetEconomicBindingStoreError")),
        (
            "evaluation",
            "subject",
            (
                "OnlyExactAuthoringGenerationReader",
                "OnlyExactEvaluationIntentResolverV1",
                "OnlyExactEvaluationIntentSubjectV1",
                "OnlyResearchEvaluationSubjectSetV1",
            ),
        ),
        (
            "artifact",
            "calculation_v2_model",
            (
                "OnlyResearchCalculationArtifactFileV2",
                "OnlyResearchCalculationArtifactManifestV2",
                "RESEARCH_CALCULATION_ARTIFACT_V2_PROFILE",
                "RESEARCH_CALCULATION_ARTIFACT_V2_SCHEMA_VERSION",
            ),
        ),
        ("artifact", "calculation_v2_store", ("OnlyParquetResearchCalculationArtifactStoreV2",)),
        ("artifact", "calculation_v2_materializer", ("OnlyResearchCalculationArtifactMaterializerV2",)),
        ("artifact", "calculation_v2_verification", ("OnlyResearchCalculationArtifactV2",)),
    ),
)
def test_public_lazy_exports_are_identical_to_the_owning_definition(package, owner, names):
    facade = import_module(f"onlyalpha.research.{package}")
    canonical = import_module(f"onlyalpha.research.{package}.{owner}")
    for name in names:
        assert getattr(facade, name) is getattr(canonical, name)
        assert getattr(facade, name) is getattr(facade, name)
    assert len(facade.__all__) == len(set(facade.__all__))
    if owner not in {"economic", "economic_store"}:
        assert set(names) <= set(facade.__all__)
    with pytest.raises(AttributeError):
        _ = facade.OnlyUnknownResearchExport
