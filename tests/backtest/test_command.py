from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.backtest import (
    OnlyBacktestCommandService,
    OnlyBacktestProfileReference,
    OnlyBacktestSpecification,
    OnlyInMemoryBacktestCommandStore,
)
from onlyalpha.backtest.errors import OnlyBacktestError
from tests.runtime_support.generation_support import only_ready_test_generation


class _Admission:
    def validate_runtime(self, run, authority):
        pass

    def resolve(self, specification):  # type: ignore[no-untyped-def]
        from onlyalpha.backtest import OnlyBacktestAdmissionResolution

        return OnlyBacktestAdmissionResolution(
            1,
            specification.strategy_fingerprint,
            specification.dataset_binding_fingerprint,
            "1" * 64,
            specification.market_product_configuration_fingerprint,
            "2" * 64,
            "3" * 64,
            "4" * 64,
            "kernel-v1",
            (),
        )


class _RuntimeGenerations:
    def __init__(self) -> None:
        self.work: set[str] = set()

    def bind_new_work(self, work_id, **_):  # type: ignore[no-untyped-def]
        self.work.add(work_id)

    def release_work(self, work_id, **_):  # type: ignore[no-untyped-def]
        self.work.discard(work_id)

    def require_work_binding(self, work_id):  # type: ignore[no-untyped-def]
        if work_id not in self.work:
            raise ValueError("RUNTIME_WORK_GENERATION_UNBOUND")

    def require_work_generation(self, work_id, process_generation_fingerprint):  # type: ignore[no-untyped-def]
        del process_generation_fingerprint
        return self.require_work_binding(work_id)

    def work_ids_for_generation(self, process_generation_fingerprint):  # type: ignore[no-untyped-def]
        del process_generation_fingerprint
        return tuple(sorted(self.work))

    def verify_hosted_generation(self, generation_fingerprint):  # type: ignore[no-untyped-def]
        del generation_fingerprint


def _spec() -> OnlyBacktestSpecification:
    ref = OnlyBacktestProfileReference("x", "1")
    return OnlyBacktestSpecification("a" * 64, "b" * 64, "c" * 64, ref, ref, ref, "USDT", "1")


def test_create_retry_converges_and_different_intent_fails() -> None:
    store = OnlyInMemoryBacktestCommandStore()
    service = OnlyBacktestCommandService(
        admission=_Admission(),
        store=store,
        now_utc=lambda: datetime.now(UTC),
        runtime_generations=_RuntimeGenerations(),
    )
    command_id = OnlyProductCommandId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    first = service.submit(command_id, _spec())
    second = service.submit(command_id, _spec())
    assert first.run.run_id == second.run.run_id
    changed = _spec()
    object.__setattr__(changed, "base_currency", "BTC")
    with pytest.raises(OnlyBacktestError, match="PRODUCT_COMMAND_CONFLICT"):
        service.submit(command_id, changed)


def test_formal_backtests_bind_active_generation_across_activation_rollback_and_restart(tmp_path: Path) -> None:
    now = datetime(2026, 9, 5, tzinfo=UTC)
    authority = OnlyRuntimeGenerationRegistry(tmp_path / "runtime-authority")
    g1 = only_ready_test_generation(authority, "a", now)
    g2 = only_ready_test_generation(authority, "b", now + timedelta(seconds=1))
    authority.activate_for_new_work(
        expected_current=None,
        target=g1,
        actor="operator",
        occurred_at=now + timedelta(seconds=2),
    )
    service = OnlyBacktestCommandService(
        admission=_Admission(),
        store=OnlyInMemoryBacktestCommandStore(),
        now_utc=lambda: now,
        runtime_generations=authority,
    )
    r1 = service.submit(OnlyProductCommandId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"), _spec()).run
    authority.activate_for_new_work(
        expected_current=g1,
        target=g2,
        actor="operator",
        occurred_at=now + timedelta(seconds=3),
    )
    r2 = service.submit(OnlyProductCommandId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2"), _spec()).run
    authority.activate_for_new_work(
        expected_current=g2,
        target=g1,
        actor="operator",
        occurred_at=now + timedelta(seconds=4),
    )
    r3 = service.submit(OnlyProductCommandId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3"), _spec()).run

    restarted = OnlyRuntimeGenerationRegistry(tmp_path / "runtime-authority")
    assert restarted.require_work_binding(r1.run_id.value).runtime_generation_fingerprint == g1
    assert restarted.require_work_binding(r2.run_id.value).runtime_generation_fingerprint == g2
    assert restarted.require_work_binding(r3.run_id.value).runtime_generation_fingerprint == g1
    with pytest.raises(ValueError, match="RUNTIME_WORK_GENERATION_MISMATCH"):
        restarted.require_work_generation(r2.run_id.value, g1)


def test_runtime_binding_must_be_admitted_before_queue_or_receipt_and_failure_releases_work() -> None:
    from onlyalpha.backtest.errors import OnlyBacktestErrorPhase

    class Denied(_Admission):
        def validate_runtime(self, run, authority):
            assert run.run_id.value in authority.work
            raise OnlyBacktestError(
                OnlyBacktestErrorPhase.ADMISSION,
                "BACKTEST_NATIVE_RUNTIME_UNAVAILABLE",
                "exact native execution closure is unavailable",
            )

    store = OnlyInMemoryBacktestCommandStore()
    authority = _RuntimeGenerations()
    service = OnlyBacktestCommandService(
        admission=Denied(), store=store, now_utc=lambda: datetime(2026, 9, 5, tzinfo=UTC), runtime_generations=authority
    )
    with pytest.raises(OnlyBacktestError, match="BACKTEST_NATIVE_RUNTIME_UNAVAILABLE"):
        service.submit(OnlyProductCommandId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"), _spec())
    assert store.runs == {} and store.receipts == {} and authority.work == set()


def test_lost_create_commit_ack_keeps_original_work_binding_for_same_command_retry() -> None:
    from onlyalpha.backtest.errors import OnlyBacktestStoreUnavailableError

    class Store(OnlyInMemoryBacktestCommandStore):
        interrupted = False

        def create_queued_with_receipt(self, run, receipt):
            accepted = super().create_queued_with_receipt(run, receipt)
            if not self.interrupted:
                self.interrupted = True
                raise OnlyBacktestStoreUnavailableError("commit acknowledgement lost")
            return accepted

    store = Store()
    authority = _RuntimeGenerations()
    command = OnlyProductCommandId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    service = OnlyBacktestCommandService(
        admission=_Admission(),
        store=store,
        now_utc=lambda: datetime(2026, 9, 5, tzinfo=UTC),
        runtime_generations=authority,
    )
    with pytest.raises(OnlyBacktestStoreUnavailableError):
        service.submit(command, _spec())
    assert len(store.runs) == 1
    original = next(iter(store.runs.values()))
    assert original.run_id.value in authority.work
    assert service.submit(command, _spec()).run == original
    assert len(store.runs) == 1


def test_native_creation_retries_the_original_exact_intent_after_unknown_commit() -> None:
    from dataclasses import replace

    from onlyalpha.backtest.errors import OnlyBacktestStoreUnavailableError
    from onlyalpha.backtest.model import OnlyBacktestLimitPolicy, OnlyBacktestRunId

    class Exact(_RuntimeGenerations):
        def __init__(self):
            super().__init__()
            self.active = "a" * 64
            self.bindings = {}

        def bind_new_work_exact(self, work_id, generation, *, owner, **_):
            proposed = (generation, owner)
            if work_id in self.bindings:
                assert self.bindings[work_id] == proposed
                return
            assert self.active == generation
            self.bindings[work_id] = proposed
            self.work.add(work_id)

    class Store(OnlyInMemoryBacktestCommandStore):
        calls = 0

        def create_queued_with_receipt(self, run, receipt):
            self.calls += 1
            if self.calls == 1:
                raise OnlyBacktestStoreUnavailableError("unknown before commit acknowledgement")
            return super().create_queued_with_receipt(run, receipt)

    store = Store()
    authority = Exact()
    now = datetime(2026, 9, 5, tzinfo=UTC)
    service = OnlyBacktestCommandService(
        admission=_Admission(), store=store, now_utc=lambda: now, runtime_generations=authority
    )
    command = OnlyProductCommandId("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    run_id = OnlyBacktestRunId("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    spec = replace(_spec(), schema_version=2, order_policy=OnlyBacktestLimitPolicy("1", "10", "11", "1", 1))
    with pytest.raises(OnlyBacktestStoreUnavailableError):
        service.submit(command, spec, run_id=run_id, runtime_generation_fingerprint="a" * 64)
    authority.active = "b" * 64
    now += timedelta(seconds=5)
    accepted = service.submit(command, spec, run_id=run_id, runtime_generation_fingerprint="a" * 64)
    assert accepted.run.run_id == run_id and len(authority.work) == 1
    for replacement in (
        {
            "run_id": OnlyBacktestRunId("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
            "runtime_generation_fingerprint": "a" * 64,
        },
        {"run_id": run_id, "runtime_generation_fingerprint": "b" * 64},
    ):
        with pytest.raises(OnlyBacktestError, match="PRODUCT_COMMAND_CONFLICT"):
            service.submit(command, spec, **replacement)
    assert authority.work == {run_id.value}
