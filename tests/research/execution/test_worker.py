from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.output import OnlyUserDataLayout
from onlyalpha.research.dataset import OnlyParquetResearchDatasetSnapshotStore
from onlyalpha.research.execution import (
    OnlyEngineResearchRuntimeExecutor,
    OnlyResearchExecutionClaim,
    OnlyResearchExecutionOwnershipLostError,
    OnlyResearchExecutionPolicy,
    OnlyResearchExecutionStoreUnavailableError,
    OnlyResearchRetryDecision,
    OnlyResearchRunAttempt,
    OnlyResearchRunAttemptId,
    OnlyResearchRunAttemptState,
    OnlyResearchWorker,
    OnlyResearchWorkerInstanceId,
    OnlyResearchWorkerOutcomeKind,
    OnlyResearchWorkerService,
)
from onlyalpha.research.run import (
    OnlyResearchRun,
    OnlyResearchRunId,
    OnlyResearchRunState,
    only_research_admission_resolution_fingerprint,
)
from onlyalpha.research.run.errors import OnlyResearchRunStoreUnavailableError
from onlyalpha.research.specification import (
    OnlyResearchSpecificationError,
    OnlyResearchSpecificationPhase,
    OnlyResearchSpecificationResolver,
)
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.research import OnlyResearchRuntimePhase, OnlyResearchRuntimeResult
from onlyalpha.runtime.result import OnlyRuntimeResultStatus
from tests.research.specification.support import registry, specification
from tests.runtime.research.support import workload_case

NOW = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)
WORKER_ID = OnlyResearchWorkerInstanceId("00000000-0000-4000-8000-000000000201")
ATTEMPT_ID = OnlyResearchRunAttemptId("00000000-0000-4000-8000-000000000202")
RUN_ID = OnlyResearchRunId("00000000-0000-4000-8000-000000000203")


class _RunStore:
    def __init__(self, run: OnlyResearchRun) -> None:
        self.run = run

    def create_queued(self, run: OnlyResearchRun) -> OnlyResearchRun:
        self.run = run
        return run

    def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun:
        assert run_id == self.run.run_id
        return self.run

    def commit_transition(self, previous: OnlyResearchRun, transitioned: OnlyResearchRun) -> OnlyResearchRun:
        assert previous == self.run
        self.run = transitioned
        return transitioned


class _ExecutionStore:
    def __init__(self, run_store: _RunStore, claim: OnlyResearchExecutionClaim) -> None:
        self.run_store = run_store
        self.attempt = claim.attempt
        self.heartbeat_count = 0
        self.error_on: str | None = None

    def load_attempt(self, attempt_id: OnlyResearchRunAttemptId) -> OnlyResearchRunAttempt:
        assert attempt_id == self.attempt.attempt_id
        return self.attempt

    def heartbeat(self, **kwargs: object) -> OnlyResearchRunAttempt:
        if self.error_on == "heartbeat":
            raise OnlyResearchExecutionStoreUnavailableError("down")
        assert kwargs["attempt_id"] == self.attempt.attempt_id
        self.heartbeat_count += 1
        return self.attempt

    def complete(self, **kwargs: object) -> OnlyResearchRun:
        if self.error_on == "complete":
            raise OnlyResearchExecutionOwnershipLostError("stale")
        run = self.run_store.run
        completed = run.transition(
            OnlyResearchRunState.COMPLETED,
            at=kwargs["run_finished_at"],  # type: ignore[arg-type]
            research_result_fingerprint=kwargs["research_result_fingerprint"],  # type: ignore[arg-type]
            artifact_content_fingerprint=kwargs["artifact_content_fingerprint"],  # type: ignore[arg-type]
        )
        self.run_store.run = completed
        return completed

    def fail(self, **kwargs: object) -> OnlyResearchRun:
        if self.error_on == "fail":
            raise OnlyResearchExecutionOwnershipLostError("stale")
        run = self.run_store.run
        if kwargs["retry_decision"] is OnlyResearchRetryDecision.FINAL_FAIL:
            run = run.transition(
                OnlyResearchRunState.FAILED,
                at=kwargs["run_finished_at"],  # type: ignore[arg-type]
                failure=kwargs["failure"],  # type: ignore[arg-type]
            )
            self.run_store.run = run
        return run

    def cancel(self, **kwargs: object) -> OnlyResearchRun:
        if self.error_on == "cancel":
            raise OnlyResearchExecutionStoreUnavailableError("down")
        run = self.run_store.run.transition(
            OnlyResearchRunState.CANCELLED,
            at=kwargs["run_finished_at"],  # type: ignore[arg-type]
        )
        self.run_store.run = run
        return run

    def claim_next(self, **kwargs: object) -> None:
        return None

    def expire_next(self, **kwargs: object) -> None:
        return None

    def load_cancellation_recovery_candidate(self) -> None:
        return None

    def reconcile_cancellation(self, **kwargs: object) -> OnlyResearchRun:
        raise AssertionError(f"unexpected reconciliation: {kwargs}")


class _RuntimeExecutor:
    def __init__(self, result: OnlyResearchRuntimeResult | None = None, error: Exception | None = None) -> None:
        self.result = result or _runtime_result(OnlyRuntimeResultStatus.COMPLETED)
        self.error = error

    def execute(self, workload: object, control: object) -> OnlyResearchRuntimeResult:
        del workload
        if self.error is not None:
            raise self.error
        return self.result


class _BrokenDatasetStore:
    def load_verified_table(self, fingerprint: str) -> object:
        del fingerprint
        raise RuntimeError("corrupt")


def _runtime_result(
    status: OnlyRuntimeResultStatus,
    *,
    phase: OnlyResearchRuntimePhase | None = None,
    code: str | None = None,
) -> OnlyResearchRuntimeResult:
    return OnlyResearchRuntimeResult(
        OnlyRuntimeId("research-test"),
        status,
        "a" * 64,
        research_result_plan_fingerprint="d" * 64,
        research_result_fingerprint="b" * 64,
        artifact_content_fingerprint="c" * 64,
        calculation_execution_evidence_fingerprints=("e" * 64,),
        phase=phase,
        code=code,
        detail="detail" if phase is not None else None,
    )


def _case(
    tmp_path: Path,
    *,
    runtime_executor: object | None = None,
    dataset_store: object | None = None,
) -> tuple[OnlyResearchWorker, _RunStore, _ExecutionStore, OnlyResearchExecutionClaim]:
    _, workload = workload_case(tmp_path)
    services = only_default_engine_services() if runtime_executor is None else None
    calculations = services.assembler.components.calculations if services is not None else registry()
    resolver = OnlyResearchSpecificationResolver(calculations)
    spec = specification(workload.dataset_snapshot_fingerprint)
    resolution = resolver.resolve(spec)
    queued = OnlyResearchRun.queued(
        run_id=RUN_ID,
        specification=spec,
        canonical_specification_payload=only_canonical_json(spec.to_dict()),
        admission_resolution_fingerprint=only_research_admission_resolution_fingerprint(resolution),
        queued_at=NOW,
    )
    running = queued.transition(OnlyResearchRunState.RUNNING, at=NOW + timedelta(seconds=1))
    run_store = _RunStore(running)
    attempt = OnlyResearchRunAttempt(
        ATTEMPT_ID,
        RUN_ID,
        1,
        OnlyResearchRunAttemptState.ACTIVE,
        WORKER_ID,
        NOW,
        NOW,
        NOW + timedelta(minutes=2),
    )
    claim = OnlyResearchExecutionClaim(attempt)
    execution_store = _ExecutionStore(run_store, claim)
    layout = OnlyUserDataLayout(tmp_path)
    worker = OnlyResearchWorker(
        worker_instance_id=WORKER_ID,
        execution_store=execution_store,  # type: ignore[arg-type]
        run_store=run_store,
        resolver=resolver,
        dataset_store=(
            dataset_store
            if dataset_store is not None
            else OnlyParquetResearchDatasetSnapshotStore(layout.research_dataset_root)
        ),  # type: ignore[arg-type]
        runtime_executor=(
            runtime_executor if runtime_executor is not None else OnlyEngineResearchRuntimeExecutor(tmp_path, services)
        ),  # type: ignore[arg-type]
        policy=OnlyResearchExecutionPolicy(
            lease_duration=timedelta(seconds=1), heartbeat_interval=timedelta(milliseconds=10)
        ),
        now_utc=lambda: NOW + timedelta(minutes=1),
    )
    return worker, run_store, execution_store, claim


def test_worker_reverifies_and_enters_real_engine_runtime_to_complete(tmp_path: Path) -> None:
    worker, run_store, execution_store, claim = _case(tmp_path)
    outcome = worker.execute_claim(claim)
    assert outcome.kind is OnlyResearchWorkerOutcomeKind.COMPLETED
    assert run_store.run.state is OnlyResearchRunState.COMPLETED
    assert run_store.run.research_result_fingerprint is not None
    assert run_store.run.artifact_content_fingerprint is not None
    assert execution_store.heartbeat_count >= 2


def test_runtime_executor_reuses_services_but_creates_a_fresh_engine_per_claim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    services = only_default_engine_services()
    engines: list[object] = []
    service_identities: list[object] = []

    class _RecordingEngine:
        def __init__(self, config: object, storage: object = None, *, services: object = None) -> None:
            del config, storage
            engines.append(self)
            service_identities.append(services)

        def add_research_workload(self, workload: object) -> OnlyRuntimeId:
            del workload
            return OnlyRuntimeId(f"research-{len(engines)}")

        def initialize(self) -> None:
            return None

        def start(self) -> None:
            return None

        def run_runtime(self, runtime_id: OnlyRuntimeId, *, research_control: object) -> OnlyResearchRuntimeResult:
            del runtime_id, research_control
            return _runtime_result(OnlyRuntimeResultStatus.COMPLETED)

        def close(self) -> None:
            return None

    monkeypatch.setattr("onlyalpha.research.execution.worker.OnlyEngine", _RecordingEngine)
    executor = OnlyEngineResearchRuntimeExecutor(tmp_path, services)
    _, workload = workload_case(tmp_path)

    executor.execute(workload, object())  # type: ignore[arg-type]
    executor.execute(workload, object())  # type: ignore[arg-type]

    assert len(engines) == 2 and engines[0] is not engines[1]
    assert service_identities == [services, services]


def test_worker_cooperatively_cancels_at_safe_boundary(tmp_path: Path) -> None:
    worker, run_store, _, claim = _case(tmp_path)
    run_store.run = run_store.run.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2))
    outcome = worker.execute_claim(claim)
    assert outcome.kind is OnlyResearchWorkerOutcomeKind.CANCELLED
    assert run_store.run.state is OnlyResearchRunState.CANCELLED


def test_worker_rejects_claim_owned_by_another_instance(tmp_path: Path) -> None:
    worker, _, _, claim = _case(tmp_path, runtime_executor=_RuntimeExecutor())
    foreign = OnlyResearchExecutionClaim(
        replace(
            claim.attempt,
            worker_instance_id=OnlyResearchWorkerInstanceId("00000000-0000-4000-8000-000000000299"),
        )
    )
    with pytest.raises(OnlyResearchExecutionOwnershipLostError, match="different Worker"):
        worker.execute_claim(foreign)


def test_dataset_corruption_and_semantic_drift_fail_without_retry(tmp_path: Path) -> None:
    worker, run_store, _, claim = _case(
        tmp_path, runtime_executor=_RuntimeExecutor(), dataset_store=_BrokenDatasetStore()
    )
    outcome = worker.execute_claim(claim)
    assert outcome.kind is OnlyResearchWorkerOutcomeKind.FAILED
    assert outcome.failure is not None and outcome.failure.code == "DATASET_VERIFICATION_FAILED"
    assert run_store.run.state is OnlyResearchRunState.FAILED

    worker, run_store, _, claim = _case(tmp_path / "drift", runtime_executor=_RuntimeExecutor())
    run_store.run = replace(run_store.run, admission_resolution_fingerprint="f" * 64)
    outcome = worker.execute_claim(claim)
    assert outcome.kind is OnlyResearchWorkerOutcomeKind.FAILED
    assert outcome.failure is not None and outcome.failure.code == "EXECUTION_SEMANTIC_DRIFT"


def test_execution_time_specification_resolution_failure_is_deterministic_final_failure(tmp_path: Path) -> None:
    worker, run_store, _, claim = _case(tmp_path, runtime_executor=_RuntimeExecutor())

    class _ResolverFailure:
        def resolve(self, specification: object) -> None:
            del specification
            raise OnlyResearchSpecificationError(
                OnlyResearchSpecificationPhase.TYPE_RESOLUTION,
                "RESEARCH_SPEC_CALCULATION_TYPE_UNKNOWN",
                "deployment-specific detail must not enter durable failure",
            )

    worker._resolver = _ResolverFailure()  # type: ignore[assignment]
    outcome = worker.execute_claim(claim)

    assert outcome.kind is OnlyResearchWorkerOutcomeKind.FAILED
    assert run_store.run.state is OnlyResearchRunState.FAILED
    assert outcome.failure is not None
    assert outcome.failure.code == "EXECUTION_SEMANTIC_DRIFT"
    assert outcome.failure.detail == (
        "Specification re-resolution failed: TYPE_RESOLUTION:RESEARCH_SPEC_CALCULATION_TYPE_UNKNOWN"
    )


def test_run_store_unavailability_keeps_stable_transient_failure_code(tmp_path: Path) -> None:
    worker, run_store, _, claim = _case(tmp_path, runtime_executor=_RuntimeExecutor())

    class _UnavailableRunStore:
        def load(self, run_id: OnlyResearchRunId) -> OnlyResearchRun:
            del run_id
            raise OnlyResearchRunStoreUnavailableError("secret infrastructure detail")

    worker._run_store = _UnavailableRunStore()  # type: ignore[assignment]
    outcome = worker.execute_claim(claim)

    assert outcome.kind is OnlyResearchWorkerOutcomeKind.RETRY_PENDING
    assert run_store.run.state is OnlyResearchRunState.RUNNING
    assert outcome.failure is not None
    assert outcome.failure.code == "RESEARCH_RUN_STORE_UNAVAILABLE"
    assert "secret infrastructure detail" not in outcome.failure.detail


@pytest.mark.parametrize(
    ("phase", "expected_phase"),
    (
        (OnlyResearchRuntimePhase.JOB_EXECUTION, "EXECUTION"),
        (OnlyResearchRuntimePhase.RESULT_COMMIT, "RESULT_COMMIT"),
        (OnlyResearchRuntimePhase.ARTIFACT_COMMIT, "ARTIFACT_COMMIT"),
    ),
)
def test_runtime_failure_maps_to_stable_run_failure_phase(
    tmp_path: Path, phase: OnlyResearchRuntimePhase, expected_phase: str
) -> None:
    executor = _RuntimeExecutor(_runtime_result(OnlyRuntimeResultStatus.FAILED, phase=phase, code="RUNTIME_FAILED"))
    worker, _, _, claim = _case(tmp_path, runtime_executor=executor)
    outcome = worker.execute_claim(claim)
    assert outcome.kind is OnlyResearchWorkerOutcomeKind.FAILED
    assert outcome.failure is not None and outcome.failure.phase.value == expected_phase


def test_unexpected_failure_retries_and_fenced_failure_cannot_mutate_run(tmp_path: Path) -> None:
    worker, run_store, _, claim = _case(tmp_path, runtime_executor=_RuntimeExecutor(error=RuntimeError("boom")))
    outcome = worker.execute_claim(claim)
    assert outcome.kind is OnlyResearchWorkerOutcomeKind.RETRY_PENDING
    assert run_store.run.state is OnlyResearchRunState.RUNNING

    worker, _, execution_store, claim = _case(
        tmp_path / "fenced", runtime_executor=_RuntimeExecutor(error=RuntimeError("boom"))
    )
    execution_store.error_on = "fail"
    assert worker.execute_claim(claim).kind is OnlyResearchWorkerOutcomeKind.OWNERSHIP_LOST


def test_heartbeat_completion_and_cancellation_uncertainty_never_finalize(tmp_path: Path) -> None:
    worker, _, execution_store, claim = _case(tmp_path, runtime_executor=_RuntimeExecutor())
    execution_store.error_on = "heartbeat"
    assert worker.execute_claim(claim).kind is OnlyResearchWorkerOutcomeKind.OWNERSHIP_LOST

    worker, _, execution_store, claim = _case(tmp_path / "complete", runtime_executor=_RuntimeExecutor())
    execution_store.error_on = "complete"
    assert worker.execute_claim(claim).kind is OnlyResearchWorkerOutcomeKind.OWNERSHIP_LOST

    worker, run_store, execution_store, claim = _case(tmp_path / "cancel", runtime_executor=_RuntimeExecutor())
    run_store.run = run_store.run.transition(OnlyResearchRunState.CANCEL_REQUESTED, at=NOW + timedelta(seconds=2))
    execution_store.error_on = "cancel"
    assert worker.execute_claim(claim).kind is OnlyResearchWorkerOutcomeKind.OWNERSHIP_LOST


class _Scheduler:
    def __init__(self, claim: OnlyResearchExecutionClaim | None) -> None:
        self.claim = claim
        self.expired = 0
        self.claimed = 0
        self.before_claim: object | None = None

    def expire_once(self) -> None:
        self.expired += 1

    def claim_once(self, worker_id: OnlyResearchWorkerInstanceId) -> OnlyResearchExecutionClaim | None:
        assert worker_id == WORKER_ID
        self.claimed += 1
        if callable(self.before_claim):
            self.before_claim()
        return self.claim


class _ServiceWorker:
    worker_instance_id = WORKER_ID

    def execute_claim(self, claim: OnlyResearchExecutionClaim):
        return OnlyResearchWorkerOutcomeKind.COMPLETED, claim


class _Reconciler:
    def __init__(self, after_reconcile: object | None = None) -> None:
        self.calls = 0
        self.after_reconcile = after_reconcile

    def reconcile_once(self) -> None:
        self.calls += 1
        if callable(self.after_reconcile):
            self.after_reconcile()


class _Presence:
    def __init__(self) -> None:
        self.started = 0
        self.draining_count = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def draining(self) -> None:
        self.draining_count += 1

    def stop(self) -> None:
        self.stopped += 1


def test_worker_service_has_finite_entry_and_shutdown_stops_new_claims(tmp_path: Path) -> None:
    _, _, _, claim = _case(tmp_path, runtime_executor=_RuntimeExecutor())
    scheduler = _Scheduler(claim)
    reconciler = _Reconciler()
    service = OnlyResearchWorkerService(
        scheduler=scheduler,  # type: ignore[arg-type]
        worker=_ServiceWorker(),  # type: ignore[arg-type]
        cancellation_reconciler=reconciler,  # type: ignore[arg-type]
        polling_interval=timedelta(milliseconds=1),
    )
    assert service.run_once() == (OnlyResearchWorkerOutcomeKind.COMPLETED, claim)
    assert scheduler.expired == 1
    assert reconciler.calls == 1
    service.stop()
    assert service.run_once() is None
    service.run_forever()
    with pytest.raises(ValueError, match="positive"):
        OnlyResearchWorkerService(
            scheduler=scheduler,  # type: ignore[arg-type]
            worker=_ServiceWorker(),  # type: ignore[arg-type]
            cancellation_reconciler=reconciler,  # type: ignore[arg-type]
            polling_interval=timedelta(0),
        )


def test_external_stop_observed_after_housekeeping_is_a_claim_barrier(tmp_path: Path) -> None:
    _, _, _, claim = _case(tmp_path, runtime_executor=_RuntimeExecutor())
    stopped = False

    def request_stop() -> None:
        nonlocal stopped
        stopped = True

    scheduler = _Scheduler(claim)
    presence = _Presence()
    service = OnlyResearchWorkerService(
        scheduler=scheduler,  # type: ignore[arg-type]
        worker=_ServiceWorker(),  # type: ignore[arg-type]
        cancellation_reconciler=_Reconciler(request_stop),  # type: ignore[arg-type]
        presence_reporter=presence,
    )

    assert service.run_once(stop_requested=lambda: stopped) is None
    assert scheduler.expired == 1
    assert scheduler.claimed == 0
    assert presence.draining_count == 1


def test_service_stop_observed_after_housekeeping_is_a_claim_barrier_and_idempotent(tmp_path: Path) -> None:
    _, _, _, claim = _case(tmp_path, runtime_executor=_RuntimeExecutor())
    scheduler = _Scheduler(claim)
    presence = _Presence()
    service: OnlyResearchWorkerService

    def stop_service() -> None:
        service.stop()
        service.stop()

    service = OnlyResearchWorkerService(
        scheduler=scheduler,  # type: ignore[arg-type]
        worker=_ServiceWorker(),  # type: ignore[arg-type]
        cancellation_reconciler=_Reconciler(stop_service),  # type: ignore[arg-type]
        presence_reporter=presence,
    )

    assert service.run_once() is None
    assert scheduler.expired == 1
    assert scheduler.claimed == 0
    assert presence.draining_count == 1


def test_stop_after_claim_transaction_begins_drains_current_claim_and_blocks_next(tmp_path: Path) -> None:
    _, _, _, claim = _case(tmp_path, runtime_executor=_RuntimeExecutor())
    stopped = False

    def request_stop() -> None:
        nonlocal stopped
        stopped = True

    scheduler = _Scheduler(claim)
    scheduler.before_claim = request_stop
    service = OnlyResearchWorkerService(
        scheduler=scheduler,  # type: ignore[arg-type]
        worker=_ServiceWorker(),  # type: ignore[arg-type]
        cancellation_reconciler=_Reconciler(),  # type: ignore[arg-type]
    )

    assert service.run_once(stop_requested=lambda: stopped) == (OnlyResearchWorkerOutcomeKind.COMPLETED, claim)
    assert scheduler.claimed == 1
    assert service.run_once(stop_requested=lambda: stopped) is None
    assert scheduler.claimed == 1
