from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Thread

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
    OnlyRuntimeProviderBinding,
)
from tests.strategy.p9_support import p9_strategy_case

NOW = datetime(2026, 9, 5, tzinfo=UTC)


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
    registry.mark_ready(fingerprint, actor="validator", occurred_at=NOW + timedelta(seconds=offset + 1))
    return fingerprint


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
    registry.retire(g2, actor="operator", occurred_at=NOW + timedelta(seconds=12))
    assert registry.projection().states[g2] is OnlyGenerationState.RETIRED


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
    case = p9_strategy_case(tmp_path / "strategy")
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
