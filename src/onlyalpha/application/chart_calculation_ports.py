"""Business-shaped T1 admission persistence port; no Run scheduler capability."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .chart_calculation import (
    OnlyChartCalculationAdmissionOutcome,
    OnlyChartCalculationCatalogWitnessV1,
    OnlyChartCalculationOperationV1,
    OnlyChartCalculationRequestV1,
)
from .product_command_receipt import OnlyProductCommandId


class OnlyChartCalculationAdmissionStore(Protocol):
    def load_verified(self, command_id: OnlyProductCommandId) -> OnlyChartCalculationOperationV1 | None: ...

    def admit_or_replay(
        self,
        command_id: OnlyProductCommandId,
        request: OnlyChartCalculationRequestV1,
        witness: OnlyChartCalculationCatalogWitnessV1,
        *,
        accepted_at: datetime,
    ) -> OnlyChartCalculationAdmissionOutcome: ...
