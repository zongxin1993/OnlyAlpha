"""Reference-only composition for retained Research history/fault tests.

No Product ingress, executable backend, HTTP factory, process entry point or
current-runtime admission is provided here. Existing owning readers/builders
remain the implementation under test; these fixtures only connect their inputs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, cast

from onlyalpha_authoring_execution_worker.generation import (
    OnlyVerifiedAuthoringGenerationReader,
)
from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry
from onlyalpha_runtime_generation_manager.catalog_context import (
    OnlyRuntimeGenerationExactCatalogDescriptorReader,
)

from onlyalpha.backtest import OnlyBacktestEvidenceStore
from onlyalpha.output.user_data import OnlyUserDataLayout
from onlyalpha.persistence.postgres.research_source_cut_store import (
    OnlyPostgresResearchSourceCutAuthority,
)
from onlyalpha.research.agent.source_cut import OnlyAgentProvenanceClosedCutAuthority
from onlyalpha.research.calculation.result_store import (
    OnlyParquetResearchCalculationResultStore,
)
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.evaluation.factor_pair.result_store import (
    OnlyParquetResearchFactorPairStatisticsResultStore,
)
from onlyalpha.research.evaluation.result_store import (
    OnlyParquetResearchStatisticsResultStore,
)
from onlyalpha.research.evaluation.summary.result_store import (
    OnlyJsonResearchSummaryStatisticsResultStore,
)
from onlyalpha.research.experiment import (
    OnlyJsonSearchProvenanceStore,
    OnlySearchExperimentManifestV2,
    OnlySearchExperimentManifestV3,
)
from onlyalpha.research.memory.advisory import (
    OnlyExperimentMemoryAdvisoryProjectionBuilder,
)
from onlyalpha.research.memory.production import (
    OnlyCapturableMemoryCutReader,
    OnlyExperimentMemoryProductionBuilder,
    OnlyExperimentMemoryReferenceReadersV1,
)
from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from onlyalpha.research.search.parameter.context import (
    OnlyParameterSearchContextResolver,
)
from onlyalpha.research.search.parameter.errors import OnlyParameterSearchStoreError
from onlyalpha.research.search.parameter.store import OnlyJsonParameterSearchStore
from onlyalpha.research.search.symbolic.context import OnlySymbolicSearchContextResolver
from onlyalpha.research.search.symbolic.errors import OnlySymbolicSearchStoreError
from onlyalpha.research.search.symbolic.store import OnlyJsonSymbolicSearchStore
from onlyalpha.strategy.qualification_store import (
    OnlyQualificationDecisionStore,
    OnlyQualificationPolicyStore,
)


class OnlySearchAuthoringValue(Protocol):
    def to_dict(self) -> Mapping[str, object]: ...


class _SearchAuthoringInputReader:
    """Exact dispatch over existing Search-owned immutable stores."""

    def __init__(
        self,
        symbolic: OnlyJsonSymbolicSearchStore,
        parameter: OnlyJsonParameterSearchStore,
    ) -> None:
        self._symbolic = symbolic
        self._parameter = parameter

    def load_search_authoring_input_verified(self, reference_kind: str, fingerprint: str) -> OnlySearchAuthoringValue:
        if reference_kind == "SYMBOLIC_SEARCH_SPACE":
            return self._symbolic.load_search_space_intrinsic_verified(fingerprint)
        if reference_kind == "RESEARCH_EVALUATION":
            return self._symbolic.load_evaluation_contract_intrinsic_verified(fingerprint)
        if reference_kind == "PARAMETER_SEARCH_SPACE":
            return self._parameter.load_search_space_intrinsic_verified(fingerprint)
        if reference_kind == "SEARCH_POLICY":
            return self._parameter.load_policy_intrinsic_verified(fingerprint)
        if reference_kind == "SEARCH_ALGORITHM":
            values: list[OnlySearchAuthoringValue] = []
            try:
                values.append(self._symbolic.load_algorithm_implementation_manifest_intrinsic_verified(fingerprint))
            except OnlySymbolicSearchStoreError as error:
                if error.code != "SEARCH_ALGORITHM_MANIFEST_NOT_FOUND":
                    raise
            try:
                values.append(self._parameter.load_algorithm_manifest_intrinsic_verified(fingerprint))
            except OnlyParameterSearchStoreError as error:
                if error.code != "PARAMETER_ALGORITHM_MANIFEST_NOT_FOUND":
                    raise
            if len(values) != 1:
                raise LookupError("SEARCH_ALGORITHM_NOT_FOUND_OR_AMBIGUOUS")
            return values[0]
        raise LookupError(reference_kind)


class _GenerationOwnedCatalogReader:
    """Fail closed if a historical Search path attempts parent-runtime Catalog execution."""

    def generation(self, fingerprint: str) -> object:
        raise RuntimeError(f"SEARCH_CATALOG_IS_RUNTIME_GENERATION_OWNED:{fingerprint}")


class _SearchContextReader:
    """Dispatch shared provenance verification by the Experiment's exact schema."""

    def __init__(
        self,
        symbolic: OnlySymbolicSearchContextResolver,
        parameter: OnlyParameterSearchContextResolver,
    ) -> None:
        self._symbolic = symbolic
        self._parameter = parameter

    def _resolver(
        self, experiment: OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3
    ) -> OnlySymbolicSearchContextResolver | OnlyParameterSearchContextResolver:
        if isinstance(experiment, OnlySearchExperimentManifestV2):
            return self._symbolic
        if isinstance(experiment, OnlySearchExperimentManifestV3):
            return self._parameter
        raise TypeError("SEARCH_EXPERIMENT_SCHEMA_UNSUPPORTED")

    def __getattr__(self, name: str) -> object:
        if name.startswith("_"):
            raise AttributeError(name)

        def dispatch(
            experiment: OnlySearchExperimentManifestV2 | OnlySearchExperimentManifestV3,
            *args: object,
        ) -> object:
            method = getattr(self._resolver(experiment), name)
            return method(experiment, *args)

        return dispatch


def _compose_experiment_memory_projection_builder(
    *,
    layout: OnlyUserDataLayout,
    postgres_dsn: str,
    search: OnlyJsonSearchProvenanceStore,
    results: OnlyJsonResearchResultStore,
    statistics: OnlyParquetResearchStatisticsResultStore,
    factor_pair_statistics: OnlyParquetResearchFactorPairStatisticsResultStore,
    summary_statistics: OnlyJsonResearchSummaryStatisticsResultStore,
    qualification_decisions: OnlyQualificationDecisionStore,
    datasets: OnlyParquetResearchDatasetSnapshotStore,
    catalogs: OnlyRuntimeGenerationExactCatalogDescriptorReader,
    calculations: OnlyParquetResearchCalculationResultStore,
    runtime_generations: OnlyRuntimeGenerationRegistry,
    authoring_generations: OnlyVerifiedAuthoringGenerationReader,
) -> tuple[OnlyExperimentMemoryProductionBuilder, OnlyExperimentMemoryAdvisoryProjectionBuilder]:
    """Reference fixture fixes all eleven existing owners; no external callback enters."""
    postgres = OnlyPostgresResearchSourceCutAuthority(postgres_dsn)
    sources: dict[str, OnlyCapturableMemoryCutReader] = {
        "SEARCH_PROVENANCE": search,
        "AGENT_PROVENANCE": OnlyAgentProvenanceClosedCutAuthority(layout.research_root),
        "RESEARCH_RESULT": results,
        "RESEARCH_STATISTICS": statistics,
        "RESEARCH_FACTOR_PAIR_STATISTICS": factor_pair_statistics,
        "RESEARCH_SUMMARY_STATISTICS": summary_statistics,
        "QUALIFICATION_DECISION": qualification_decisions,
        **{
            family: postgres.for_family(family)
            for family in (
                "RESEARCH_RUN",
                "RESEARCH_ATTEMPT",
                "PRODUCT_COMMAND_ADMISSION",
                "PRODUCT_COMMAND_RECEIPT",
            )
        },
    }
    references = OnlyExperimentMemoryReferenceReadersV1(
        datasets,
        catalogs,
        OnlyJsonSymbolicSearchStore(layout.research_root),
        OnlyJsonParameterSearchStore(layout.research_root),
        calculations,
        runtime_generations,
        authoring_generations,
        OnlyQualificationPolicyStore(layout.research_root),
        OnlyBacktestEvidenceStore(layout.root),
    )
    revisions = OnlyExperimentMemoryRevisionStore(layout.experiment_memory_projection_root)
    return (
        OnlyExperimentMemoryProductionBuilder(sources, references, revisions),
        OnlyExperimentMemoryAdvisoryProjectionBuilder(revisions, sources, references, cast(Any, calculations)),
    )
