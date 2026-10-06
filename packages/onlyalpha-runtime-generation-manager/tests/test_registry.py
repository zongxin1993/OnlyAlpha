from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from threading import Barrier, Event, Thread

import pytest
from onlyalpha_runtime_generation_manager import (
    OnlyGenerationState,
    OnlyHistoricalRuntimeGenerationResolver,
    OnlyRuntimeGenerationRegistry,
)

from onlyalpha.runtime.generation import (
    OnlyArtifactCalculationImplementation,
    OnlyCoreExecutionIdentity,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeGenerationValidationEvidence,
    OnlyRuntimeProviderBinding,
)
from tests.strategy.product_support import strategy_product_case

NOW = datetime(2026, 9, 5, tzinfo=UTC)


def test_atomic_new_work_replay_rejects_historical_exact_binding(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    generation = _ready(registry, _manifest("a"), 0)
    registry.activate_for_new_work(expected_current=None, target=generation, actor="operator", occurred_at=NOW)
    registry.bind_work_exact("chart", generation, actor="foreign", occurred_at=NOW)
    with pytest.raises(ValueError, match="RUNTIME_WORK_GENERATION_BINDING_CONFLICT"):
        registry.bind_new_work_exact(
            "chart", generation, owner="CHART_CALCULATION_INPUT", actor="chart", occurred_at=NOW
        )


def test_new_work_evidence_preserves_owner_original_event_and_release(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    generation = _ready(registry, _manifest("a"), 0)
    registry.activate_for_new_work(expected_current=None, target=generation, actor="operator", occurred_at=NOW)
    registry.bind_new_work_exact(
        "chart", generation, owner="CHART_CALCULATION_INPUT", actor="original", occurred_at=NOW
    )
    proof = registry.require_work_binding_evidence("chart")
    assert proof.binding_kind == "NEW_WORK" and proof.binding_owner == "CHART_CALCULATION_INPUT"
    assert proof.binding_actor == "original" and type(proof.binding_sequence) is int
    assert len(proof.binding_event_fingerprint) == 64
    ledger = (tmp_path / "generation-events.jsonl").read_bytes()
    registry.bind_new_work_exact("chart", generation, owner="CHART_CALCULATION_INPUT", actor="retry", occurred_at=NOW)
    assert (tmp_path / "generation-events.jsonl").read_bytes() == ledger
    with pytest.raises(ValueError, match="RUNTIME_WORK_GENERATION_BINDING_CONFLICT"):
        registry.bind_new_work_exact("chart", generation, owner="OTHER", actor="retry", occurred_at=NOW)
    registry.release_work("chart", actor="terminal", occurred_at=NOW)
    recovered = OnlyRuntimeGenerationRegistry(tmp_path).require_work_binding_evidence("chart")
    assert recovered == replace(proof, active=False)
    registry.bind_work_exact("historical", generation, actor="foreign", occurred_at=NOW)
    exact = registry.require_work_binding_evidence("historical")
    assert exact.binding_kind == "EXACT" and exact.binding_owner is None


def test_ownerless_new_work_history_cannot_supply_ownership_proof(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    generation = _ready(registry, _manifest("a"), 0)
    registry.activate_for_new_work(expected_current=None, target=generation, actor="operator", occurred_at=NOW)
    binding = registry.bind_new_work("legacy", actor="legacy", occurred_at=NOW)
    assert OnlyRuntimeGenerationRegistry(tmp_path).require_work_binding("legacy") == binding
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_EVENT_CHAIN_CORRUPT"):
        registry.require_work_binding_evidence("legacy")


def test_binding_evidence_rejects_duplicate_original_event(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    generation = _ready(registry, _manifest("a"), 0)
    registry.activate_for_new_work(expected_current=None, target=generation, actor="operator", occurred_at=NOW)
    registry.bind_new_work_exact("chart", generation, owner="CHART_CALCULATION_INPUT", actor="chart", occurred_at=NOW)
    event = registry._read_events()[-1]
    registry._append(replace(event, sequence=event.sequence + 1, previous_event_fingerprint=event.event_fingerprint))
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_EVENT_ORDER_INVALID"):
        OnlyRuntimeGenerationRegistry(tmp_path).require_work_binding_evidence("chart")


def test_unbound_closure_blocks_every_first_binding_family_and_replays(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    generation = _ready(registry, _manifest("a"), 0)
    registry.activate_for_new_work(expected_current=None, target=generation, actor="operator", occurred_at=NOW)
    closure = registry.close_new_work_exact(
        "closed",
        generation,
        owner="CHART_CALCULATION_INPUT",
        closure_reason="CHART_RUNTIME_GENERATION_NOT_ELIGIBLE",
        actor="chart",
        occurred_at=NOW,
    )
    registry.bind_new_work("parent", actor="test", occurred_at=NOW)
    calls = (
        lambda: registry.bind_new_work("closed", actor="stale", occurred_at=NOW),
        lambda: registry.bind_new_work_exact(
            "closed", generation, owner="CHART_CALCULATION_INPUT", actor="stale", occurred_at=NOW
        ),
        lambda: registry.bind_work_exact("closed", generation, actor="stale", occurred_at=NOW),
        lambda: registry.bind_derived_work("parent", "closed", actor="stale", occurred_at=NOW),
    )
    for call in calls:
        with pytest.raises(ValueError, match="RUNTIME_WORK_ADMISSION_CLOSED"):
            call()
    restarted = OnlyRuntimeGenerationRegistry(tmp_path)
    assert restarted.require_work_admission_closure_evidence("closed") == closure
    assert (
        restarted.close_new_work_exact(
            "closed",
            generation,
            owner="CHART_CALCULATION_INPUT",
            closure_reason="CHART_RUNTIME_GENERATION_NOT_ELIGIBLE",
            actor="retry",
            occurred_at=NOW,
        )
        == closure
    )
    with pytest.raises(ValueError, match="RUNTIME_WORK_GENERATION_BINDING_CONFLICT"):
        restarted.close_new_work_exact(
            "closed",
            generation,
            owner="OTHER",
            closure_reason="CHART_RUNTIME_GENERATION_NOT_ELIGIBLE",
            actor="retry",
            occurred_at=NOW,
        )


@pytest.mark.parametrize("family", ("EXACT", "FOREIGN", "CHART"))
def test_closure_releases_only_matching_new_work_owner(tmp_path: Path, family: str) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    generation = _ready(registry, _manifest("a"), 0)
    registry.activate_for_new_work(expected_current=None, target=generation, actor="operator", occurred_at=NOW)
    if family == "EXACT":
        registry.bind_work_exact("work", generation, actor="test", occurred_at=NOW)
    else:
        registry.bind_new_work_exact(
            "work",
            generation,
            owner="CHART_CALCULATION_INPUT" if family == "CHART" else "OTHER",
            actor="test",
            occurred_at=NOW,
        )
    if family != "CHART":
        with pytest.raises(ValueError, match="RUNTIME_WORK_GENERATION_BINDING_CONFLICT"):
            registry.close_new_work_exact(
                "work",
                generation,
                owner="CHART_CALCULATION_INPUT",
                closure_reason="CHART_SEALED_COVERAGE_UNAVAILABLE",
                actor="chart",
                occurred_at=NOW,
            )
        assert registry.require_work_binding("work").active
    else:
        registry.close_new_work_exact(
            "work",
            generation,
            owner="CHART_CALCULATION_INPUT",
            closure_reason="CHART_SEALED_COVERAGE_UNAVAILABLE",
            actor="chart",
            occurred_at=NOW,
        )
        assert not registry.require_work_binding("work").active
        other = _ready(registry, _manifest("b"), 1)
        registry.activate_for_new_work(expected_current=generation, target=other, actor="operator", occurred_at=NOW)
        registry.retire(generation, actor="operator", occurred_at=NOW)


@pytest.mark.parametrize("first", ("bind", "close"))
def test_first_bind_and_close_have_one_atomic_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first: str
) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    other = OnlyRuntimeGenerationRegistry(tmp_path)
    generation = _ready(registry, _manifest("a"), 0)
    registry.activate_for_new_work(expected_current=None, target=generation, actor="operator", occurred_at=NOW)
    holding, resume, second_started = Event(), Event(), Event()
    original = OnlyRuntimeGenerationRegistry._append
    outcomes = {}

    def held_append(self, event):
        if self is registry:
            holding.set()
            assert resume.wait(10)
        original(self, event)

    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "_append", held_append)

    def perform(authority, action):
        try:
            if action == "bind":
                outcomes[action] = authority.bind_new_work_exact(
                    "work", generation, owner="CHART_CALCULATION_INPUT", actor="chart", occurred_at=NOW
                )
            else:
                outcomes[action] = authority.close_new_work_exact(
                    "work",
                    generation,
                    owner="CHART_CALCULATION_INPUT",
                    closure_reason="CHART_RUNTIME_GENERATION_NOT_ELIGIBLE",
                    actor="chart",
                    occurred_at=NOW,
                )
        except Exception as exc:
            outcomes[action] = str(exc)

    def second():
        second_started.set()
        perform(other, "close" if first == "bind" else "bind")

    t1, t2 = Thread(target=perform, args=(registry, first)), Thread(target=second)
    t1.start()
    try:
        assert holding.wait(10)
        t2.start()
        assert second_started.wait(10)
    finally:
        resume.set()
        t1.join(10)
        if t2.ident is not None:
            t2.join(10)
    assert not t1.is_alive() and not t2.is_alive()
    recovered = OnlyRuntimeGenerationRegistry(tmp_path)
    assert recovered.require_work_admission_closure_evidence("work") == outcomes["close"]
    if first == "close":
        assert outcomes["bind"] == "RUNTIME_WORK_ADMISSION_CLOSED"
    else:
        assert recovered.require_work_binding("work").active is False


def test_release_before_closure_crash_is_retryable_without_reactivation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    generation = _ready(registry, _manifest("a"), 0)
    registry.activate_for_new_work(expected_current=None, target=generation, actor="operator", occurred_at=NOW)
    registry.bind_new_work_exact("work", generation, owner="CHART_CALCULATION_INPUT", actor="chart", occurred_at=NOW)
    original = OnlyRuntimeGenerationRegistry._append

    def after_release(self, event):
        original(self, event)
        if event.kind == "RuntimeWorkReleased":
            raise RuntimeError("process loss after release fsync")

    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "_append", after_release)
    with pytest.raises(RuntimeError, match="process loss"):
        registry.close_new_work_exact(
            "work",
            generation,
            owner="CHART_CALCULATION_INPUT",
            closure_reason="CHART_SEALED_COVERAGE_UNAVAILABLE",
            actor="chart",
            occurred_at=NOW,
        )
    restarted = OnlyRuntimeGenerationRegistry(tmp_path)
    assert not restarted.require_work_binding("work").active
    with pytest.raises(ValueError, match="RUNTIME_WORK_ADMISSION_NOT_CLOSED"):
        restarted.require_work_admission_closure_evidence("work")
    closure = restarted.close_new_work_exact(
        "work",
        generation,
        owner="CHART_CALCULATION_INPUT",
        closure_reason="CHART_SEALED_COVERAGE_UNAVAILABLE",
        actor="retry",
        occurred_at=NOW,
    )
    assert restarted.require_work_admission_closure_evidence("work") == closure


def _manifest(seed: str, implementations: tuple[str, ...] = ()) -> OnlyRuntimeGenerationManifest:
    calculation_bindings = tuple(
        OnlyArtifactCalculationImplementation(
            "FACTOR",
            f"private.factor.asset{index}",
            "1",
            "RESEARCH" if index % 2 == 0 else "TRADING",
            fingerprint,
        )
        for index, fingerprint in enumerate(implementations)
    )
    return OnlyRuntimeGenerationManifest(
        core_execution=OnlyCoreExecutionIdentity("onlyalpha", "0.9.9", seed * 64),
        artifact_manifest_fingerprints=((chr(ord(seed) + 1)) * 64, "f" * 64),
        artifact_sha256s=(seed * 64, (chr(ord(seed) + 2)) * 64),
        providers=(OnlyRuntimeProviderBinding(f"private.provider.{seed}", "1", seed * 64, chr(ord(seed) + 2) * 64),),
        catalog_generation_fingerprint=chr(ord(seed) + 3) * 64,
        implementations=calculation_bindings,
    )


def _ready(registry: OnlyRuntimeGenerationRegistry, manifest: OnlyRuntimeGenerationManifest, offset: int) -> str:
    fingerprint = manifest.runtime_generation_fingerprint
    registry.prepare(manifest, actor="operator", occurred_at=NOW + timedelta(seconds=offset))
    registry.admit_ready(
        OnlyRuntimeGenerationValidationEvidence.from_manifest(manifest),
        actor="validator",
        occurred_at=NOW + timedelta(seconds=offset + 1),
    )
    return fingerprint


def test_ready_requires_exact_validation_evidence(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    manifest = _manifest("a")
    registry.prepare(manifest, actor="operator", occurred_at=NOW)
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_NOT_READY"):
        registry.activate_for_new_work(
            expected_current=None,
            target=manifest.runtime_generation_fingerprint,
            actor="operator",
            occurred_at=NOW + timedelta(seconds=1),
        )
    mismatched = replace(
        OnlyRuntimeGenerationValidationEvidence.from_manifest(manifest),
        catalog_generation_fingerprint="f" * 64,
    )
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_VALIDATION_EVIDENCE_MISMATCH"):
        registry.admit_ready(mismatched, actor="validator", occurred_at=NOW + timedelta(seconds=2))
    assert registry.projection().state(manifest.runtime_generation_fingerprint) is OnlyGenerationState.PREPARING


def test_bind_new_work_exact_requires_active_generation_and_replays_exactly(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    g1 = _ready(registry, _manifest("a"), 0)
    g2 = _ready(registry, _manifest("b"), 2)
    bind = partial(registry.bind_new_work_exact, owner="CHART_CALCULATION_INPUT")
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK"):
        bind("chart", g1, actor="chart", occurred_at=NOW)
    registry.activate_for_new_work(expected_current=None, target=g1, actor="operator", occurred_at=NOW)
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK"):
        bind("chart", g2, actor="chart", occurred_at=NOW)
    binding = bind("chart", g1, actor="chart", occurred_at=NOW)
    ledger = (tmp_path / "generation-events.jsonl").read_bytes()
    assert bind("chart", g1, actor="retry", occurred_at=NOW) == binding
    assert (tmp_path / "generation-events.jsonl").read_bytes() == ledger
    registry.activate_for_new_work(expected_current=g1, target=g2, actor="operator", occurred_at=NOW)
    assert bind("chart", g1, actor="retry", occurred_at=NOW) == binding
    with pytest.raises(ValueError, match="RUNTIME_WORK_GENERATION_BINDING_CONFLICT"):
        bind("chart", g2, actor="wrong", occurred_at=NOW)
    registry.release_work("chart", actor="terminal", occurred_at=NOW)
    with pytest.raises(ValueError, match="RUNTIME_WORK_GENERATION_BINDING_CONFLICT"):
        bind("chart", g1, actor="retry", occurred_at=NOW)
    assert OnlyRuntimeGenerationRegistry(tmp_path).require_work_binding("chart").active is False
    assert b'"kind":"RuntimeWorkBound"' in ledger
    assert b'"kind":"RuntimeExactWorkBound"' not in ledger


@pytest.mark.parametrize("first", ("bind", "activation"))
def test_bind_new_work_exact_and_activation_have_one_atomic_commit_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, first: str
) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    other = OnlyRuntimeGenerationRegistry(tmp_path)
    g1 = _ready(registry, _manifest("a"), 0)
    g2 = _ready(registry, _manifest("b"), 2)
    registry.activate_for_new_work(expected_current=None, target=g1, actor="operator", occurred_at=NOW)
    bind = partial(registry.bind_new_work_exact, owner="CHART_CALCULATION_INPUT")
    holding, release, second_started = Event(), Event(), Event()
    original = OnlyRuntimeGenerationRegistry._append

    def held_append(self, event):
        if self is registry:
            holding.set()
            assert release.wait(10)
        original(self, event)

    monkeypatch.setattr(OnlyRuntimeGenerationRegistry, "_append", held_append)
    outcomes = {}

    def perform(action, authority):
        try:
            if action == "bind":
                method = (
                    bind
                    if authority is registry
                    else partial(authority.bind_new_work_exact, owner="CHART_CALCULATION_INPUT")
                )
                outcomes[action] = method("chart", g1, actor="chart", occurred_at=NOW)
            else:
                authority.activate_for_new_work(expected_current=g1, target=g2, actor="operator", occurred_at=NOW)
                outcomes[action] = "activated"
        except Exception as exc:
            outcomes[action] = str(exc)

    def second():
        second_started.set()
        perform("activation" if first == "bind" else "bind", other)

    t1 = Thread(target=perform, args=(first, registry))
    t2 = Thread(target=second)
    t1.start()
    try:
        assert holding.wait(10)
        t2.start()
        assert second_started.wait(10)
    finally:
        release.set()
        t1.join(10)
        if t2.ident is not None:
            t2.join(10)
    assert not t1.is_alive() and not t2.is_alive()
    assert outcomes["activation"] == "activated"
    recovered = OnlyRuntimeGenerationRegistry(tmp_path)
    assert recovered.projection().active_for_new_work == g2
    if first == "bind":
        assert recovered.require_work_binding("chart") == outcomes["bind"]
        assert outcomes["bind"].runtime_generation_fingerprint == g1
    else:
        assert outcomes["bind"] == "RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK"
        with pytest.raises(ValueError, match="RUNTIME_WORK_GENERATION_UNBOUND"):
            recovered.require_work_binding("chart")


def test_activation_isolation_rollback_drain_retire_and_restart(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    g1 = _ready(registry, _manifest("a"), 0)
    g2 = _ready(registry, _manifest("b"), 2)
    registry.activate_for_new_work(
        expected_current=None, target=g1, actor="operator", occurred_at=NOW + timedelta(seconds=4)
    )
    r1 = registry.bind_new_work("R1", actor="admission", occurred_at=NOW + timedelta(seconds=5))
    registry.activate_for_new_work(
        expected_current=g1, target=g2, actor="operator", occurred_at=NOW + timedelta(seconds=6)
    )
    r2 = registry.bind_new_work("R2", actor="admission", occurred_at=NOW + timedelta(seconds=7))
    registry.activate_for_new_work(
        expected_current=g2, target=g1, actor="operator", occurred_at=NOW + timedelta(seconds=8)
    )
    r3 = registry.bind_new_work("R3", actor="admission", occurred_at=NOW + timedelta(seconds=9))
    assert (
        r1.runtime_generation_fingerprint,
        r2.runtime_generation_fingerprint,
        r3.runtime_generation_fingerprint,
    ) == (
        g1,
        g2,
        g1,
    )
    assert registry.require_work_generation("R1", g1).runtime_generation_fingerprint == g1
    with pytest.raises(ValueError, match="RUNTIME_WORK_GENERATION_MISMATCH"):
        registry.require_work_generation("R1", g2)
    recovered = OnlyRuntimeGenerationRegistry(tmp_path).projection()
    assert recovered.active_for_new_work == g1
    assert recovered.states[g2] is OnlyGenerationState.DRAINING
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_STILL_REQUIRED"):
        registry.retire(g2, actor="operator", occurred_at=NOW + timedelta(seconds=10))
    registry.release_work("R2", actor="worker", occurred_at=NOW + timedelta(seconds=11))
    released = registry.require_work_binding("R2")
    assert released.runtime_generation_fingerprint == g2
    assert not released.active
    assert registry.bind_new_work("R2", actor="admission", occurred_at=NOW + timedelta(seconds=12)) == released
    registry.retire(g2, actor="operator", occurred_at=NOW + timedelta(seconds=12))
    assert registry.projection().states[g2] is OnlyGenerationState.RETIRED


def test_exact_and_derived_work_binding_replay_conflict_and_draining_recovery(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    g1 = _ready(registry, _manifest("a"), 0)
    g2 = _ready(registry, _manifest("b"), 2)
    registry.activate_for_new_work(
        expected_current=None, target=g1, actor="operator", occurred_at=NOW + timedelta(seconds=4)
    )
    root = registry.bind_work_exact(
        "search-experiment:" + "1" * 64,
        g1,
        actor="search-admission",
        occurred_at=NOW + timedelta(seconds=5),
    )
    assert (
        registry.bind_work_exact(
            root.work_id,
            g1,
            actor="search-retry",
            occurred_at=NOW + timedelta(seconds=6),
        )
        == root
    )
    with pytest.raises(ValueError, match="RUNTIME_WORK_GENERATION_BINDING_CONFLICT"):
        registry.bind_work_exact(
            root.work_id,
            g2,
            actor="conflict",
            occurred_at=NOW + timedelta(seconds=7),
        )
    registry.activate_for_new_work(
        expected_current=g1, target=g2, actor="operator", occurred_at=NOW + timedelta(seconds=8)
    )
    child = registry.bind_derived_work(
        root.work_id,
        "00000000-0000-4000-8000-000000000123",
        actor="derived-research",
        occurred_at=NOW + timedelta(seconds=9),
    )
    assert child.runtime_generation_fingerprint == g1
    assert (
        registry.bind_derived_work(
            root.work_id,
            child.work_id,
            actor="derived-retry",
            occurred_at=NOW + timedelta(seconds=10),
        )
        == child
    )
    assert registry.require_new_work_generation(g2).runtime_generation_fingerprint == g2
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK"):
        registry.require_new_work_generation(g1)


def test_derived_binding_conflicts_with_prebound_current_generation(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    g1 = _ready(registry, _manifest("a"), 0)
    g2 = _ready(registry, _manifest("b"), 2)
    registry.activate_for_new_work(
        expected_current=None, target=g1, actor="operator", occurred_at=NOW + timedelta(seconds=4)
    )
    parent = registry.bind_new_work("search:" + "1" * 64, actor="root", occurred_at=NOW + timedelta(seconds=5))
    registry.activate_for_new_work(
        expected_current=g1, target=g2, actor="operator", occurred_at=NOW + timedelta(seconds=6)
    )
    registry.bind_new_work("child", actor="standalone", occurred_at=NOW + timedelta(seconds=7))
    with pytest.raises(ValueError, match="RUNTIME_DERIVED_WORK_GENERATION_BINDING_CONFLICT"):
        registry.bind_derived_work(
            parent.work_id,
            "child",
            actor="derived",
            occurred_at=NOW + timedelta(seconds=8),
        )


def test_concurrent_exact_binding_has_one_generation_winner(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    g1 = _ready(registry, _manifest("a"), 0)
    g2 = _ready(registry, _manifest("b"), 2)
    registry.activate_for_new_work(
        expected_current=None, target=g1, actor="operator", occurred_at=NOW + timedelta(seconds=4)
    )
    registry.activate_for_new_work(
        expected_current=g1, target=g2, actor="operator", occurred_at=NOW + timedelta(seconds=5)
    )
    barrier = Barrier(3)
    outcomes: list[str] = []

    def bind(generation: str, offset: int) -> None:
        barrier.wait()
        try:
            result = registry.bind_work_exact(
                "contended-search",
                generation,
                actor=f"actor-{offset}",
                occurred_at=NOW + timedelta(seconds=offset),
            )
            outcomes.append(result.runtime_generation_fingerprint)
        except ValueError as exc:
            outcomes.append(str(exc))

    threads = (Thread(target=bind, args=(g1, 6)), Thread(target=bind, args=(g2, 7)))
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert outcomes.count("RUNTIME_WORK_GENERATION_BINDING_CONFLICT") == 1
    winner = registry.require_work_binding("contended-search").runtime_generation_fingerprint
    assert winner in {g1, g2}
    assert winner in outcomes


def test_concurrent_derived_binding_replays_one_exact_child_generation(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    generation = _ready(registry, _manifest("a"), 0)
    registry.activate_for_new_work(
        expected_current=None,
        target=generation,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=2),
    )
    parent = registry.bind_new_work("search-parent", actor="root", occurred_at=NOW + timedelta(seconds=3))
    barrier = Barrier(3)
    outcomes: list[str] = []

    def bind(offset: int) -> None:
        barrier.wait()
        result = registry.bind_derived_work(
            parent.work_id,
            "derived-child",
            actor=f"derived-{offset}",
            occurred_at=NOW + timedelta(seconds=offset),
        )
        outcomes.append(result.runtime_generation_fingerprint)

    threads = (Thread(target=bind, args=(4,)), Thread(target=bind, args=(5,)))
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert outcomes == [generation, generation]
    assert registry.work_ids_for_generation(generation).count("derived-child") == 1


def test_exact_and_derived_binding_fail_closed_after_release(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    generation = _ready(registry, _manifest("a"), 0)
    registry.activate_for_new_work(
        expected_current=None,
        target=generation,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=2),
    )
    parent = registry.bind_new_work("search-parent", actor="root", occurred_at=NOW + timedelta(seconds=3))
    registry.bind_derived_work(
        parent.work_id,
        "derived-child",
        actor="derived",
        occurred_at=NOW + timedelta(seconds=4),
    )
    registry.release_work("derived-child", actor="worker", occurred_at=NOW + timedelta(seconds=5))
    with pytest.raises(ValueError, match="RUNTIME_DERIVED_WORK_GENERATION_BINDING_CONFLICT"):
        registry.bind_derived_work(
            parent.work_id,
            "derived-child",
            actor="derived-retry",
            occurred_at=NOW + timedelta(seconds=6),
        )
    registry.release_work(parent.work_id, actor="search", occurred_at=NOW + timedelta(seconds=7))
    historical = registry.bind_work_exact(
        parent.work_id,
        generation,
        actor="search-retry",
        occurred_at=NOW + timedelta(seconds=8),
    )
    assert historical.runtime_generation_fingerprint == generation
    assert historical.active is False


def test_concurrent_activation_has_one_durable_winner(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    g0 = _ready(registry, _manifest("a"), 0)
    g1 = _ready(registry, _manifest("b"), 2)
    g2 = _ready(registry, _manifest("c"), 4)
    registry.activate_for_new_work(
        expected_current=None, target=g0, actor="operator", occurred_at=NOW + timedelta(seconds=6)
    )
    barrier = Barrier(3)
    outcomes: list[str] = []

    def activate(target: str, offset: int) -> None:
        barrier.wait()
        try:
            registry.activate_for_new_work(
                expected_current=g0,
                target=target,
                actor=f"actor-{offset}",
                occurred_at=NOW + timedelta(seconds=offset),
            )
            outcomes.append("PASS")
        except ValueError as exc:
            outcomes.append(str(exc))

    threads = (Thread(target=activate, args=(g1, 7)), Thread(target=activate, args=(g2, 8)))
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["GENERATION_ACTIVATION_CONFLICT", "PASS"]
    assert registry.projection().active_for_new_work in {g1, g2}


def test_crash_before_and_after_activation_commit_recover_exactly(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    g1 = _ready(registry, _manifest("a"), 0)
    g2 = _ready(registry, _manifest("b"), 2)
    registry.activate_for_new_work(
        expected_current=None, target=g1, actor="operator", occurred_at=NOW + timedelta(seconds=4)
    )

    def before(stage: str) -> None:
        if stage == "before_commit":
            raise RuntimeError("injected before commit")

    with pytest.raises(RuntimeError, match="before commit"):
        registry.activate_for_new_work(
            expected_current=g1,
            target=g2,
            actor="operator",
            occurred_at=NOW + timedelta(seconds=5),
            fault=before,
        )
    assert OnlyRuntimeGenerationRegistry(tmp_path).projection().active_for_new_work == g1

    def after(stage: str) -> None:
        if stage == "after_commit":
            raise RuntimeError("injected after commit")

    with pytest.raises(RuntimeError, match="after commit"):
        registry.activate_for_new_work(
            expected_current=g1,
            target=g2,
            actor="operator",
            occurred_at=NOW + timedelta(seconds=6),
            fault=after,
        )
    assert OnlyRuntimeGenerationRegistry(tmp_path).projection().active_for_new_work == g2
    registry.activate_for_new_work(
        expected_current=g1,
        target=g2,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=6),
    )


def test_rejected_candidate_never_changes_active_generation(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    g1 = _ready(registry, _manifest("a"), 0)
    rejected = _manifest("b")
    g2 = rejected.runtime_generation_fingerprint
    registry.prepare(rejected, actor="operator", occurred_at=NOW + timedelta(seconds=2))
    registry.activate_for_new_work(
        expected_current=None, target=g1, actor="operator", occurred_at=NOW + timedelta(seconds=3)
    )
    registry.reject(
        g2,
        actor="validator",
        occurred_at=NOW + timedelta(seconds=4),
        reason="RUNTIME_GENERATION_CATALOG_MISMATCH",
    )
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_NOT_READY"):
        registry.activate_for_new_work(
            expected_current=g1,
            target=g2,
            actor="operator",
            occurred_at=NOW + timedelta(seconds=5),
        )
    projection = OnlyRuntimeGenerationRegistry(tmp_path).projection()
    assert projection.active_for_new_work == g1
    assert projection.states[g2] is OnlyGenerationState.REJECTED


def test_restart_fails_closed_when_generation_manifest_or_event_chain_is_corrupt(tmp_path: Path) -> None:
    registry = OnlyRuntimeGenerationRegistry(tmp_path)
    g1 = _ready(registry, _manifest("a"), 0)
    registry.activate_for_new_work(
        expected_current=None,
        target=g1,
        actor="operator",
        occurred_at=NOW + timedelta(seconds=2),
    )
    manifest_path = tmp_path / "runtime-generations" / f"{g1}.json"
    original = manifest_path.read_bytes()
    manifest_path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_MANIFEST_MISMATCH"):
        OnlyRuntimeGenerationRegistry(tmp_path).projection()
    manifest_path.write_bytes(original)
    ledger = tmp_path / "generation-events.jsonl"
    ledger.write_bytes(ledger.read_bytes() + b"{}\n")
    with pytest.raises(ValueError, match="RUNTIME_GENERATION_EVENT_CHAIN_CORRUPT"):
        OnlyRuntimeGenerationRegistry(tmp_path).projection()


def test_historical_revision_resolves_exact_implementation_not_same_semantic_version(tmp_path: Path) -> None:
    case = strategy_product_case(tmp_path / "strategy")
    required = tuple(
        fingerprint
        for binding in case.revision.implementation_bindings
        for fingerprint in (
            binding.research_implementation_fingerprint,
            binding.trading_implementation_fingerprint,
        )
    )
    changed = tuple("f" * 64 if value != "f" * 64 else "e" * 64 for value in required)
    registry = OnlyRuntimeGenerationRegistry(tmp_path / "registry")
    g1 = _ready(registry, _manifest("a", required), 0)
    _ready(registry, _manifest("b", changed), 2)
    resolved = OnlyHistoricalRuntimeGenerationResolver(registry).resolve(case.revision)
    assert resolved.runtime_generation_fingerprint == g1
    missing = replace(case.revision, implementation_bindings=case.revision.implementation_bindings)
    other_registry = OnlyRuntimeGenerationRegistry(tmp_path / "other")
    _ready(other_registry, _manifest("c", changed), 4)
    with pytest.raises(ValueError, match="HISTORICAL_IMPLEMENTATION_UNAVAILABLE"):
        OnlyHistoricalRuntimeGenerationResolver(other_registry).resolve(missing)
