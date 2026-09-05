from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

from onlyalpha.backtest import (
    OnlyBacktestAdmissionResolution,
    OnlyBacktestAttemptId,
    OnlyBacktestEvidenceStore,
    OnlyBacktestExecutionPolicy,
    OnlyBacktestProfileReference,
    OnlyBacktestRun,
    OnlyBacktestRunId,
    OnlyBacktestRunState,
    OnlyBacktestSpecification,
    OnlyBacktestWorkerInstanceId,
    OnlyInMemoryBacktestExecutionStore,
)
from onlyalpha.backtest.presence import OnlyBacktestWorkerPresenceReporter
from onlyalpha.backtest.worker import (
    OnlyBacktestReconciler,
    OnlyBacktestRuntimeExecutionResult,
    OnlyBacktestWorker,
    OnlyBacktestWorkerOutcomeKind,
    _LeaseControl,
)
from onlyalpha.backtest.worker_main import _shutdown_presence


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


class _RuntimeGenerations:
    def __init__(self, work_id: str) -> None:
        self.work_id = work_id

    def work_ids_for_generation(self, process_generation_fingerprint):  # type: ignore[no-untyped-def]
        assert process_generation_fingerprint == "7" * 64
        return (self.work_id,)

    def require_work_generation(self, work_id, process_generation_fingerprint):  # type: ignore[no-untyped-def]
        if work_id != self.work_id or process_generation_fingerprint != "7" * 64:
            raise ValueError("RUNTIME_WORK_GENERATION_MISMATCH")

    def release_work(self, work_id, **_):  # type: ignore[no-untyped-def]
        assert work_id == self.work_id
        self.work_id = ""


class _PresenceWriter:
    def __init__(self) -> None:
        self.announced = Event()

    def announce_worker(self, *_: object) -> None:
        self.announced.set()

    def heartbeat_worker(self, *_: object) -> None:
        raise AssertionError("long heartbeat interval must remain wakeable")

    def mark_worker_draining(self, *_: object) -> None:
        return None


class _AliveThread:
    ident = 1

    def __init__(self) -> None:
        self.join_timeout: float | None = None

    def join(self, timeout: float | None = None) -> None:
        self.join_timeout = timeout

    def is_alive(self) -> bool:
        return True


def test_backtest_presence_thread_is_non_daemon_wakeable_and_stop_is_bounded() -> None:
    writer = _PresenceWriter()
    reporter = OnlyBacktestWorkerPresenceReporter(
        writer,  # type: ignore[arg-type]
        OnlyBacktestWorkerInstanceId.new(),
        "test",
        timedelta(days=1),
    )
    assert not reporter._thread.daemon

    reporter.start()
    assert writer.announced.is_set()
    reporter.stop()

    assert not reporter._thread.is_alive()


def test_backtest_presence_stop_timeout_fails_explicitly() -> None:
    reporter = OnlyBacktestWorkerPresenceReporter(
        _PresenceWriter(),  # type: ignore[arg-type]
        OnlyBacktestWorkerInstanceId.new(),
        "test",
        timedelta(seconds=2),
    )
    thread = _AliveThread()
    reporter._thread = thread  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="BACKTEST_WORKER_PRESENCE_STOP_TIMEOUT"):
        reporter.stop()

    assert thread.join_timeout == 3


def test_backtest_lease_thread_is_non_daemon_wakeable_and_stop_is_bounded() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    policy = OnlyBacktestExecutionPolicy(lease_duration=timedelta(days=2), heartbeat_interval=timedelta(days=1))
    store = OnlyInMemoryBacktestExecutionStore((_run(now),), now_utc=lambda: now)
    claim = store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy)
    assert claim is not None
    control = _LeaseControl(store, claim, policy)
    assert not control._thread.daemon

    with control:
        pass

    assert not control._thread.is_alive()


def test_backtest_lease_stop_timeout_fails_explicitly() -> None:
    now = datetime(2026, 9, 2, tzinfo=UTC)
    policy = OnlyBacktestExecutionPolicy(lease_duration=timedelta(seconds=4), heartbeat_interval=timedelta(seconds=2))
    store = OnlyInMemoryBacktestExecutionStore((_run(now),), now_utc=lambda: now)
    claim = store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy)
    assert claim is not None
    control = _LeaseControl(store, claim, policy)
    thread = _AliveThread()
    control._thread = thread  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="BACKTEST_LEASE_CONTROL_STOP_TIMEOUT"):
        control.__exit__()

    assert thread.join_timeout == 3


def test_backtest_worker_cleanup_stops_presence_and_preserves_first_failure() -> None:
    calls: list[str] = []

    class _FailingPresence:
        def draining(self) -> None:
            calls.append("draining")
            raise RuntimeError("DRAINING_FAILED")

        def stop(self) -> None:
            calls.append("stop")
            raise RuntimeError("STOP_FAILED")

    with pytest.raises(RuntimeError, match="DRAINING_FAILED"):
        _shutdown_presence(_FailingPresence())  # type: ignore[arg-type]

    assert calls == ["draining", "stop"]


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
        runtime_generations=_RuntimeGenerations(_run(now[0]).run_id.value),  # type: ignore[arg-type]
        process_generation_fingerprint="7" * 64,
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
        runtime_generations=_RuntimeGenerations(_run(now).run_id.value),  # type: ignore[arg-type]
        process_generation_fingerprint="7" * 64,
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
        runtime_generations=_RuntimeGenerations(_run(now).run_id.value),  # type: ignore[arg-type]
        process_generation_fingerprint="7" * 64,
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
        runtime_generations=_RuntimeGenerations(_run(now[0]).run_id.value),  # type: ignore[arg-type]
        process_generation_fingerprint="7" * 64,
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
