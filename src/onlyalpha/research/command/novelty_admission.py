"""Immutable provenance for converting one Novelty Decision into one Research Run."""

from __future__ import annotations

from dataclasses import dataclass

from onlyalpha.application.product_command_receipt import OnlyProductCommandId
from onlyalpha.canonical import only_canonical_fingerprint
from onlyalpha.research.run.model import OnlyResearchRunId


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lower-case SHA256 fingerprint")
    return value


@dataclass(frozen=True, slots=True)
class OnlyResearchNoveltyAdmissionV1:
    command_id: OnlyProductCommandId
    command_fingerprint: str
    novelty_decision_fingerprint: str
    canonical_intent_fingerprint: str
    evaluation_subject_fingerprint: str
    decision_time_proof_fingerprint: str
    action_time_proof_fingerprint: str
    action_source_manifest_fingerprint: str
    same_subject_guard_key: str
    runtime_work_id: str
    run_id: OnlyResearchRunId
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1 or not isinstance(self.command_id, OnlyProductCommandId):
            raise ValueError("Research Novelty Admission schema is unsupported")
        for name in (
            "command_fingerprint",
            "novelty_decision_fingerprint",
            "canonical_intent_fingerprint",
            "evaluation_subject_fingerprint",
            "decision_time_proof_fingerprint",
            "action_time_proof_fingerprint",
            "action_source_manifest_fingerprint",
            "same_subject_guard_key",
        ):
            _sha(getattr(self, name), name)
        if not isinstance(self.run_id, OnlyResearchRunId) or self.runtime_work_id != self.run_id.value:
            raise ValueError("Research Novelty Admission Runtime/Run binding is invalid")
        if self.same_subject_guard_key != only_canonical_fingerprint(
            {
                "domain": "onlyalpha.research.novelty-same-subject-guard-v1",
                "evaluation_subject_fingerprint": self.evaluation_subject_fingerprint,
            }
        ):
            raise ValueError("Research Novelty Admission guard key is invalid")

    @property
    def admission_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.research.novelty-admission-v1",
                "schema_version": self.schema_version,
                "command_id": self.command_id.value,
                "command_fingerprint": self.command_fingerprint,
                "novelty_decision_fingerprint": self.novelty_decision_fingerprint,
                "canonical_intent_fingerprint": self.canonical_intent_fingerprint,
                "evaluation_subject_fingerprint": self.evaluation_subject_fingerprint,
                "decision_time_proof_fingerprint": self.decision_time_proof_fingerprint,
                "action_time_proof_fingerprint": self.action_time_proof_fingerprint,
                "action_source_manifest_fingerprint": self.action_source_manifest_fingerprint,
                "same_subject_guard_key": self.same_subject_guard_key,
                "runtime_work_id": self.runtime_work_id,
                "run_id": self.run_id.value,
            }
        )


@dataclass(frozen=True, slots=True)
class OnlyResearchNoveltyAdmissionSubjectV1:
    ordinal: int
    evaluation_subject_fingerprint: str
    novelty_decision_fingerprint: str
    canonical_intent_fingerprint: str
    decision_time_proof_fingerprint: str
    action_time_proof_fingerprint: str
    same_subject_guard_key: str
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.ordinal) is not int or self.ordinal < 0 or self.schema_version != 1:
            raise ValueError("Research Novelty Admission member is invalid")
        for name in (
            "evaluation_subject_fingerprint",
            "novelty_decision_fingerprint",
            "canonical_intent_fingerprint",
            "decision_time_proof_fingerprint",
            "action_time_proof_fingerprint",
            "same_subject_guard_key",
        ):
            _sha(getattr(self, name), name)
        if self.same_subject_guard_key != only_novelty_same_subject_guard_key(self.evaluation_subject_fingerprint):
            raise ValueError("Research Novelty Admission member guard key is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "ordinal": self.ordinal,
            "evaluation_subject_fingerprint": self.evaluation_subject_fingerprint,
            "novelty_decision_fingerprint": self.novelty_decision_fingerprint,
            "canonical_intent_fingerprint": self.canonical_intent_fingerprint,
            "decision_time_proof_fingerprint": self.decision_time_proof_fingerprint,
            "action_time_proof_fingerprint": self.action_time_proof_fingerprint,
            "same_subject_guard_key": self.same_subject_guard_key,
        }


@dataclass(frozen=True, slots=True)
class OnlyResearchNoveltyAdmissionV2:
    command_id: OnlyProductCommandId
    command_fingerprint: str
    decision_group_fingerprint: str
    subject_set_fingerprint: str
    action_source_manifest_fingerprint: str
    runtime_work_id: str
    run_id: OnlyResearchRunId
    members: tuple[OnlyResearchNoveltyAdmissionSubjectV1, ...]
    schema_version: int = 2

    def __post_init__(self) -> None:
        if self.schema_version != 2 or not isinstance(self.command_id, OnlyProductCommandId):
            raise ValueError("Research Novelty Admission schema is unsupported")
        for name in (
            "command_fingerprint",
            "decision_group_fingerprint",
            "subject_set_fingerprint",
            "action_source_manifest_fingerprint",
        ):
            _sha(getattr(self, name), name)
        fingerprints = tuple(item.evaluation_subject_fingerprint for item in self.members)
        if (
            not self.members
            or any(not isinstance(item, OnlyResearchNoveltyAdmissionSubjectV1) for item in self.members)
            or tuple(item.ordinal for item in self.members) != tuple(range(len(self.members)))
            or fingerprints != tuple(sorted(fingerprints))
            or len(set(fingerprints)) != len(fingerprints)
        ):
            raise ValueError("Research Novelty Admission members are not complete and canonical")
        if not isinstance(self.run_id, OnlyResearchRunId) or self.runtime_work_id != self.run_id.value:
            raise ValueError("Research Novelty Admission Runtime/Run binding is invalid")

    @property
    def admission_fingerprint(self) -> str:
        return only_canonical_fingerprint(
            {
                "domain": "onlyalpha.research.novelty-admission-v2",
                "schema_version": self.schema_version,
                "command_id": self.command_id.value,
                "command_fingerprint": self.command_fingerprint,
                "decision_group_fingerprint": self.decision_group_fingerprint,
                "subject_set_fingerprint": self.subject_set_fingerprint,
                "action_source_manifest_fingerprint": self.action_source_manifest_fingerprint,
                "runtime_work_id": self.runtime_work_id,
                "run_id": self.run_id.value,
                "members": [item.to_dict() for item in self.members],
            }
        )


def only_novelty_same_subject_guard_key(subject_fingerprint: str) -> str:
    return only_canonical_fingerprint(
        {
            "domain": "onlyalpha.research.novelty-same-subject-guard-v1",
            "evaluation_subject_fingerprint": _sha(subject_fingerprint, "evaluation subject fingerprint"),
        }
    )


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
