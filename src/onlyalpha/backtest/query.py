"""Read-only Backtest Product projections over durable and immutable authorities."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from .admission import OnlyBacktestAdmissionService
from .creation_query import OnlyBacktestCreationQuery
from .errors import OnlyBacktestArtifactNotFoundError, OnlyBacktestIntegrityError, OnlyBacktestStateConflictError
from .evidence import OnlyBacktestEvidenceManifest, OnlyBacktestEvidenceStore
from .model import OnlyBacktestRun, OnlyBacktestRunId, OnlyBacktestRunState
from .runtime_generation import OnlyBacktestRuntimeGenerationWorkAuthority


class _RunReader(Protocol):
    def recent_runs(self) -> tuple[OnlyBacktestRun, ...]: ...

    def load(self, run_id: OnlyBacktestRunId) -> OnlyBacktestRun: ...


@dataclass(frozen=True, slots=True)
class OnlyBacktestArtifactContent:
    content: bytes
    media_type: str


class OnlyBacktestQueryService:
    def __init__(
        self,
        runs: _RunReader,
        evidence: OnlyBacktestEvidenceStore,
        creation: OnlyBacktestCreationQuery | None = None,
        runtime_generations: OnlyBacktestRuntimeGenerationWorkAuthority | None = None,
        admission: OnlyBacktestAdmissionService | None = None,
    ) -> None:
        self._runs = runs
        self._evidence = evidence
        self._creation = creation
        self._runtime_generations = runtime_generations
        self._admission = admission

    def creation_context(self) -> dict[str, Any]:
        if self._creation is None:
            raise OnlyBacktestStateConflictError("Backtest creation context is unavailable")
        return self._creation.get()

    def recent(self) -> tuple[OnlyBacktestRun, ...]:
        return self._runs.recent_runs()

    def result(self, run_id: OnlyBacktestRunId) -> dict[str, Any]:
        run = self.get(run_id)
        manifest = self.evidence(run_id)
        try:
            value = json.loads(self.artifact(run_id, "result.json").content)
            if (
                type(value) is not dict
                or value.get("result_fingerprint") != manifest.result_fingerprint
                or value.get("determinism_fingerprint") != manifest.determinism_fingerprint
            ):
                raise ValueError("owning result identity differs")
        except (ValueError, TypeError, UnicodeError) as exc:
            raise OnlyBacktestIntegrityError("BACKTEST_EVIDENCE_CORRUPT", run_id.value) from exc
        if run.specification.order_policy is None:
            return {"schema_version": 1, "implementation": "PYTHON", "runtime": None, "result": value}
        if self._admission is None or self._runtime_generations is None:
            raise OnlyBacktestIntegrityError("BACKTEST_EVIDENCE_CORRUPT", "Native owning readers are unavailable")
        return self._admission.verify_evidence(run, manifest, self._evidence, self._runtime_generations)

    def get(self, run_id: OnlyBacktestRunId) -> OnlyBacktestRun:
        return self._runs.load(run_id)

    def evidence(self, run_id: OnlyBacktestRunId) -> OnlyBacktestEvidenceManifest:
        run = self._runs.load(run_id)
        if run.state is not OnlyBacktestRunState.COMPLETED or run.evidence_fingerprint is None:
            raise OnlyBacktestStateConflictError("Backtest Evidence is unavailable before completion")
        try:
            manifest = self._evidence.load_verified(run.evidence_fingerprint)
        except ValueError as exc:
            raise OnlyBacktestIntegrityError("BACKTEST_EVIDENCE_CORRUPT", run_id.value) from exc
        if (
            manifest.backtest_run_id != run_id.value
            or manifest.result_fingerprint != run.result_fingerprint
            or manifest.determinism_fingerprint != run.determinism_fingerprint
        ):
            raise OnlyBacktestIntegrityError("BACKTEST_EVIDENCE_CORRUPT", run_id.value)
        return manifest

    def artifact(self, run_id: OnlyBacktestRunId, name: str) -> OnlyBacktestArtifactContent:
        manifest = self.evidence(run_id)
        try:
            content, media_type = self._evidence.read_artifact(manifest.evidence_fingerprint, name)
        except ValueError as exc:
            code = "BACKTEST_ARTIFACT_NOT_FOUND" if "NOT_FOUND" in str(exc) else "BACKTEST_EVIDENCE_CORRUPT"
            if code == "BACKTEST_ARTIFACT_NOT_FOUND":
                raise OnlyBacktestArtifactNotFoundError(name) from exc
            raise OnlyBacktestIntegrityError(code, run_id.value) from exc
        return OnlyBacktestArtifactContent(content, media_type)


__all__ = [name for name in globals() if name.startswith("Only")]
