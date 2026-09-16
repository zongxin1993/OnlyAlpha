"""Atomic put-once persistence for one Decision and its Witness."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.memory.store import OnlyExperimentMemoryRevisionStore

from .decision import (
    OnlyNoveltyDecisionBundleV1,
    OnlyNoveltyDecisionBundleV2,
    OnlyNoveltyDecisionConflictError,
    OnlyNoveltyDecisionCorruptError,
    OnlyNoveltyDecisionError,
    OnlyNoveltyDecisionRequestV1,
    OnlyNoveltyDecisionRequestV2,
    OnlyNoveltyDecisionSchemaUnsupportedError,
    OnlyNoveltyDecisionV1,
    OnlyNoveltyDecisionV2,
    OnlyNoveltyDecisionWitnessV1,
    OnlyNoveltyDecisionWitnessV2,
    OnlyNoveltyFreezeRelationReader,
    OnlyNoveltyQualificationDecisionReader,
    OnlyNoveltyWitnessSchemaUnsupportedError,
    _build_novelty_decision_bundle,
    _build_novelty_decision_bundle_v2,
)
from .store import OnlyNoveltyPolicyStore


class OnlyNoveltyDecisionNotFoundError(OnlyNoveltyDecisionError):
    code = "NOVELTY_DECISION_NOT_FOUND"


class OnlyNoveltyDecisionAuthority:
    """The sole supported authoring path for authoritative Novelty Decisions."""

    def __init__(self, semantic_root: Path) -> None:
        self._semantic_root = semantic_root
        self._root = semantic_root / "research" / "novelty-decisions"

    def seal_from_request(
        self,
        request: OnlyNoveltyDecisionRequestV1 | OnlyNoveltyDecisionRequestV2,
        projection_revision_fingerprint: str,
        revisions: OnlyExperimentMemoryRevisionStore,
        policies: OnlyNoveltyPolicyStore,
        *,
        qualification_decisions: OnlyNoveltyQualificationDecisionReader | None = None,
        freeze_relations: OnlyNoveltyFreezeRelationReader | None = None,
    ) -> OnlyNoveltyDecisionBundleV1 | OnlyNoveltyDecisionBundleV2:
        """Derive and persist one Decision; retries consult sealed history first."""
        if not isinstance(request, (OnlyNoveltyDecisionRequestV1, OnlyNoveltyDecisionRequestV2)):
            raise OnlyNoveltyDecisionCorruptError("authoritative seal requires a Decision request")
        try:
            existing = self.load_exact(request.command_id)
        except OnlyNoveltyDecisionNotFoundError:
            pass
        else:
            if existing.decision.subject.canonical_intent_fingerprint != request.canonical_intent_fingerprint:
                raise OnlyNoveltyDecisionConflictError(request.command_id.value)
            return existing
        proposed: OnlyNoveltyDecisionBundleV1 | OnlyNoveltyDecisionBundleV2
        if isinstance(request, OnlyNoveltyDecisionRequestV2):
            proposed = _build_novelty_decision_bundle_v2(
                request,
                projection_revision_fingerprint,
                revisions,
                policies,
                qualification_decisions=qualification_decisions,
                freeze_relations=freeze_relations,
            )
        else:
            proposed = _build_novelty_decision_bundle(
                request,
                projection_revision_fingerprint,
                revisions,
                policies,
                qualification_decisions=qualification_decisions,
                freeze_relations=freeze_relations,
            )
        try:
            return self._put_verified_bundle(proposed)
        except OnlyNoveltyDecisionConflictError:
            existing = self.load_exact(request.command_id)
            if existing.decision.subject.canonical_intent_fingerprint != request.canonical_intent_fingerprint:
                raise
            return existing

    def _put_verified_bundle(
        self, bundle: OnlyNoveltyDecisionBundleV1 | OnlyNoveltyDecisionBundleV2
    ) -> OnlyNoveltyDecisionBundleV1 | OnlyNoveltyDecisionBundleV2:
        if not isinstance(bundle, (OnlyNoveltyDecisionBundleV1, OnlyNoveltyDecisionBundleV2)):
            raise OnlyNoveltyDecisionCorruptError("verified put requires a validated Decision Bundle")
        command_id = OnlyProductCommandId(bundle.decision.subject.product_command_id)
        target = self._target(command_id)
        self._require_safe(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        lock = target.parent / f".{command_id.value}.lock"
        with self._locked(lock):
            if target.exists() or target.is_symlink():
                existing = self.load_exact(command_id)
                if existing != bundle:
                    raise OnlyNoveltyDecisionConflictError(command_id.value)
                return existing
            stage = target.parent / f".{command_id.value}.{uuid.uuid4().hex}.stage"
            try:
                stage.mkdir(mode=0o700)
                with (stage / "bundle.json").open("x", encoding="utf-8") as stream:
                    stream.write(only_canonical_json(bundle.to_dict()))
                    stream.flush()
                    os.fsync(stream.fileno())
                self._fsync(stage)
                os.rename(stage, target)
                self._fsync(target.parent)
            except OnlyNoveltyDecisionError:
                raise
            except Exception as exc:
                raise OnlyNoveltyDecisionCorruptError(command_id.value) from exc
            finally:
                shutil.rmtree(stage, ignore_errors=True)
        return self.load_exact(command_id)

    def load_exact(self, command_id: OnlyProductCommandId) -> OnlyNoveltyDecisionBundleV1 | OnlyNoveltyDecisionBundleV2:
        target = self._target(command_id)
        self._require_safe(target)
        if not target.exists() and not target.is_symlink():
            raise OnlyNoveltyDecisionNotFoundError(command_id.value)
        try:
            manifest = target / "bundle.json"
            if (
                not target.is_dir()
                or manifest.is_symlink()
                or {item.name for item in target.iterdir()} != {"bundle.json"}
            ):
                raise ValueError("unexpected Decision Bundle shape")
            raw = manifest.read_text(encoding="utf-8")
            payload = json.loads(raw)
            if (
                not isinstance(payload, dict)
                or set(payload) != {"decision", "witness"}
                or raw != only_canonical_json(payload)
            ):
                raise ValueError("Decision Bundle is not canonical")
            witness_payload = payload["witness"]
            decision_payload = payload["decision"]
            if not isinstance(witness_payload, dict) or not isinstance(decision_payload, dict):
                raise ValueError("Decision Bundle members are invalid")
            witness_schema = witness_payload.get("schema_version")
            if witness_schema == 1:
                witness_v1 = OnlyNoveltyDecisionWitnessV1.from_dict(witness_payload)
                decision_v1 = OnlyNoveltyDecisionV1.from_dict(decision_payload, witness_v1.subject)
                bundle: OnlyNoveltyDecisionBundleV1 | OnlyNoveltyDecisionBundleV2 = OnlyNoveltyDecisionBundleV1(
                    decision_v1, witness_v1
                )
            elif witness_schema == 2:
                subject = witness_payload.get("subject")
                if (
                    not isinstance(subject, dict)
                    or not isinstance(subject.get("resolved_subject"), dict)
                    or "evaluation_subject" not in subject["resolved_subject"]
                ):
                    raise OnlyNoveltyWitnessSchemaUnsupportedError("Decision Witness V2")
                witness_v2 = OnlyNoveltyDecisionWitnessV2.from_dict(witness_payload)
                decision_v2 = OnlyNoveltyDecisionV2.from_dict(decision_payload, witness_v2.subject)
                bundle = OnlyNoveltyDecisionBundleV2(decision_v2, witness_v2)
            else:
                raise OnlyNoveltyWitnessSchemaUnsupportedError(str(witness_schema))
            if bundle.decision.subject.product_command_id != command_id.value:
                raise ValueError("Decision path identity differs")
            return bundle
        except (OnlyNoveltyDecisionSchemaUnsupportedError, OnlyNoveltyWitnessSchemaUnsupportedError):
            raise
        except OnlyNoveltyDecisionError:
            raise
        except Exception as exc:
            raise OnlyNoveltyDecisionCorruptError(command_id.value) from exc

    def _target(self, command_id: OnlyProductCommandId) -> Path:
        if not isinstance(command_id, OnlyProductCommandId):
            raise OnlyNoveltyDecisionCorruptError("Product Command ID is invalid")
        return self._root / command_id.value

    def _require_safe(self, target: Path) -> None:
        paths = (self._semantic_root, self._semantic_root / "research", self._root, target)
        if any(path.is_symlink() for path in paths):
            raise OnlyNoveltyDecisionCorruptError("unsafe Decision authority path")

    @staticmethod
    @contextmanager
    def _locked(path: Path) -> Iterator[None]:
        if path.is_symlink():
            raise OnlyNoveltyDecisionCorruptError("unsafe Decision authority lock")
        with path.open("a+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    @staticmethod
    def _fsync(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


__all__ = [name for name in globals() if name.startswith("OnlyNovelty")]
