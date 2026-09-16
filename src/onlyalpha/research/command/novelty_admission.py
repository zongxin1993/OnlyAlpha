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


def only_novelty_same_subject_guard_key(subject_fingerprint: str) -> str:
    return only_canonical_fingerprint(
        {
            "domain": "onlyalpha.research.novelty-same-subject-guard-v1",
            "evaluation_subject_fingerprint": _sha(subject_fingerprint, "evaluation subject fingerprint"),
        }
    )


__all__ = [name for name in globals() if name.startswith("Only") or name.startswith("only_")]
