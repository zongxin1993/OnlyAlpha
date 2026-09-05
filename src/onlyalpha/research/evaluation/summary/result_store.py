"""Verified atomic immutable JSON store for typed Summary Statistics."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from onlyalpha.canonical import only_canonical_json

from ..errors import OnlyResearchStatisticsResultStoreError
from ..result import OnlyResearchStatisticsResult
from .execution import (
    OnlyResearchCoverageSummaryExecution,
    OnlyResearchEffectSummaryExecution,
    OnlyResearchSummaryExecution,
    _validate_source,
    only_compute_research_coverage_summary,
    only_compute_research_effect_summary,
)
from .identity import (
    only_research_summary_result_content_fingerprint,
    only_research_summary_result_fingerprint,
)
from .plan import OnlyResearchSummaryPlan
from .result import (
    OnlyResearchSummary,
    OnlyResearchSummaryStatisticsResult,
    OnlyResearchSummaryStatisticsResultManifest,
    only_research_summary_from_dict,
)


class _LegacyStatisticsResultStore(Protocol):
    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchStatisticsResult: ...


class OnlyJsonResearchSummaryStatisticsResultStore:
    def __init__(
        self,
        root: Path,
        source_statistics_result_store: _LegacyStatisticsResultStore,
        *,
        audit_time: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = root
        self._source_store = source_statistics_result_store
        self._audit_time = audit_time

    def exists(self, statistics_fingerprint: str) -> bool:
        return self._target(statistics_fingerprint).exists()

    def commit(self, execution: OnlyResearchSummaryExecution) -> OnlyResearchSummaryStatisticsResult:
        if not isinstance(execution, (OnlyResearchEffectSummaryExecution, OnlyResearchCoverageSummaryExecution)):
            raise OnlyResearchStatisticsResultStoreError(
                "SUMMARY_STATISTICS_RESULT_INVALID", "execution contract is invalid"
            )
        target = self._target(execution.plan.statistics_fingerprint)
        if target.exists():
            existing = self.load_verified(execution.plan.statistics_fingerprint)
            if existing.manifest.plan != execution.plan or existing.summary != execution.summary:
                raise OnlyResearchStatisticsResultStoreError(
                    "DETERMINISTIC_RESULT_CONFLICT", execution.plan.statistics_fingerprint
                )
            return existing
        created_at = self._audit_timestamp()
        summary, content, result_fingerprint = self._admit(execution)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        stage.mkdir()
        try:
            summary_path = stage / "summary.json"
            summary_path.write_text(only_canonical_json(summary.to_dict()), encoding="utf-8")
            manifest = OnlyResearchSummaryStatisticsResultManifest(
                statistics_fingerprint=execution.plan.statistics_fingerprint,
                plan=execution.plan,
                source_statistics_fingerprint=execution.plan.source_statistics_fingerprint,
                source_statistics_result_fingerprint=execution.plan.source_statistics_result_fingerprint,
                dataset_snapshot_fingerprint=execution.plan.dataset_snapshot_fingerprint,
                result_content_fingerprint=content,
                statistics_result_fingerprint=result_fingerprint,
                summary_byte_sha256=_sha(summary_path),
                created_at=created_at,
            )
            (stage / "manifest.json").write_text(only_canonical_json(manifest.to_dict()), encoding="utf-8")
            try:
                self._read_verified(stage, execution.plan.statistics_fingerprint)
            except OnlyResearchStatisticsResultStoreError as exc:
                raise OnlyResearchStatisticsResultStoreError(
                    "SUMMARY_STATISTICS_RESULT_COMMIT_FAILED", "staged round-trip verification failed"
                ) from exc
            try:
                os.rename(stage, target)
            except OSError:
                if not target.exists():
                    raise
                return self._resolve_existing(execution, content)
            return self.load_verified(execution.plan.statistics_fingerprint)
        except OnlyResearchStatisticsResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchStatisticsResultStoreError(
                "SUMMARY_STATISTICS_RESULT_COMMIT_FAILED", "atomic publication failed"
            ) from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def load_verified(self, statistics_fingerprint: str) -> OnlyResearchSummaryStatisticsResult:
        return self._read_verified(self._target(statistics_fingerprint), statistics_fingerprint)

    def _admit(self, execution: OnlyResearchSummaryExecution) -> tuple[OnlyResearchSummary, str, str]:
        try:
            source = self._source_store.load_verified(execution.plan.source_statistics_fingerprint)
            _validate_source(source, execution.plan)
            expected = _compute_summary(source, execution)
            if execution.summary != expected:
                raise ValueError("Summary content is not the deterministic source projection")
            content = only_research_summary_result_content_fingerprint(
                execution.plan.source_statistics_fingerprint,
                execution.plan.source_statistics_result_fingerprint,
                expected.to_dict(),
            )
            return (
                expected,
                content,
                only_research_summary_result_fingerprint(execution.plan.statistics_fingerprint, content),
            )
        except OnlyResearchStatisticsResultStoreError:
            raise
        except Exception as exc:
            raise OnlyResearchStatisticsResultStoreError("SUMMARY_STATISTICS_RESULT_INVALID", str(exc)) from exc

    def _resolve_existing(
        self,
        execution: OnlyResearchSummaryExecution,
        result_content_fingerprint: str,
    ) -> OnlyResearchSummaryStatisticsResult:
        existing = self.load_verified(execution.plan.statistics_fingerprint)
        if existing.manifest.result_content_fingerprint != result_content_fingerprint:
            raise OnlyResearchStatisticsResultStoreError(
                "DETERMINISTIC_RESULT_CONFLICT", execution.plan.statistics_fingerprint
            )
        return existing

    def _read_verified(self, root: Path, expected_fingerprint: str) -> OnlyResearchSummaryStatisticsResult:
        if not root.is_dir():
            raise OnlyResearchStatisticsResultStoreError("SUMMARY_STATISTICS_RESULT_NOT_FOUND", expected_fingerprint)
        try:
            manifest_path = root / "manifest.json"
            summary_path = root / "summary.json"
            if root.is_symlink() or manifest_path.is_symlink() or summary_path.is_symlink():
                raise ValueError("Summary Statistics authority may not contain symlinks")
            if {item.name for item in root.iterdir()} != {"manifest.json", "summary.json"}:
                raise ValueError("unexpected Summary Statistics Result files")
            manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
            if not isinstance(manifest_payload, dict) or not isinstance(summary_payload, dict):
                raise ValueError("Summary Statistics JSON roots must be objects")
            manifest = OnlyResearchSummaryStatisticsResultManifest.from_dict(manifest_payload)
            if manifest.statistics_fingerprint != expected_fingerprint:
                raise ValueError("Summary Statistics path identity mismatch")
            if not summary_path.is_file() or _sha(summary_path) != manifest.summary_byte_sha256:
                raise ValueError("Summary Statistics byte hash mismatch")
            source = self._source_store.load_verified(manifest.source_statistics_fingerprint)
            _validate_source(source, manifest.plan)
            summary = only_research_summary_from_dict(summary_payload)
            expected = _compute_plan_summary(source, manifest.plan)
            if summary != expected:
                raise ValueError("Summary Statistics semantic payload mismatch")
            content = only_research_summary_result_content_fingerprint(
                manifest.source_statistics_fingerprint,
                manifest.source_statistics_result_fingerprint,
                summary.to_dict(),
            )
            if content != manifest.result_content_fingerprint:
                raise ValueError("Summary Statistics content fingerprint mismatch")
            result = only_research_summary_result_fingerprint(expected_fingerprint, content)
            if result != manifest.statistics_result_fingerprint:
                raise ValueError("Summary Statistics Result fingerprint mismatch")
            return OnlyResearchSummaryStatisticsResult(manifest, summary)
        except OnlyResearchStatisticsResultStoreError as exc:
            raise OnlyResearchStatisticsResultStoreError(
                "SUMMARY_STATISTICS_RESULT_CORRUPT", f"upstream Statistics invalid: {exc.code}"
            ) from exc
        except Exception as exc:
            raise OnlyResearchStatisticsResultStoreError("SUMMARY_STATISTICS_RESULT_CORRUPT", str(exc)) from exc

    def _target(self, fingerprint: str) -> Path:
        if not _valid_sha(fingerprint):
            raise OnlyResearchStatisticsResultStoreError(
                "SUMMARY_STATISTICS_RESULT_NOT_FOUND", "invalid Statistics fingerprint"
            )
        return self._root / "sha256" / fingerprint[:2] / fingerprint

    def _audit_timestamp(self) -> datetime:
        if self._audit_time is None:
            raise OnlyResearchStatisticsResultStoreError(
                "SUMMARY_STATISTICS_RESULT_INVALID", "audit time authority is required for commit"
            )
        value = self._audit_time()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise OnlyResearchStatisticsResultStoreError(
                "SUMMARY_STATISTICS_RESULT_INVALID", "audit time must be timezone-aware UTC"
            )
        return value


def _valid_sha(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _compute_summary(
    source: OnlyResearchStatisticsResult,
    execution: OnlyResearchSummaryExecution,
) -> OnlyResearchSummary:
    return _compute_plan_summary(source, execution.plan)


def _compute_plan_summary(source: OnlyResearchStatisticsResult, plan: OnlyResearchSummaryPlan) -> OnlyResearchSummary:
    from .plan import OnlyResearchCoverageSummaryPlan, OnlyResearchEffectSummaryPlan

    if isinstance(plan, OnlyResearchEffectSummaryPlan):
        return only_compute_research_effect_summary(source, plan)
    if isinstance(plan, OnlyResearchCoverageSummaryPlan):
        return only_compute_research_coverage_summary(source, plan)
    raise ValueError("Summary Statistics Plan kind is unsupported")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["OnlyJsonResearchSummaryStatisticsResultStore"]
