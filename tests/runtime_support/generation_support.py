"""Deterministic fake for formal RuntimeGeneration work-binding tests."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from onlyalpha_runtime_generation_manager import OnlyRuntimeGenerationRegistry

from onlyalpha.application.runtime_generation import (
    OnlyRuntimeWorkAdmissionClosureEvidence,
    OnlyRuntimeWorkBindingEvidence,
)
from onlyalpha.runtime.generation import (
    OnlyCoreExecutionIdentity,
    OnlyRuntimeGenerationManifest,
    OnlyRuntimeGenerationValidationEvidence,
    OnlyRuntimeProviderBinding,
)


class OnlyTestRuntimeGenerationAuthority:
    def __init__(
        self,
        generation_fingerprint: str = "f" * 64,
        catalog_generation_fingerprint: str = "e" * 64,
    ) -> None:
        self.generation_fingerprint = generation_fingerprint
        self.catalog_generation_fingerprint = catalog_generation_fingerprint
        self.available_generations = {generation_fingerprint: catalog_generation_fingerprint}
        self.bindings: dict[str, str] = {}
        self.inactive_work_ids: set[str] = set()
        self.binding_evidence: dict[str, OnlyRuntimeWorkBindingEvidence] = {}
        self.closures: dict[str, OnlyRuntimeWorkAdmissionClosureEvidence] = {}

    def activate(self, generation_fingerprint: str, *, catalog_generation_fingerprint: str | None = None) -> None:
        catalog = catalog_generation_fingerprint or self.catalog_generation_fingerprint
        self.available_generations[generation_fingerprint] = catalog
        self.generation_fingerprint = generation_fingerprint
        self.catalog_generation_fingerprint = catalog

    def bind_new_work(self, work_id: str, **_: object) -> object:
        self._require_open(work_id)
        self.bindings.setdefault(work_id, self.generation_fingerprint)
        return self.require_work_binding(work_id)

    def bind_new_work_exact(
        self, work_id: str, runtime_generation_fingerprint: str, *, owner: str, **kwargs: object
    ) -> object:
        self._require_open(work_id)
        if work_id in self.bindings:
            evidence = self.require_work_binding_evidence(work_id)
            if (
                self.bindings[work_id] != runtime_generation_fingerprint
                or work_id in self.inactive_work_ids
                or evidence.binding_kind != "NEW_WORK"
                or evidence.binding_owner != owner
            ):
                raise ValueError("RUNTIME_WORK_GENERATION_BINDING_CONFLICT")
            return self.require_work_binding(work_id)
        self.require_new_work_generation(runtime_generation_fingerprint)
        self.bindings[work_id] = runtime_generation_fingerprint
        self.binding_evidence[work_id] = OnlyRuntimeWorkBindingEvidence(
            work_id,
            runtime_generation_fingerprint,
            "NEW_WORK",
            owner,
            str(kwargs.get("actor", "test")),
            "a" * 64,
            1,
            True,
        )
        return self.require_work_binding(work_id)

    def require_work_binding_evidence(self, work_id: str) -> OnlyRuntimeWorkBindingEvidence:
        from dataclasses import replace

        self.require_work_binding(work_id)
        evidence = self.binding_evidence.get(work_id)
        if evidence is None:
            evidence = OnlyRuntimeWorkBindingEvidence(
                work_id, self.bindings[work_id], "EXACT", None, "test", "a" * 64, 1, True
            )
        return replace(evidence, active=work_id not in self.inactive_work_ids)

    def bind_work_exact(self, work_id: str, runtime_generation_fingerprint: str, **_: object) -> object:
        self._require_open(work_id)
        if runtime_generation_fingerprint not in self.available_generations:
            raise ValueError("RUNTIME_GENERATION_NOT_FOUND")
        existing = self.bindings.setdefault(work_id, runtime_generation_fingerprint)
        if existing != runtime_generation_fingerprint:
            raise ValueError("RUNTIME_WORK_GENERATION_BINDING_CONFLICT")
        return self.require_work_binding(work_id)

    def bind_derived_work(self, parent_work_id: str, child_work_id: str, **_: object) -> object:
        self._require_open(child_work_id)
        if parent_work_id not in self.bindings:
            raise ValueError("RUNTIME_DERIVED_PARENT_GENERATION_UNBOUND")
        parent = self.bindings[parent_work_id]
        if child_work_id not in self.bindings and parent_work_id in self.inactive_work_ids:
            raise ValueError("RUNTIME_DERIVED_PARENT_GENERATION_UNBOUND")
        existing = self.bindings.setdefault(child_work_id, parent)
        if existing != parent or child_work_id in self.inactive_work_ids:
            raise ValueError("RUNTIME_DERIVED_WORK_GENERATION_BINDING_CONFLICT")
        return self.require_work_binding(child_work_id)

    def require_new_work_generation(self, runtime_generation_fingerprint: str) -> object:
        if runtime_generation_fingerprint != self.generation_fingerprint:
            raise ValueError("RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK")
        return self.require_runtime_generation(runtime_generation_fingerprint)

    def _require_open(self, work_id: str) -> None:
        if work_id not in self.bindings and work_id in self.closures:
            raise ValueError("RUNTIME_WORK_ADMISSION_CLOSED")

    def require_work_admission_closure_evidence(self, work_id: str) -> OnlyRuntimeWorkAdmissionClosureEvidence:
        if work_id not in self.closures:
            raise ValueError("RUNTIME_WORK_ADMISSION_NOT_CLOSED")
        return self.closures[work_id]

    def close_new_work_exact(
        self,
        work_id: str,
        runtime_generation_fingerprint: str,
        *,
        owner: str,
        closure_reason: str,
        actor: str,
        occurred_at: datetime,
    ) -> OnlyRuntimeWorkAdmissionClosureEvidence:
        del occurred_at
        if work_id in self.closures:
            evidence = self.closures[work_id]
            if (evidence.runtime_generation_fingerprint, evidence.binding_owner, evidence.closure_reason) != (
                runtime_generation_fingerprint,
                owner,
                closure_reason,
            ):
                raise ValueError("RUNTIME_WORK_GENERATION_BINDING_CONFLICT")
            return evidence
        if work_id in self.bindings:
            proof = self.require_work_binding_evidence(work_id)
            if (
                proof.runtime_generation_fingerprint != runtime_generation_fingerprint
                or proof.binding_kind != "NEW_WORK"
                or proof.binding_owner != owner
            ):
                raise ValueError("RUNTIME_WORK_GENERATION_BINDING_CONFLICT")
            self.inactive_work_ids.add(work_id)
        evidence = OnlyRuntimeWorkAdmissionClosureEvidence(
            work_id, runtime_generation_fingerprint, owner, closure_reason, actor, "b" * 64, 2
        )
        self.closures[work_id] = evidence
        return evidence

    def require_runtime_generation(self, runtime_generation_fingerprint: str) -> object:
        if runtime_generation_fingerprint not in self.available_generations:
            raise ValueError("RUNTIME_GENERATION_NOT_FOUND")
        return SimpleNamespace(
            runtime_generation_fingerprint=runtime_generation_fingerprint,
            catalog_generation_fingerprint=self.available_generations[runtime_generation_fingerprint],
        )

    def release_work(self, work_id: str, **_: object) -> object:
        if work_id not in self.bindings:
            raise KeyError(work_id)
        self.inactive_work_ids.add(work_id)
        return self.require_work_binding(work_id)

    def require_work_binding(self, work_id: str) -> object:
        if work_id not in self.bindings:
            raise ValueError("RUNTIME_WORK_GENERATION_UNBOUND")
        return SimpleNamespace(
            work_id=work_id,
            runtime_generation_fingerprint=self.bindings[work_id],
            active=work_id not in self.inactive_work_ids,
        )

    def require_work_generation(self, work_id: str, process_generation_fingerprint: str) -> object:
        if self.bindings.get(work_id) != process_generation_fingerprint or work_id in self.inactive_work_ids:
            raise ValueError("RUNTIME_WORK_GENERATION_MISMATCH")
        return object()

    def work_ids_for_generation(self, process_generation_fingerprint: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                key
                for key, value in self.bindings.items()
                if value == process_generation_fingerprint and key not in self.inactive_work_ids
            )
        )

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
