"""Explicit V2 immutable Result authority port; no V1 fallback."""

from __future__ import annotations

from typing import Protocol

from onlyalpha.calculation.graph import OnlyCalculationGraphDefinition

from .execution import _OnlyVerifiedResearchCalculationExecutionV2
from .result_v2 import OnlyResearchCalculationResultV2, OnlyResearchCalculationResultVerificationV2


class OnlyResearchCalculationResultStoreV2(Protocol):
    def exists(self, calculation_fingerprint: str) -> bool: ...

    def commit(
        self, verified_execution: _OnlyVerifiedResearchCalculationExecutionV2, graph: OnlyCalculationGraphDefinition
    ) -> OnlyResearchCalculationResultV2: ...

    def load_verified(self, calculation_fingerprint: str) -> OnlyResearchCalculationResultV2: ...

    def acknowledge_exact(
        self, calculation_fingerprint: str, result_fingerprint: str
    ) -> OnlyResearchCalculationResultV2: ...

    def verify(self, calculation_fingerprint: str) -> OnlyResearchCalculationResultVerificationV2: ...
