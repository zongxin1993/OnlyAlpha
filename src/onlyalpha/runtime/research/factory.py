"""Formal composition factory for the finite Research Runtime product."""

from __future__ import annotations

from onlyalpha.core.clock import only_system_utc_now
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.research.artifact.materializer import OnlyResearchArtifactMaterializer
from onlyalpha.research.artifact.scientific_materializer import OnlyResearchScientificArtifactMaterializer
from onlyalpha.research.artifact.scientific_store import OnlyParquetResearchScientificArtifactStore
from onlyalpha.research.artifact.store import OnlyParquetResearchArtifactStore
from onlyalpha.research.calculation.backend import OnlyResearchCalculationBackendResolver
from onlyalpha.research.calculation.execution import OnlyResearchCalculationExecutor
from onlyalpha.research.calculation.predicate import only_register_research_predicate_primitives
from onlyalpha.research.calculation.result_store import OnlyParquetResearchCalculationResultStore
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.evaluation.execution import OnlyResearchStatisticsExecutor
from onlyalpha.research.evaluation.result_store import OnlyParquetResearchStatisticsResultStore
from onlyalpha.research.job import OnlyResearchJobExecutor
from onlyalpha.research.result.assembler import OnlyResearchResultAssembler
from onlyalpha.research.result.result_store import OnlyJsonResearchResultStore
from onlyalpha.research.sweep.executor import OnlyResearchSweepExecutor
from onlyalpha.runtime.assembler import OnlyComponentFactoryRegistries
from onlyalpha.runtime.factory import OnlyRuntimeBuildRequest, OnlyRuntimeBuildResult

from .planning import OnlyResearchRuntimePlan
from .runtime import OnlyResearchRuntime


class OnlyResearchRuntimeFactory:
    @property
    def runtime_type(self) -> str:
        return "RESEARCH"

    def validate(self, request: OnlyRuntimeBuildRequest) -> OnlyRuntimeBuildResult:
        return self._validate(request)

    def create(self, request: OnlyRuntimeBuildRequest) -> OnlyRuntimeBuildResult:
        failure = self._validate(request)
        if failure.failure_code is not None:
            return failure
        assert isinstance(request.plan, OnlyResearchRuntimePlan)
        assert request.user_data_root is not None
        assert isinstance(request.components, OnlyComponentFactoryRegistries)
        layout = OnlyUserDataLayout(request.user_data_root)
        dataset = OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
        calculation_store = OnlyParquetResearchCalculationResultStore(
            layout.research_calculation_result_root,
            dataset,
            audit_time=only_system_utc_now,
        )
        only_register_research_predicate_primitives(request.components.calculations)
        calculation = OnlyResearchCalculationExecutor(
            dataset,
            OnlyResearchCalculationBackendResolver(request.components.calculations),
        )
        job = OnlyResearchJobExecutor(calculation, calculation_store)
        sweep = OnlyResearchSweepExecutor(job)
        statistics_store = OnlyParquetResearchStatisticsResultStore(
            layout.research_statistics_result_root,
            calculation_store,
            audit_time=only_system_utc_now,
        )
        statistics = OnlyResearchStatisticsExecutor(calculation_store, statistics_store)
        result_store = OnlyJsonResearchResultStore(layout.research_result_root, statistics_store, calculation_store)
        assembler = OnlyResearchResultAssembler(
            statistics_store,
            audit_time=only_system_utc_now,
            calculation_result_store=calculation_store,
        )
        artifact: OnlyParquetResearchArtifactStore | OnlyParquetResearchScientificArtifactStore
        materializer: OnlyResearchArtifactMaterializer | OnlyResearchScientificArtifactMaterializer
        if request.plan.workload.result_plan.schema_version == 2:
            artifact = OnlyParquetResearchScientificArtifactStore(
                layout.research_artifact_root, audit_time=only_system_utc_now
            )
            materializer = OnlyResearchScientificArtifactMaterializer(
                result_store, dataset, calculation_store, statistics_store
            )
        else:
            artifact = OnlyParquetResearchArtifactStore(layout.research_artifact_root, audit_time=only_system_utc_now)
            materializer = OnlyResearchArtifactMaterializer(result_store, statistics_store)
        runtime = OnlyResearchRuntime(
            OnlyRuntimeId(str(request.plan.runtime_id)),
            request.plan.environment,
            request.plan.workload,
            dataset,
            job,
            sweep,
            statistics,
            assembler,
            result_store,
            materializer,
            artifact,
        )
        return OnlyRuntimeBuildResult(runtime=runtime)

    @staticmethod
    def _validate(request: OnlyRuntimeBuildRequest) -> OnlyRuntimeBuildResult:
        if not isinstance(request.plan, OnlyResearchRuntimePlan):
            return OnlyRuntimeBuildResult(
                failure_code="RESEARCH_RUNTIME_PLAN_REQUIRED",
                failure_message="Research factory requires OnlyResearchRuntimePlan",
            )
        if not isinstance(request.components, OnlyComponentFactoryRegistries):
            return OnlyRuntimeBuildResult(
                failure_code="RESEARCH_RUNTIME_COMPONENTS_INVALID",
                failure_message="Research factory requires OnlyComponentFactoryRegistries",
            )
        if request.user_data_root is None:
            return OnlyRuntimeBuildResult(
                failure_code="RESEARCH_USER_DATA_ROOT_REQUIRED",
                failure_message="Research Runtime requires a stable user_data root",
            )
        return OnlyRuntimeBuildResult()


__all__ = ["OnlyResearchRuntimeFactory"]
