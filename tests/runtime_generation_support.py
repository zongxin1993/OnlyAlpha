"""Deterministic fake for formal RuntimeGeneration work-binding tests."""

from __future__ import annotations

from datetime import datetime

from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

from onlyalpha.runtime.generation import (
    OnlyCoreExecutionIdentity,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeGenerationValidationEvidence,
    OnlyRuntimeProviderBinding,
)


class OnlyTestRuntimeGenerationAuthority:
    def __init__(self, generation_fingerprint: str = "f" * 64) -> None:
        self.generation_fingerprint = generation_fingerprint
        self.bindings: dict[str, str] = {}

    def bind_new_work(self, work_id: str, **_: object) -> object:
        self.bindings.setdefault(work_id, self.generation_fingerprint)
        return object()

    def release_work(self, work_id: str, **_: object) -> object:
        self.bindings.pop(work_id, None)
        return object()

    def require_work_binding(self, work_id: str) -> object:
        if work_id not in self.bindings:
            raise ValueError("RUNTIME_WORK_GENERATION_UNBOUND")
        return object()

    def require_work_generation(self, work_id: str, process_generation_fingerprint: str) -> object:
        if self.bindings.get(work_id) != process_generation_fingerprint:
            raise ValueError("RUNTIME_WORK_GENERATION_MISMATCH")
        return object()

    def work_ids_for_generation(self, process_generation_fingerprint: str) -> tuple[str, ...]:
        return tuple(sorted(key for key, value in self.bindings.items() if value == process_generation_fingerprint))

    def verify_hosted_generation(self, generation_fingerprint: str) -> None:
        if generation_fingerprint != self.generation_fingerprint:
            raise RuntimeError("RUNTIME_GENERATION_HOSTED_PROCESS_MISMATCH")


def only_ready_test_generation(
    registry: OnlyRuntimeGenerationRegistry,
    seed: str,
    occurred_at: datetime,
) -> str:
    manifest = OnlyRuntimeGenerationManifest(
        core_execution=OnlyCoreExecutionIdentity("onlyalpha", "0.9.9", seed * 64),
        artifact_manifest_fingerprints=(seed * 64,),
        artifact_sha256s=(seed * 64,),
        providers=(OnlyRuntimeProviderBinding(f"test.provider.{seed}", "1", seed * 64, seed * 64),),
        catalog_generation_fingerprint=seed * 64,
        implementations=(),
    )
    registry.prepare(manifest, actor="test-operator", occurred_at=occurred_at)
    registry.admit_ready(
        OnlyRuntimeGenerationValidationEvidence.from_manifest(manifest),
        actor="test-validator",
        occurred_at=occurred_at,
    )
    return manifest.runtime_generation_fingerprint
