"""Verified atomic immutable JSON Research Result authority."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Protocol

from onlyalpha.research.calculation.result import OnlyResearchCalculationResult
from onlyalpha.research.evaluation.result import OnlyResearchStatisticsResult

from .errors import OnlyResearchResultStoreError
from .identity import only_research_result_content_fingerprint, only_research_result_fingerprint
from .result import (
    OnlyResearchResult,
    OnlyResearchResultDisposition,
    OnlyResearchResultManifest,
    OnlyResearchResultOutcome,
)


class _StatisticsResultStore(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchStatisticsResult: ...


class _CalculationResultStore(Protocol):
    def load_verified(self, calculation_fingerprint: str) -> OnlyResearchCalculationResult: ...


class OnlyJsonResearchResultStore:
    def __init__(
        self,
        root: Path,
        statistics_result_store: _StatisticsResultStore,
        calculation_result_store: _CalculationResultStore | None = None,
    ) -> None:
        self._root = root
        self._statistics_result_store = statistics_result_store
        self._calculation_result_store = calculation_result_store

    def exists(self, research_result_plan_fingerprint: str) -> bool:
        return self._target(research_result_plan_fingerprint).exists()

    def commit(self, result: OnlyResearchResult) -> OnlyResearchResultOutcome:
        candidate = self._admit(result)
        plan_fingerprint = candidate.manifest.research_result_plan_fingerprint
        target = self._target(plan_fingerprint)
        if target.exists():
            existing = self._resolve_existing(candidate)
            return self._outcome(OnlyResearchResultDisposition.REUSED, existing)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        stage.mkdir()
        try:
            (stage / "manifest.json").write_text(
                json.dumps(candidate.manifest.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            try:
                self._read_verified(stage, plan_fingerprint)
            except OnlyResearchResultStoreError as exc:
                raise OnlyResearchResultStoreError(
                    "RESEARCH_RESULT_COMMIT_FAILED", "staged Research Result verification failed"
                ) from exc
            try:
                os.rename(stage, target)
            except OSError:
                if not target.exists():
                    raise
                existing = self._resolve_existing(candidate)
                return self._outcome(OnlyResearchResultDisposition.REUSED, existing)
            committed = self.load_verified(plan_fingerprint)
            return self._outcome(OnlyResearchResultDisposition.EXECUTED, committed)
        except OnlyResearchResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_COMMIT_FAILED", "atomic publication failed") from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def load_verified(self, research_result_plan_fingerprint: str) -> OnlyResearchResult:
        return self._read_verified(self._target(research_result_plan_fingerprint), research_result_plan_fingerprint)

    def _admit(self, result: OnlyResearchResult) -> OnlyResearchResult:
        if not isinstance(result, OnlyResearchResult):
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_INVALID", "Result contract is invalid")
        try:
            self._verify_upstream(result.manifest)
            return result
        except OnlyResearchResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_INVALID", str(exc)) from exc

    def _resolve_existing(self, candidate: OnlyResearchResult) -> OnlyResearchResult:
        existing = self.load_verified(candidate.manifest.research_result_plan_fingerprint)
        if (
            existing.manifest.research_result_content_fingerprint
            != candidate.manifest.research_result_content_fingerprint
            or existing.manifest.research_result_fingerprint != candidate.manifest.research_result_fingerprint
        ):
            raise OnlyResearchResultStoreError(
                "DETERMINISTIC_RESULT_CONFLICT", candidate.manifest.research_result_plan_fingerprint
            )
        return existing

    def _read_verified(self, root: Path, expected_plan_fingerprint: str) -> OnlyResearchResult:
        if not root.is_dir():
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_NOT_FOUND", expected_plan_fingerprint)
        try:
            manifest_path = root / "manifest.json"
            if root.is_symlink() or manifest_path.is_symlink():
                raise ValueError("Research Result authority may not contain symlinks")
            if {item.name for item in root.iterdir()} != {"manifest.json"}:
                raise ValueError("unexpected Research Result files")
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Research Result manifest must be an object")
            manifest = OnlyResearchResultManifest.from_dict(payload)
            if manifest.research_result_plan_fingerprint != expected_plan_fingerprint:
                raise ValueError("Research Result path identity mismatch")
            self._verify_upstream(manifest)
            return OnlyResearchResult(manifest)
        except OnlyResearchResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_CORRUPT", str(exc)) from exc

    def _verify_upstream(self, manifest: OnlyResearchResultManifest) -> None:
        schema_version = getattr(manifest, "schema_version", 1)
        dataset: str | None = None
        actual_references = []
        for reference in manifest.statistics_results:
            upstream = self._statistics_result_store.load_verified(reference.statistics_fingerprint)
            upstream_manifest = upstream.manifest
            if upstream_manifest.statistics_fingerprint != reference.statistics_fingerprint:
                raise ValueError("Research Result Statistics logical identity mismatch")
            if upstream_manifest.statistics_result_fingerprint != reference.statistics_result_fingerprint:
                raise ValueError("Research Result Statistics Result identity mismatch")
            if dataset is None:
                dataset = upstream_manifest.dataset_snapshot_fingerprint
            elif dataset != upstream_manifest.dataset_snapshot_fingerprint:
                raise ValueError("Research Result Statistics Results use different Dataset Snapshots")
            actual_references.append(reference.to_dict())
        if dataset != manifest.dataset_snapshot_fingerprint:
            raise ValueError("Research Result Dataset Snapshot linkage mismatch")
        actual_calculations = []
        if schema_version == 2:
            if self._calculation_result_store is None:
                raise ValueError("Scientific Research Result requires Calculation Result Store")
            for calculation_member, calculation_reference in zip(
                manifest.plan.calculations, manifest.calculation_results, strict=True
            ):
                calculation_upstream = self._calculation_result_store.load_verified(
                    calculation_reference.calculation_fingerprint
                )
                calculation_manifest = calculation_upstream.manifest
                if calculation_manifest.calculation_fingerprint != calculation_member.calculation_fingerprint:
                    raise ValueError("Research Result Calculation logical identity mismatch")
                if (
                    calculation_manifest.calculation_result_fingerprint
                    != calculation_reference.calculation_result_fingerprint
                ):
                    raise ValueError("Research Result Calculation Result identity mismatch")
                if calculation_manifest.dataset_snapshot_fingerprint != manifest.dataset_snapshot_fingerprint:
                    raise ValueError("Research Result Calculation Dataset linkage mismatch")
                if calculation_manifest.calculation_graph_fingerprint != calculation_member.graph_fingerprint:
                    raise ValueError("Research Result Calculation Graph linkage mismatch")
                actual_calculations.append(calculation_reference.to_dict())
            calculations = {
                item.calculation_fingerprint: self._calculation_result_store.load_verified(item.calculation_fingerprint)
                for item in manifest.calculation_results
            }
            for member in manifest.plan.published_series:
                graph = calculations[member.calculation_fingerprint].manifest.calculation_graph
                node = next((item for item in graph.nodes if item.fingerprint == member.node_fingerprint), None)
                if node is None:
                    raise ValueError("Research Result scientific node linkage mismatch")
                output = next((item for item in node.definition.outputs if item.name == member.output_name), None)
                if output is None:
                    raise ValueError("Research Result scientific output linkage mismatch")
            for signal_member in manifest.plan.signals:
                graph = calculations[signal_member.calculation_fingerprint].manifest.calculation_graph
                node = next((item for item in graph.nodes if item.fingerprint == signal_member.node_fingerprint), None)
                if node is None:
                    raise ValueError("Research Result scientific node linkage mismatch")
                output = next(
                    (item for item in node.definition.outputs if item.name == signal_member.output_name), None
                )
                if output is None or output.semantic_type != signal_member.role:
                    raise ValueError("Research Result scientific output linkage mismatch")
        content = only_research_result_content_fingerprint(
            tuple(actual_references), tuple(actual_calculations), schema_version=schema_version
        )
        if content != manifest.research_result_content_fingerprint:
            raise ValueError("Research Result content fingerprint mismatch")
        result = only_research_result_fingerprint(
            manifest.research_result_plan_fingerprint, content, schema_version=schema_version
        )
        if result != manifest.research_result_fingerprint:
            raise ValueError("Research Result fingerprint mismatch")

    def _target(self, fingerprint: str) -> Path:
        if not _valid_sha(fingerprint):
            raise OnlyResearchResultStoreError("RESEARCH_RESULT_NOT_FOUND", "invalid Research Result Plan fingerprint")
        return self._root / "sha256" / fingerprint[:2] / fingerprint

    @staticmethod
    def _outcome(disposition: OnlyResearchResultDisposition, result: OnlyResearchResult) -> OnlyResearchResultOutcome:
        return OnlyResearchResultOutcome(
            disposition,
            result.manifest.research_result_plan_fingerprint,
            result.manifest.research_result_fingerprint,
        )


def _valid_sha(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(item in "0123456789abcdef" for item in value)
