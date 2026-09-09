"""Run the production ResearchWorker and Engine inside an exact fixture runtime."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry
from onlyalpha_runtime_generation_manager.search_worker import _calculation_registry

from onlyalpha.canonical import only_canonical_json
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.quant_assets import only_discover_quant_asset_providers
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.execution.model import (
    OnlyResearchExecutionClaim,
    OnlyResearchRunAttempt,
    OnlyResearchRunAttemptId,
    OnlyResearchRunAttemptState,
    OnlyResearchWorkerInstanceId,
)
from onlyalpha.research.execution.policy import OnlyResearchExecutionPolicy
from onlyalpha.research.execution.worker import OnlyEngineResearchRuntimeExecutor, OnlyResearchWorker
from onlyalpha.research.run.evidence import only_research_admission_resolution_fingerprint
from onlyalpha.research.run.model import OnlyResearchRun, OnlyResearchRunId, OnlyResearchRunState
from onlyalpha.research.specification.model import OnlyResearchSpecification
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from onlyalpha.runtime.defaults import only_default_engine_services


class _AttemptAuthority:
    """Test-owned lease/Run authority; all executable work remains production."""

    def __init__(self, run: OnlyResearchRun, claim: OnlyResearchExecutionClaim) -> None:
        self.run = run
        self.claim = claim

    def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun:
        assert run_id == self.run.run_id
        return self.run

    def heartbeat(self, **kwargs: Any) -> OnlyResearchRunAttempt:
        assert kwargs["attempt_id"] == self.claim.attempt.attempt_id
        return self.claim.attempt

    def complete(self, **kwargs: Any) -> OnlyResearchRun:
        self.run = self.run.transition(
            OnlyResearchRunState.COMPLETED,
            at=kwargs["run_finished_at"],
            research_result_fingerprint=kwargs["research_result_fingerprint"],
            artifact_content_fingerprint=kwargs["artifact_content_fingerprint"],
        )
        return self.run

    def fail(self, **kwargs: Any) -> OnlyResearchRun:
        self.run = self.run.transition(
            OnlyResearchRunState.FAILED, at=kwargs["run_finished_at"], failure=kwargs["failure"]
        )
        return self.run


def main() -> None:
    value = json.loads(Path(sys.argv[1]).read_text())
    root = Path(value["root"])
    generation = value["generation"]
    registry = OnlyRuntimeGenerationRegistry(Path(value["authority_root"]))
    registry.verify_hosted_generation(generation)
    now = datetime(2026, 9, 10, tzinfo=UTC)
    specification = OnlyResearchSpecification.from_dict(value["specification"])
    run = OnlyResearchRun.queued(
        run_id=OnlyResearchRunId(value["run_id"]),
        specification=specification,
        canonical_specification_payload=only_canonical_json(specification.to_dict()),
        admission_resolution_fingerprint=value["admission_fingerprint"],
        queued_at=now,
    ).transition(OnlyResearchRunState.RUNNING, at=now + timedelta(seconds=1))
    worker_id = OnlyResearchWorkerInstanceId("00000000-0000-4000-8000-000000000201")
    attempt = OnlyResearchRunAttempt(
        OnlyResearchRunAttemptId("00000000-0000-4000-8000-000000000202"),
        run.run_id,
        1,
        OnlyResearchRunAttemptState.ACTIVE,
        worker_id,
        now,
        now,
        now + timedelta(minutes=2),
    )
    claim = OnlyResearchExecutionClaim(attempt)
    authority = _AttemptAuthority(run, claim)
    resolver = OnlyResearchSpecificationResolver(
        _calculation_registry(only_discover_quant_asset_providers().calculation_registry())
    )
    actual_resolver = resolver
    evidence = []

    class _ResolutionFault:
        def resolve(self, specification: Any) -> Any:
            resolution = actual_resolver.resolve(specification)
            if value.get("resolver_drift"):
                first = resolution.candidates[0]
                changed = replace(first, calculation_fingerprint="0" * 64)
                resolution = replace(resolution, candidates=(changed, *resolution.candidates[1:]))
            evidence.append(only_research_admission_resolution_fingerprint(resolution))
            return resolution

    executor = OnlyEngineResearchRuntimeExecutor(root, only_default_engine_services())
    executed = []

    class _ObserveExecution:
        def execute(self, workload: Any, control: Any) -> Any:
            executed.append(workload)
            return executor.execute(workload, control)

    worker = OnlyResearchWorker(
        worker_instance_id=worker_id,
        execution_store=cast(Any, authority),
        run_store=cast(Any, authority),
        resolver=cast(Any, _ResolutionFault()),
        dataset_store=OnlyParquetResearchDatasetSnapshotStore(OnlyUserDataLayout(root).research_dataset_root),
        runtime_executor=_ObserveExecution(),
        policy=OnlyResearchExecutionPolicy(
            lease_duration=timedelta(seconds=30), heartbeat_interval=timedelta(seconds=10)
        ),
        now_utc=lambda: now + timedelta(seconds=2),
        runtime_generations=registry,
        process_generation_fingerprint=generation,
    )
    outcome = worker.execute_claim(claim)
    print(
        json.dumps(
            {
                "kind": outcome.kind.value,
                "failure": None if outcome.failure is None else outcome.failure.code,
                "result": None if outcome.run is None else outcome.run.research_result_fingerprint,
                "resolution_fingerprint": evidence[0],
                "execution_calls": len(executed),
            }
        )
    )


if __name__ == "__main__":
    main()
