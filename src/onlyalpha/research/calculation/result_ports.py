"""Immutable Research Calculation Result Store contract."""

from __future__ import annotations

from typing import Protocol

from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition

from .execution import OnlyResearchCalculationExecution
from .result import OnlyResearchCalculationResult, OnlyResearchCalculationResultVerification


class OnlyResearchCalculationResultStore(Protocol):
    def commit(
        self,
        execution: OnlyResearchCalculationExecution,
        graph: OnlyCalculationGraphDefinition,
    ) -> OnlyResearchCalculationResult: ...

    def load_verified(self, calculation_fingerprint: str) -> OnlyResearchCalculationResult: ...

    def verify(self, calculation_fingerprint: str) -> OnlyResearchCalculationResultVerification: ...

    def exists(self, calculation_fingerprint: str) -> bool: ...
