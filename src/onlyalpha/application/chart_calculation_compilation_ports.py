"""Compile-only chart authority seams; no preparation mutation or Run admission."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from onlyalpha.application.chart_calculation import OnlyChartCalculationOperationV1
from onlyalpha.application.chart_calculation_preparation import OnlyChartCalculationPreparationV1
from onlyalpha.research.run.calculation_resolution import OnlyResearchCalculationRuntimeResolutionV1
from onlyalpha.research.specification.model import OnlyResearchSpecification

if TYPE_CHECKING:
    from .chart_calculation_compilation import OnlyChartCalculationCompilationV1


class OnlyChartCalculationPreparationReader(Protocol):
    def load_verified(self, operation: OnlyChartCalculationOperationV1) -> OnlyChartCalculationPreparationV1 | None: ...


class OnlyChartCalculationPublicationResolver(Protocol):
    """The implementation must prove hosted provenance in the exact requested generation."""

    def resolve_calculation_publication(
        self, runtime_generation_fingerprint: str, specification: OnlyResearchSpecification
    ) -> OnlyResearchCalculationRuntimeResolutionV1: ...


class OnlyChartCalculationCompilationStore(Protocol):
    def load_verified(self, operation: OnlyChartCalculationOperationV1) -> OnlyChartCalculationCompilationV1 | None: ...

    def commit_or_replay(
        self,
        operation: OnlyChartCalculationOperationV1,
        preparation: OnlyChartCalculationPreparationV1,
        compilation: OnlyChartCalculationCompilationV1,
    ) -> OnlyChartCalculationCompilationV1: ...
