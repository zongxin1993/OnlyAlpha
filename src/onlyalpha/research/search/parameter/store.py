"""Put-once content-addressed authority for adaptive parameter search."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar, cast

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.experiment import OnlySearchCommitDisposition, OnlySearchCommitOutcome

from .errors import OnlyParameterSearchStoreError
from .model import (
    OnlyParameterFactorSearchSpaceV1,
    OnlyParameterGraphProposalV1,
    OnlyParameterSearchAlgorithmManifestV1,
    OnlyParameterSearchFeedbackDecisionV1,
    OnlyParameterSearchPolicyV1,
)

_T = TypeVar("_T")


class OnlyJsonParameterSearchStore:
    """Durable exact objects plus a single conflict-checked Experiment frontier."""

    def __init__(self, semantic_root: Path) -> None:
        self._semantic_root = semantic_root
        self._root = semantic_root / "research" / "parameter-search"

    def commit_search_space(self, value: OnlyParameterFactorSearchSpaceV1) -> OnlySearchCommitOutcome:
        return self._commit(
            "spaces",
            value.search_space_fingerprint,
            value,
            OnlyParameterFactorSearchSpaceV1.from_dict,
            "PARAMETER_SEARCH_SPACE",
        )

    def load_search_space_intrinsic_verified(self, fingerprint: str) -> OnlyParameterFactorSearchSpaceV1:
        return self._load("spaces", fingerprint, OnlyParameterFactorSearchSpaceV1.from_dict, "PARAMETER_SEARCH_SPACE")

    def commit_policy(self, value: OnlyParameterSearchPolicyV1) -> OnlySearchCommitOutcome:
        return self._commit(
            "policies",
            value.policy_fingerprint,
            value,
            OnlyParameterSearchPolicyV1.from_dict,
            "PARAMETER_SEARCH_POLICY",
        )

    def load_policy_intrinsic_verified(self, fingerprint: str) -> OnlyParameterSearchPolicyV1:
        return self._load("policies", fingerprint, OnlyParameterSearchPolicyV1.from_dict, "PARAMETER_SEARCH_POLICY")

    def commit_proposal(self, value: OnlyParameterGraphProposalV1) -> OnlySearchCommitOutcome:
        return self._commit(
            "proposals", value.proposal_fingerprint, value, OnlyParameterGraphProposalV1.from_dict, "PARAMETER_PROPOSAL"
        )

    def load_proposal_intrinsic_verified(self, fingerprint: str) -> OnlyParameterGraphProposalV1:
        return self._load("proposals", fingerprint, OnlyParameterGraphProposalV1.from_dict, "PARAMETER_PROPOSAL")

    def commit_algorithm_manifest(self, value: OnlyParameterSearchAlgorithmManifestV1) -> OnlySearchCommitOutcome:
        return self._commit(
            "algorithm-manifests",
            value.implementation_fingerprint,
            value,
            OnlyParameterSearchAlgorithmManifestV1.from_dict,
            "PARAMETER_ALGORITHM_MANIFEST",
        )

    def load_algorithm_manifest_intrinsic_verified(self, fingerprint: str) -> OnlyParameterSearchAlgorithmManifestV1:
        return self._load(
            "algorithm-manifests",
            fingerprint,
            OnlyParameterSearchAlgorithmManifestV1.from_dict,
            "PARAMETER_ALGORITHM_MANIFEST",
        )

    def commit_feedback_decision(
        self,
        value: OnlyParameterSearchFeedbackDecisionV1,
        *,
        expected_predecessor_fingerprint: str | None,
    ) -> OnlySearchCommitOutcome:
        """Publish the decision and advance exactly one Experiment frontier."""

        lock = self._root / "frontiers" / f".{value.experiment_fingerprint}.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with self._locked(lock):
            current = self.load_frontier_fingerprint(value.experiment_fingerprint)
            if current == value.feedback_decision_fingerprint:
                stored = self.load_feedback_decision_intrinsic_verified(current)
                if stored != value:
                    raise OnlyParameterSearchStoreError("PARAMETER_FEEDBACK_DECISION_CONFLICT", current)
                return OnlySearchCommitOutcome(OnlySearchCommitDisposition.REUSED, current)
            if current != expected_predecessor_fingerprint:
                raise OnlyParameterSearchStoreError(
                    "PARAMETER_FEEDBACK_FRONTIER_CONFLICT", value.experiment_fingerprint
                )
            outcome = self._commit(
                "feedback-decisions",
                value.feedback_decision_fingerprint,
                value,
                OnlyParameterSearchFeedbackDecisionV1.from_dict,
                "PARAMETER_FEEDBACK_DECISION",
            )
            locator = self._frontier_path(value.experiment_fingerprint)
            locator.parent.mkdir(parents=True, exist_ok=True)
            stage = locator.parent / f".{locator.name}.{uuid.uuid4().hex}.stage"
            stage.write_text(value.feedback_decision_fingerprint + "\n", encoding="ascii")
            with stage.open("rb") as handle:
                os.fsync(handle.fileno())
            os.replace(stage, locator)
            self._fsync(locator.parent)
            return outcome

    def load_feedback_decision_intrinsic_verified(self, fingerprint: str) -> OnlyParameterSearchFeedbackDecisionV1:
        return self._load(
            "feedback-decisions",
            fingerprint,
            OnlyParameterSearchFeedbackDecisionV1.from_dict,
            "PARAMETER_FEEDBACK_DECISION",
        )

    def load_frontier_fingerprint(self, experiment_fingerprint: str) -> str | None:
        path = self._frontier_path(experiment_fingerprint)
        if not path.exists():
            return None
        try:
            self._require_safe(path)
            if path.is_symlink() or not path.is_file():
                raise ValueError("unsafe frontier")
            value = path.read_text(encoding="ascii")
            if not value.endswith("\n") or value.count("\n") != 1:
                raise ValueError("non-canonical frontier")
            fingerprint = value[:-1]
            decision = self.load_feedback_decision_intrinsic_verified(fingerprint)
            if decision.experiment_fingerprint != experiment_fingerprint:
                raise ValueError("frontier Experiment differs")
            return fingerprint
        except OnlyParameterSearchStoreError:
            raise
        except Exception as exc:
            raise OnlyParameterSearchStoreError("PARAMETER_FEEDBACK_FRONTIER_CORRUPT", experiment_fingerprint) from exc

    def _commit(
        self,
        category: str,
        fingerprint: str,
        value: object,
        parser: Callable[[Mapping[str, object]], _T],
        code: str,
    ) -> OnlySearchCommitOutcome:
        payload = payload_for(value)
        target = self._target(category, fingerprint, code)
        lock = target.parent / f".{fingerprint}.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with self._locked(lock):
            if target.exists():
                existing = self._load(category, fingerprint, parser, code)
                if only_canonical_json(payload) != only_canonical_json(payload_for(existing)):
                    raise OnlyParameterSearchStoreError(f"{code}_CONFLICT", fingerprint)
                return OnlySearchCommitOutcome(OnlySearchCommitDisposition.REUSED, fingerprint)
            stage = target.parent / f".{fingerprint}.{uuid.uuid4().hex}.stage"
            try:
                stage.mkdir(mode=0o700)
                manifest = stage / "manifest.json"
                manifest.write_text(only_canonical_json(payload), encoding="utf-8")
                with manifest.open("rb") as handle:
                    os.fsync(handle.fileno())
                decoded = json.loads(manifest.read_text(encoding="utf-8"))
                if not isinstance(decoded, dict):
                    raise ValueError("parameter-search manifest must be an object")
                parser(decoded)
                os.replace(stage, target)
                self._fsync(target.parent)
            except Exception as exc:
                if stage.exists():
                    shutil.rmtree(stage)
                if isinstance(exc, OnlyParameterSearchStoreError):
                    raise
                raise OnlyParameterSearchStoreError(f"{code}_COMMIT_FAILED", fingerprint) from exc
        return OnlySearchCommitOutcome(OnlySearchCommitDisposition.CREATED, fingerprint)

    def _load(self, category: str, fingerprint: str, parser: Callable[[Mapping[str, object]], _T], code: str) -> _T:
        target = self._target(category, fingerprint, code)
        if not target.exists():
            raise OnlyParameterSearchStoreError(f"{code}_NOT_FOUND", fingerprint)
        try:
            self._require_safe(target)
            manifest = target / "manifest.json"
            if (
                target.is_symlink()
                or manifest.is_symlink()
                or {item.name for item in target.iterdir()} != {"manifest.json"}
            ):
                raise ValueError("unsafe or unexpected authority entries")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or raw != only_canonical_json(payload):
                raise ValueError("authority bytes are non-canonical")
            value = parser(payload)
            actual = self._identity(category, value)
            if actual != fingerprint:
                raise ValueError("authority path identity differs")
            return value
        except OnlyParameterSearchStoreError:
            raise
        except Exception as exc:
            raise OnlyParameterSearchStoreError(f"{code}_CORRUPT", fingerprint) from exc

    @staticmethod
    def _identity(category: str, value: object) -> str:
        typed = cast(Any, value)
        if category == "spaces":
            result: str = typed.search_space_fingerprint
        elif category == "policies":
            result = typed.policy_fingerprint
        elif category == "proposals":
            result = typed.proposal_fingerprint
        elif category == "algorithm-manifests":
            result = typed.implementation_fingerprint
        elif category == "feedback-decisions":
            result = typed.feedback_decision_fingerprint
        else:  # pragma: no cover - internal category exhaustiveness
            raise ValueError("unknown parameter-search authority category")
        return result

    def _target(self, category: str, fingerprint: str, code: str) -> Path:
        if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
            raise OnlyParameterSearchStoreError(f"{code}_NOT_FOUND", "invalid fingerprint")
        target = self._root / category / "sha256" / fingerprint[:2] / fingerprint
        self._require_safe(target)
        return target

    def _frontier_path(self, experiment_fingerprint: str) -> Path:
        if len(experiment_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in experiment_fingerprint
        ):
            raise OnlyParameterSearchStoreError("PARAMETER_FEEDBACK_FRONTIER_NOT_FOUND", "invalid fingerprint")
        path = self._root / "frontiers" / "sha256" / experiment_fingerprint[:2] / experiment_fingerprint
        self._require_safe(path)
        return path

    def _require_safe(self, target: Path) -> None:
        if self._semantic_root.is_symlink() or self._root.is_symlink():
            raise OnlyParameterSearchStoreError("PARAMETER_SEARCH_UNSAFE_PATH", str(target))
        current = target
        while current != self._semantic_root:
            if current.exists() and current.is_symlink():
                raise OnlyParameterSearchStoreError("PARAMETER_SEARCH_UNSAFE_PATH", str(target))
            if current == current.parent:
                raise OnlyParameterSearchStoreError("PARAMETER_SEARCH_UNSAFE_PATH", str(target))
            current = current.parent

    @staticmethod
    @contextmanager
    def _locked(path: Path) -> Iterator[None]:
        with path.open("a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _fsync(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def payload_for(value: object) -> Mapping[str, object]:
    payload = value.to_dict()  # type: ignore[attr-defined]
    if not isinstance(payload, Mapping):
        raise TypeError("parameter-search authority payload must be an object")
    return payload


__all__ = ["OnlyJsonParameterSearchStore"]
