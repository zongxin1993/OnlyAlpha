from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from onlyalpha.backtest import (
    OnlyBacktestAdmissionResolution,
    OnlyBacktestAttemptId,
    OnlyBacktestEvidenceStore,
    OnlyBacktestExecutionPolicy,
    OnlyBacktestProfileReference,
    OnlyBacktestReconciler,
    OnlyBacktestRun,
    OnlyBacktestRunId,
    OnlyBacktestRunState,
    OnlyBacktestRuntimeExecutionResult,
    OnlyBacktestSpecification,
    OnlyBacktestWorker,
    OnlyBacktestWorkerInstanceId,
    OnlyBacktestWorkerOutcomeKind,
    OnlyInMemoryBacktestExecutionStore,
)


def _resolution(*, kernel: str = "kernel-v1") -> OnlyBacktestAdmissionResolution:
    return OnlyBacktestAdmissionResolution(
        1,
        "a" * 64,
        "b" * 64,
        "d" * 64,
        "e" * 64,
        "1" * 64,
        "2" * 64,
        "3" * 64,
        kernel,
        ("4" * 64,),
    )


def _run(now: datetime) -> OnlyBacktestRun:
    reference = OnlyBacktestProfileReference("profile", "1")
    specification = OnlyBacktestSpecification(
        "a" * 64,
        "b" * 64,
        "c" * 64,
        reference,
        reference,
        reference,
        "USDT",
        "100",
    )
    return OnlyBacktestRun.queued(
        run_id=OnlyBacktestRunId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        specification=specification,
        admission_resolution=_resolution(),
        queued_at=now,
    )


class _Admission:
    def __init__(self, resolution: OnlyBacktestAdmissionResolution) -> None:
        self.resolution = resolution

    def resolve(self, specification: OnlyBacktestSpecification) -> OnlyBacktestAdmissionResolution:
        del specification
        return self.resolution


class _Executor:
    def execute(self, run: OnlyBacktestRun) -> OnlyBacktestRuntimeExecutionResult:
        del run
        return OnlyBacktestRuntimeExecutionResult(
            "5" * 64,
            "6" * 64,
            (("result.json", b"{}", "application/json"),),
        )


class _NoThreadLease:
    ownership_lost = False

    def __enter__(self) -> _NoThreadLease:
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _lease(*_: object) -> _NoThreadLease:
    return _NoThreadLease()


class _LostLease(_NoThreadLease):
    ownership_lost = True


class _FailIfExecuted:
    def execute(self, run: OnlyBacktestRun) -> OnlyBacktestRuntimeExecutionResult:
        del run
        raise AssertionError("Engine must not start after lease ownership is lost")


def test_worker_revalidates_admission_publishes_evidence_then_completes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    now = [datetime(2026, 9, 2, tzinfo=UTC)]
    store = OnlyInMemoryBacktestExecutionStore((_run(now[0]),), now_utc=lambda: now[0])
    worker = OnlyBacktestWorker(
        worker_instance_id=OnlyBacktestWorkerInstanceId.new(),
        store=store,
        admission=_Admission(_resolution()),  # type: ignore[arg-type]
        executor=_Executor(),
        evidence=OnlyBacktestEvidenceStore(tmp_path),
        lease_control_factory=_lease,  # type: ignore[arg-type]
    )

    outcome = worker.run_once()

    assert outcome is not None and outcome.kind is OnlyBacktestWorkerOutcomeKind.COMPLETED
    assert outcome.run is not None and outcome.run.state is OnlyBacktestRunState.COMPLETED
    assert outcome.run.evidence_fingerprint is not None


def test_worker_fails_closed_on_execution_semantic_drift(tmp_path) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2026, 9, 2, tzinfo=UTC)
    store = OnlyInMemoryBacktestExecutionStore((_run(now),), now_utc=lambda: now)
    worker = OnlyBacktestWorker(
        worker_instance_id=OnlyBacktestWorkerInstanceId.new(),
        store=store,
        admission=_Admission(_resolution(kernel="kernel-v2")),  # type: ignore[arg-type]
        executor=_Executor(),
        evidence=OnlyBacktestEvidenceStore(tmp_path),
        lease_control_factory=_lease,  # type: ignore[arg-type]
    )

    outcome = worker.run_once()

    assert outcome is not None and outcome.kind is OnlyBacktestWorkerOutcomeKind.FAILED
    assert outcome.failure is not None and outcome.failure.code == "EXECUTION_SEMANTIC_DRIFT"


def test_worker_starts_lease_before_revalidation_and_does_not_execute_after_loss(tmp_path) -> None:  # type: ignore[no-untyped-def]
    now = datetime(2026, 9, 2, tzinfo=UTC)
    store = OnlyInMemoryBacktestExecutionStore((_run(now),), now_utc=lambda: now)
    lease_entered = False

    class _AdmissionAfterLease(_Admission):
        def resolve(self, specification: OnlyBacktestSpecification) -> OnlyBacktestAdmissionResolution:
            assert lease_entered
            return super().resolve(specification)

    class _ObservedLostLease(_LostLease):
        def __enter__(self):  # type: ignore[no-untyped-def]
            nonlocal lease_entered
            lease_entered = True
            return self

    worker = OnlyBacktestWorker(
        worker_instance_id=OnlyBacktestWorkerInstanceId.new(),
        store=store,
        admission=_AdmissionAfterLease(_resolution()),  # type: ignore[arg-type]
        executor=_FailIfExecuted(),
        evidence=OnlyBacktestEvidenceStore(tmp_path),
        lease_control_factory=lambda *_: _ObservedLostLease(),  # type: ignore[arg-type]
    )

    outcome = worker.run_once()

    assert outcome is not None and outcome.kind is OnlyBacktestWorkerOutcomeKind.OWNERSHIP_LOST


def test_reconciliation_completes_after_evidence_publish_crash(tmp_path) -> None:  # type: ignore[no-untyped-def]
    now = [datetime(2026, 9, 2, tzinfo=UTC)]
    base = OnlyInMemoryBacktestExecutionStore((_run(now[0]),), now_utc=lambda: now[0])

    class _CrashAfterPublishStore:
        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            return getattr(base, name)

        def complete(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            del args, kwargs
            raise SystemExit("crash after Evidence publish")

    evidence = OnlyBacktestEvidenceStore(tmp_path)
    worker = OnlyBacktestWorker(
        worker_instance_id=OnlyBacktestWorkerInstanceId.new(),
        store=_CrashAfterPublishStore(),
        admission=_Admission(_resolution()),  # type: ignore[arg-type]
        executor=_Executor(),
        evidence=evidence,
        lease_control_factory=_lease,  # type: ignore[arg-type]
    )

    with pytest.raises(SystemExit, match="crash after Evidence"):
        worker.run_once()

    now[0] += OnlyBacktestExecutionPolicy().lease_duration + timedelta(microseconds=1)
    assert base.expire_next(OnlyBacktestExecutionPolicy()) is not None
    completed = OnlyBacktestReconciler(base, evidence).run_once()
    assert completed is not None and completed.state is OnlyBacktestRunState.COMPLETED


def test_stale_worker_cannot_finalize_after_replacement_claim(tmp_path) -> None:  # type: ignore[no-untyped-def]
    del tmp_path
    now = [datetime(2026, 9, 2, tzinfo=UTC)]
    policy = OnlyBacktestExecutionPolicy()
    store = OnlyInMemoryBacktestExecutionStore((_run(now[0]),), now_utc=lambda: now[0])
    stale = store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy)
    assert stale is not None
    now[0] += policy.lease_duration + timedelta(microseconds=1)
    store.expire_next(policy)
    replacement = store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy)
    assert replacement is not None

    with pytest.raises(RuntimeError, match="FENCED"):
        store.complete(
            stale,
            evidence_fingerprint="7" * 64,
            result_fingerprint="8" * 64,
            determinism_fingerprint="9" * 64,
        )
