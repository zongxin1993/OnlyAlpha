"""Read-only Backtest Product projections over durable and immutable authorities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .errors import OnlyBacktestArtifactNotFoundError, OnlyBacktestIntegrityError, OnlyBacktestStateConflictError
from .evidence import OnlyBacktestEvidenceManifest, OnlyBacktestEvidenceStore
from .model import OnlyBacktestRun, OnlyBacktestRunId, OnlyBacktestRunState


class _RunReader(Protocol):
    def load(self, run_id: OnlyBacktestRunId) -> OnlyBacktestRun: ...


@dataclass(frozen=True, slots=True)
class OnlyBacktestArtifactContent:
    content: bytes
    media_type: str


class OnlyBacktestQueryService:
    def __init__(self, runs: _RunReader, evidence: OnlyBacktestEvidenceStore) -> None:
        self._runs = runs
        self._evidence = evidence

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
