"""Freeze every direct onlyalpha_api to Core capability crossing."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.architecture._p9_k0_guard_helpers import CanonicalImport, onlyalpha_imports, onlyalpha_imports_for_path

pytestmark = pytest.mark.architecture

ROOT = Path(__file__).parents[2]
API_ROOT = ROOT / "packages/api/onlyalpha-api/src/onlyalpha_api"

COMPOSITION_ROOT = "COMPOSITION ROOT"
TRANSPORT_ROUTE = "TRANSPORT ROUTE"
API_LOCAL_SERVICE_ADAPTER = "API-LOCAL SERVICE ADAPTER"
DTO_ERROR_MAPPER = "DTO / ERROR / MAPPER"

API_MODULE_ROLES = {
    "app.py": COMPOSITION_ROOT,
    "artifact_main.py": COMPOSITION_ROOT,
    "health.py": TRANSPORT_ROUTE,
    "main.py": COMPOSITION_ROOT,
    "research/definition_errors.py": DTO_ERROR_MAPPER,
    "research/definition_routes.py": TRANSPORT_ROUTE,
    "research/definition_schema.py": DTO_ERROR_MAPPER,
    "research/definition_service.py": API_LOCAL_SERVICE_ADAPTER,
    "research/discovery.py": API_LOCAL_SERVICE_ADAPTER,
    "research/errors.py": DTO_ERROR_MAPPER,
    "research/routes.py": TRANSPORT_ROUTE,
    "research/run_errors.py": DTO_ERROR_MAPPER,
    "research/run_routes.py": TRANSPORT_ROUTE,
    "research/run_schema.py": DTO_ERROR_MAPPER,
    "research/schema.py": DTO_ERROR_MAPPER,
}


def _symbols(specification: str) -> frozenset[CanonicalImport]:
    result: set[CanonicalImport] = set()
    for qualified in specification.split():
        module, _, symbol = qualified.rpartition(".")
        result.add(("symbol", module, symbol))
    return frozenset(result)


EXPECTED_API_CORE_CROSSINGS = {
    "app.py": _symbols(
        """
        onlyalpha.calculation.registry.OnlyCalculationRegistry
        onlyalpha.research.command.errors.OnlyResearchCommandError
        onlyalpha.research.command.query.OnlyResearchRunQueryService
        onlyalpha.research.command.service.OnlyResearchCommandService
        onlyalpha.research.definition.errors.OnlyResearchDefinitionError
        onlyalpha.research.definition.ports.OnlyResearchUniverseCatalog
        onlyalpha.research.definition.resolver.OnlyResearchDefinitionResolver
        onlyalpha.research.operations.readiness.OnlyResearchReadiness
        onlyalpha.research.operations.readiness.OnlyResearchReadinessStatus
        onlyalpha.research.operations.readiness.OnlyResearchServiceReadinessProbe
        onlyalpha.research.query.OnlyResearchArtifactReader
        onlyalpha.research.query.OnlyResearchQueryError
        onlyalpha.research.query.OnlyResearchQueryService
        onlyalpha.research.run.errors.OnlyResearchRunError
        onlyalpha.research.specification.errors.OnlyResearchSpecificationError
        """
    ),
    "artifact_main.py": _symbols("onlyalpha.research.artifact.reader.OnlyResearchArtifactProfileReader"),
    "health.py": _symbols(
        """
        onlyalpha.research.operations.readiness.OnlyResearchReadiness
        onlyalpha.research.operations.readiness.OnlyResearchReadinessCheck
        onlyalpha.research.operations.readiness.OnlyResearchReadinessStatus
        """
    ),
    "main.py": _symbols(
        """
        onlyalpha.broker.factory.OnlyBrokerFactoryRegistry
        onlyalpha.calculation.registry.OnlyCalculationRegistry
        onlyalpha.core.clock.only_system_utc_now
        onlyalpha.data.factory.OnlyDataSourceFactoryRegistry
        onlyalpha.fee.broker_contract.OnlyBrokerFeeContractRegistry
        onlyalpha.market.product.OnlyMarketProductFactoryRegistry
        onlyalpha.output.user_data.OnlyUserDataLayout
        onlyalpha.persistence.postgres.OnlyPostgresConfig
        onlyalpha.persistence.postgres.OnlyPostgresMigrationAuthority
        onlyalpha.persistence.postgres.OnlyPostgresOperationalConnectionOptions
        onlyalpha.persistence.postgres.OnlyPostgresResearchDeploymentStore
        onlyalpha.persistence.postgres.OnlyPostgresResearchRunStore
        onlyalpha.persistence.postgres.only_assert_supported_postgres_server
        onlyalpha.plugin.discovery.only_discover_plugins
        onlyalpha.research.artifact.reader.OnlyResearchArtifactProfileReader
        onlyalpha.research.calculation.predicate.only_register_research_predicate_primitives
        onlyalpha.research.command.query.OnlyResearchRunQueryService
        onlyalpha.research.command.service.OnlyResearchCommandService
        onlyalpha.research.dataset.OnlyParquetResearchDatasetSnapshotStore
        onlyalpha.research.definition.resolver.OnlyResearchDefinitionResolver
        onlyalpha.research.operations.deployment.OnlyResearchDeploymentCoherenceVerifier
        onlyalpha.research.operations.deployment.OnlyResearchFrozenDeploymentCheck
        onlyalpha.research.operations.deployment.OnlyResearchSemanticStoreIdentity
        onlyalpha.research.operations.readiness.OnlyResearchRequiredRoot
        onlyalpha.research.operations.readiness.OnlyResearchServiceReadinessProbe
        onlyalpha.research.run.admission.OnlyResearchRunAdmissionService
        onlyalpha.research.specification.resolver.OnlyResearchSpecificationResolver
        """
    ),
    "research/definition_errors.py": _symbols("onlyalpha.research.definition.OnlyResearchDefinitionError"),
    "research/definition_schema.py": _symbols(
        """
        onlyalpha.calculation.OnlyCalculationDataType
        onlyalpha.calculation.OnlyCalculationKind
        onlyalpha.calculation.OnlyCalculationScalar
        onlyalpha.calculation.OnlyCalculationTypeDefinition
        onlyalpha.calculation.only_calculation_scalar_to_dict
        onlyalpha.domain.enums.OnlyAdjustmentType
        onlyalpha.domain.enums.OnlyAggregationSource
        onlyalpha.domain.enums.OnlyBarAggregation
        onlyalpha.domain.enums.OnlyPriceType
        onlyalpha.research.definition.model.OnlyResearchDefinition
        onlyalpha.research.definition.model.OnlyResearchUniverseKind
        onlyalpha.research.definition.resolver.OnlyResearchDefinitionResolution
        onlyalpha.research.evaluation.capability.OnlyResearchStatisticsCapability
        onlyalpha.research.evaluation.definition.OnlyResearchPairingPolicy
        onlyalpha.research.evaluation.definition.OnlyResearchRankTieMethod
        onlyalpha.research.evaluation.definition.OnlyResearchStatisticsMethod
        onlyalpha.research.evaluation.definition.OnlyResearchUniversePolicy
        onlyalpha.research.evaluation.definition.OnlyResearchWeighting
        """
    ),
    "research/definition_service.py": _symbols(
        """
        onlyalpha.research.definition.errors.OnlyResearchDefinitionError
        onlyalpha.research.definition.errors.OnlyResearchDefinitionPhase
        onlyalpha.research.definition.resolver.OnlyResearchDefinitionResolver
        """
    ),
    "research/discovery.py": _symbols(
        """
        onlyalpha.calculation.definition.OnlyCalculationBackendKind
        onlyalpha.calculation.definition.OnlyCalculationTypeDefinition
        onlyalpha.calculation.definition.OnlyCalculationTypeReference
        onlyalpha.calculation.registry.OnlyCalculationRegistry
        onlyalpha.research.calculation.binding.OnlyResearchDatasetSourceContract
        onlyalpha.research.calculation.binding.only_research_dataset_source_contracts
        onlyalpha.research.definition.model.OnlyResearchUniverseKind
        onlyalpha.research.definition.ports.OnlyResearchRegisteredUniverse
        onlyalpha.research.definition.ports.OnlyResearchUniverseCatalog
        onlyalpha.research.evaluation.capability.OnlyResearchStatisticsCapability
        onlyalpha.research.evaluation.capability.only_research_statistics_capabilities
        """
    ),
    "research/errors.py": _symbols(
        """
        onlyalpha.research.query.OnlyResearchQueryError
        onlyalpha.research.query.OnlyResearchQueryErrorCode
        """
    ),
    "research/routes.py": _symbols(
        """
        onlyalpha.research.query.DEFAULT_PAGE_SIZE
        onlyalpha.research.query.OnlyResearchQueryService
        onlyalpha.research.query.OnlyResearchScientificSeriesQuery
        onlyalpha.research.query.OnlyResearchStatisticSeriesQuery
        """
    ),
    "research/run_errors.py": _symbols(
        """
        onlyalpha.research.command.errors.OnlyResearchCommandError
        onlyalpha.research.run.errors.OnlyPostgresSchemaIncompatibleError
        onlyalpha.research.run.errors.OnlyResearchRunAdmissionError
        onlyalpha.research.run.errors.OnlyResearchRunIntegrityError
        onlyalpha.research.run.errors.OnlyResearchRunNotFoundError
        onlyalpha.research.run.errors.OnlyResearchRunStoreUnavailableError
        onlyalpha.research.specification.errors.OnlyResearchSpecificationError
        """
    ),
    "research/run_routes.py": _symbols(
        """
        onlyalpha.research.command.errors.OnlyResearchCommandError
        onlyalpha.research.command.errors.OnlyResearchCommandPhase
        onlyalpha.research.command.model.OnlyResearchSubmissionKey
        onlyalpha.research.command.query.DEFAULT_RESEARCH_RUN_PAGE_SIZE
        onlyalpha.research.command.query.OnlyResearchRunQueryService
        onlyalpha.research.command.service.OnlyResearchCommandService
        onlyalpha.research.run.model.OnlyResearchRunId
        onlyalpha.research.specification.model.OnlyResearchSpecification
        """
    ),
    "research/run_schema.py": _symbols(
        """
        onlyalpha.research.command.model.OnlyResearchRunPage
        onlyalpha.research.command.model.OnlyResearchSubmitOutcome
        onlyalpha.research.run.model.OnlyResearchRun
        onlyalpha.research.run.model.OnlyResearchRunFailure
        """
    ),
    "research/schema.py": _symbols(
        """
        onlyalpha.calculation.OnlyCalculationScalar
        onlyalpha.calculation.only_calculation_scalar_to_dict
        onlyalpha.canonical.only_canonical_payload
        onlyalpha.research.query.OnlyResearchArtifactSummary
        onlyalpha.research.query.OnlyResearchCandidateCatalog
        onlyalpha.research.query.OnlyResearchCandidateGraph
        onlyalpha.research.query.OnlyResearchMarketPoint
        onlyalpha.research.query.OnlyResearchPublishedSeriesCatalog
        onlyalpha.research.query.OnlyResearchScientificSeriesPage
        onlyalpha.research.query.OnlyResearchSignalPoint
        onlyalpha.research.query.OnlyResearchStatisticPoint
        onlyalpha.research.query.OnlyResearchStatisticSeriesPage
        onlyalpha.research.query.OnlyResearchStatisticsCatalog
        onlyalpha.research.query.OnlyResearchStatisticsDefinitionDescriptor
        onlyalpha.research.query.OnlyResearchStatisticsDescriptor
        onlyalpha.research.query.OnlyResearchVariablePoint
        """
    ),
}

PRIVILEGED_API_MODULES = (
    "onlyalpha.application.strategy_authority",
    "onlyalpha.kernel",
    "onlyalpha.persistence.postgres.migration",
    "onlyalpha.persistence.postgres.strategy_store",
    "onlyalpha.research.execution.scheduler",
    "onlyalpha.research.execution.worker",
    "onlyalpha.runtime.live",
    "onlyalpha.strategy.freeze",
    "onlyalpha.strategy.promotion",
    "onlyalpha.strategy.store",
)
PRIVILEGED_API_SYMBOLS = {
    "OnlyPostgresMigrationAuthority",
    "OnlyStrategyFreezeApplicationService",
    "OnlyStrategyPromotionApplicationService",
    "OnlyStrategyFreezeService",
    "OnlyStrategyPromotionService",
    "_OnlyFrozenStrategyPublisher",
}


def _api_core_crossings(root: Path) -> dict[str, frozenset[CanonicalImport]]:
    return {
        path.relative_to(root).as_posix(): imports
        for path in sorted(root.rglob("*.py"))
        if (imports := onlyalpha_imports_for_path(path, ROOT))
    }


def _privileged_api_imports(imports: frozenset[CanonicalImport]) -> frozenset[CanonicalImport]:
    return frozenset(
        capability
        for capability in imports
        if any(capability[1] == module or capability[1].startswith(f"{module}.") for module in PRIVILEGED_API_MODULES)
        or (len(capability) == 3 and capability[2] in PRIVILEGED_API_SYMBOLS)
    )


def test_every_api_module_role_is_explicit() -> None:
    actual = {path.relative_to(API_ROOT).as_posix() for path in API_ROOT.rglob("*.py") if path.name != "__init__.py"}
    assert set(API_MODULE_ROLES) == actual


def test_every_api_core_crossing_and_capability_is_exactly_inventoried() -> None:
    assert _api_core_crossings(API_ROOT) == EXPECTED_API_CORE_CROSSINGS
    assert set(EXPECTED_API_CORE_CROSSINGS) <= set(API_MODULE_ROLES)


def test_non_composition_api_modules_have_no_privileged_authority() -> None:
    for relative, imports in EXPECTED_API_CORE_CROSSINGS.items():
        if API_MODULE_ROLES[relative] != COMPOSITION_ROOT:
            assert not _privileged_api_imports(imports), relative


@pytest.mark.parametrize(
    ("filename", "source"),
    (
        (
            "strategy_api.py",
            "from onlyalpha.application.strategy_authority import OnlyStrategyPromotionApplicationService\n",
        ),
        (
            "helper.py",
            "from onlyalpha.application.strategy_authority import OnlyStrategyFreezeApplicationService as Freeze\n",
        ),
        ("commands2.py", "import onlyalpha.kernel\n"),
    ),
)
def test_oddly_named_api_helper_cannot_hide_privileged_authority(filename: str, source: str, tmp_path: Path) -> None:
    helper = tmp_path / filename
    helper.write_text(source, encoding="utf-8")
    imports = onlyalpha_imports(source)
    assert helper.name not in EXPECTED_API_CORE_CROSSINGS
    assert _privileged_api_imports(imports)


def test_current_definition_resolver_adapter_remains_approved() -> None:
    relative = "research/definition_service.py"
    assert API_MODULE_ROLES[relative] == API_LOCAL_SERVICE_ADAPTER
    assert EXPECTED_API_CORE_CROSSINGS[relative] == onlyalpha_imports_for_path(API_ROOT / relative, ROOT)
