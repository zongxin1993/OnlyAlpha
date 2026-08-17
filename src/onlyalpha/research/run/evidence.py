"""Canonical operational evidence for deterministic admission re-resolution."""

from __future__ import annotations

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolution


def only_research_admission_resolution_fingerprint(resolution: OnlyResearchSpecificationResolution) -> str:
    if not isinstance(resolution, OnlyResearchSpecificationResolution):
        raise TypeError("admission evidence requires a Specification Resolution")
    return only_canonical_fingerprint(
        {
            "schema_version": 1,
            "specification_fingerprint": resolution.specification_fingerprint,
            "candidates": [
                {
                    "calculation_id": item.calculation_id,
                    "assignment": item.assignment,
                    "graph_fingerprint": item.graph_fingerprint,
                    "calculation_fingerprint": item.calculation_fingerprint,
                    "node_fingerprints": item.node_fingerprints,
                }
                for item in resolution.candidates
            ],
            "statistics_fingerprints": [item.statistics_fingerprint for item in resolution.statistics],
            "research_result_plan_fingerprint": resolution.workload.result_plan.fingerprint,
        }
    )


__all__ = ["only_research_admission_resolution_fingerprint"]
