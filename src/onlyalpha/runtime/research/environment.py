"""Operational identity for finite Research Runtime grouping and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.canonical import only_canonical_fingerprint

from .plan import OnlyResearchWorkloadPlan


@dataclass(frozen=True, slots=True)
class OnlyResearchRuntimeEnvironmentIdentity:
    dataset_snapshot_fingerprint: str
    calculation_fingerprints: tuple[str, ...]
    statistics_fingerprints: tuple[str, ...]
    research_result_plan_fingerprint: str
    artifact_profile: str
    runtime_type: str = "RESEARCH"

    @classmethod
    def from_workload(cls, workload: OnlyResearchWorkloadPlan) -> OnlyResearchRuntimeEnvironmentIdentity:
        return cls(
            workload.dataset_snapshot_fingerprint,
            tuple(sorted(item.calculation_fingerprint for item in workload.calculation_jobs)),
            tuple(sorted(item.statistics_fingerprint for item in workload.statistics_plans)),
            workload.result_plan.fingerprint,
            "RESEARCH_STATISTICS_V1",
        )

    @property
    def fingerprint(self) -> str:
        return only_canonical_fingerprint(self)


__all__ = ["OnlyResearchRuntimeEnvironmentIdentity"]
