"""Put-once verified JSON Store for Search Experiment provenance V1."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import TypeVar

from onlyalpha.canonical import only_canonical_json

from .errors import OnlySearchProvenanceError, OnlySearchProvenanceStoreError
from .model import (
    OnlySearchCommitDisposition,
    OnlySearchCommitOutcome,
    OnlySearchExperimentManifestV1,
    OnlySearchIterationPlanV1,
    OnlySearchIterationResultV1,
)
from .verification import (
    OnlySearchCandidateReader,
    OnlySearchCatalogGenerationReader,
    OnlySearchDatasetReader,
    OnlySearchQualificationDecisionReader,
    OnlySearchResearchResultReader,
    verify_search_experiment_references,
    verify_search_iteration_lineage,
    verify_search_iteration_result_references,
)

_T = TypeVar("_T")


class OnlyJsonSearchProvenanceStore:
    """Exact-identity persistence; deliberately not a scheduler or Experiment Memory."""

    def __init__(
        self,
        semantic_root: Path,
        *,
        catalogs: OnlySearchCatalogGenerationReader,
        datasets: OnlySearchDatasetReader,
        candidates: OnlySearchCandidateReader | None = None,
        research_results: OnlySearchResearchResultReader | None = None,
        qualification_decisions: OnlySearchQualificationDecisionReader | None = None,
    ) -> None:
        self._semantic_root = semantic_root
        self._root = semantic_root / "research" / "search-provenance"
        self._catalogs = catalogs
        self._datasets = datasets
        self._candidates = candidates
        self._research_results = research_results
        self._qualification_decisions = qualification_decisions

    def commit_experiment(self, experiment: OnlySearchExperimentManifestV1) -> OnlySearchCommitOutcome:
        if not isinstance(experiment, OnlySearchExperimentManifestV1):
            raise OnlySearchProvenanceStoreError("SEARCH_EXPERIMENT_INVALID", "manifest contract is invalid")
        verify_search_experiment_references(experiment, catalogs=self._catalogs, datasets=self._datasets)
        if experiment.parent_experiment_fingerprint is not None:
            if experiment.parent_experiment_fingerprint == experiment.experiment_fingerprint:
                raise OnlySearchProvenanceStoreError(
                    "SEARCH_EXPERIMENT_PARENT_INVALID",
                    experiment.experiment_fingerprint,
                )
            self.load_experiment_verified(experiment.parent_experiment_fingerprint)
        return self._commit(
            "experiments",
            experiment.experiment_fingerprint,
            experiment,
            OnlySearchExperimentManifestV1.from_dict,
            "SEARCH_EXPERIMENT",
        )

    def load_experiment_verified(self, experiment_fingerprint: str) -> OnlySearchExperimentManifestV1:
        experiment = self._load(
            "experiments",
            experiment_fingerprint,
            OnlySearchExperimentManifestV1.from_dict,
            "SEARCH_EXPERIMENT",
        )
        verify_search_experiment_references(experiment, catalogs=self._catalogs, datasets=self._datasets)
        self._verify_parent_experiment_chain(experiment)
        return experiment

    def commit_iteration_plan(self, plan: OnlySearchIterationPlanV1) -> OnlySearchCommitOutcome:
        if not isinstance(plan, OnlySearchIterationPlanV1):
            raise OnlySearchProvenanceStoreError("SEARCH_ITERATION_PLAN_INVALID", "Plan contract is invalid")
        verify_search_iteration_lineage(plan, experiments=self, plans=self._raw, results=self._raw)
        if plan.parent_iteration_result_fingerprint is not None:
            self.load_iteration_result_verified(plan.parent_iteration_result_fingerprint)
        return self._commit(
            "iteration-plans",
            plan.iteration_plan_fingerprint,
            plan,
            OnlySearchIterationPlanV1.from_dict,
            "SEARCH_ITERATION_PLAN",
        )

    def load_iteration_plan_verified(self, iteration_plan_fingerprint: str) -> OnlySearchIterationPlanV1:
        plan = self._load(
            "iteration-plans",
            iteration_plan_fingerprint,
            OnlySearchIterationPlanV1.from_dict,
            "SEARCH_ITERATION_PLAN",
        )
        verify_search_iteration_lineage(plan, experiments=self, plans=self._raw, results=self._raw)
        if plan.parent_iteration_result_fingerprint is not None:
            self.load_iteration_result_verified(plan.parent_iteration_result_fingerprint)
        return plan

    def commit_iteration_result(self, result: OnlySearchIterationResultV1) -> OnlySearchCommitOutcome:
        if not isinstance(result, OnlySearchIterationResultV1):
            raise OnlySearchProvenanceStoreError("SEARCH_ITERATION_RESULT_INVALID", "Result contract is invalid")
        plan = self.load_iteration_plan_verified(result.iteration_plan_fingerprint)
        experiment = self.load_experiment_verified(plan.experiment_fingerprint)
        verify_search_iteration_result_references(
            result,
            expected_dataset_snapshot_fingerprint=experiment.dataset_snapshot_fingerprint,
            candidates=self._candidates,
            research_results=self._research_results,
            qualification_decisions=self._qualification_decisions,
        )
        with self._terminal_result_lock(result.iteration_plan_fingerprint):
            existing_terminal = self._terminal_result_for_plan(result.iteration_plan_fingerprint)
            if existing_terminal is not None:
                if existing_terminal == result:
                    return OnlySearchCommitOutcome(
                        OnlySearchCommitDisposition.REUSED,
                        result.iteration_result_fingerprint,
                    )
                raise OnlySearchProvenanceStoreError(
                    "SEARCH_ITERATION_TERMINAL_RESULT_CONFLICT",
                    result.iteration_plan_fingerprint,
                )
            return self._commit(
                "iteration-results",
                result.iteration_result_fingerprint,
                result,
                OnlySearchIterationResultV1.from_dict,
                "SEARCH_ITERATION_RESULT",
            )

    def load_iteration_result_verified(self, iteration_result_fingerprint: str) -> OnlySearchIterationResultV1:
        result = self._load(
            "iteration-results",
            iteration_result_fingerprint,
            OnlySearchIterationResultV1.from_dict,
            "SEARCH_ITERATION_RESULT",
        )
        terminal = self._terminal_result_for_plan(result.iteration_plan_fingerprint)
        if terminal != result:
            raise OnlySearchProvenanceStoreError(
                "SEARCH_ITERATION_TERMINAL_RESULT_CONFLICT",
                result.iteration_plan_fingerprint,
            )
        plan = self.load_iteration_plan_verified(result.iteration_plan_fingerprint)
        experiment = self.load_experiment_verified(plan.experiment_fingerprint)
        verify_search_iteration_result_references(
            result,
            expected_dataset_snapshot_fingerprint=experiment.dataset_snapshot_fingerprint,
            candidates=self._candidates,
            research_results=self._research_results,
            qualification_decisions=self._qualification_decisions,
        )
        return result

    @property
    def _raw(self) -> _RawSearchProvenanceReader:
        return _RawSearchProvenanceReader(self)

    def _verify_parent_experiment_chain(self, experiment: OnlySearchExperimentManifestV1) -> None:
        seen = {experiment.experiment_fingerprint}
        parent_fingerprint = experiment.parent_experiment_fingerprint
        while parent_fingerprint is not None:
            if parent_fingerprint in seen:
                raise OnlySearchProvenanceStoreError("SEARCH_EXPERIMENT_PARENT_CYCLE", parent_fingerprint)
            seen.add(parent_fingerprint)
            parent = self._raw.load_experiment_verified(parent_fingerprint)
            verify_search_experiment_references(parent, catalogs=self._catalogs, datasets=self._datasets)
            parent_fingerprint = parent.parent_experiment_fingerprint

    def _terminal_result_for_plan(self, plan_fingerprint: str) -> OnlySearchIterationResultV1 | None:
        authority = self._root / "iteration-results" / "sha256"
        if not authority.exists():
            return None
        self._require_safe_path(authority)
        if not authority.is_dir():
            raise OnlySearchProvenanceStoreError("SEARCH_ITERATION_RESULT_CORRUPT", "authority root")
        found: OnlySearchIterationResultV1 | None = None
        try:
            for prefix in authority.iterdir():
                if prefix.is_symlink() or not prefix.is_dir() or len(prefix.name) != 2:
                    raise ValueError("unexpected Result prefix")
                for target in prefix.iterdir():
                    if target.name.startswith(".stage-"):
                        continue
                    result = self._load(
                        "iteration-results",
                        target.name,
                        OnlySearchIterationResultV1.from_dict,
                        "SEARCH_ITERATION_RESULT",
                    )
                    if result.iteration_plan_fingerprint == plan_fingerprint:
                        if found is not None and found != result:
                            raise ValueError("Plan already has multiple terminal Results")
                        found = result
        except OnlySearchProvenanceStoreError:
            raise
        except Exception as exc:
            raise OnlySearchProvenanceStoreError("SEARCH_ITERATION_RESULT_CORRUPT", plan_fingerprint) from exc
        return found

    @contextmanager
    def _terminal_result_lock(self, plan_fingerprint: str) -> Iterator[None]:
        lock_root = self._root / ".locks" / "iteration-results"
        self._require_safe_path(lock_root)
        lock_root.mkdir(parents=True, exist_ok=True)
        lock_path = lock_root / f"{plan_fingerprint}.lock"
        self._require_safe_path(lock_path)
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except Exception as exc:
            raise OnlySearchProvenanceStoreError(
                "SEARCH_ITERATION_RESULT_COMMIT_FAILED",
                plan_fingerprint,
            ) from exc
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _commit(
        self,
        category: str,
        fingerprint: str,
        value: _T,
        parser: Callable[[Mapping[str, object]], _T],
        code: str,
    ) -> OnlySearchCommitOutcome:
        target = self._target(category, fingerprint, code)
        if target.exists() or target.is_symlink():
            existing = self._load(category, fingerprint, parser, code)
            if existing != value:
                raise OnlySearchProvenanceStoreError(f"{code}_CONFLICT", fingerprint)
            return OnlySearchCommitOutcome(OnlySearchCommitDisposition.REUSED, fingerprint)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._require_safe_path(target)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        try:
            stage.mkdir()
            to_dict = getattr(value, "to_dict", None)
            if not callable(to_dict):
                raise TypeError("Search provenance value is not serializable")
            _write_manifest(stage / "manifest.json", to_dict())
            self._read_record(stage, fingerprint, parser, code)
            try:
                os.rename(stage, target)
            except OSError:
                if not target.exists():
                    raise
                existing = self._load(category, fingerprint, parser, code)
                if existing != value:
                    raise OnlySearchProvenanceStoreError(f"{code}_CONFLICT", fingerprint) from None
                return OnlySearchCommitOutcome(OnlySearchCommitDisposition.REUSED, fingerprint)
            _fsync_directory(target.parent)
            committed = self._load(category, fingerprint, parser, code)
            if committed != value:
                raise OnlySearchProvenanceStoreError(f"{code}_CONFLICT", fingerprint)
            return OnlySearchCommitOutcome(OnlySearchCommitDisposition.CREATED, fingerprint)
        except (OnlySearchProvenanceError, OnlySearchProvenanceStoreError):
            raise
        except Exception as exc:
            raise OnlySearchProvenanceStoreError(f"{code}_COMMIT_FAILED", fingerprint) from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def _load(
        self,
        category: str,
        fingerprint: str,
        parser: Callable[[Mapping[str, object]], _T],
        code: str,
    ) -> _T:
        target = self._target(category, fingerprint, code)
        if not target.is_dir() or target.is_symlink():
            raise OnlySearchProvenanceStoreError(f"{code}_NOT_FOUND", fingerprint)
        return self._read_record(target, fingerprint, parser, code)

    def _read_record(
        self,
        target: Path,
        fingerprint: str,
        parser: Callable[[Mapping[str, object]], _T],
        code: str,
    ) -> _T:
        try:
            self._require_safe_path(target)
            manifest = target / "manifest.json"
            if (
                target.is_symlink()
                or manifest.is_symlink()
                or {item.name for item in target.iterdir()} != {"manifest.json"}
            ):
                raise ValueError("Search provenance record contains unsafe or unexpected entries")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or any(not isinstance(key, str) for key in payload):
                raise ValueError("Search provenance manifest must be an object")
            value = parser(payload)
            expected = getattr(value, _fingerprint_attribute(code))
            if expected != fingerprint or raw != only_canonical_json(payload):
                raise ValueError("Search provenance path/content identity differs")
            return value
        except OnlySearchProvenanceStoreError:
            raise
        except Exception as exc:
            raise OnlySearchProvenanceStoreError(f"{code}_CORRUPT", fingerprint) from exc

    def _target(self, category: str, fingerprint: str, code: str) -> Path:
        if not _valid_sha(fingerprint):
            raise OnlySearchProvenanceStoreError(f"{code}_NOT_FOUND", "invalid fingerprint")
        target = self._root / category / "sha256" / fingerprint[:2] / fingerprint
        self._require_safe_path(target)
        return target

    def _require_safe_path(self, target: Path) -> None:
        if self._semantic_root.is_symlink() or self._root.is_symlink():
            raise OnlySearchProvenanceStoreError("SEARCH_PROVENANCE_UNSAFE_PATH", str(target))
        current = target
        while current != self._semantic_root:
            if current.exists() and current.is_symlink():
                raise OnlySearchProvenanceStoreError("SEARCH_PROVENANCE_UNSAFE_PATH", str(target))
            if current == current.parent:
                raise OnlySearchProvenanceStoreError("SEARCH_PROVENANCE_UNSAFE_PATH", str(target))
            current = current.parent


class _RawSearchProvenanceReader:
    """Internal decoder used to verify a finite lineage without recursive public loads."""

    def __init__(self, store: OnlyJsonSearchProvenanceStore) -> None:
        self._store = store

    def load_experiment_verified(self, fingerprint: str) -> OnlySearchExperimentManifestV1:
        return self._store._load(
            "experiments",
            fingerprint,
            OnlySearchExperimentManifestV1.from_dict,
            "SEARCH_EXPERIMENT",
        )

    def load_iteration_plan_verified(self, fingerprint: str) -> OnlySearchIterationPlanV1:
        return self._store._load(
            "iteration-plans",
            fingerprint,
            OnlySearchIterationPlanV1.from_dict,
            "SEARCH_ITERATION_PLAN",
        )

    def load_iteration_result_verified(self, fingerprint: str) -> OnlySearchIterationResultV1:
        return self._store._load(
            "iteration-results",
            fingerprint,
            OnlySearchIterationResultV1.from_dict,
            "SEARCH_ITERATION_RESULT",
        )


def _fingerprint_attribute(code: str) -> str:
    return {
        "SEARCH_EXPERIMENT": "experiment_fingerprint",
        "SEARCH_ITERATION_PLAN": "iteration_plan_fingerprint",
        "SEARCH_ITERATION_RESULT": "iteration_result_fingerprint",
    }[code]


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _write_manifest(path: Path, payload: Mapping[str, object]) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as stream:
            stream.write(only_canonical_json(payload))
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["OnlyJsonSearchProvenanceStore"]
