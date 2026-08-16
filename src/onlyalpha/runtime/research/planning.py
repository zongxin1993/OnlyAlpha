"""Engine-build plan for one finite Research Runtime product."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.domain.identifiers import OnlyRuntimeId

from .environment import OnlyResearchRuntimeEnvironmentIdentity
from .plan import OnlyResearchWorkloadPlan


@dataclass(frozen=True, slots=True)
class OnlyResearchRuntimePlan:
    runtime_id: OnlyRuntimeId
    environment: OnlyResearchRuntimeEnvironmentIdentity
    workload: OnlyResearchWorkloadPlan


def only_research_runtime_plan(workload: OnlyResearchWorkloadPlan) -> OnlyResearchRuntimePlan:
    environment = OnlyResearchRuntimeEnvironmentIdentity.from_workload(workload)
    runtime_id = OnlyRuntimeId(f"research-{environment.fingerprint[:16]}")
    return OnlyResearchRuntimePlan(runtime_id, environment, workload)


__all__ = ["OnlyResearchRuntimePlan", "only_research_runtime_plan"]
