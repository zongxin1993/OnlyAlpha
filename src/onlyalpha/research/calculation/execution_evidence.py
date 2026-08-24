"""Immutable provenance for the exact implementation that produced a Calculation Result."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from onlyalpha.canonical import only_canonical_fingerprint, only_canonical_json

from .errors import OnlyResearchCalculationError
from .execution import OnlyResearchCalculationExecution, OnlyResearchCalculationImplementationBinding
from .result import OnlyResearchCalculationResult


@dataclass(frozen=True, slots=True)
class OnlyResearchCalculationExecutionEvidence:
    calculation_fingerprint: str
    dataset_snapshot_fingerprint: str
    calculation_graph_fingerprint: str
    calculation_result_fingerprint: str
    result_content_fingerprint: str
    research_implementation_bindings: tuple[OnlyResearchCalculationImplementationBinding, ...]
    execution_contract_version: str = "RESEARCH_CALCULATION_EXECUTION_V1"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not self.execution_contract_version.strip():
            raise ValueError("Research Execution Evidence contract is invalid")
        for name in (
            "calculation_fingerprint",
            "dataset_snapshot_fingerprint",
            "calculation_graph_fingerprint",
            "calculation_result_fingerprint",
            "result_content_fingerprint",
        ):
            _sha(getattr(self, name), name)
        canonical = tuple(sorted(self.research_implementation_bindings))
        if canonical != self.research_implementation_bindings or len(
            {item.node_fingerprint for item in canonical}
        ) != len(canonical):
            raise ValueError("Research implementation bindings must be canonical, non-empty and unique")

    @property
    def evidence_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.research.calculation-execution-evidence",
                **self.to_dict(include_fingerprint=False),
            }
        )

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "calculation_fingerprint": self.calculation_fingerprint,
            "dataset_snapshot_fingerprint": self.dataset_snapshot_fingerprint,
            "calculation_graph_fingerprint": self.calculation_graph_fingerprint,
            "calculation_result_fingerprint": self.calculation_result_fingerprint,
            "result_content_fingerprint": self.result_content_fingerprint,
            "research_implementation_bindings": [
                {
                    "node_fingerprint": item.node_fingerprint,
                    "research_implementation_fingerprint": item.research_implementation_fingerprint,
                }
                for item in self.research_implementation_bindings
            ],
            "execution_contract_version": self.execution_contract_version,
        }
        if include_fingerprint:
            payload["evidence_fingerprint"] = self.evidence_fingerprint
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> OnlyResearchCalculationExecutionEvidence:
        expected = {
            "schema_version",
            "calculation_fingerprint",
            "dataset_snapshot_fingerprint",
            "calculation_graph_fingerprint",
            "calculation_result_fingerprint",
            "result_content_fingerprint",
            "research_implementation_bindings",
            "execution_contract_version",
            "evidence_fingerprint",
        }
        if set(payload) != expected or not isinstance(payload["research_implementation_bindings"], list):
            raise ValueError("Research Execution Evidence fields are invalid")
        bindings: list[OnlyResearchCalculationImplementationBinding] = []
        for raw in payload["research_implementation_bindings"]:
            if not isinstance(raw, Mapping) or set(raw) != {
                "node_fingerprint",
                "research_implementation_fingerprint",
            }:
                raise ValueError("Research implementation binding fields are invalid")
            bindings.append(
                OnlyResearchCalculationImplementationBinding(
                    _string(raw, "node_fingerprint"),
                    _string(raw, "research_implementation_fingerprint"),
                )
            )
        evidence = cls(
            _string(payload, "calculation_fingerprint"),
            _string(payload, "dataset_snapshot_fingerprint"),
            _string(payload, "calculation_graph_fingerprint"),
            _string(payload, "calculation_result_fingerprint"),
            _string(payload, "result_content_fingerprint"),
            tuple(bindings),
            _string(payload, "execution_contract_version"),
            _integer(payload, "schema_version"),
        )
        if payload["evidence_fingerprint"] != evidence.evidence_fingerprint:
            raise ValueError("Research Execution Evidence identity differs")
        return evidence


class OnlyResearchCalculationExecutionEvidenceStore:
    """Verified content-addressed evidence; callers cannot submit claimed provenance."""

    def __init__(self, semantic_root: Path) -> None:
        self._root = semantic_root / "calculation-execution-evidence" / "sha256"

    def exists(self, evidence_fingerprint: str) -> bool:
        return self._target(_fingerprint(evidence_fingerprint)).is_dir()

    def commit_execution(
        self,
        execution: OnlyResearchCalculationExecution,
        result: OnlyResearchCalculationResult,
    ) -> OnlyResearchCalculationExecutionEvidence:
        manifest = result.manifest
        graph_nodes = {item.fingerprint for item in manifest.calculation_graph.nodes}
        binding_nodes = {item.node_fingerprint for item in execution.research_implementation_bindings}
        if (
            execution.calculation_fingerprint != manifest.calculation_fingerprint
            or execution.dataset_snapshot_fingerprint != manifest.dataset_snapshot_fingerprint
            or execution.calculation_graph_fingerprint != manifest.calculation_graph_fingerprint
            or graph_nodes != binding_nodes
        ):
            raise OnlyResearchCalculationError(
                "RESEARCH_EXECUTION_IDENTITY_MISMATCH",
                "Execution, Result, Graph, Dataset, or implementation binding linkage differs",
            )
        evidence = OnlyResearchCalculationExecutionEvidence(
            manifest.calculation_fingerprint,
            manifest.dataset_snapshot_fingerprint,
            manifest.calculation_graph_fingerprint,
            manifest.calculation_result_fingerprint,
            manifest.result_content_fingerprint,
            execution.research_implementation_bindings,
        )
        return self._publish(evidence)

    def load_verified(self, evidence_fingerprint: str) -> OnlyResearchCalculationExecutionEvidence:
        fingerprint = _fingerprint(evidence_fingerprint)
        return self._read_verified(self._target(fingerprint), fingerprint)

    def require_for_result(self, result: OnlyResearchCalculationResult) -> OnlyResearchCalculationExecutionEvidence:
        manifest = result.manifest
        if not self._root.exists():
            raise OnlyResearchCalculationError(
                "RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND", manifest.calculation_result_fingerprint
            )
        if not self._root.is_dir() or self._root.is_symlink():
            raise OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_CORRUPT", "authority root")
        matches: list[OnlyResearchCalculationExecutionEvidence] = []
        try:
            for prefix in sorted(self._root.iterdir(), key=lambda item: item.name):
                if prefix.is_symlink() or not prefix.is_dir() or len(prefix.name) != 2:
                    raise ValueError("unexpected Research Execution Evidence prefix")
                for target in sorted(prefix.iterdir(), key=lambda item: item.name):
                    evidence = self.load_verified(target.name)
                    if (
                        evidence.calculation_fingerprint == manifest.calculation_fingerprint
                        and evidence.dataset_snapshot_fingerprint == manifest.dataset_snapshot_fingerprint
                        and evidence.calculation_graph_fingerprint == manifest.calculation_graph_fingerprint
                        and evidence.calculation_result_fingerprint == manifest.calculation_result_fingerprint
                        and evidence.result_content_fingerprint == manifest.result_content_fingerprint
                    ):
                        matches.append(evidence)
        except OnlyResearchCalculationError:
            raise
        except Exception as exc:
            raise OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_CORRUPT", "authority scan") from exc
        if not matches:
            raise OnlyResearchCalculationError(
                "RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND", manifest.calculation_result_fingerprint
            )
        if len(matches) != 1:
            raise OnlyResearchCalculationError(
                "RESEARCH_EXECUTION_IDENTITY_MISMATCH",
                "Calculation Result has more than one exact producer evidence; explicit provenance is required",
            )
        return matches[0]

    def _publish(self, evidence: OnlyResearchCalculationExecutionEvidence) -> OnlyResearchCalculationExecutionEvidence:
        fingerprint = evidence.evidence_fingerprint
        target = self._target(fingerprint)
        if target.exists() or target.is_symlink():
            existing = self.load_verified(fingerprint)
            if existing != evidence:
                raise OnlyResearchCalculationError("DETERMINISTIC_EXECUTION_EVIDENCE_CONFLICT", fingerprint)
            return existing
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        try:
            stage.mkdir()
            manifest = stage / "manifest.json"
            with manifest.open("x", encoding="utf-8") as stream:
                stream.write(only_canonical_json(evidence.to_dict()))
                stream.flush()
                os.fsync(stream.fileno())
            self._read_verified(stage, fingerprint)
            directory = os.open(stage, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            os.rename(stage, target)
            parent = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)
            return self.load_verified(fingerprint)
        except OnlyResearchCalculationError:
            raise
        except OSError as exc:
            if target.is_dir():
                existing = self.load_verified(fingerprint)
                if existing == evidence:
                    return existing
            raise OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_COMMIT_FAILED", fingerprint) from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def _read_verified(self, root: Path, expected: str) -> OnlyResearchCalculationExecutionEvidence:
        if not root.is_dir():
            raise OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND", expected)
        try:
            manifest = root / "manifest.json"
            if root.is_symlink() or manifest.is_symlink():
                raise ValueError("Research Execution Evidence may not contain symlinks")
            if {item.name for item in root.iterdir()} != {"manifest.json"} or not manifest.is_file():
                raise ValueError("unexpected Research Execution Evidence entries")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, Mapping):
                raise ValueError("Research Execution Evidence manifest must be an object")
            evidence = OnlyResearchCalculationExecutionEvidence.from_dict(payload)
            if evidence.evidence_fingerprint != expected or raw != only_canonical_json(payload):
                raise ValueError("Research Execution Evidence path/content identity differs")
            return evidence
        except OnlyResearchCalculationError:
            raise
        except Exception as exc:
            raise OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_CORRUPT", expected) from exc

    def _target(self, fingerprint: str) -> Path:
        return self._root / fingerprint[:2] / fingerprint


def _fingerprint(value: str) -> str:
    try:
        _sha(value, "fingerprint")
    except ValueError as exc:
        raise OnlyResearchCalculationError("RESEARCH_EXECUTION_EVIDENCE_NOT_FOUND", "invalid fingerprint") from exc
    return value


def _sha(value: str, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256")


def _string(payload: Mapping[str, object], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _integer(payload: Mapping[str, object], key: str) -> int:
    value = payload[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    return value


__all__ = [name for name in globals() if name.startswith("Only")]
