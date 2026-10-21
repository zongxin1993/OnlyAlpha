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
    def validate_runtime(self, run, authority):
        pass

    def __init__(self, resolution: OnlyBacktestAdmissionResolution) -> None:
        self.resolution = resolution

    def resolve(self, specification: OnlyBacktestSpecification) -> OnlyBacktestAdmissionResolution:
        del specification
        return self.resolution


class _Executor:
    def execute(self, run: OnlyBacktestRun, control=None, *, initialize=False) -> OnlyBacktestRuntimeExecutionResult:
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
    def execute(self, run: OnlyBacktestRun, control=None, *, initialize=False) -> OnlyBacktestRuntimeExecutionResult:
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


def test_worker_cooperatively_cancels_during_execution_without_publishing_evidence(tmp_path) -> None:
    from onlyalpha.backtest.worker import OnlyBacktestRuntimeCancellation

    now = [datetime(2026, 9, 2, tzinfo=UTC)]
    run = _run(now[0])
    store = OnlyInMemoryBacktestExecutionStore((run,), now_utc=lambda: now[0])
    evidence = OnlyBacktestEvidenceStore(tmp_path)

    class Executor:
        def execute(self, current, control, *, initialize=False):
            assert control() == "CONTINUE"
            store.runs[current.run_id] = store.load(current.run_id).transition(
                OnlyBacktestRunState.CANCEL_REQUESTED, at=now[0]
            )
            assert control() == "CANCEL"
            return OnlyBacktestRuntimeCancellation()

    worker = OnlyBacktestWorker(
        worker_instance_id=OnlyBacktestWorkerInstanceId.new(),
        store=store,
        admission=_Admission(_resolution()),
        executor=Executor(),
        evidence=evidence,
        lease_control_factory=_lease,
        runtime_generations=_RuntimeGenerations(run.run_id.value),
        process_generation_fingerprint="7" * 64,
    )
    outcome = worker.run_once()
    assert outcome is not None and outcome.kind is OnlyBacktestWorkerOutcomeKind.CANCELLED
    assert outcome.run is not None and outcome.run.state is OnlyBacktestRunState.CANCELLED
    assert evidence.find_for_run(run.run_id.value) is None


def test_control_fences_an_old_attempt_before_any_more_native_dispatch(tmp_path) -> None:
    now = [datetime(2026, 9, 2, tzinfo=UTC)]
    run = _run(now[0])
    policy = OnlyBacktestExecutionPolicy()
    store = OnlyInMemoryBacktestExecutionStore((run,), now_utc=lambda: now[0])
    evidence = OnlyBacktestEvidenceStore(tmp_path)
    reached = []

    class Executor:
        def execute(self, current, control, *, initialize=False):
            assert control() == "CONTINUE"
            now[0] += policy.lease_duration
            assert store.expire_next(policy) is not None
            replacement = store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy)
            assert replacement is not None and replacement.attempt.fencing_token == 2
            control()
            reached.append("illegal old dispatch")
            return _Executor().execute(current)

    worker = OnlyBacktestWorker(
        worker_instance_id=OnlyBacktestWorkerInstanceId.new(),
        store=store,
        admission=_Admission(_resolution()),
        executor=Executor(),
        evidence=evidence,
        lease_control_factory=_lease,
        runtime_generations=_RuntimeGenerations(run.run_id.value),
        process_generation_fingerprint="7" * 64,
    )
    outcome = worker.run_once()
    assert outcome is not None and outcome.kind is OnlyBacktestWorkerOutcomeKind.OWNERSHIP_LOST
    assert reached == []
    assert evidence.find_for_run(run.run_id.value) is None


def test_native_cancel_after_worker_death_requires_a_new_fenced_runtime_stop(tmp_path) -> None:
    from dataclasses import replace

    from onlyalpha.backtest.model import OnlyBacktestLimitPolicy
    from onlyalpha.backtest.worker import OnlyBacktestRuntimeCancellation

    now = [datetime(2026, 9, 2, tzinfo=UTC)]
    old = _run(now[0])
    specification = replace(
        old.specification, schema_version=2, order_policy=OnlyBacktestLimitPolicy("4", "10.00", "12.00", "2", 1)
    )
    run = OnlyBacktestRun.queued(
        run_id=old.run_id,
        specification=specification,
        admission_resolution=old.admission_resolution,
        queued_at=old.queued_at,
    )
    policy = OnlyBacktestExecutionPolicy()
    store = OnlyInMemoryBacktestExecutionStore((run,), now_utc=lambda: now[0])
    evidence = OnlyBacktestEvidenceStore(tmp_path)
    claim = store.claim_next(OnlyBacktestWorkerInstanceId.new(), OnlyBacktestAttemptId.new(), policy)
    assert claim is not None
    store.runs[run.run_id] = store.load(run.run_id).transition(OnlyBacktestRunState.CANCEL_REQUESTED, at=now[0])
    now[0] += policy.lease_duration
    assert store.expire_next(policy) is not None
    assert OnlyBacktestReconciler(store, evidence).run_once() is None, (
        "missing Evidence cannot prove native execution has stopped"
    )
    stopped = []

    class Executor:
        def execute(self, current, control, *, initialize=False):
            assert initialize is False, "a later fenced Attempt cannot grant initialization"
            assert control() == "CANCEL"
            stopped.append(current.run_id.value)
            return OnlyBacktestRuntimeCancellation()

    worker = OnlyBacktestWorker(
        worker_instance_id=OnlyBacktestWorkerInstanceId.new(),
        store=store,
        admission=_Admission(_resolution()),
        executor=Executor(),
        evidence=evidence,
        lease_control_factory=_lease,
        runtime_generations=_RuntimeGenerations(run.run_id.value),
        process_generation_fingerprint="7" * 64,
    )
    outcome = worker.run_once()
    assert outcome is not None and outcome.kind is OnlyBacktestWorkerOutcomeKind.CANCELLED
    assert outcome.claim.attempt.fencing_token == 2 and stopped == [run.run_id.value]
    assert evidence.find_for_run(run.run_id.value) is None


def test_only_first_native_attempt_receives_initialization_grant(tmp_path) -> None:
    from dataclasses import replace

    from onlyalpha.backtest.model import OnlyBacktestLimitPolicy
    from onlyalpha.backtest.worker import OnlyBacktestRuntimeCancellation

    now = datetime(2026, 9, 2, tzinfo=UTC)
    old = _run(now)
    run = OnlyBacktestRun.queued(
        run_id=old.run_id,
        specification=replace(
            old.specification, schema_version=2, order_policy=OnlyBacktestLimitPolicy("4", "10.00", "12.00", "2", 1)
        ),
        admission_resolution=old.admission_resolution,
        queued_at=old.queued_at,
    )
    store = OnlyInMemoryBacktestExecutionStore((run,), now_utc=lambda: now)

    class Executor:
        def execute(self, current, control, *, initialize=False):
            assert initialize is True
            assert control() == "CONTINUE"
            store.runs[current.run_id] = store.load(current.run_id).transition(
                OnlyBacktestRunState.CANCEL_REQUESTED, at=now
            )
            assert control() == "CANCEL"
            return OnlyBacktestRuntimeCancellation()

    worker = OnlyBacktestWorker(
        worker_instance_id=OnlyBacktestWorkerInstanceId.new(),
        store=store,
        admission=_Admission(_resolution()),
        executor=Executor(),
        evidence=OnlyBacktestEvidenceStore(tmp_path),
        lease_control_factory=_lease,
        runtime_generations=_RuntimeGenerations(run.run_id.value),
        process_generation_fingerprint="7" * 64,
    )
    outcome = worker.run_once()
    assert outcome is not None and outcome.kind is OnlyBacktestWorkerOutcomeKind.CANCELLED
    assert outcome.claim.attempt.attempt_number == 1
