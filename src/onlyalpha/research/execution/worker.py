"""Fenced Worker orchestration through the existing Engine/Research Runtime path."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from threading import Event, Thread
from typing import Protocol, cast

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.research.dataset import OnlyResearchDatasetSnapshotStore
from onlyalpha.research.operations.logging import only_log_research_operational_event
from onlyalpha.research.run.errors import OnlyResearchRunStoreUnavailableError
from onlyalpha.research.run.evidence import only_research_admission_resolution_fingerprint
from onlyalpha.research.run.model import (
    OnlyResearchRun,
    OnlyResearchRunFailure,
    OnlyResearchRunFailurePhase,
    OnlyResearchRunState,
)
from onlyalpha.research.run.store import OnlyResearchRunStore
from onlyalpha.research.specification.errors import OnlyResearchSpecificationError
from onlyalpha.research.specification.resolver import OnlyResearchSpecificationResolver
from onlyalpha.research.workload import OnlyResearchWorkloadPlan
from onlyalpha.runtime.defaults import OnlyEngineServices
from onlyalpha.runtime.research import (
    OnlyResearchRuntimeBoundary,
    OnlyResearchRuntimeCancellationRequested,
    OnlyResearchRuntimeExecutionControl,
    OnlyResearchRuntimeOwnershipLost,
    OnlyResearchRuntimeResult,
)
from onlyalpha.runtime.result import OnlyRuntimeResultStatus

from .errors import (
    OnlyResearchExecutionOwnershipLostError,
    OnlyResearchExecutionStoreUnavailableError,
)
from .model import OnlyResearchExecutionClaim, OnlyResearchWorkerInstanceId
from .policy import OnlyResearchExecutionPolicy
from .reconciliation import OnlyResearchCancellationRecoveryReconciler
from .scheduler import OnlyResearchScheduler
from .store import OnlyResearchExecutionStore

_LOG = logging.getLogger(__name__)


class OnlyResearchWorkerOutcomeKind(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRY_PENDING = "RETRY_PENDING"
    CANCELLED = "CANCELLED"
    OWNERSHIP_LOST = "OWNERSHIP_LOST"


@dataclass(frozen=True, slots=True)
class OnlyResearchWorkerOutcome:
    kind: OnlyResearchWorkerOutcomeKind
    claim: OnlyResearchExecutionClaim
    run: OnlyResearchRun | None = None
    failure: OnlyResearchRunFailure | None = None


class OnlyResearchRuntimeExecutor(Protocol):
    def execute(
        self,
        workload: OnlyResearchWorkloadPlan,
        control: OnlyResearchRuntimeExecutionControl,
    ) -> OnlyResearchRuntimeResult: ...


class _PresenceReporter(Protocol):
    def start(self) -> None: ...

    def draining(self) -> None: ...

    def stop(self) -> None: ...


class OnlyEngineResearchRuntimeExecutor:
    """Minimal composition adapter; execution still enters only through OnlyEngine."""

    def __init__(self, user_data_root: Path, services: OnlyEngineServices) -> None:
        self._user_data_root = user_data_root
        self._services = services

    def execute(
        self,
        workload: OnlyResearchWorkloadPlan,
        control: OnlyResearchRuntimeExecutionControl,
    ) -> OnlyResearchRuntimeResult:
        engine = OnlyEngine(
            OnlyEngineConfig(OnlyEngineId("research-worker"), self._user_data_root),
            services=self._services,
        )
        runtime_id = engine.add_research_workload(workload)
        try:
            engine.initialize()
            engine.start()
            return cast(
                OnlyResearchRuntimeResult,
                engine.run_runtime(runtime_id, research_control=control),
            )
        finally:
            engine.close()


class _LeaseControl:
    def __init__(
        self,
        *,
        claim: OnlyResearchExecutionClaim,
        store: OnlyResearchExecutionStore,
        run_store: OnlyResearchRunStore,
        policy: OnlyResearchExecutionPolicy,
    ) -> None:
        self._claim = claim
        self._store = store
        self._run_store = run_store
        self._policy = policy
        self._stop = Event()
        self._lost: BaseException | None = None
        self._thread = Thread(target=self._heartbeat_loop, name=f"research-heartbeat-{claim.attempt.attempt_id}")

    def start(self) -> None:
        self._renew()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.ident is not None:
            self._thread.join(timeout=self._policy.heartbeat_interval.total_seconds() + 1.0)
            if self._thread.is_alive():
                raise RuntimeError("Research heartbeat thread did not stop within its bounded deadline")

    def checkpoint(self, boundary: OnlyResearchRuntimeBoundary) -> None:
        del boundary
        self._raise_if_lost()
        self._renew()
        run = self._run_store.load(self._claim.attempt.run_id)
        if run.state is OnlyResearchRunState.CANCEL_REQUESTED:
            raise OnlyResearchRuntimeCancellationRequested(str(run.run_id))
        if run.state is not OnlyResearchRunState.RUNNING:
            raise OnlyResearchRuntimeOwnershipLost(f"Run is no longer executable: {run.state}")

    def assert_authoritative(self) -> None:
        self._raise_if_lost()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._policy.heartbeat_interval.total_seconds()):
            try:
                self._renew()
            except BaseException as exc:
                self._lost = exc
                return

    def _renew(self) -> None:
        try:
            self._store.heartbeat(
                attempt_id=self._claim.attempt.attempt_id,
                worker_instance_id=self._claim.attempt.worker_instance_id,
                lease_duration=self._policy.lease_duration,
            )
        except (OnlyResearchExecutionOwnershipLostError, OnlyResearchExecutionStoreUnavailableError) as exc:
            self._lost = exc
            only_log_research_operational_event(
                _LOG,
                logging.ERROR,
                "research.attempt.heartbeat_failed",
                run_id=str(self._claim.attempt.run_id),
                attempt_id=str(self._claim.attempt.attempt_id),
                worker_instance_id=str(self._claim.attempt.worker_instance_id),
                failure_code="ATTEMPT_OWNERSHIP_LOST",
            )
            raise OnlyResearchRuntimeOwnershipLost(type(exc).__name__) from exc

    def _raise_if_lost(self) -> None:
        if self._lost is not None:
            raise OnlyResearchRuntimeOwnershipLost(type(self._lost).__name__) from self._lost


class _MappedWorkerFailure(RuntimeError):
    def __init__(self, failure: OnlyResearchRunFailure) -> None:
        self.failure = failure
        super().__init__(failure.code)


class OnlyResearchWorker:
    def __init__(
        self,
        *,
        worker_instance_id: OnlyResearchWorkerInstanceId,
        execution_store: OnlyResearchExecutionStore,
        run_store: OnlyResearchRunStore,
        resolver: OnlyResearchSpecificationResolver,
        dataset_store: OnlyResearchDatasetSnapshotStore,
        runtime_executor: OnlyResearchRuntimeExecutor,
        policy: OnlyResearchExecutionPolicy,
        now_utc: Callable[[], datetime],
    ) -> None:
        self.worker_instance_id = worker_instance_id
        self._execution_store = execution_store
        self._run_store = run_store
        self._resolver = resolver
        self._dataset_store = dataset_store
        self._runtime_executor = runtime_executor
        self._policy = policy
        self._now_utc = now_utc

    def execute_claim(self, claim: OnlyResearchExecutionClaim) -> OnlyResearchWorkerOutcome:
        if claim.attempt.worker_instance_id != self.worker_instance_id:
            raise OnlyResearchExecutionOwnershipLostError("Claim belongs to a different Worker instance")
        only_log_research_operational_event(
            _LOG,
            logging.INFO,
            "research.run.claimed",
            run_id=str(claim.attempt.run_id),
            attempt_id=str(claim.attempt.attempt_id),
            worker_instance_id=str(self.worker_instance_id),
            lease_expires_at=claim.attempt.lease_expires_at.isoformat(),
        )
        control = _LeaseControl(
            claim=claim,
            store=self._execution_store,
            run_store=self._run_store,
            policy=self._policy,
        )
        try:
            control.start()
            run = self._run_store.load(claim.attempt.run_id)
            control.checkpoint(OnlyResearchRuntimeBoundary.BEFORE_DATASET_VERIFICATION)
            try:
                self._dataset_store.load_verified_table(run.specification.dataset_snapshot_fingerprint)
            except Exception as exc:
                raise _MappedWorkerFailure(
                    OnlyResearchRunFailure(
                        OnlyResearchRunFailurePhase.EXECUTION,
                        "DATASET_VERIFICATION_FAILED",
                        f"Dataset verified load failed: {type(exc).__name__}",
                    )
                ) from exc
            resolution = self._resolver.resolve(run.specification)
            current_evidence = only_research_admission_resolution_fingerprint(resolution)
            if current_evidence != run.admission_resolution_fingerprint:
                raise _MappedWorkerFailure(
                    OnlyResearchRunFailure(
                        OnlyResearchRunFailurePhase.ADMISSION,
                        "EXECUTION_SEMANTIC_DRIFT",
                        "Admission resolution evidence changed before execution",
                    )
                )
            result = self._runtime_executor.execute(resolution.workload, control)
            if result.status is not OnlyRuntimeResultStatus.COMPLETED:
                raise _MappedWorkerFailure(_runtime_failure(result))
            control.assert_authoritative()
            completed = self._execution_store.complete(
                claim=claim,
                run_finished_at=self._now_utc(),
                research_result_fingerprint=result.research_result_fingerprint,
                artifact_content_fingerprint=result.artifact_content_fingerprint,
                calculation_execution_evidence_fingerprints=(result.calculation_execution_evidence_fingerprints),
            )
            return OnlyResearchWorkerOutcome(OnlyResearchWorkerOutcomeKind.COMPLETED, claim, completed)
        except OnlyResearchRuntimeCancellationRequested:
            return self._cancel(claim)
        except (
            OnlyResearchRuntimeOwnershipLost,
            OnlyResearchExecutionOwnershipLostError,
            OnlyResearchExecutionStoreUnavailableError,
        ):
            return OnlyResearchWorkerOutcome(OnlyResearchWorkerOutcomeKind.OWNERSHIP_LOST, claim)
        except _MappedWorkerFailure as exc:
            return self._fail(claim, exc.failure)
        except OnlyResearchSpecificationError as exc:
            return self._fail(
                claim,
                OnlyResearchRunFailure(
                    OnlyResearchRunFailurePhase.ADMISSION,
                    "EXECUTION_SEMANTIC_DRIFT",
                    f"Specification re-resolution failed: {exc.phase.value}:{exc.code}",
                ),
            )
        except OnlyResearchRunStoreUnavailableError:
            return self._fail(
                claim,
                OnlyResearchRunFailure(
                    OnlyResearchRunFailurePhase.OPERATIONAL,
                    "RESEARCH_RUN_STORE_UNAVAILABLE",
                    "Research Run Store unavailable during execution revalidation",
                ),
            )
        except Exception as exc:
            _LOG.exception(
                "unexpected Research Worker failure run_id=%s attempt_id=%s worker_instance_id=%s",
                claim.attempt.run_id,
                claim.attempt.attempt_id,
                self.worker_instance_id,
            )
            failure = OnlyResearchRunFailure(
                OnlyResearchRunFailurePhase.OPERATIONAL,
                "UNEXPECTED_WORKER_FAILURE",
                f"Unexpected Worker failure: {type(exc).__name__}",
            )
            return self._fail(claim, failure)
        finally:
            control.stop()

    def _fail(self, claim: OnlyResearchExecutionClaim, failure: OnlyResearchRunFailure) -> OnlyResearchWorkerOutcome:
        decision = self._policy.retry_decision(failure, attempt_number=claim.attempt.attempt_number)
        try:
            run = self._execution_store.fail(
                claim=claim,
                run_finished_at=self._now_utc(),
                failure=failure,
                retry_decision=decision,
            )
        except (OnlyResearchExecutionOwnershipLostError, OnlyResearchExecutionStoreUnavailableError):
            return OnlyResearchWorkerOutcome(OnlyResearchWorkerOutcomeKind.OWNERSHIP_LOST, claim, failure=failure)
        kind = (
            OnlyResearchWorkerOutcomeKind.RETRY_PENDING
            if run.state is OnlyResearchRunState.RUNNING
            else OnlyResearchWorkerOutcomeKind.FAILED
        )
        return OnlyResearchWorkerOutcome(kind, claim, run, failure)

    def _cancel(self, claim: OnlyResearchExecutionClaim) -> OnlyResearchWorkerOutcome:
        try:
            run = self._execution_store.cancel(claim=claim, run_finished_at=self._now_utc())
        except (OnlyResearchExecutionOwnershipLostError, OnlyResearchExecutionStoreUnavailableError):
            return OnlyResearchWorkerOutcome(OnlyResearchWorkerOutcomeKind.OWNERSHIP_LOST, claim)
        return OnlyResearchWorkerOutcome(OnlyResearchWorkerOutcomeKind.CANCELLED, claim, run)


class OnlyResearchWorkerService:
    """Bounded single-Worker composition; PostgreSQL remains the queue authority."""

    def __init__(
        self,
        *,
        scheduler: OnlyResearchScheduler,
        worker: OnlyResearchWorker,
        cancellation_reconciler: OnlyResearchCancellationRecoveryReconciler,
        polling_interval: timedelta = timedelta(seconds=1),
        presence_reporter: _PresenceReporter | None = None,
    ) -> None:
        if polling_interval <= timedelta(0):
            raise ValueError("polling_interval must be positive")
        self._scheduler = scheduler
        self._worker = worker
        self._cancellation_reconciler = cancellation_reconciler
        self._polling_interval = polling_interval
        self._presence_reporter = presence_reporter
        self._stop = Event()

    def run_once(self, *, stop_requested: Callable[[], bool] | None = None) -> OnlyResearchWorkerOutcome | None:
        if self._stop.is_set():
            return None
        self._scheduler.expire_once()
        self._cancellation_reconciler.reconcile_once()
        if self._stop.is_set() or (stop_requested or (lambda: False))():
            self.stop()
            return None
        claim = self._scheduler.claim_once(self._worker.worker_instance_id)
        return None if claim is None else self._worker.execute_claim(claim)

    def run_forever(self, *, stop_requested: Callable[[], bool] | None = None) -> None:
        externally_stopped = stop_requested or (lambda: False)
        reporter = self._presence_reporter
        if reporter is not None:
            reporter.start()
        only_log_research_operational_event(
            _LOG,
            logging.INFO,
            "research.worker.ready",
            worker_instance_id=str(self._worker.worker_instance_id),
        )
        try:
            while not self._stop.is_set() and not externally_stopped():
                try:
                    outcome = self.run_once(stop_requested=externally_stopped)
                except (OnlyResearchExecutionStoreUnavailableError, OnlyResearchRunStoreUnavailableError):
                    only_log_research_operational_event(
                        _LOG,
                        logging.ERROR,
                        "research.worker.database_unavailable",
                        worker_instance_id=str(self._worker.worker_instance_id),
                        failure_code="RESEARCH_EXECUTION_STORE_UNAVAILABLE",
                    )
                    outcome = None
                if outcome is not None:
                    only_log_research_operational_event(
                        _LOG,
                        logging.INFO,
                        f"research.run.{outcome.kind.value.lower()}",
                        run_id=str(outcome.claim.attempt.run_id),
                        attempt_id=str(outcome.claim.attempt.attempt_id),
                        worker_instance_id=str(self._worker.worker_instance_id),
                        failure_code=None if outcome.failure is None else outcome.failure.code,
                    )
                else:
                    self._stop.wait(self._polling_interval.total_seconds())
        finally:
            if externally_stopped() and not self._stop.is_set():
                self.stop()
            if reporter is not None:
                reporter.stop()
            only_log_research_operational_event(
                _LOG,
                logging.INFO,
                "research.worker.stopped",
                worker_instance_id=str(self._worker.worker_instance_id),
            )

    def stop(self) -> None:
        """Stop new claims; an already executing claim drains with heartbeat ownership."""
        if self._stop.is_set():
            return
        self._stop.set()
        if self._presence_reporter is not None:
            self._presence_reporter.draining()
        only_log_research_operational_event(
            _LOG,
            logging.INFO,
            "research.worker.draining",
            worker_instance_id=str(self._worker.worker_instance_id),
        )


def _runtime_failure(result: OnlyResearchRuntimeResult) -> OnlyResearchRunFailure:
    phase = OnlyResearchRunFailurePhase.EXECUTION
    if result.phase is not None:
        if result.phase.value in {"RESULT_ASSEMBLY", "RESULT_COMMIT"}:
            phase = OnlyResearchRunFailurePhase.RESULT_COMMIT
        elif result.phase.value in {"ARTIFACT_MATERIALIZATION", "ARTIFACT_COMMIT", "FINAL_VERIFICATION"}:
            phase = OnlyResearchRunFailurePhase.ARTIFACT_COMMIT
    return OnlyResearchRunFailure(
        phase,
        result.code or "WORKER_EXECUTION_FAILED",
        result.detail or "Research Runtime returned FAILED",
    )


__all__ = [name for name in globals() if name.startswith("Only")]
