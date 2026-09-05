"""Put-once verified stores for Qualification Policy revisions and Decisions."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from decimal import Decimal
from pathlib import Path

from onlyalpha.canonical import only_canonical_json
from onlyalpha.strategy.errors import OnlyQualificationError
from onlyalpha.strategy.qualification import (
    _QUALIFICATION_DECISION_PUBLICATION_SEAL,
    OnlyQualificationCriterion,
    OnlyQualificationDecision,
    OnlyQualificationEvidenceKind,
    OnlyQualificationGate,
    OnlyQualificationPolicyRevision,
    _OnlyQualificationDecisionPublication,
)


class OnlyQualificationPolicyStore:
    def __init__(self, semantic_root: Path) -> None:
        self._root = semantic_root / "strategy" / "qualification-policies"

    def put(self, policy: OnlyQualificationPolicyRevision) -> OnlyQualificationPolicyRevision:
        target = self._target(policy.policy_id, policy.policy_version)
        self._require_safe_policy_path(target)
        if target.exists() or target.is_symlink():
            existing = self.load_exact(policy.policy_id, policy.policy_version)
            if existing != policy:
                raise OnlyQualificationError(
                    "QUALIFICATION_POLICY_IDENTITY_CONFLICT", f"{policy.policy_id}@{policy.policy_version}"
                )
            return existing
        return self._publish(target, policy)

    def load_exact(self, policy_id: str, policy_version: str) -> OnlyQualificationPolicyRevision:
        target = self._target(policy_id, policy_version)
        self._require_safe_policy_path(target)
        if not target.is_dir() or target.is_symlink():
            raise OnlyQualificationError("QUALIFICATION_POLICY_NOT_FOUND", f"{policy_id}@{policy_version}")
        try:
            manifest = target / "manifest.json"
            if manifest.is_symlink() or {item.name for item in target.iterdir()} != {"manifest.json"}:
                raise ValueError("unexpected Policy entries")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("Policy manifest must be an object")
            policy = OnlyQualificationPolicyRevision.from_dict(payload)
            if policy.policy_id != policy_id or policy.policy_version != policy_version:
                raise ValueError("Policy path identity differs")
            if raw != only_canonical_json(payload):
                raise ValueError("Policy manifest is not canonical")
            return policy
        except OnlyQualificationError:
            raise
        except Exception as exc:
            raise OnlyQualificationError(
                "QUALIFICATION_POLICY_IDENTITY_CONFLICT", f"{policy_id}@{policy_version}"
            ) from exc

    def policies(self) -> tuple[OnlyQualificationPolicyRevision, ...]:
        if not self._root.exists():
            return ()
        if self._root.is_symlink() or not self._root.is_dir():
            raise OnlyQualificationError("QUALIFICATION_POLICY_IDENTITY_CONFLICT", "authority root")
        result: list[OnlyQualificationPolicyRevision] = []
        try:
            for policy_root in sorted(self._root.iterdir(), key=lambda item: item.name):
                if policy_root.is_symlink() or not policy_root.is_dir():
                    raise ValueError("unexpected Policy identity entry")
                for version_root in sorted(policy_root.iterdir(), key=lambda item: item.name):
                    if version_root.is_symlink() or not version_root.is_dir():
                        raise ValueError("unexpected Policy version entry")
                    result.append(self.load_exact(policy_root.name, version_root.name))
        except OnlyQualificationError:
            raise
        except Exception as exc:
            raise OnlyQualificationError("QUALIFICATION_POLICY_IDENTITY_CONFLICT", "authority inventory") from exc
        return tuple(result)

    def _publish(self, target: Path, policy: OnlyQualificationPolicyRevision) -> OnlyQualificationPolicyRevision:
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        try:
            stage.mkdir()
            _write_manifest(stage / "manifest.json", policy.to_dict())
            _fsync_directory(stage)
            try:
                os.rename(stage, target)
            except OSError:
                if not target.exists():
                    raise
                existing = self.load_exact(policy.policy_id, policy.policy_version)
                if existing != policy:
                    raise OnlyQualificationError(
                        "QUALIFICATION_POLICY_IDENTITY_CONFLICT",
                        f"{policy.policy_id}@{policy.policy_version}",
                    ) from None
                return existing
            _fsync_directory(target.parent)
            return self.load_exact(policy.policy_id, policy.policy_version)
        except OnlyQualificationError:
            raise
        except Exception as exc:
            raise OnlyQualificationError(
                "QUALIFICATION_POLICY_IDENTITY_CONFLICT", f"{policy.policy_id}@{policy.policy_version}"
            ) from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)

    def _target(self, policy_id: str, policy_version: str) -> Path:
        try:
            # Reuse the Domain constructor as the exact path-admission validator.
            probe = OnlyQualificationPolicyRevision(
                policy_id,
                policy_version,
                _PROBE_POLICY.gate,
                _PROBE_POLICY.criteria,
            )
        except ValueError as exc:
            raise OnlyQualificationError("QUALIFICATION_POLICY_NOT_FOUND", f"{policy_id}@{policy_version}") from exc
        return self._root / probe.policy_id / probe.policy_version

    def _require_safe_policy_path(self, target: Path) -> None:
        if self._root.is_symlink() or target.parent.is_symlink() or target.is_symlink():
            raise OnlyQualificationError("QUALIFICATION_POLICY_IDENTITY_CONFLICT", "authority path")


class OnlyQualificationDecisionStore:
    """Read-only verified view of immutable Qualification Decisions."""

    def __init__(self, semantic_root: Path) -> None:
        self._root = semantic_root / "strategy" / "qualification-decisions" / "sha256"

    def load_verified(self, decision_fingerprint: str) -> OnlyQualificationDecision:
        target = self._target(decision_fingerprint)
        self._require_safe_decision_path(target)
        if not target.is_dir() or target.is_symlink():
            raise OnlyQualificationError("QUALIFICATION_DECISION_CORRUPT", decision_fingerprint)
        try:
            manifest = target / "manifest.json"
            if manifest.is_symlink() or {item.name for item in target.iterdir()} != {"manifest.json"}:
                raise ValueError("unexpected Decision entries")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("Decision manifest must be an object")
            decision = OnlyQualificationDecision.from_dict(payload)
            if decision.decision_fingerprint != decision_fingerprint or raw != only_canonical_json(payload):
                raise ValueError("Decision path/content identity differs")
            return decision
        except OnlyQualificationError:
            raise
        except Exception as exc:
            raise OnlyQualificationError("QUALIFICATION_DECISION_CORRUPT", decision_fingerprint) from exc

    def decisions_for_subject(self, strategy_fingerprint: str) -> tuple[OnlyQualificationDecision, ...]:
        if not self._root.exists():
            return ()
        if self._root.is_symlink():
            raise OnlyQualificationError("QUALIFICATION_DECISION_CORRUPT", "authority root")
        result: list[OnlyQualificationDecision] = []
        try:
            for prefix in sorted(self._root.iterdir(), key=lambda item: item.name):
                if prefix.is_symlink() or not prefix.is_dir():
                    raise ValueError("unexpected Decision prefix")
                for target in sorted(prefix.iterdir(), key=lambda item: item.name):
                    decision = self.load_verified(target.name)
                    if decision.subject_strategy_fingerprint == strategy_fingerprint:
                        result.append(decision)
        except OnlyQualificationError:
            raise
        except Exception as exc:
            raise OnlyQualificationError("QUALIFICATION_DECISION_CORRUPT", strategy_fingerprint) from exc
        return tuple(sorted(result, key=lambda item: item.decision_fingerprint))

    def _target(self, fingerprint: str) -> Path:
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise OnlyQualificationError("QUALIFICATION_DECISION_CORRUPT", "invalid Decision fingerprint")
        return self._root / fingerprint[:2] / fingerprint

    def _require_safe_decision_path(self, target: Path) -> None:
        if self._root.is_symlink() or target.parent.is_symlink() or target.is_symlink():
            raise OnlyQualificationError("QUALIFICATION_DECISION_CORRUPT", target.name)


class _OnlyQualificationDecisionPublisher:
    """Internal write capability composed only into the deterministic evaluator."""

    def __init__(self, reader: OnlyQualificationDecisionStore) -> None:
        self._reader = reader

    def load_verified(self, decision_fingerprint: str) -> OnlyQualificationDecision:
        return self._reader.load_verified(decision_fingerprint)

    def publish_verified(self, publication: _OnlyQualificationDecisionPublication) -> OnlyQualificationDecision:
        if (
            not isinstance(publication, _OnlyQualificationDecisionPublication)
            or publication.seal is not _QUALIFICATION_DECISION_PUBLICATION_SEAL
        ):
            raise OnlyQualificationError(
                "QUALIFICATION_DECISION_PUBLICATION_UNAUTHORIZED",
                "Decision publication requires evaluator proof",
            )
        decision = publication.decision
        return self._publish(decision)

    def _publish(self, decision: OnlyQualificationDecision) -> OnlyQualificationDecision:
        target = self._reader._target(decision.decision_fingerprint)
        self._reader._require_safe_decision_path(target)
        if target.exists() or target.is_symlink():
            existing = self._reader.load_verified(decision.decision_fingerprint)
            if existing != decision:
                raise OnlyQualificationError("QUALIFICATION_DECISION_CORRUPT", decision.decision_fingerprint)
            return existing
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = target.parent / f".stage-{uuid.uuid4().hex}"
        try:
            stage.mkdir()
            _write_manifest(stage / "manifest.json", decision.to_dict())
            _fsync_directory(stage)
            try:
                os.rename(stage, target)
            except OSError:
                if not target.exists():
                    raise
            _fsync_directory(target.parent)
            existing = self._reader.load_verified(decision.decision_fingerprint)
            if existing != decision:
                raise OnlyQualificationError("QUALIFICATION_DECISION_CORRUPT", decision.decision_fingerprint)
            return existing
        except OnlyQualificationError:
            raise
        except Exception as exc:
            raise OnlyQualificationError("QUALIFICATION_DECISION_CORRUPT", decision.decision_fingerprint) from exc
        finally:
            shutil.rmtree(stage, ignore_errors=True)


def _only_compose_qualification_decision_authority(
    semantic_root: Path,
) -> tuple[OnlyQualificationDecisionStore, _OnlyQualificationDecisionPublisher]:
    reader = OnlyQualificationDecisionStore(semantic_root)
    return reader, _OnlyQualificationDecisionPublisher(reader)


def _write_manifest(path: Path, payload: dict[str, object]) -> None:
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


# Exact ID/path validation should not duplicate Domain rules.
_PROBE_POLICY = OnlyQualificationPolicyRevision(
    "probe",
    "1",
    OnlyQualificationGate.RESEARCH_TO_BACKTEST,
    (
        OnlyQualificationCriterion(
            "probe",
            OnlyQualificationEvidenceKind.RESEARCH_RESULT,
            "probe",
            "EQ",
            Decimal(0),
        ),
    ),
)


__all__ = [name for name in globals() if name.startswith("Only")]
