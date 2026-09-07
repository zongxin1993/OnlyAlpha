"""Put-once verified stores for symbolic Search Space and Proposal authorities."""

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

from .algorithm import OnlySymbolicSearchAlgorithmImplementationManifestV1
from .enumeration_result import OnlySymbolicEnumerationResultV1
from .errors import OnlySymbolicSearchStoreError
from .evaluation import OnlySymbolicResearchEvaluationContractV1
from .model import (
    OnlySymbolicFactorSearchSpace,
    OnlySymbolicFactorSearchSpaceV1,
    OnlySymbolicFactorSearchSpaceV2,
    OnlySymbolicGraphProposalV1,
    only_symbolic_search_space_from_dict,
)

_T = TypeVar("_T")


class OnlyJsonSymbolicSearchStore:
    """Exact content-addressed authority; deliberately has no latest or scan API."""

    def __init__(self, semantic_root: Path) -> None:
        self._semantic_root = semantic_root
        self._root = semantic_root / "research" / "symbolic-search"

    def commit_search_space(self, value: OnlySymbolicFactorSearchSpace) -> OnlySearchCommitOutcome:
        if not isinstance(value, (OnlySymbolicFactorSearchSpaceV1, OnlySymbolicFactorSearchSpaceV2)):
            raise OnlySymbolicSearchStoreError("SEARCH_SPACE_INVALID", "contract is invalid")
        return self._commit(
            "spaces",
            value.search_space_fingerprint,
            value.to_dict(),
            only_symbolic_search_space_from_dict,
            "SEARCH_SPACE",
        )

    def load_search_space_intrinsic_verified(self, fingerprint: str) -> OnlySymbolicFactorSearchSpace:
        return self._load("spaces", fingerprint, only_symbolic_search_space_from_dict, "SEARCH_SPACE")

    def commit_proposal(self, value: OnlySymbolicGraphProposalV1) -> OnlySearchCommitOutcome:
        if not isinstance(value, OnlySymbolicGraphProposalV1):
            raise OnlySymbolicSearchStoreError("SEARCH_PROPOSAL_INVALID", "contract is invalid")
        return self._commit(
            "proposals",
            value.proposal_fingerprint,
            value.to_dict(),
            OnlySymbolicGraphProposalV1.from_dict,
            "SEARCH_PROPOSAL",
        )

    def load_proposal_intrinsic_verified(self, fingerprint: str) -> OnlySymbolicGraphProposalV1:
        return self._load("proposals", fingerprint, OnlySymbolicGraphProposalV1.from_dict, "SEARCH_PROPOSAL")

    def commit_evaluation_contract(self, value: OnlySymbolicResearchEvaluationContractV1) -> OnlySearchCommitOutcome:
        if not isinstance(value, OnlySymbolicResearchEvaluationContractV1):
            raise OnlySymbolicSearchStoreError("SEARCH_EVALUATION_INVALID", "contract is invalid")
        return self._commit(
            "evaluations",
            value.evaluation_contract_fingerprint,
            value.to_dict(),
            OnlySymbolicResearchEvaluationContractV1.from_dict,
            "SEARCH_EVALUATION",
        )

    def load_evaluation_contract_intrinsic_verified(self, fingerprint: str) -> OnlySymbolicResearchEvaluationContractV1:
        return self._load(
            "evaluations",
            fingerprint,
            OnlySymbolicResearchEvaluationContractV1.from_dict,
            "SEARCH_EVALUATION",
        )

    def commit_algorithm_implementation_manifest(
        self, value: OnlySymbolicSearchAlgorithmImplementationManifestV1
    ) -> OnlySearchCommitOutcome:
        if not isinstance(value, OnlySymbolicSearchAlgorithmImplementationManifestV1):
            raise OnlySymbolicSearchStoreError("SEARCH_ALGORITHM_MANIFEST_INVALID", "contract is invalid")
        return self._commit(
            "algorithm-manifests",
            value.implementation_fingerprint,
            value.to_dict(),
            OnlySymbolicSearchAlgorithmImplementationManifestV1.from_dict,
            "SEARCH_ALGORITHM_MANIFEST",
        )

    def load_algorithm_implementation_manifest_intrinsic_verified(
        self, fingerprint: str
    ) -> OnlySymbolicSearchAlgorithmImplementationManifestV1:
        return self._load(
            "algorithm-manifests",
            fingerprint,
            OnlySymbolicSearchAlgorithmImplementationManifestV1.from_dict,
            "SEARCH_ALGORITHM_MANIFEST",
        )

    def commit_enumeration_result(
        self,
        value: OnlySymbolicEnumerationResultV1,
        *,
        context: object,
    ) -> OnlySearchCommitOutcome:
        """Publish one exact ordered stream at its Experiment locator."""

        if not isinstance(value, OnlySymbolicEnumerationResultV1):
            raise OnlySymbolicSearchStoreError("SEARCH_ENUMERATION_RESULT_INVALID", "contract is invalid")
        from .historical import verify_symbolic_enumeration_result

        verify_symbolic_enumeration_result(value, context, self)
        outcome = self._commit(
            "enumeration-results",
            value.experiment_fingerprint,
            value.to_dict(),
            OnlySymbolicEnumerationResultV1.from_dict,
            "SEARCH_ENUMERATION_RESULT",
        )
        return OnlySearchCommitOutcome(outcome.disposition, value.enumeration_result_fingerprint)

    def load_enumeration_result_verified(self, experiment_fingerprint: str) -> OnlySymbolicEnumerationResultV1:
        """Load by exact Experiment locator; locator and Result identity stay distinct."""

        return self._load(
            "enumeration-results",
            experiment_fingerprint,
            OnlySymbolicEnumerationResultV1.from_dict,
            "SEARCH_ENUMERATION_RESULT",
        )

    def _commit(
        self,
        category: str,
        fingerprint: str,
        payload: Mapping[str, object],
        parser: Callable[[Mapping[str, object]], _T],
        code: str,
    ) -> OnlySearchCommitOutcome:
        target = self._target(category, fingerprint, code)
        lock = target.parent / f".{fingerprint}.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with self._locked(lock):
            if target.exists():
                existing = self._load(category, fingerprint, parser, code)
                if only_canonical_json(payload) != only_canonical_json(payload_for(existing)):
                    raise OnlySymbolicSearchStoreError(f"{code}_CONFLICT", fingerprint) from None
                return OnlySearchCommitOutcome(OnlySearchCommitDisposition.REUSED, fingerprint)
            stage = target.parent / f".{fingerprint}.{uuid.uuid4().hex}.stage"
            try:
                stage.mkdir(mode=0o700)
                manifest = stage / "manifest.json"
                manifest.write_text(only_canonical_json(payload), encoding="utf-8")
                with manifest.open("rb") as handle:
                    os.fsync(handle.fileno())
                # Verify the staged bytes before the atomic publication point.
                decoded = json.loads(manifest.read_text(encoding="utf-8"))
                if not isinstance(decoded, dict):
                    raise ValueError("symbolic manifest must be an object")
                parser(decoded)
                os.replace(stage, target)
                self._fsync(target.parent)
            except FileExistsError:
                if stage.exists():
                    shutil.rmtree(stage)
                existing = self._load(category, fingerprint, parser, code)
                if only_canonical_json(payload) != only_canonical_json(payload_for(existing)):
                    raise OnlySymbolicSearchStoreError(f"{code}_CONFLICT", fingerprint) from None
                return OnlySearchCommitOutcome(OnlySearchCommitDisposition.REUSED, fingerprint)
            except Exception as exc:
                if stage.exists():
                    shutil.rmtree(stage)
                if isinstance(exc, OnlySymbolicSearchStoreError):
                    raise
                raise OnlySymbolicSearchStoreError(f"{code}_COMMIT_FAILED", fingerprint) from exc
        loaded = self._load(category, fingerprint, parser, code)
        if only_canonical_json(payload) != only_canonical_json(payload_for(loaded)):
            raise OnlySymbolicSearchStoreError(f"{code}_CORRUPT", fingerprint)
        return OnlySearchCommitOutcome(OnlySearchCommitDisposition.CREATED, fingerprint)

    def _load(
        self,
        category: str,
        fingerprint: str,
        parser: Callable[[Mapping[str, object]], _T],
        code: str,
    ) -> _T:
        target = self._target(category, fingerprint, code)
        if not target.exists():
            raise OnlySymbolicSearchStoreError(f"{code}_NOT_FOUND", fingerprint)
        try:
            self._require_safe(target)
            manifest = target / "manifest.json"
            if (
                target.is_symlink()
                or manifest.is_symlink()
                or {item.name for item in target.iterdir()} != {"manifest.json"}
            ):
                raise ValueError("unsafe or unexpected symbolic authority entries")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict) or raw != only_canonical_json(payload):
                raise ValueError("symbolic authority bytes are non-canonical")
            value = parser(payload)
            typed_value = cast(Any, value)
            actual = (
                typed_value.search_space_fingerprint
                if category == "spaces"
                else typed_value.proposal_fingerprint
                if category == "proposals"
                else typed_value.evaluation_contract_fingerprint
                if category == "evaluations"
                else typed_value.experiment_fingerprint
                if category == "enumeration-results"
                else typed_value.implementation_fingerprint
            )
            if actual != fingerprint:
                raise ValueError("symbolic authority path identity differs")
            return value
        except OnlySymbolicSearchStoreError:
            raise
        except Exception as exc:
            raise OnlySymbolicSearchStoreError(f"{code}_CORRUPT", fingerprint) from exc

    def _target(self, category: str, fingerprint: str, code: str) -> Path:
        if len(fingerprint) != 64 or any(character not in "0123456789abcdef" for character in fingerprint):
            raise OnlySymbolicSearchStoreError(f"{code}_NOT_FOUND", "invalid fingerprint")
        target = self._root / category / "sha256" / fingerprint[:2] / fingerprint
        self._require_safe(target)
        return target

    def _require_safe(self, target: Path) -> None:
        if self._semantic_root.is_symlink() or self._root.is_symlink():
            raise OnlySymbolicSearchStoreError("SEARCH_SYMBOLIC_UNSAFE_PATH", str(target))
        current = target
        while current != self._semantic_root:
            if current.exists() and current.is_symlink():
                raise OnlySymbolicSearchStoreError("SEARCH_SYMBOLIC_UNSAFE_PATH", str(target))
            if current == current.parent:
                raise OnlySymbolicSearchStoreError("SEARCH_SYMBOLIC_UNSAFE_PATH", str(target))
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
        raise TypeError("symbolic authority payload must be an object")
    return payload


__all__ = ["OnlyJsonSymbolicSearchStore"]
