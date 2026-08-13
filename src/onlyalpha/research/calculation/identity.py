"""Research Calculation semantic identity."""

from __future__ import annotations

from onlyalpha.calculation import OnlyCalculationBackendKind
from onlyalpha.canonical import only_canonical_fingerprint

RESEARCH_CALCULATION_IDENTITY_SCHEMA_VERSION = 1


def only_research_calculation_fingerprint(dataset_snapshot_fingerprint: str, graph_fingerprint: str) -> str:
    return only_canonical_fingerprint(
        {
            "schema_version": RESEARCH_CALCULATION_IDENTITY_SCHEMA_VERSION,
            "dataset_snapshot_fingerprint": dataset_snapshot_fingerprint,
            "calculation_graph_fingerprint": graph_fingerprint,
            "backend": OnlyCalculationBackendKind.RESEARCH.value,
        }
    )
