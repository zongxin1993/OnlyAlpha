"""Canonical operational evidence for deterministic admission re-resolution."""

from __future__ import annotations

from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolution


def only_research_admission_resolution_fingerprint(resolution: OnlyResearchSpecificationResolution) -> str:
    if not isinstance(resolution, OnlyResearchSpecificationResolution):
        raise TypeError("admission evidence requires a Specification Resolution")
    scientific = resolution.workload.result_plan.schema_version == 2
    candidates: list[dict[str, object]] = [
        {
            "calculation_id": item.calculation_id,
            "assignment": item.assignment,
            "graph_fingerprint": item.graph_fingerprint,
            "calculation_fingerprint": item.calculation_fingerprint,
            "node_fingerprints": item.node_fingerprints,
            **({"candidate_fingerprint": item.candidate_fingerprint} if scientific else {}),
        }
        for item in resolution.candidates
    ]
    payload: dict[str, object] = {
        "schema_version": 2 if scientific else 1,
        "specification_fingerprint": resolution.specification_fingerprint,
        "candidates": candidates,
        "statistics_fingerprints": [item.statistics_fingerprint for item in resolution.statistics],
        "research_result_plan_fingerprint": resolution.workload.result_plan.fingerprint,
    }
    if scientific:
        payload["published_series"] = resolution.published_series
        payload["signals"] = resolution.signals
    return only_canonical_fingerprint(payload)


__all__ = ["only_research_admission_resolution_fingerprint"]
