from __future__ import annotations

from pathlib import Path
from threading import Barrier, Lock, Thread
from types import SimpleNamespace
from typing import cast

import pytest
from onlyalpha_runtime_generation_manager.host_manager import (
    OnlyHistoricalGenerationHostManager,
    _HostedWorker,
)

from onlyalpha.application.search_generation_execution import (
    OnlyHistoricalGenerationArtifactMissing,
    OnlyHistoricalGenerationCapabilityUnsupported,
    OnlyHistoricalGenerationCorrupt,
    OnlyHistoricalGenerationHostMismatch,
    OnlySearchGenerationExecutionRequestV1,
    OnlySearchGenerationOperationV1,
    OnlySearchGenerationWorkerHandshakeV1,
)

G = "1" * 64
K = "2" * 64
C = "3" * 64
V = "4" * 64


class _Process:
    def __init__(self) -> None:
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    def communicate(self, timeout=None):  # type: ignore[no-untyped-def]
        del timeout
        return "", ""


def _manager(tmp_path: Path) -> OnlyHistoricalGenerationHostManager:
    return OnlyHistoricalGenerationHostManager(
        registry=cast(object, object()),
        builder=cast(object, object()),
        cache_root=tmp_path,
    )


def _identity():  # type: ignore[no-untyped-def]
    manifest = SimpleNamespace(
        runtime_generation_fingerprint=G,
        core_execution=SimpleNamespace(fingerprint=K),
        catalog_generation_fingerprint=C,
    )
    evidence = SimpleNamespace(
        runtime_generation_fingerprint=G,
        validation_evidence_fingerprint=V,
    )
    handshake = OnlySearchGenerationWorkerHandshakeV1(
        G,
        K,
        C,
        V,
        (OnlySearchGenerationOperationV1.DERIVE_SYMBOLIC_ENUMERATION,),
    )
    return manifest, evidence, handshake


def test_same_generation_acquire_is_single_flight_and_dead_worker_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    (tmp_path / G).mkdir()
    manifest, evidence, handshake = _identity()
    spawned: list[_HostedWorker] = []

    monkeypatch.setattr(manager, "_load_exact", lambda value: (manifest, evidence))

    def spawn(environment, expected):  # type: ignore[no-untyped-def]
        assert environment == tmp_path / G
        assert expected is evidence
        worker = _HostedWorker(cast(object, _Process()), handshake, Lock())
        spawned.append(worker)
        return worker

    monkeypatch.setattr(manager, "_spawn", spawn)
    barrier = Barrier(3)
    acquired: list[_HostedWorker] = []

    def acquire() -> None:
        barrier.wait()
        acquired.append(manager.acquire(G))

    threads = (Thread(target=acquire), Thread(target=acquire))
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert len(spawned) == 1
    assert acquired == [spawned[0], spawned[0]]

    cast(_Process, spawned[0].process).returncode = -9
    assert manager.acquire(G) is not spawned[0]
    assert len(spawned) == 2
    manager.close()


def test_wrong_generation_handshake_is_terminated_before_cache_admission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _manager(tmp_path)
    (tmp_path / G).mkdir()
    manifest, evidence, handshake = _identity()
    wrong = OnlySearchGenerationWorkerHandshakeV1(
        "9" * 64,
        handshake.core_execution_fingerprint,
        handshake.catalog_generation_fingerprint,
        handshake.validation_evidence_fingerprint,
        handshake.supported_capabilities,
    )
    process = _Process()
    monkeypatch.setattr(manager, "_load_exact", lambda value: (manifest, evidence))
    monkeypatch.setattr(
        manager,
        "_spawn",
        lambda environment, expected: _HostedWorker(cast(object, process), wrong, Lock()),
    )
    with pytest.raises(OnlyHistoricalGenerationHostMismatch):
        manager.acquire(G)
    assert process.returncode == 0
    assert manager._workers == {}


def test_evict_deletes_only_disposable_exact_generation_cache(tmp_path: Path) -> None:
    manager = _manager(tmp_path)
    environment = tmp_path / G
    environment.mkdir()
    (environment / "cache-only").write_text("x", encoding="utf-8")
    manager.evict(G, delete_environment=True)
    assert not environment.exists()


def test_unadvertised_operation_fails_before_worker_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(tmp_path)
    _manifest, _evidence, handshake = _identity()
    worker = _HostedWorker(cast(object, _Process()), handshake, Lock())
    monkeypatch.setattr(manager, "acquire", lambda value: worker)
    with pytest.raises(OnlyHistoricalGenerationCapabilityUnsupported):
        manager.execute(
            OnlySearchGenerationExecutionRequestV1(
                G,
                OnlySearchGenerationOperationV1.DERIVE_PARAMETER_DECISION,
                {},
            )
        )


@pytest.mark.parametrize(
    ("code", "error_type"),
    (
        ("RUNTIME_GENERATION_ARTIFACT_MISSING", OnlyHistoricalGenerationArtifactMissing),
        ("RUNTIME_GENERATION_ARTIFACT_CORRUPT", OnlyHistoricalGenerationCorrupt),
        ("RUNTIME_GENERATION_VALIDATION_EVIDENCE_MISMATCH", OnlyHistoricalGenerationCorrupt),
    ),
)
def test_rebuild_failures_remain_typed_and_never_fall_forward(
    tmp_path: Path,
    code: str,
    error_type: type[Exception],
) -> None:
    class _Builder:
        def rebuild_validated(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            raise ValueError(code)

    manager = OnlyHistoricalGenerationHostManager(
        registry=cast(object, object()),
        builder=cast(object, _Builder()),
        cache_root=tmp_path,
    )
    manifest, evidence, _handshake = _identity()
    with pytest.raises(error_type):
        manager._rebuild(cast(object, manifest), cast(object, evidence), tmp_path / G)
