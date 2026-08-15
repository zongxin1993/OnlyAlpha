"""Verified atomic immutable JSON Research Result authority."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Protocol

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


class OnlyJsonResearchResultStore:
    def __init__(self, root: Path, statistics_result_store: _StatisticsResultStore) -> None:
        self._root = root
        self._statistics_result_store = statistics_result_store

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
        content = only_research_result_content_fingerprint(tuple(actual_references))
        if content != manifest.research_result_content_fingerprint:
            raise ValueError("Research Result content fingerprint mismatch")
        result = only_research_result_fingerprint(manifest.research_result_plan_fingerprint, content)
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
